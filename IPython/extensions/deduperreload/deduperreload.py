"""Deduperreload Extension for IPython.

This module provides smart code reloading that can selectively update functions
and classes without reloading entire modules, preserving state and improving
development workflow.

The core idea is to compare AST nodes between old and new versions of code,
identify what has changed, and patch only the changed components in-place.
"""

from __future__ import annotations
import ast
import builtins
import contextlib
import itertools
import os
import platform
import sys
import textwrap
from types import ModuleType
from typing import TYPE_CHECKING, Any, Generator, Iterable, NamedTuple, cast

from IPython.extensions.deduperreload.deduperreload_patching import (
    DeduperReloaderPatchingMixin,
)
from IPython.extensions.deduperreload.line_number_patcher import (
    LineNumberPatcher,
)

if TYPE_CHECKING:
    TDefinitionAst = (
        ast.FunctionDef
        | ast.AsyncFunctionDef
        | ast.Import
        | ast.ImportFrom
        | ast.Assign
        | ast.AnnAssign
    )


def get_module_file_name(module: ModuleType | str) -> str | None:
    """Get the file path for a module.

    Args:
        module: Either a module object or module name as string

    Returns:
        Module file path, or empty string if not accessible
    """
    if isinstance(module, str):
        mod = sys.modules.get(module)
    else:
        mod = module

    if mod is None:
        return ""

    return getattr(mod, "__file__", "") or ""


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

        if isinstance(node1, ast.AST):
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


# Maintain backward compatibility
def compare_ast(node1: ast.AST | list[ast.AST], node2: ast.AST | list[ast.AST]) -> bool:
    """Compare two AST nodes for structural equality (backward compatibility wrapper)."""
    return ASTAnalyzer.compare_ast(node1, node2)


class DependencyNode(NamedTuple):
    """
    Each node represents a function.
    qualified_name: string which represents the namespace/name of the function
    abstract_syntax_tree: subtree of the overall module which corresponds to this function

    qualified_name is of the structure: (namespace1, namespace2, ..., name)

    For example, foo() in the following would be represented as (A, B, foo):

    class A:
        class B:
            def foo():
                pass
    """

    qualified_name: tuple[str, ...]
    abstract_syntax_tree: ast.AST


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


