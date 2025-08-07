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
from typing import Dict, Any


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
    """Tracks source code for modules and parses code positions.

    This class is responsible for:
    - Caching module source code
    - Parsing source code to extract positions of all code constructs
    - Tracking position changes over time
    - Providing position information for line number patching

    The position tracking includes:
    - Functions and async functions (with decorator handling)
    - Classes and nested classes
    - Methods within classes
    - Lambda functions and comprehensions
    - Nested functions within other functions
    """

    def __init__(self) -> None:
        self.module_snapshots: Dict[str, str] = {}  # module_name -> source
        self.code_positions: Dict[str, Dict[str, CodePosition]] = {}
        # module_name -> {name -> position}

    def track_module_source(self, module: Any) -> str:
        """Get and cache current module source code.

        Args:
            module: Module object to get source for

        Returns:
            Source code string, empty if not available
        """
        module_name = module.__name__

        # Check if module has a source file before attempting to get source
        # Modules without __file__ (like synthetic modules created with ModuleType)
        # will cause inspect.getsource() to raise TypeError with misleading
        # "is a built-in module" message, when they're actually just sourceless
        if not hasattr(module, "__file__") or getattr(module, "__file__", None) is None:
            # Fall back to cached source if available for sourceless modules
            cached_source = self.module_snapshots.get(module_name, "")
            if not cached_source:
                # Don't warn for synthetic modules - this is expected behavior
                pass
            return cached_source

        try:
            # Get fresh source code
            source = inspect.getsource(module)
            self.module_snapshots[module_name] = source
            return source
        except (OSError, IOError):
            # Fall back to cached source if available
            cached_source = self.module_snapshots.get(module_name, "")
            if not cached_source:
                warnings.warn(f"Could not retrieve source for module {module_name}")
            return cached_source

    def parse_all_code_positions(self, source: str) -> Dict[str, CodePosition]:
        """Parse positions of ALL code constructs with __code__ attributes.

        This method analyzes the source code AST to find the positions of all
        code constructs that have __code__ attributes, including functions,
        methods, classes, lambdas, and comprehensions.

        Args:
            source: Python source code to parse

        Returns:
            Dictionary mapping qualified names to their positions
        """
        positions: Dict[str, CodePosition] = {}

        if not source.strip():
            return positions

        try:
            tree = ast.parse(source)
            self._extract_all_positions(tree, positions)

            # Normalize spacing in names to be resilient to unusual whitespace
            # in class or function definitions when later combined with module prefixing.
            # We keep keys as-is for exact lookups, but also provide a space-normalized
            # variant (single spaces between identifier tokens) for matching.
            normalized: Dict[str, CodePosition] = {}
            for name, pos in positions.items():
                norm = name.replace("  ", " ")
                # Only add if normalization changed something and key not taken
                if norm != name and norm not in positions:
                    normalized[norm] = pos
            if normalized:
                positions.update(normalized)
        except SyntaxError as e:
            warnings.warn(f"Syntax error while parsing source: {e}")

        return positions

    def _extract_all_positions(
        self, tree: ast.AST, positions: Dict[str, CodePosition], prefix: str = ""
    ) -> None:
        """Extract all code positions from AST tree.

        This method handles the complexity of extracting positions from various
        Python constructs while avoiding duplicates from nested structures.

        Args:
            tree: AST tree or subtree to process
            positions: Dictionary to populate with positions
            prefix: Namespace prefix for nested constructs
        """
        # Extract from direct body elements (functions, classes)
        self._extract_from_body(tree, positions, prefix)

        # Extract special constructs (lambdas, comprehensions) using ast.walk
        self._extract_special_constructs(tree, positions, prefix)

    def _extract_from_body(
        self, tree: ast.AST, positions: Dict[str, CodePosition], prefix: str
    ) -> None:
        """Extract positions from AST body elements using unified dispatch."""
        # Define body element extractors
        extractors = [
            (
                ast.FunctionDef,
                lambda node: self._extract_function_position(
                    node, positions, prefix, "function"
                ),
            ),
            (
                ast.AsyncFunctionDef,
                lambda node: self._extract_function_position(
                    node, positions, prefix, "async_function"
                ),
            ),
            (
                ast.ClassDef,
                lambda node: self._extract_class_position(node, positions, prefix),
            ),
        ]

        for node in getattr(tree, "body", []):
            self._apply_node_extractor(node, extractors)

    def _apply_node_extractor(self, node: ast.AST, extractors: list) -> None:
        """Apply the appropriate extractor for a given node type."""
        for node_type, extractor in extractors:
            if isinstance(node, node_type):
                extractor(node)
                break

    def _extract_function_position(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        positions: Dict[str, CodePosition],
        prefix: str,
        func_type: str,
    ) -> None:
        """Extract position information for a function node."""
        qualified_name = f"{prefix}.{node.name}" if prefix else node.name

        # For decorated functions, start line should be the first decorator
        # This matches how Python sets co_firstlineno
        start_line = node.lineno
        if node.decorator_list:
            start_line = node.decorator_list[0].lineno

        positions[qualified_name] = CodePosition(
            name=qualified_name,
            type=func_type,
            start_line=start_line,
            end_line=getattr(node, "end_lineno", node.lineno),
            original_start=node.lineno,
        )

        # Handle nested functions within this function
        self._extract_nested_functions(node, positions, qualified_name)

    def _extract_class_position(
        self, node: ast.ClassDef, positions: Dict[str, CodePosition], prefix: str
    ) -> None:
        """Extract position information for a class node."""
        qualified_name = f"{prefix}.{node.name}" if prefix else node.name

        positions[qualified_name] = CodePosition(
            name=qualified_name,
            type="class",
            start_line=node.lineno,
            end_line=getattr(node, "end_lineno", node.lineno),
            original_start=node.lineno,
        )

        # Extract methods and nested classes within this class
        self._extract_class_methods(node, positions, qualified_name)

    def _extract_special_constructs(
        self, tree: ast.AST, positions: Dict[str, CodePosition], prefix: str
    ) -> None:
        """Extract positions for special constructs using unified dispatch."""
        # Define special construct extractors
        extractors = [
            (
                ast.Lambda,
                lambda node: self._extract_lambda_position(node, positions, prefix),
            ),
            (
                (ast.ListComp, ast.DictComp, ast.SetComp, ast.GeneratorExp),
                lambda node: self._extract_comprehension_position(
                    node, positions, prefix
                ),
            ),
        ]

        for node in ast.walk(tree):
            self._apply_node_extractor(node, extractors)

    def _extract_lambda_position(
        self, node: ast.Lambda, positions: Dict[str, CodePosition], prefix: str
    ) -> None:
        """Extract position for a lambda function."""
        # Use position as identifier since lambdas don't have names
        lambda_id = f"lambda_{node.lineno}_{node.col_offset}"
        qualified_name = f"{prefix}.{lambda_id}" if prefix else lambda_id

        positions[qualified_name] = CodePosition(
            name=qualified_name,
            type="lambda",
            start_line=node.lineno,
            end_line=getattr(node, "end_lineno", node.lineno),
            original_start=node.lineno,
        )

    def _extract_comprehension_position(
        self, node: ast.expr, positions: Dict[str, CodePosition], prefix: str
    ) -> None:
        """Extract position for a comprehension expression."""
        # Generate readable type name
        node_type = type(node).__name__.lower()
        comp_type = node_type.replace("comp", "_comp").replace("exp", "_exp")

        # Use position as identifier
        comp_id = f"{comp_type}_{node.lineno}_{node.col_offset}"
        qualified_name = f"{prefix}.{comp_id}" if prefix else comp_id

        positions[qualified_name] = CodePosition(
            name=qualified_name,
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
        """Extract nested functions from within a function node.

        Args:
            func_node: Function AST node to search within
            positions: Dictionary to populate with positions
            parent_name: Qualified name of the parent function
        """
        # Recursively extract from function body using parent name as prefix
        self._extract_all_positions(func_node, positions, parent_name)

    def _extract_class_methods(
        self,
        class_node: ast.ClassDef,
        positions: Dict[str, CodePosition],
        class_name: str,
    ) -> None:
        """Extract methods and nested classes from a class node using unified dispatch.

        Args:
            class_node: Class AST node to search within
            positions: Dictionary to populate with positions
            class_name: Qualified name of the class
        """
        # Define class member extractors
        extractors = [
            (
                ast.FunctionDef,
                lambda node: self._extract_method_position(
                    node, positions, class_name, "method"
                ),
            ),
            (
                ast.AsyncFunctionDef,
                lambda node: self._extract_method_position(
                    node, positions, class_name, "method"
                ),
            ),
            (
                ast.ClassDef,
                lambda node: self._extract_nested_class_position(
                    node, positions, class_name
                ),
            ),
        ]

        for node in class_node.body:
            self._apply_node_extractor(node, extractors)

    def _extract_method_position(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        positions: Dict[str, CodePosition],
        class_name: str,
        method_type: str,
    ) -> None:
        """Extract position for a method within a class."""
        method_name = f"{class_name}.{node.name}"

        positions[method_name] = CodePosition(
            name=method_name,
            type=method_type,
            start_line=node.lineno,
            end_line=getattr(node, "end_lineno", node.lineno),
            original_start=node.lineno,
        )

        # Handle nested functions within methods
        self._extract_nested_functions(node, positions, method_name)

    def _extract_nested_class_position(
        self, node: ast.ClassDef, positions: Dict[str, CodePosition], parent_class: str
    ) -> None:
        """Extract position for a nested class."""
        nested_class_name = f"{parent_class}.{node.name}"

        positions[nested_class_name] = CodePosition(
            name=nested_class_name,
            type="class",
            start_line=node.lineno,
            end_line=getattr(node, "end_lineno", node.lineno),
            original_start=node.lineno,
        )

        # Recursively extract from nested class
        self._extract_class_methods(node, positions, nested_class_name)

    def clear_module(self, module_name: str) -> None:
        """Clear all cached data for a module.

        This removes both the source code snapshot and position information.

        Args:
            module_name: Name of the module to clear
        """
        _ = self.module_snapshots.pop(module_name, None)
        _ = self.code_positions.pop(module_name, None)
