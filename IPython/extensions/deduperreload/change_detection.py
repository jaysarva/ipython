"""Change Detection Module for Deduperreload Extension.

This module provides comprehensive analysis capabilities for detecting and validating
changes between old and new versions of Python code. It determines if deduperreload
is applicable for given changes by comparing AST structures and categorizing different
types of definitions.

Key Features:
- AST comparison and structural analysis
- Detection of constant expressions that can be safely reloaded
- Categorization of code constructs (functions, classes, imports, assignments)
- Validation logic to determine if targeted autoreload is possible
- Hierarchical data structures for tracking reloadable constructs

Classes:
- ASTAnalyzer: Helper class for AST analysis and comparison operations
- ConstexprDetector: Detects if an AST node represents a constant expression
- GatherResult: Container for AST gathering results
- AutoreloadTree: Hierarchical structure for tracking reloadable constructs
- ChangeDetector: Main class for change detection and validation
"""

from __future__ import annotations
import ast
import builtins
import contextlib
import itertools
from typing import TYPE_CHECKING, Generator, Iterable, NamedTuple, cast

if TYPE_CHECKING:
    TDefinitionAst = (
        ast.FunctionDef
        | ast.AsyncFunctionDef
        | ast.Import
        | ast.ImportFrom
        | ast.Assign
        | ast.AnnAssign
    )


class ASTAnalyzer:
    """Helper class for AST analysis and comparison operations.

    This class encapsulates all AST-related logic including comparison,
    validation, and structural analysis.
    """

    # Attributes to ignore when comparing AST nodes
    IGNORED_AST_ATTRS = {
        "lineno",
        "end_lineno",
        "col_offset",
        "end_col_offset",
        "ctx",
        "parent",
    }

    @classmethod
    def compare_ast(
        cls, node1: ast.AST | list[ast.AST], node2: ast.AST | list[ast.AST]
    ) -> bool:
        """Compare two AST nodes for structural equality.

        Ignores position-related attributes like line numbers and column offsets,
        focusing on the actual code structure and content.

        Args:
            node1: First AST node or list of nodes
            node2: Second AST node or list of nodes

        Returns:
            True if nodes are structurally identical, False otherwise
        """
        if type(node1) is not type(node2):
            return False

        if isinstance(node1, ast.AST) and isinstance(node2, ast.AST):
            return cls._compare_ast_nodes(node1, node2)
        elif isinstance(node1, list) and isinstance(node2, list):
            return cls._compare_ast_lists(node1, node2)
        else:
            return node1 == node2

    @classmethod
    def _compare_ast_nodes(cls, node1: ast.AST, node2: ast.AST) -> bool:
        """Compare two individual AST nodes."""
        for attr_name, attr_value in node1.__dict__.items():
            if attr_name in cls.IGNORED_AST_ATTRS:
                continue

            if not hasattr(node2, attr_name):
                return False

            if not cls.compare_ast(attr_value, getattr(node2, attr_name)):
                return False

        return True

    @classmethod
    def _compare_ast_lists(cls, list1: list[ast.AST], list2: list[ast.AST]) -> bool:
        """Compare two lists of AST nodes."""
        if len(list1) != len(list2):
            return False

        return all(cls.compare_ast(n1, n2) for n1, n2 in zip(list1, list2))


class ConstexprDetector(ast.NodeVisitor):
    """Detects if an AST node represents a constant expression.

    A constant expression is one that only uses built-in values and doesn't
    reference variables that could change. This is used to determine if
    assignments can be safely reloaded.
    """

    def __init__(self) -> None:
        self.is_constexpr = True
        self._allow_builtins_exceptions = True

    @contextlib.contextmanager
    def disallow_builtins_exceptions(self) -> Generator[None, None, None]:
        """Context manager to temporarily disallow builtin exceptions."""
        prev_allow = self._allow_builtins_exceptions
        self._allow_builtins_exceptions = False
        try:
            yield
        finally:
            self._allow_builtins_exceptions = prev_allow

    def visit_Attribute(self, node: ast.Attribute) -> None:
        """Visit attribute access - attributes are not constant expressions."""
        with self.disallow_builtins_exceptions():
            self.visit(node.value)

    def visit_Name(self, node: ast.Name) -> None:
        """Visit name references - only builtins are allowed."""
        if self._allow_builtins_exceptions and hasattr(builtins, node.id):
            return
        self.is_constexpr = False

    def visit(self, node: ast.AST) -> None:
        """Visit any AST node with short-circuiting optimization."""
        if not self.is_constexpr:
            # Short-circuit if we've already detected it's not a constant expression
            return
        super().visit(node)

    def __call__(self, node: ast.AST) -> bool:
        """Check if a node is a constant expression.

        Args:
            node: AST node to analyze

        Returns:
            True if the node represents a constant expression
        """
        self.is_constexpr = True
        self.visit(node)
        return self.is_constexpr


