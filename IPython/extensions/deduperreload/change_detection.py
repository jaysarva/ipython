"""Detect and validate reloadable changes using AST analysis."""

from __future__ import annotations
import ast
import builtins
import itertools
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Generator, Iterable, cast

from .dependency_graph import QualifiedFunctionDef

if TYPE_CHECKING:
    from typing import Union

    TDefinitionAst = Union[ast.FunctionDef,
                           ast.AsyncFunctionDef,
                           ast.Import,
                           ast.ImportFrom,
                           ast.Assign,
                           ast.AnnAssign,
                           ]


class ASTAnalyzer:
    """AST utilities: structural comparison that ignores positional metadata except for function definitions."""

    @classmethod
    def compare_ast(cls,
                    node1: ast.AST | list[ast.AST],
                    node2: ast.AST | list[ast.AST],
                    compare_positions: bool = False) -> bool:
        """Return True if nodes/lists are structurally equal (ignoring positions except for function definitions)."""
        if type(node1) is not type(node2):
            return False

        if isinstance(node1, ast.AST) and isinstance(node2, ast.AST):
            return cls._compare_ast_nodes(
                node1,
                node2,
                compare_positions=compare_positions or
                isinstance(node1, (ast.AsyncFunctionDef, ast.FunctionDef, ast.Lambda)))
        elif isinstance(node1, list) and isinstance(node2, list):
            return cls._compare_ast_lists(node1, node2, compare_positions=compare_positions)
        else:
            return node1 == node2

    @classmethod
    def _compare_ast_nodes(cls, node1: ast.AST, node2: ast.AST, compare_positions: bool) -> bool:
        """Compare two AST nodes by non-positional attributes recursively."""
        for attr_name, attr_value in node1.__dict__.items():
            if not compare_positions and attr_name in ("lineno", "end_lineno", "col_offset",
                                                       "end_col_offset"):
                continue
            if attr_name in ("ctx", "parent"):
                continue

            if not hasattr(node2, attr_name):
                return False

            if not cls.compare_ast(
                    attr_value, getattr(node2, attr_name), compare_positions=compare_positions):
                return False

        return True

    @classmethod
    def _compare_ast_lists(cls, list1: list[ast.AST], list2: list[ast.AST],
                           compare_positions: bool) -> bool:
        """Compare lists elementwise using structural comparison."""
        if len(list1) != len(list2):
            return False

        return all(
            cls.compare_ast(n1, n2, compare_positions=compare_positions)
            for n1, n2 in zip(list1, list2))


class ConstexprDetector(ast.NodeVisitor):
    """Detect whether an AST node represents a constant expression."""

    def __init__(self) -> None:
        self.is_constexpr = True
        self._allow_builtins_exceptions = True
        self._lambda_args: set[str] = set()

    @contextmanager
    def disallow_builtins_exceptions(self) -> Generator[None, None, None]:
        """Temporarily disallow builtin exceptions while visiting names."""
        prev_allow = self._allow_builtins_exceptions
        self._allow_builtins_exceptions = False
        try:
            yield
        finally:
            self._allow_builtins_exceptions = prev_allow

    def visit_Attribute(self, node: ast.Attribute) -> None:
        """Attributes are non-constexpr; only visit value with stricter rules."""
        with self.disallow_builtins_exceptions():
            self.visit(node.value)

    def visit_Name(self, node: ast.Name) -> None:
        """Only allow builtins or lambda args; otherwise mark as non-constexpr."""
        if self._allow_builtins_exceptions and hasattr(builtins, node.id):
            return
        elif node.id not in self._lambda_args:
            self.is_constexpr = False

    def visit_arg(self, node: ast.arg) -> None:
        self._lambda_args.add(node.arg)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        orig_captures = self._lambda_args
        self._lambda_args = set(orig_captures)
        self.visit(node.args)
        self.visit(node.body)
        self._lambda_args = orig_captures

    def visit(self, node: ast.AST) -> None:
        """Visit with short-circuiting once non-constexpr is determined."""
        if not self.is_constexpr:
            # Short-circuit if we've already detected it's not a constant expression
            return
        super().visit(node)

    def __call__(self, node: ast.AST) -> bool:
        """Return True if the node is a constant expression."""
        self.is_constexpr = True
        self.visit(node)
        return self.is_constexpr


