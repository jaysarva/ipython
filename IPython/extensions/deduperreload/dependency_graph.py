"""Build and query decorator dependency graphs for deduperreload."""

from __future__ import annotations
import ast
from typing import NamedTuple


class QualifiedFunctionDef(NamedTuple):
    """Function node used in the decorator dependency graph.

    path is a tuple path (e.g., (Module, ClassA, ...)) of the function (excluding the function name).
    func_node is the function's AST node.
    """

    path: tuple[str, ...]
    func_def: ast.FunctionDef | ast.AsyncFunctionDef


class DependencyGraphManager:
    """Track decorator→function edges and query transitive dependents."""

    def __init__(self) -> None:
        """Initialize the dependency graph manager."""
        # Graph tracking decorator dependencies between functions
        self.function_def_by_decorated_path: dict[tuple[str, ...], list[QualifiedFunctionDef]] = {}

    def clear(self) -> None:
        """Clear the dependency graph."""
        self.function_def_by_decorated_path.clear()

    def build_dependency_graph(self, new_ast: ast.Module | ast.ClassDef) -> None:
        """Populate the graph from the given AST."""
        self._gather_dependents(new_ast.body)

    def _gather_dependents(self, body: list[ast.stmt],
                           body_prefixes: list[str] | None = None) -> None:
        """Gather decorator dependencies from a list of statements; recurse into classes."""
        body_prefixes = body_prefixes or []

        for ast_node in body:
            if isinstance(ast_node, ast.ClassDef):
                self._gather_dependents(ast_node.body, body_prefixes + [ast_node.name])
            elif isinstance(ast_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._process_function_decorators(ast_node, body_prefixes)

    def _process_function_decorators(self, func_node: ast.FunctionDef | ast.AsyncFunctionDef,
                                     prefixes: list[str]) -> None:
        """Record edges from decorator names to the qualified function name."""
        dependency_node = QualifiedFunctionDef(path=tuple(prefixes), func_def=func_node)

        for decorator in func_node.decorator_list:
            if not (decorator_path := self._qualified_decorator_path(decorator)):
                continue
            self.function_def_by_decorated_path.setdefault(decorator_path,
                                                           []).append(dependency_node)

    @classmethod
    def _qualified_decorator_path(
            cls,
            decorator: ast.Name | ast.Call | ast.Attribute | ast.expr,
    ) -> tuple[str, ...] | None:
        """Extract name parts from a decorator expression (optionally unwrap calls)."""
        if isinstance(decorator, ast.Name):
            return (decorator.id, )
        elif isinstance(decorator, ast.Call):
            # For calls like @decorator(), extract the function being called
            return cls._qualified_decorator_path(decorator.func)
        elif isinstance(decorator, ast.Attribute) and (prefix := cls._qualified_decorator_path(
                decorator.value)):
            assert prefix is not None
            return prefix + (decorator.attr, )

        return None

    def get_dependents(self, qualname: tuple[str, ...]) -> list[QualifiedFunctionDef]:
        """Return all direct and transitive dependents of the given decorator name."""
        dependents = []
        for dependent_node in self.function_def_by_decorated_path.get(qualname, []):
            # Recursively find dependents of dependents
            dependents.extend(
                self.get_dependents(dependent_node.path + (dependent_node.func_def.name, )))
            # Add the direct dependent
            dependents.append(dependent_node)

        return dependents