class GatherResult(NamedTuple):
    """Container for AST gathering results.

    This class holds the results of parsing an AST body, categorizing
    different types of definitions that can be reloaded.
    """

    # Import statements (import x, from y import z)
    import_defs: list[tuple[tuple[str, ...], ast.Import | ast.ImportFrom]] = []

    # Variable assignments (x = 1, y: int = 2)
    assign_defs: list[tuple[tuple[str, ...], ast.Assign | ast.AnnAssign]] = []

    # Function definitions (def, async def)
    function_defs: list[
        tuple[tuple[str, ...], ast.FunctionDef | ast.AsyncFunctionDef]
    ] = []

    # Class definitions
    classes: dict[str, ast.ClassDef] = {}

    # AST nodes that cannot be safely reloaded
    unfixable: list[ast.AST] = []

    @classmethod
    def create(cls) -> GatherResult:
        """Create an empty GatherResult."""
        return cls([], [], [], {}, [])

    def all_defs(self) -> Iterable[tuple[tuple[str, ...], TDefinitionAst]]:
        """Get all definition types as a single iterable."""
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
    """Hierarchical data structure for tracking reloadable code constructs.

    This tree mirrors the namespace structure of Python modules, with each
    node representing a scope level (module, class, nested class, etc.).

    Attributes:
        children: Maps nested scope names to their AutoreloadTree instances
        defs_to_reload: List of (name_tuple, ast_node) pairs to be reloaded
        defs_to_delete: Set of definition names to be removed
        new_nested_classes: New classes being added in the current reload cycle
    """

    def __init__(self) -> None:
        # Nested scopes (e.g., classes within this scope)
        self.children: dict[str, AutoreloadTree] = {}

        # Definitions that need to be reloaded in this scope
        self.defs_to_reload: list[tuple[tuple[str, ...], ast.AST]] = []

        # Definitions that need to be deleted from this scope
        self.defs_to_delete: set[str] = set()

        # New nested classes being added
        self.new_nested_classes: dict[str, ast.AST] = {}

    def traverse_prefixes(self, prefixes: list[str]) -> AutoreloadTree:
        """Navigate to a specific namespace in the tree.

        Creates intermediate nodes if they don't exist.

        Args:
            prefixes: List of namespace components (e.g., ['MyClass', 'NestedClass'])

        Returns:
            AutoreloadTree node at the specified namespace
        """
        current_node = self
        for prefix in prefixes:
            if prefix not in current_node.children:
                current_node.children[prefix] = AutoreloadTree()
            current_node = current_node.children[prefix]
        return current_node