@dataclass
class GatherResult:
    """Categorized AST results for reloadable constructs."""

    import_defs: list[tuple[tuple[str, ...], ast.Import | ast.ImportFrom]] = field(default_factory=list)
    assign_defs: list[tuple[tuple[str, ...], ast.Assign | ast.AnnAssign]] = field(default_factory=list)
    function_defs: list[tuple[tuple[str, ...], ast.FunctionDef | ast.AsyncFunctionDef]] = field(default_factory=list)
    classes: dict[str, ast.ClassDef] = field(default_factory=dict)
    unfixable: list[ast.AST] = field(default_factory=list)

    def all_top_level_reloadable_defs(self) -> Iterable[tuple[tuple[str, ...], TDefinitionAst]]:
        return itertools.chain(self.import_defs, self.assign_defs, self.function_defs)

    def inplace_merge(self, other: GatherResult) -> None:
        """Merge another GatherResult into this one.

        Args:
            other: GatherResult to merge from
        """
        self.import_defs.extend(other.import_defs)
        self.assign_defs.extend(other.assign_defs)
        self.function_defs.extend(other.function_defs)
        self.classes.update(other.classes)
        self.unfixable.extend(other.unfixable)


class AutoreloadTree:
    """Tree of reloadable defs mirroring module/class nesting."""

    def __init__(self, path: tuple[str, ...] = ()) -> None:
        # Qualified name of this scope
        self.path = path

        # Nested scopes (e.g., classes within this scope)
        self.children: dict[str, AutoreloadTree] = {}

        # Definitions that need to be reloaded in this scope
        self.defs_to_reload: list[tuple[tuple[str, ...], ast.stmt | ast.Module]] = []

        # Definitions that need to be deleted from this scope
        self.defs_to_delete: set[str] = set()

        # New nested classes being added
        self.new_nested_classes: dict[str, ast.ClassDef] = {}

    def get_child(self, prefix: str) -> AutoreloadTree:
        return self.children.setdefault(prefix, AutoreloadTree(self.path + (prefix, )))

    def traverse_prefixes(self, prefixes: list[str] | tuple[str, ...]) -> AutoreloadTree:
        """Navigate to a specific namespace in the tree.

        Creates intermediate nodes if they don't exist.

        Args:
            prefixes: List of namespace components (e.g., ['MyClass', 'NestedClass'])

        Returns:
            AutoreloadTree node at the specified namespace
        """
        current_node = self
        for prefix in prefixes:
            current_node = current_node.get_child(prefix)
        return current_node

    def add_qualified_def(self, node: QualifiedFunctionDef) -> None:
        self.traverse_prefixes(node.path).defs_to_reload.append(((node.func_def.name, ),
                                                                 node.func_def))


