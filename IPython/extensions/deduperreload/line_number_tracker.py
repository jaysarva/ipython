"""
Line number tracking system for deduperreload.

This module provides classes to track source code positions and calculate
line number shifts when code is reloaded. It's designed to fix traceback
line number accuracy issues in deduperreload.
"""

from __future__ import annotations

import ast
import inspect
import warnings
from dataclasses import dataclass
from typing import Dict, Set, List, Optional, Any


@dataclass
class CodePosition:
    """Represents the position of a code construct in source."""

    name: str
    type: str  # 'function', 'class', 'method', 'lambda', 'comprehension', 'async_function'
    start_line: int
    end_line: int
    original_start: int  # Track original position for debugging

    def __post_init__(self) -> None:
        if self.end_line < self.start_line:
            self.end_line = self.start_line

    @property
    def size(self) -> int:
        """Number of lines this code construct spans."""
        return self.end_line - self.start_line + 1


@dataclass
class LineShift:
    """Represents a line number shift caused by code changes."""

    position: int  # Line where shift occurs
    delta: int  # Number of lines added/removed (+/-)
    cause: str  # Function name that caused the shift

    def __post_init__(self) -> None:
        if self.delta == 0:
            warnings.warn(f"LineShift with delta=0 for {self.cause}")


class ModuleSourceTracker:
    """Tracks source code for modules and parses code positions."""

    def __init__(self) -> None:
        self.module_snapshots: Dict[str, str] = {}  # module_name -> source
        self.code_positions: Dict[
            str, Dict[str, CodePosition]
        ] = {}  # module_name -> {name -> position}

    def track_module_source(self, module: Any) -> str:
        """Get and cache current module source."""
        module_name = module.__name__
        try:
            source = inspect.getsource(module)
            self.module_snapshots[module_name] = source
            return source
        except (OSError, IOError):
            # Handle cases where source isn't available
            cached_source = self.module_snapshots.get(module_name, "")
            if not cached_source:
                warnings.warn(f"Could not retrieve source for module {module_name}")
            return cached_source

    def parse_all_code_positions(self, source: str) -> Dict[str, CodePosition]:
        """Parse positions of ALL code constructs with __code__ attributes."""
        positions: Dict[str, CodePosition] = {}
        if not source.strip():
            return positions

        try:
            tree = ast.parse(source)
            self._extract_positions_from_ast(tree, positions)
        except SyntaxError as e:
            warnings.warn(f"Syntax error while parsing source: {e}")
        return positions

    def _extract_positions_from_ast(
        self, tree: ast.AST, positions: Dict[str, CodePosition], prefix: str = ""
    ) -> None:
        """Recursively extract code positions from AST."""
        # Use direct iteration over body instead of ast.walk to avoid nested duplication
        for node in getattr(tree, "body", []):
            if isinstance(node, ast.FunctionDef):
                name = f"{prefix}.{node.name}" if prefix else node.name
                positions[name] = CodePosition(
                    name=name,
                    type="function",
                    start_line=node.lineno,
                    end_line=getattr(node, "end_lineno", node.lineno),
                    original_start=node.lineno,
                )
                # Handle nested functions
                self._extract_nested_functions(node, positions, name)

            elif isinstance(node, ast.AsyncFunctionDef):
                name = f"{prefix}.{node.name}" if prefix else node.name
                positions[name] = CodePosition(
                    name=name,
                    type="async_function",
                    start_line=node.lineno,
                    end_line=getattr(node, "end_lineno", node.lineno),
                    original_start=node.lineno,
                )
                # Handle nested functions
                self._extract_nested_functions(node, positions, name)

            elif isinstance(node, ast.ClassDef):
                name = f"{prefix}.{node.name}" if prefix else node.name
                positions[name] = CodePosition(
                    name=name,
                    type="class",
                    start_line=node.lineno,
                    end_line=getattr(node, "end_lineno", node.lineno),
                    original_start=node.lineno,
                )
                # Track methods within class
                self._extract_class_methods(node, positions, name)

        # Handle lambda functions and comprehensions with ast.walk
        for node in ast.walk(tree):
            if isinstance(node, (ast.Lambda)):
                # Lambda functions - use position as identifier since they don't have names
                lambda_id = f"lambda_{node.lineno}_{node.col_offset}"
                name = f"{prefix}.{lambda_id}" if prefix else lambda_id
                positions[name] = CodePosition(
                    name=name,
                    type="lambda",
                    start_line=node.lineno,
                    end_line=getattr(node, "end_lineno", node.lineno),
                    original_start=node.lineno,
                )

            elif isinstance(
                node, (ast.ListComp, ast.DictComp, ast.SetComp, ast.GeneratorExp)
            ):
                # Comprehensions
                comp_type = (
                    type(node)
                    .__name__.lower()
                    .replace("comp", "_comp")
                    .replace("exp", "_exp")
                )
                comp_id = f"{comp_type}_{node.lineno}_{node.col_offset}"
                name = f"{prefix}.{comp_id}" if prefix else comp_id
                positions[name] = CodePosition(
                    name=name,
                    type="comprehension",
                    start_line=node.lineno,
                    end_line=getattr(node, "end_lineno", node.lineno),
                    original_start=node.lineno,
                )

    def _extract_nested_functions(
        self,
        func_node: ast.FunctionDef | ast.AsyncFunctionDef,
        positions: Dict[str, CodePosition],
        parent_name: str,
    ) -> None:
        """Extract nested functions from a function node."""
        # Recursively extract from function body
        self._extract_positions_from_ast(func_node, positions, parent_name)

    def _extract_class_methods(
        self,
        class_node: ast.ClassDef,
        positions: Dict[str, CodePosition],
        class_name: str,
    ) -> None:
        """Extract methods from a class node."""
        for node in class_node.body:
            if isinstance(node, ast.FunctionDef):
                method_name = f"{class_name}.{node.name}"
                positions[method_name] = CodePosition(
                    name=method_name,
                    type="method",
                    start_line=node.lineno,
                    end_line=getattr(node, "end_lineno", node.lineno),
                    original_start=node.lineno,
                )
                # Handle nested functions within methods
                self._extract_nested_functions(node, positions, method_name)

            elif isinstance(node, ast.AsyncFunctionDef):
                method_name = f"{class_name}.{node.name}"
                positions[method_name] = CodePosition(
                    name=method_name,
                    type="method",
                    start_line=node.lineno,
                    end_line=getattr(node, "end_lineno", node.lineno),
                    original_start=node.lineno,
                )
                # Handle nested functions within async methods
                self._extract_nested_functions(node, positions, method_name)

            elif isinstance(node, ast.ClassDef):
                # Nested classes
                nested_class_name = f"{class_name}.{node.name}"
                positions[nested_class_name] = CodePosition(
                    name=nested_class_name,
                    type="class",
                    start_line=node.lineno,
                    end_line=getattr(node, "end_lineno", node.lineno),
                    original_start=node.lineno,
                )
                # Recursively extract from nested class
                self._extract_class_methods(node, positions, nested_class_name)

    def calculate_line_shifts(
        self, module_name: str, reloaded_functions: Set[str]
    ) -> List[LineShift]:
        """Calculate how line numbers have shifted due to reloaded code objects."""
        current_positions = self.code_positions.get(module_name, {})

        # Get stored positions from previous parse (if any)
        # This would be set by a previous call to track_module_source + parse_all_code_positions
        old_positions: Dict[
            str, CodePosition
        ] = {}  # For now, we'll implement this in the next phase

        shifts = []
        for func_name in reloaded_functions:
            if func_name in old_positions and func_name in current_positions:
                old_pos = old_positions[func_name]
                new_pos = current_positions[func_name]

                # Calculate size change
                old_size = old_pos.size
                new_size = new_pos.size
                delta = new_size - old_size

                if delta != 0:
                    shifts.append(
                        LineShift(
                            position=old_pos.end_line, delta=delta, cause=func_name
                        )
                    )

        # Sort shifts by position to apply them in order
        shifts.sort(key=lambda s: s.position)
        return shifts

    def update_positions(
        self, module_name: str, positions: Dict[str, CodePosition]
    ) -> None:
        """Update stored positions for a module."""
        import copy

        self.code_positions[module_name] = copy.deepcopy(positions)

    def get_positions(self, module_name: str) -> Dict[str, CodePosition]:
        """Get stored positions for a module."""
        import copy

        return copy.deepcopy(self.code_positions.get(module_name, {}))

    def clear_module(self, module_name: str) -> None:
        """Clear cached data for a module."""
        self.module_snapshots.pop(module_name, None)
        self.code_positions.pop(module_name, None)