class ChangeDetector:
    """Main class for change detection and validation logic.

    This class provides the core functionality for detecting changes between
    old and new versions of code and determining if targeted autoreload is
    possible.
    """

    def __init__(self) -> None:
        """Initialize the change detector."""
        # Tree structure tracking what needs to be reloaded
        self._to_autoreload: AutoreloadTree = AutoreloadTree()

        # Shared instance for detecting constant expressions
        self._constexpr_detector = ConstexprDetector()

    def reset(self) -> None:
        """Reset the change detector state."""
        self._to_autoreload = AutoreloadTree()

    def get_autoreload_tree(self) -> AutoreloadTree:
        """Get the current autoreload tree."""
        return self._to_autoreload

    @staticmethod
    def is_enum_subclass(node: ast.Module | ast.ClassDef) -> bool:
        """Check if a class node is an Enum subclass."""
        if isinstance(node, ast.Module):
            return False
        for base in node.bases:
            if isinstance(base, ast.Name) and base.id == "Enum":
                return True
            elif (
                isinstance(base, ast.Attribute)
                and base.attr == "Enum"
                and isinstance(base.value, ast.Name)
                and base.value.id == "enum"
            ):
                return True
        return False

    def is_constexpr_assign(
        self, node: ast.AST, parent_node: ast.Module | ast.ClassDef
    ) -> bool:
        """Check if an assignment is a constant expression that can be safely reloaded.

        Args:
            node: AST node to check
            parent_node: Parent context (module or class)

        Returns:
            True if this is a constant expression assignment
        """
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

        # Check if the assigned value is a constant expression
        return self._constexpr_detector(node.value)

    def _gather_children(
        self, body: list[ast.stmt], parent_node: ast.Module | ast.ClassDef
    ) -> GatherResult:
        """Parse AST body and categorize different types of definitions.

        This method analyzes a list of AST statements and categorizes them into:
        - Function definitions (can be reloaded)
        - Import statements (can be reloaded)
        - Class definitions (need special handling)
        - Constant assignments (can be reloaded)
        - Control flow constructs (analyzed recursively)
        - Other statements (marked as unfixable)

        Args:
            body: List of AST statements to analyze
            parent_node: Parent context (module or class)

        Returns:
            GatherResult containing categorized definitions
        """
        result = GatherResult.create()

        for ast_node in body:
            # Unwrap expression statements
            ast_elt = self._unwrap_expression(ast_node)

            # Categorize the AST element
            if isinstance(ast_elt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._gather_function_def(result, ast_elt)
            elif isinstance(ast_elt, (ast.Import, ast.ImportFrom)):
                self._gather_import_def(result, ast_elt)
            elif isinstance(ast_elt, ast.ClassDef):
                self._gather_class_def(result, ast_elt)
            elif isinstance(ast_elt, ast.If):
                self._gather_if_statement(result, ast_elt, parent_node)
            elif isinstance(ast_elt, (ast.AsyncWith, ast.With)):
                self._gather_with_statement(result, ast_elt, parent_node)
            elif isinstance(ast_elt, ast.Try):
                self._gather_try_statement(result, ast_elt, parent_node)
            elif not isinstance(ast_elt, (ast.Ellipsis, ast.Pass)):
                self._gather_other_statement(result, ast_elt, parent_node)

        return result

    @classmethod
    def _unwrap_expression(cls, ast_node: ast.stmt) -> ast.expr | ast.stmt:
        """Unwrap expression statements to get the actual expression."""
        ast_elt: ast.expr | ast.stmt = ast_node
        while isinstance(ast_elt, ast.Expr):
            ast_elt = ast_elt.value
        return ast_elt

    @classmethod
    def _gather_function_def(
        cls, result: GatherResult, ast_elt: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> None:
        """Add function definition to the result."""
        result.function_defs.append(((ast_elt.name,), ast_elt))

    @classmethod
    def _gather_import_def(
        cls, result: GatherResult, ast_elt: ast.Import | ast.ImportFrom
    ) -> None:
        """Add import statement to the result."""
        names = tuple(name.asname or name.name for name in ast_elt.names)
        result.import_defs.append((names, ast_elt))

    @classmethod
    def _gather_class_def(cls, result: GatherResult, ast_elt: ast.ClassDef) -> None:
        """Add class definition to the result."""
        result.classes[ast_elt.name] = ast_elt

    def _gather_if_statement(
        self,
        result: GatherResult,
        ast_elt: ast.If,
        parent_node: ast.Module | ast.ClassDef,
    ) -> None:
        """Handle if statements by recursively gathering from both branches."""
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
        """Handle with statements by marking context items as unfixable."""
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
        """Handle try statements by recursively gathering from all blocks."""
        # Gather from main try block
        result.inplace_merge(self._gather_children(ast_elt.body, parent_node))

        # Gather from else block
        result.inplace_merge(self._gather_children(ast_elt.orelse, parent_node))

        # Gather from finally block
        result.inplace_merge(self._gather_children(ast_elt.finalbody, parent_node))

        # Handle exception handlers
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
        """Handle other statements - either constant assignments or unfixable."""
        if self.is_constexpr_assign(ast_elt, parent_node):
            # This is a constant assignment that can be reloaded
            assert isinstance(ast_elt, (ast.Assign, ast.AnnAssign))
            targets = (
                ast_elt.targets if isinstance(ast_elt, ast.Assign) else [ast_elt.target]
            )
            target_names = tuple(cast(ast.Name, target).id for target in targets)
            result.assign_defs.append((target_names, ast_elt))
        else:
            # Mark as unfixable
            result.unfixable.append(ast_elt)

    def detect_autoreload(
        self,
        old_node: ast.Module | ast.ClassDef,
        new_node: ast.Module | ast.ClassDef,
        prefixes: list[str] | None = None,
    ) -> bool:
        """Analyze if targeted autoreload is possible for the given changes.

        This method compares old and new AST nodes to determine if the changes
        are simple enough to handle with targeted reloading. It builds up the
        autoreload tree with what needs to be reloaded.

        Args:
            old_node: AST node from the previous version
            new_node: AST node from the current version
            prefixes: Namespace prefixes for nested scopes

        Returns:
            True if targeted autoreload is possible, False if full reload needed
        """
        prefixes = prefixes or []

        # Parse and categorize definitions from both old and new versions
        old_result = self._gather_children(old_node.body, old_node)
        new_result = self._gather_children(new_node.body, new_node)

        # Create name-to-definition mappings for quick lookup
        old_defs_by_name = self._create_definition_mapping(old_result)
        new_defs_by_name = self._create_definition_mapping(new_result)

        if not ASTAnalyzer.compare_ast(old_result.unfixable, new_result.unfixable):
            return False

        # Find what definitions need to be reloaded
        current_scope = self._to_autoreload.traverse_prefixes(prefixes)
        self._identify_definitions_to_reload(
            current_scope, old_defs_by_name, new_defs_by_name, new_result
        )

        # Find what definitions need to be deleted
        current_scope.defs_to_delete |= set(old_defs_by_name.keys()) - set(
            new_defs_by_name.keys()
        )
        # Handle class definitions (new, changed, or unchanged)
        return self._handle_class_definitions(
            old_result, new_result, current_scope, prefixes
        )

    def _create_definition_mapping(self, result: GatherResult) -> dict[str, ast.AST]:
        """Create a mapping from definition names to their AST nodes."""
        return {name: ast_def for names, ast_def in result.all_defs() for name in names}

    def _identify_definitions_to_reload(
        self,
        current_scope: AutoreloadTree,
        old_defs: dict[str, ast.AST],
        new_defs: dict[str, ast.AST],
        new_result: GatherResult,
    ) -> None:
        """Identify which definitions need to be reloaded based on changes."""
        for names, new_ast_def in new_result.all_defs():
            names_to_reload = []

            for name in names:
                # Skip if this name points to a different definition
                if new_defs[name] is not new_ast_def:
                    continue

                # Check if definition is new or changed
                if name not in old_defs or not ASTAnalyzer.compare_ast(
                    new_ast_def, old_defs[name]
                ):
                    names_to_reload.append(name)

            # Add to reload list if any names need reloading
            if names_to_reload:
                current_scope.defs_to_reload.append((tuple(names), new_ast_def))

    def _handle_class_definitions(
        self,
        old_result: GatherResult,
        new_result: GatherResult,
        current_scope: AutoreloadTree,
        prefixes: list[str],
    ) -> bool:
        """Handle class definitions - new, changed, or unchanged.

        Returns:
            True if all class changes can be handled, False otherwise
        """
        for class_name, new_class_def in new_result.classes.items():
            if class_name not in old_result.classes:
                # This is a new class
                current_scope.new_nested_classes[class_name] = new_class_def
            elif not ASTAnalyzer.compare_ast(
                new_class_def, old_result.classes[class_name]
            ):
                # Class has changed - try to handle it recursively
                if not self.detect_autoreload(
                    old_result.classes[class_name],
                    new_class_def,
                    prefixes + [class_name],
                ):
                    return False

        return True


# Maintain backward compatibility
def compare_ast(node1: ast.AST | list[ast.AST], node2: ast.AST | list[ast.AST]) -> bool:
    """Compare two AST nodes for structural equality (backward compatibility wrapper)."""
    return ASTAnalyzer.compare_ast(node1, node2)