class ChangeDetector:
    """Build the tree of reload operations by diffing old/new ASTs."""

    def __init__(self) -> None:
        """Initialize the change detector."""
        # Tree structure tracking what needs to be reloaded
        self.autoreload_tree: AutoreloadTree = AutoreloadTree(())

        # Shared instance for detecting constant expressions
        self._constexpr_detector = ConstexprDetector()

    def reset(self) -> None:
        """Reset the change detector state."""
        self.autoreload_tree = AutoreloadTree(())

    @staticmethod
    def is_enum_subclass(node: ast.Module | ast.ClassDef) -> bool:
        """Check if a class node is an Enum subclass."""
        if isinstance(node, ast.Module):
            return False
        for base in node.bases:
            if isinstance(base, ast.Name) and base.id == "Enum":
                return True
            elif (isinstance(base, ast.Attribute) and base.attr == "Enum" and
                  isinstance(base.value, ast.Name) and base.value.id == "enum"):
                return True
        return False

    def is_constexpr_assign(self, node: ast.AST, parent_node: ast.Module | ast.ClassDef) -> bool:
        """Return True for simple-name assignments whose value is constexpr (non-Enum)."""
        if not isinstance(node, (ast.Assign, ast.AnnAssign)) or node.value is None:
            return False

        # Don't treat enum assignments as constant expressions
        if self.is_enum_subclass(parent_node):
            return False

        # All targets must be simple names (not attributes or subscripts)
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if not isinstance(target, ast.Name):
                return False

        if isinstance(node.value, ast.Lambda):
            # if it's a lambda that doesn't get called, it's always a constant
            # expression, even if the lambda body references other variables
            return True

        # Check if the assigned value is a constant expression
        return self._constexpr_detector(node.value)

    def _gather_children(self, body: list[ast.stmt],
                         parent_node: ast.Module | ast.ClassDef) -> GatherResult:
        """Categorize statements in a body into reloadable defs, classes, and unfixables."""
        result = GatherResult()

        for stmt in body:
            self._gather_statement(result, self._unwrap_expression(stmt), parent_node)

        return result

    def _gather_statement(
            self,
            result: GatherResult,
            ast_elt: ast.expr | ast.stmt,
            parent_node: ast.Module | ast.ClassDef,
    ) -> None:
        """Dispatch a single AST element into the appropriate GatherResult bucket."""
        if isinstance(ast_elt, ast.Pass):
            pass
        elif isinstance(ast_elt, ast.Constant) and ast_elt.value is ...:
            pass
        elif isinstance(ast_elt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            self._gather_function_def(result, ast_elt)
        elif isinstance(ast_elt, (ast.Import, ast.ImportFrom)):
            self._gather_import_def(result, ast_elt)
        elif isinstance(ast_elt, ast.ClassDef):
            self._gather_class_def(result, ast_elt)
        elif isinstance(ast_elt, (ast.AsyncWith, ast.With)):
            self._gather_with_statement(result, ast_elt, parent_node)
        elif isinstance(ast_elt, ast.Try):
            self._gather_try_statement(result, ast_elt, parent_node)
        elif isinstance(ast_elt, ast.If):
            self._gather_if_statement(result, ast_elt, parent_node)
        else:
            self._gather_other_statement(result, ast_elt, parent_node)

    @classmethod
    def _unwrap_expression(cls, ast_node: ast.stmt) -> ast.expr | ast.stmt:
        """Return the underlying expression for Expr-wrapped statements."""
        ast_elt: ast.expr | ast.stmt = ast_node
        while isinstance(ast_elt, ast.Expr):
            ast_elt = ast_elt.value
        return ast_elt

    @classmethod
    def _gather_function_def(cls, result: GatherResult,
                             ast_elt: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        """Record a function/async-function definition."""
        result.function_defs.append(((ast_elt.name, ), ast_elt))

    @classmethod
    def _gather_import_def(cls, result: GatherResult, ast_elt: ast.Import | ast.ImportFrom) -> None:
        """Record an import or from-import definition."""
        names = tuple(name.asname or name.name for name in ast_elt.names)
        result.import_defs.append((names, ast_elt))

    @classmethod
    def _gather_class_def(cls, result: GatherResult, ast_elt: ast.ClassDef) -> None:
        """Record a class definition."""
        result.classes[ast_elt.name] = ast_elt

    def _gather_if_statement(
            self,
            result: GatherResult,
            ast_elt: ast.If,
            parent_node: ast.Module | ast.ClassDef,
    ) -> None:
        """Recurse into both branches; mark condition as unfixable."""
        # The condition is unfixable (can't be safely reloaded)
        result.unfixable.append(ast_elt.test)

        # Recursively gather from both branches
        result.inplace_merge(self._gather_children(ast_elt.body, parent_node))
        result.inplace_merge(self._gather_children(ast_elt.orelse, parent_node))

    def _gather_with_statement(
            self,
            result: GatherResult,
            ast_elt: ast.AsyncWith | ast.With,
            parent_node: ast.Module | ast.ClassDef,
    ) -> None:
        """Mark context items unfixable and gather from the body."""
        # Context manager items are unfixable
        result.unfixable.extend(ast_elt.items)

        # Recursively gather from the body
        result.inplace_merge(self._gather_children(ast_elt.body, parent_node))

    def _gather_try_statement(
            self,
            result: GatherResult,
            ast_elt: ast.Try,
            parent_node: ast.Module | ast.ClassDef,
    ) -> None:
        """Gather from try/else/finally and handlers (mark types unfixable)."""
        result.inplace_merge(self._gather_children(ast_elt.body, parent_node))
        result.inplace_merge(self._gather_children(ast_elt.orelse, parent_node))
        result.inplace_merge(self._gather_children(ast_elt.finalbody, parent_node))

        for handler in ast_elt.handlers:
            if handler.type is not None:
                result.unfixable.append(handler.type)
            result.inplace_merge(self._gather_children(handler.body, parent_node))

    def _gather_other_statement(
            self,
            result: GatherResult,
            ast_elt: ast.expr | ast.stmt,
            parent_node: ast.Module | ast.ClassDef,
    ) -> None:
        """Record constexpr assignments; otherwise mark unfixable."""
        if self.is_constexpr_assign(ast_elt, parent_node):
            assert isinstance(ast_elt, (ast.Assign, ast.AnnAssign))
            targets = (ast_elt.targets if isinstance(ast_elt, ast.Assign) else [ast_elt.target])
            target_names = tuple(cast(ast.Name, target).id for target in targets)
            result.assign_defs.append((target_names, ast_elt))
        else:
            # Mark as unfixable
            result.unfixable.append(ast_elt)

    def detect_autoreload(
            self,
            old_node: ast.Module | ast.ClassDef,
            new_node: ast.Module | ast.ClassDef,
            autoreload_tree: AutoreloadTree,
    ) -> bool:
        """Return True if changes are safely reloadable and populate the tree accordingly."""
        # Parse and categorize definitions from both old and new versions
        old_result = self._gather_children(old_node.body, old_node)
        new_result = self._gather_children(new_node.body, new_node)

        # Create name-to-definition mappings for quick lookup
        old_defs_by_name = self._create_reloadable_def_mapping(old_result)
        new_defs_by_name = self._create_reloadable_def_mapping(new_result)

        if not ASTAnalyzer.compare_ast(old_result.unfixable, new_result.unfixable):
            return False

        # Handle definitions nested in classes (new, changed, or unchanged)
        if not self._detect_nested_class_definitions(old_result, new_result, autoreload_tree):
            return False

        # Find what definitions need to be reloaded
        for names, new_ast_def in new_result.all_top_level_reloadable_defs():
            # only reload the names corresponding to the latest def
            names_to_reload = [name for name in names if new_defs_by_name[name] == new_ast_def]
            if not names_to_reload:
                continue
            if any(
                    name not in old_defs_by_name or
                    not ASTAnalyzer.compare_ast(new_ast_def, old_defs_by_name[name])
                    for name in names_to_reload):
                autoreload_tree.defs_to_reload.append((tuple(names_to_reload), new_ast_def))

        # Find what definitions need to be deleted
        autoreload_tree.defs_to_delete |= set(old_defs_by_name.keys()) - set(
            new_defs_by_name.keys())
        return True

    @staticmethod
    def _create_reloadable_def_mapping(result: GatherResult) -> dict[str, ast.AST]:
        """Map definition names to their AST nodes for quick lookup."""
        return {
            name: ast_def
            for names, ast_def in result.all_top_level_reloadable_defs() for name in names
        }

    def _detect_nested_class_definitions(
            self,
            old_result: GatherResult,
            new_result: GatherResult,
            autoreload_tree: AutoreloadTree,
    ) -> bool:
        """Handle new/changed classes, recursing into changed ones; return False if unsafe."""
        for class_name, new_class_def in new_result.classes.items():
            if class_name not in old_result.classes:
                autoreload_tree.new_nested_classes[class_name] = new_class_def
            elif not ASTAnalyzer.compare_ast(new_class_def, old_result.classes[class_name]):
                if not self.detect_autoreload(
                        old_result.classes[class_name],
                        new_class_def,
                        autoreload_tree.get_child(class_name),
                ):
                    return False

        return True