class DeduperReloader(DeduperReloaderPatchingMixin):
    """Smart code reloader that patches only changed functions and classes.

    This reloader performs intelligent analysis of code changes by comparing
    AST (Abstract Syntax Tree) structures between old and new versions of modules.
    Instead of reloading entire modules, it identifies exactly what has changed
    and patches only those specific functions, methods, or classes in-place.

    Key features:
    - Preserves object identity and state when possible
    - Handles nested classes and functions correctly
    - Tracks decorator dependencies for proper reload ordering
    - Maintains line number accuracy in tracebacks
    - Falls back to full reload when changes are too complex

    The reloader works by:
    1. Parsing both old and new module source into AST
    2. Comparing AST nodes to identify changes
    3. Building a tree of what needs to be reloaded
    4. Patching changed code objects in-place using ctypes
    5. Updating line numbers to maintain traceback accuracy
    """

    def __init__(self) -> None:
        # Tree structure tracking what needs to be reloaded
        self._to_autoreload: AutoreloadTree = AutoreloadTree()

        # Cache of module source code for comparison
        self.source_by_modname: dict[str, str] = {}

        # Graph tracking decorator dependencies between functions
        self.dependency_graph: dict[tuple[str, ...], list[DependencyNode]] = {}

        # Whether the reloader is enabled (only works on CPython)
        self._enabled = True

        # Line number patcher for maintaining traceback accuracy
        self.line_patcher = LineNumberPatcher()

        # Feature flag for line number patching
        self.enable_line_number_patching = True

    @property
    def enabled(self) -> bool:
        return self._enabled and platform.python_implementation() == "CPython"

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value

    def update_sources(self) -> None:
        """Update the source code cache for all loaded modules.

        This method scans sys.modules for any new modules that haven't been
        cached yet and reads their source code. It skips:
        - Modules without accessible files
        - Third-party packages (site-packages, dist-packages)
        - Files that can't be read
        """
        if not self.enabled:
            return

        # Find new modules that aren't in our cache
        new_module_names = sys.modules.keys() - self.source_by_modname.keys()

        for module_name in new_module_names:
            module = sys.modules[module_name]
            source_code = self._read_module_source(module)
            self.source_by_modname[module_name] = source_code

    def _read_module_source(self, module: ModuleType) -> str:
        """Read source code for a single module.

        Args:
            module: Module to read source for

        Returns:
            Source code string, or empty string if not readable
        """
        file_path = get_module_file_name(module)

        # Skip if no file or is a third-party package
        if (
            file_path is None
            or "site-packages" in file_path
            or "dist-packages" in file_path
            or not os.access(file_path, os.R_OK)
        ):
            return ""

        # Try to read the file
        try:
            with open(file_path, "r") as f:
                return f.read()
        except Exception:
            return ""

    # Shared instance for detecting constant expressions
    _constexpr_detector = ConstexprDetector()

    @staticmethod
    def is_enum_subclass(node: ast.Module | ast.ClassDef) -> bool:
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

    @classmethod
    def is_constexpr_assign(
        cls, node: ast.AST, parent_node: ast.Module | ast.ClassDef
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
        if cls.is_enum_subclass(parent_node):
            return False

        # All targets must be simple names (not attributes or subscripts)
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if not isinstance(target, ast.Name):
                return False

        # Check if the assigned value is a constant expression
        return cls._constexpr_detector(node.value)

    @classmethod
    def _gather_children(
        cls, body: list[ast.stmt], parent_node: ast.Module | ast.ClassDef
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
            ast_elt = cls._unwrap_expression(ast_node)

            # Categorize the AST element
            if isinstance(ast_elt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                cls._gather_function_def(result, ast_elt)
            elif isinstance(ast_elt, (ast.Import, ast.ImportFrom)):
                cls._gather_import_def(result, ast_elt)
            elif isinstance(ast_elt, ast.ClassDef):
                cls._gather_class_def(result, ast_elt)
            elif isinstance(ast_elt, ast.If):
                cls._gather_if_statement(result, ast_elt, parent_node)
            elif isinstance(ast_elt, (ast.AsyncWith, ast.With)):
                cls._gather_with_statement(result, ast_elt, parent_node)
            elif isinstance(ast_elt, ast.Try):
                cls._gather_try_statement(result, ast_elt, parent_node)
            elif not isinstance(ast_elt, (ast.Ellipsis, ast.Pass)):
                cls._gather_other_statement(result, ast_elt, parent_node)

        return result

    @classmethod
    def _unwrap_expression(cls, ast_node: ast.stmt) -> ast.expr | ast.stmt:
        """Unwrap expression statements to get the actual expression."""
        ast_elt = ast_node
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

    @classmethod
    def _gather_if_statement(
        cls,
        result: GatherResult,
        ast_elt: ast.If,
        parent_node: ast.Module | ast.ClassDef,
    ) -> None:
        """Handle if statements by recursively gathering from both branches."""
        # The condition is unfixable (can't be safely reloaded)
        result.unfixable.append(ast_elt.test)

        # Recursively gather from both branches
        result.inplace_merge(cls._gather_children(ast_elt.body, parent_node))
        result.inplace_merge(cls._gather_children(ast_elt.orelse, parent_node))

    @classmethod
    def _gather_with_statement(
        cls,
        result: GatherResult,
        ast_elt: ast.AsyncWith | ast.With,
        parent_node: ast.Module | ast.ClassDef,
    ) -> None:
        """Handle with statements by marking context items as unfixable."""
        # Context manager items are unfixable
        result.unfixable.extend(ast_elt.items)

        # Recursively gather from the body
        result.inplace_merge(cls._gather_children(ast_elt.body, parent_node))

    @classmethod
    def _gather_try_statement(
        cls,
        result: GatherResult,
        ast_elt: ast.Try,
        parent_node: ast.Module | ast.ClassDef,
    ) -> None:
        """Handle try statements by recursively gathering from all blocks."""
        # Gather from main try block
        result.inplace_merge(cls._gather_children(ast_elt.body, parent_node))

        # Gather from else block
        result.inplace_merge(cls._gather_children(ast_elt.orelse, parent_node))

        # Gather from finally block
        result.inplace_merge(cls._gather_children(ast_elt.finalbody, parent_node))

        # Handle exception handlers
        for handler in ast_elt.handlers:
            if handler.type is not None:
                result.unfixable.append(handler.type)
            result.inplace_merge(cls._gather_children(handler.body, parent_node))

    @classmethod
    def _gather_other_statement(
        cls,
        result: GatherResult,
        ast_elt: ast.expr | ast.stmt,
        parent_node: ast.Module | ast.ClassDef,
    ) -> None:
        """Handle other statements - either constant assignments or unfixable."""
        if cls.is_constexpr_assign(ast_elt, parent_node):
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
        if not self.enabled:
            return False

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

    def _check_dependents(self) -> bool:
        """Check for decorator dependencies and add them to the reload tree.

        When a decorator function is modified, we also need to reload any
        functions that use that decorator, since the decorator application
        happens at function definition time.

        Returns:
            True (always succeeds)
        """
        dependent_nodes = self._check_dependents_inner()
        for node in dependent_nodes:
            self._add_node_to_autoreload_tree(node)
        return True

    def _add_node_to_autoreload_tree(self, node: DependencyNode) -> None:
        """Add a dependency node to the autoreload tree.

        Args:
            node: Dependency node representing a function that needs reloading
        """
        if not node.qualified_name:
            return

        # Navigate to the appropriate scope in the tree
        scope_prefixes = list(node.qualified_name[:-1])
        current_scope = self._to_autoreload.traverse_prefixes(scope_prefixes)

        # Add the function to be reloaded
        if node.abstract_syntax_tree is not None:
            function_name = node.qualified_name[-1]
            current_scope.defs_to_reload.append(
                ((function_name,), node.abstract_syntax_tree)
            )

    def _check_dependents_inner(
        self, prefixes: list[str] | None = None
    ) -> list[DependencyNode]:
        """Recursively check for dependent functions that need reloading.

        Args:
            prefixes: Current namespace prefixes

        Returns:
            List of dependency nodes that need to be reloaded
        """
        prefixes = prefixes or []
        current_scope = self._to_autoreload.traverse_prefixes(prefixes)
        dependent_nodes = []

        # Check dependencies for functions being reloaded
        for (func_name, *_), _ in current_scope.defs_to_reload:
            qualified_name = tuple(prefixes + [func_name])
            dependent_nodes.extend(self._gen_dependents(qualified_name))

        # Recursively check new nested classes
        for class_name in current_scope.new_nested_classes:
            nested_dependents = self._check_dependents_inner(prefixes + [class_name])
            dependent_nodes.extend(nested_dependents)

        return dependent_nodes

    def _gen_dependents(self, qualname: tuple[str, ...]) -> list[DependencyNode]:
        """Generate all functions that depend on a given function (recursively).

        Args:
            qualname: Qualified name of the function to find dependents for

        Returns:
            List of all dependent functions
        """
        if qualname not in self.dependency_graph:
            return []

        dependents = []
        for dependent_node in self.dependency_graph[qualname]:
            # Recursively find dependents of dependents
            dependents.extend(self._gen_dependents(dependent_node.qualified_name))
            # Add the direct dependent
            dependents.append(dependent_node)

        return dependents

    def _patch_namespace_inner(
        self, ns: ModuleType | type, prefixes: list[str] | None = None
    ) -> bool:
        """Patch all definitions marked for reloading in a specific namespace.

        This method handles the actual patching of functions, methods, classes,
        and other definitions that have been identified as needing updates.

        The patching process:
        1. Execute new code in the old object's global environment
        2. Extract the new function/class from the execution result
        3. Patch the old object's attributes with the new one's attributes
        4. Handle special cases like properties, static methods, etc.

        Args:
            ns: The namespace (module or class) to patch
            prefixes: List of nested scope names leading to this namespace

        Returns:
            True if patching succeeded, False otherwise
        """
        prefixes = prefixes or []
        current_scope = self._to_autoreload.traverse_prefixes(prefixes)
        target_namespace = self._resolve_target_namespace(ns, prefixes)
        root_module = self._get_root_module(ns)
        # Patch all definitions that need reloading
        for names, new_ast_def in current_scope.defs_to_reload:
            if isinstance(new_ast_def, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Handle function/method patching
                if not self._patch_function_definition(
                    names, new_ast_def, target_namespace, ns, prefixes
                ):
                    return False
            else:
                # Handle other definitions (imports, assignments, etc.)
                if not self._patch_other_definition(
                    names, new_ast_def, target_namespace, ns, prefixes
                ):
                    return False
        # Clean up completed reload operations
        self._cleanup_current_scope(current_scope, target_namespace, ns)

        # Recursively patch nested scopes (classes)
        if not self._patch_nested_scopes(current_scope, ns, prefixes):
            return False

        # Update line numbers after patching (only at root module level)
        self._update_line_numbers_if_needed(prefixes, root_module)

        return True

    def _resolve_target_namespace(
        self, ns: ModuleType | type, prefixes: list[str]
    ) -> Any:
        """Resolve the target namespace by following the prefix chain."""
        target = ns
        for prefix in prefixes:
            target = target.__dict__[prefix]
        return target

    def _get_root_module(self, ns: ModuleType | type) -> ModuleType | type | None:
        """Get the root module for line number patching purposes."""
        if isinstance(ns, ModuleType):
            return ns
        else:
            # For class types, get the module they belong to
            module_name = getattr(ns, "__module__", "")
            return sys.modules.get(module_name) if module_name else ns

    def _patch_function_definition(
        self,
        names: tuple[str, ...],
        new_ast_def: ast.FunctionDef | ast.AsyncFunctionDef,
        target_namespace: Any,
        ns: ModuleType | type,
        prefixes: list[str],
    ) -> bool:
        """Patch a function or method definition."""
        if len(names) != 1:
            return True  # Skip multi-name definitions for functions

        name = names[0]

        # Check if this is an existing function that needs patching
        if name in target_namespace.__dict__:
            old_function = target_namespace.__dict__[name]

            # Execute new function code to get the new function object
            new_function = self._execute_function_code(
                new_ast_def, ns, prefixes, old_function
            )
            if new_function is None:
                return False

            # Patch the old function with the new one
            return self._patch_function_object(
                old_function, new_function, len(prefixes) > 0
            )
        else:
            # This is a new function being added - execute and add it
            return self._add_new_function(
                names, new_ast_def, target_namespace, ns, prefixes
            )

    def _execute_function_code(
        self,
        new_ast_def: ast.FunctionDef | ast.AsyncFunctionDef,
        ns: ModuleType | type,
        prefixes: list[str],
        old_function: Any,
    ) -> Any:
        """Execute the new function code and return the resulting function object."""
        try:
            # Generate source code from AST
            func_code = textwrap.dedent(ast.unparse(new_ast_def))

            # Wrap in class if this is a method
            is_method = len(prefixes) > 0
            if is_method:
                func_code = "class __autoreload_class__:\n" + textwrap.indent(
                    func_code, "    "
                )

            # Set up execution environment
            global_env = (
                dict(ns.__dict__) if not isinstance(ns.__dict__, dict) else ns.__dict__
            )
            local_env: dict[str, Any] = {}

            # Get filename for proper traceback
            filename = getattr(old_function, "__code__", None)
            filename = filename.co_filename if filename else "<string>"

            # Compile and execute
            compiled_code = compile(func_code, filename, "exec", dont_inherit=True)
            exec(compiled_code, global_env, local_env)

            # Extract the new function
            if is_method:
                return getattr(local_env["__autoreload_class__"], new_ast_def.name)
            else:
                return local_env[new_ast_def.name]

        except Exception:
            return None

    def _patch_function_object(
        self, old_function: Any, new_function: Any, is_method: bool
    ) -> bool:
        """Patch an old function object with a new one."""
        try:
            # Handle static/class method wrappers
            if isinstance(old_function, (staticmethod, classmethod)):
                old_function = old_function.__func__
            if isinstance(new_function, (staticmethod, classmethod)):
                new_function = new_function.__func__

            # Handle property objects
            if isinstance(old_function, property) and isinstance(
                new_function, property
            ):
                return self._patch_property_object(
                    old_function, new_function, is_method
                )
            elif isinstance(old_function, property) or isinstance(
                new_function, property
            ):
                raise ValueError(
                    "adding or removing property decorations not supported"
                )
            else:
                # Patch regular function
                self.patch_function(old_function, new_function, is_method)
                return True

        except Exception:
            return False

    def _patch_property_object(
        self, old_prop: Any, new_prop: Any, is_method: bool
    ) -> bool:
        """Patch a property object's getter, setter, and deleter."""
        try:
            for attr in ("fget", "fset", "fdel"):
                old_attr = getattr(old_prop, attr)
                new_attr = getattr(new_prop, attr)

                if old_attr is None or new_attr is None:
                    # One is None, just copy the attribute
                    self.try_patch_attr(old_prop, new_prop, attr)
                else:
                    # Both exist, patch the function
                    self.patch_function(old_attr, new_attr, is_method)
            return True
        except Exception:
            return False

    def _add_new_function(
        self,
        names: tuple[str, ...],
        new_ast_def: ast.FunctionDef | ast.AsyncFunctionDef,
        target_namespace: Any,
        ns: ModuleType | type,
        prefixes: list[str],
    ) -> bool:
        """Add a new function to the target namespace."""
        try:
            # Execute the function definition
            local_env: dict[str, Any] = {}

            # Generate source code from AST
            func_code = textwrap.dedent(ast.unparse(new_ast_def))

            # Wrap in class if this is a method
            is_method = len(prefixes) > 0
            if is_method:
                func_code = "class __autoreload_class__:\n" + textwrap.indent(
                    func_code, "    "
                )

            # Set up execution environment
            global_env = (
                dict(ns.__dict__) if not isinstance(ns.__dict__, dict) else ns.__dict__
            )
            global_env.update(target_namespace.__dict__)

            # Compile and execute
            compiled_code = compile(
                func_code, "<autoreload>", "exec", dont_inherit=True
            )
            exec(compiled_code, global_env, local_env)

            # Extract and set the new function
            if is_method:
                new_function = getattr(
                    local_env["__autoreload_class__"], new_ast_def.name
                )
            else:
                new_function = local_env[new_ast_def.name]

            setattr(target_namespace, names[0], new_function)
            return True

        except Exception:
            return False

    def _patch_other_definition(
        self,
        names: tuple[str, ...],
        new_ast_def: ast.AST,
        target_namespace: Any,
        ns: ModuleType | type,
        prefixes: list[str],
    ) -> bool:
        """Patch non-function definitions (imports, assignments, etc.)."""
        try:
            # Execute the new definition
            local_env: dict[str, Any] = {}
            global_env = ns.__dict__ | target_namespace.__dict__
            exec(ast.unparse(new_ast_def), global_env, local_env)

            # Set the new values in the target namespace
            for name in names:
                setattr(target_namespace, name, local_env[name])

            return True
        except Exception:
            return False

    def _cleanup_current_scope(
        self,
        current_scope: AutoreloadTree,
        target_namespace: Any,
        ns: ModuleType | type,
    ) -> None:
        """Clean up the current scope after patching."""
        # Clear the reload list
        current_scope.defs_to_reload.clear()

        # Delete removed definitions
        for name in current_scope.defs_to_delete:
            try:
                delattr(target_namespace, name)
            except (AttributeError, TypeError, ValueError):
                # If deletion fails, let the stale definition remain
                pass
        current_scope.defs_to_delete.clear()

        # Add new nested classes
        for class_name, class_ast_node in current_scope.new_nested_classes.items():
            try:
                local_env: dict[str, Any] = {}
                global_env = dict(vars(ns))
                global_env.update(vars(target_namespace))
                exec(ast.unparse(class_ast_node), global_env, local_env)
                setattr(target_namespace, class_name, local_env[class_name])
            except Exception as e:
                # If adding new class fails, try alternative approach
                import warnings

                warnings.warn(f"Failed to add nested class {class_name}: {e}")
                # Try a simpler approach: just exec in the target namespace
                try:
                    exec(ast.unparse(class_ast_node), target_namespace.__dict__)
                except Exception:
                    # If that also fails, continue with other operations
                    pass
        current_scope.new_nested_classes.clear()

    def _patch_nested_scopes(
        self, current_scope: AutoreloadTree, ns: ModuleType | type, prefixes: list[str]
    ) -> bool:
        """Recursively patch nested scopes (classes)."""
        for class_name in list(current_scope.children.keys()):
            if not self._patch_namespace(ns, prefixes + [class_name]):
                return False
        current_scope.children.clear()
        return True

    def _update_line_numbers_if_needed(
        self, prefixes: list[str], root_module: ModuleType | type | None
    ) -> None:
        """Update line numbers if we're at the root level and feature is enabled."""
        if (
            not prefixes
            and self.enable_line_number_patching
            and isinstance(root_module, ModuleType)
        ):
            try:
                # Note: force_update=True ensures all line numbers are updated
                # even when no explicit shifts are detected. This is necessary
                # because ANY change to a module can affect line numbers.
                self.line_patcher.update_all_code_object_line_numbers(
                    root_module, [], force_update=True
                )
            except Exception as e:
                # Line number patching is optional - don't break main functionality
                import warnings

                warnings.warn(f"Line number patching failed: {e}")

    def _patch_namespace(
        self, ns: ModuleType | type, prefixes: list[str] | None = None
    ) -> bool:
        """
        Wrapper for patching all elements in a namespace as specified by the to_autoreload member variable.
        Returns `true` if patching was successful, and `false` if unsuccessful.
        """
        try:
            return self._patch_namespace_inner(ns, prefixes=prefixes)
        except Exception:
            return False

    def maybe_reload_module(self, module: ModuleType) -> bool:
        """Attempt to reload a module using targeted patching.

        This is the main entry point for the dedupe reloader. It:
        1. Reads the current module source
        2. Compares with cached source to detect changes
        3. Attempts targeted reloading if changes are suitable
        4. Falls back to indicating full reload is needed if not

        Args:
            module: The module to potentially reload

        Returns:
            True if targeted reload succeeded, False if full reload needed
        """
        if not self.enabled:
            return False

        # Get module information
        module_name = getattr(module, "__name__", None)
        if not module_name:
            return False

        file_path = get_module_file_name(module)
        if file_path is None:
            return False

        # Read current source code
        try:
            with open(file_path, "r") as f:
                new_source_code = f.read()
        except Exception:
            return False

        # Try targeted reloading if we have old source to compare
        reload_succeeded = False
        old_source_code = self.source_by_modname.get(module_name)
        if old_source_code:
            reload_succeeded = self._attempt_targeted_reload(
                old_source_code, new_source_code, module
            )

        # Update source cache and reset state
        self.source_by_modname[module_name] = new_source_code
        self._to_autoreload = AutoreloadTree()

        return reload_succeeded

    def _attempt_targeted_reload(
        self, old_source: str, new_source: str, module: ModuleType
    ) -> bool:
        """Attempt targeted reload by comparing old and new source.

        Args:
            old_source: Previous source code
            new_source: Current source code
            module: Module object to patch

        Returns:
            True if targeted reload succeeded, False otherwise
        """
        try:
            # Parse both versions into AST
            old_module_ast = ast.parse(old_source)
            new_module_ast = ast.parse(new_source)
        except Exception:
            return False

        # Attempt the reload process
        try:
            with contextlib.suppress():
                # Build dependency graph for decorator handling
                self._build_dependency_graph(new_module_ast)

                # Check if we can handle the changes
                if (
                    self.detect_autoreload(old_module_ast, new_module_ast)
                    and self._check_dependents()
                    and self._patch_namespace(module)
                ):
                    return True
        except Exception:
            pass

        return False

    def _separate_name(
        self,
        decorator: ast.Attribute | ast.Name | ast.Call | ast.expr,
        accept_calls: bool,
    ) -> list[str] | None:
        """Extract a qualified name from a decorator expression.

        This handles various decorator patterns:
        - Simple names: @decorator
        - Attribute access: @module.decorator
        - Function calls: @decorator() or @module.decorator()

        Args:
            decorator: AST node representing the decorator
            accept_calls: Whether to accept function call decorators

        Returns:
            List of name components, or None if not extractable
        """
        if isinstance(decorator, ast.Name):
            return [decorator.id]
        elif isinstance(decorator, ast.Call) and accept_calls:
            # For calls like @decorator(), extract the function being called
            return self._separate_name(decorator.func, False)
        elif isinstance(decorator, ast.Attribute):
            # For attribute access like @module.decorator
            prefix = self._separate_name(decorator.value, False)
            if prefix:
                return prefix + [decorator.attr]

        return None

    def _gather_dependents(
        self, body: list[ast.stmt], body_prefixes: list[str] | None = None
    ) -> bool:
        """Gather decorator dependencies from AST body.

        Args:
            body: List of AST statements to analyze
            body_prefixes: Namespace prefixes for nested scopes

        Returns:
            True (always succeeds)
        """
        body_prefixes = body_prefixes or []

        for ast_node in body:
            if isinstance(ast_node, ast.ClassDef):
                # Recursively process class body
                self._gather_dependents(ast_node.body, body_prefixes + [ast_node.name])
            elif isinstance(ast_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Process function decorators
                self._process_function_decorators(ast_node, body_prefixes)

        return True

    def _process_function_decorators(
        self, func_node: ast.FunctionDef | ast.AsyncFunctionDef, prefixes: list[str]
    ) -> None:
        """Process decorators for a single function."""
        qualified_name = tuple(prefixes + [func_node.name])
        dependency_node = DependencyNode(qualified_name, func_node)

        for decorator in func_node.decorator_list:
            decorator_path = self._separate_name(decorator, True)
            if decorator_path:
                decorator_tuple = tuple(decorator_path)
                self.dependency_graph.setdefault(decorator_tuple, []).append(
                    dependency_node
                )

    def _build_dependency_graph(self, new_ast: ast.Module | ast.ClassDef) -> bool:
        """Build a dependency graph for decorator relationships.

        This graph tracks which functions depend on which decorators,
        so that when a decorator function changes, we can also reload
        the functions that use it.

        Args:
            new_ast: AST to analyze for dependencies

        Returns:
            True (always succeeds, dependency tracking is best-effort)
        """
        return self._gather_dependents(new_ast.body)
