"""Dependency Graph Module for Deduperreload Extension.

This module handles the tracking and management of decorator dependencies and function
relationships within the deduperreload system. It identifies which functions depend on
which decorators so that when a decorator function changes, we can also reload the 
functions that use it.

Key Features:
- Builds dependency graphs for decorator relationships
- Tracks qualified names and AST nodes for dependent functions
- Recursively finds all dependents when a decorator changes
- Handles nested scopes and complex decorator patterns

Classes:
- DependencyNode: Represents a function with its qualified name and AST
- DependencyGraphManager: Manages the dependency graph and related operations
"""

from __future__ import annotations
import ast
from typing import NamedTuple


class DependencyNode(NamedTuple):
    """
    Each node represents a function with dependency information.

    Attributes:
        qualified_name: Tuple representing the namespace/name of the function
        abstract_syntax_tree: AST subtree corresponding to this function

    The qualified_name structure: (namespace1, namespace2, ..., name)

    Example: foo() in the following would be represented as (A, B, foo):

    class A:
        class B:
            def foo():
                pass
    """

    qualified_name: tuple[str, ...]
    abstract_syntax_tree: ast.AST


class DependencyGraphManager:
    """Manages decorator dependency relationships for the deduperreload system.

    This class builds and maintains a graph of decorator dependencies, allowing
    the reloader to identify which functions need to be reloaded when a decorator
    function changes.

    The dependency graph maps decorator names to lists of functions that use them:
    {
        ('my_decorator',): [DependencyNode(('MyClass', 'method1'), ast_node), ...],
        ('module', 'decorator'): [DependencyNode(('func2',), ast_node), ...],
    }
    """

    def __init__(self) -> None:
        """Initialize the dependency graph manager."""
        # Graph tracking decorator dependencies between functions
        self.dependency_graph: dict[tuple[str, ...], list[DependencyNode]] = {}

    def clear(self) -> None:
        """Clear the dependency graph."""
        self.dependency_graph.clear()

    def build_dependency_graph(self, new_ast: ast.Module | ast.ClassDef) -> bool:
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

    def get_dependents(self, qualname: tuple[str, ...]) -> list[DependencyNode]:
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
            dependents.extend(self.get_dependents(dependent_node.qualified_name))
            # Add the direct dependent
            dependents.append(dependent_node)

        return dependents

    def has_dependents(self, qualname: tuple[str, ...]) -> bool:
        """Check if a function has any dependents.

        Args:
            qualname: Qualified name of the function to check

        Returns:
            True if the function has dependents, False otherwise
        """
        return qualname in self.dependency_graph

    def get_all_decorator_names(self) -> set[tuple[str, ...]]:
        """Get all decorator names tracked in the dependency graph.

        Returns:
            Set of all decorator qualified names
        """
        return set(self.dependency_graph.keys())
