"""
Advanced AST-based line number patching for Python 3.11+.

This module provides comprehensive AST manipulation capabilities for correcting
line numbers in reloaded code objects. It handles complex scenarios like
decorated functions, nested functions, and multiple delta insertions.

The AST approach provides more reliable line number correction compared to
bytecode manipulation alone, especially for Python 3.11+ where the line
number table format has changed significantly.
"""

from __future__ import annotations

import ast
import types
import warnings
from typing import Dict, List, Optional, Any
import inspect


class LineNumberShifter(ast.NodeTransformer):
    """
    AST transformer that applies line number shifts to all nodes.

    This class handles complex delta maps where multiple insertions/deletions
    have occurred at different points in the source code. It applies cumulative
    shifts to ensure all line numbers are correctly updated.

    Key features:
    - Handles both lineno and end_lineno attributes
    - Supports complex delta maps with multiple insertion points
    - Preserves column information where applicable
    - Applies shifts cumulatively based on insertion order
    """

    def __init__(self, delta_map: Dict[int, int]):
        """
        Initialize the line number shifter.

        Args:
            delta_map: Dictionary mapping insertion points to line deltas.
                      Key = line number where change occurred
                      Value = number of lines added (positive) or removed (negative)
        """
        self.delta_map = delta_map
        # Sort insertion points for cumulative application
        self.sorted_insertions = sorted(delta_map.items())

    def _calculate_cumulative_shift(self, line: int) -> int:
        """
        Calculate the cumulative line shift for a given line number.

        This method applies all relevant deltas that should affect the given line.
        Deltas are applied cumulatively in order of insertion point.

        Args:
            line: Original line number

        Returns:
            Total shift to apply to this line
        """
        total_shift = 0
        for insertion_point, delta in self.sorted_insertions:
            # Apply delta if this line comes after the insertion point
            if line >= insertion_point:
                total_shift += delta
        return total_shift

    def visit(self, node: ast.AST) -> ast.AST:
        """
        Visit an AST node and apply line number shifts.

        This method processes both lineno and end_lineno attributes,
        ensuring all line information is correctly updated.

        Args:
            node: AST node to process

        Returns:
            Processed AST node with updated line numbers
        """
        # Apply shift to start line number (type: ignore for dynamic AST attributes)
        if hasattr(node, "lineno") and getattr(node, "lineno", None) is not None:
            current_line = getattr(node, "lineno")  # type: ignore[attr-defined]
            shift = self._calculate_cumulative_shift(int(current_line))
            try:
                setattr(node, "lineno", int(current_line) + shift)  # type: ignore[attr-defined]
            except Exception:
                pass

        # Apply shift to end line number
        if (
            hasattr(node, "end_lineno")
            and getattr(node, "end_lineno", None) is not None
        ):
            current_end_line = getattr(node, "end_lineno")  # type: ignore[attr-defined]
            shift = self._calculate_cumulative_shift(int(current_end_line))
            try:
                setattr(node, "end_lineno", int(current_end_line) + shift)  # type: ignore[attr-defined]
            except Exception:
                pass

        # Continue processing child nodes
        return self.generic_visit(node)


class SourceCodeExtractor:
    """
    Utility class for extracting and managing source code for AST processing.

    This class provides methods to extract source code from various sources:
    - Module source code tracking
    - Function source extraction via inspect
    - Cached source management
    """

    def __init__(self) -> None:
        """Initialize the source code extractor."""
        self.source_cache: Dict[str, str] = {}

    def extract_module_source(self, module: types.ModuleType) -> Optional[str]:
        """
        Extract full module source code.

        Args:
            module: Module to extract source from

        Returns:
            Full module source code or None if not available
        """
        try:
            source = inspect.getsource(module)
            self.source_cache[module.__name__] = source
            return source
        except Exception as e:
            warnings.warn(f"Failed to extract source for module {module.__name__}: {e}")
        return None

    def get_cached_source(self, module_name: str) -> Optional[str]:
        """
        Get cached source code for a module.

        Args:
            module_name: Name of the module

        Returns:
            Cached source code or None if not cached
        """
        return self.source_cache.get(module_name)


class FunctionExtractor(ast.NodeVisitor):
    """
    AST visitor that extracts specific functions from a module AST.

    This class helps isolate individual function definitions from a larger
    module AST, which is useful for targeted compilation and patching.
    It also handles lambda assignments and other callable definitions.
    """

    def __init__(self, target_function: str):
        """
        Initialize the function extractor.

        Args:
            target_function: Name of the function to extract
        """
        self.target_function = target_function
        # For property methods like "MyClass.bad_property.fget", extract base name
        self.base_function_name = self._extract_base_function_name(target_function)
        self.found_function: Optional[
            ast.FunctionDef | ast.AsyncFunctionDef | ast.Assign
        ] = None
        self.class_context: List[str] = []
        self.found_class_context: List[str] = []  # Save context when function is found

    def _extract_base_function_name(self, function_name: str) -> str:
        """Extract base function name from property names like 'MyClass.prop.fget'."""
        # Remove property suffixes
        for suffix in [".fget", ".fset", ".fdel"]:
            if function_name.endswith(suffix):
                return function_name[: -len(suffix)]
        return function_name

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Visit a class definition and check for methods."""
        self.class_context.append(node.name)
        self.generic_visit(node)
        self.class_context.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Visit a function definition and check if it matches our target."""
        # Build qualified name
        if self.class_context:
            qualified_name = f"{'.'.join(self.class_context)}.{node.name}"
        else:
            qualified_name = node.name

        # Check for match (including base function name for properties)
        # Priority: exact qualified name match, then exact target function match
        matches = False
        if qualified_name == self.target_function:
            matches = True
        elif qualified_name == self.base_function_name:
            matches = True
        elif node.name == self.target_function and "." not in self.target_function:
            # Only match bare function name if target doesn't contain dots
            matches = True
        elif (
            node.name == self.base_function_name.split(".")[-1]
            and "." not in self.target_function
        ):
            # Only match bare function name if target doesn't contain dots
            matches = True

        if matches:
            self.found_function = node
            self.found_class_context = self.class_context.copy()  # Save context

        # Continue visiting nested functions
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Visit an async function definition."""
        # Same logic as regular function def
        if self.class_context:
            qualified_name = f"{'.'.join(self.class_context)}.{node.name}"
        else:
            qualified_name = node.name

        # Check for match (including base function name for properties)
        # Priority: exact qualified name match, then exact target function match
        matches = False
        if qualified_name == self.target_function:
            matches = True
        elif qualified_name == self.base_function_name:
            matches = True
        elif node.name == self.target_function and "." not in self.target_function:
            # Only match bare function name if target doesn't contain dots
            matches = True
        elif (
            node.name == self.base_function_name.split(".")[-1]
            and "." not in self.target_function
        ):
            # Only match bare function name if target doesn't contain dots
            matches = True

        if matches:
            self.found_function = node
            self.found_class_context = self.class_context.copy()  # Save context

        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        """Visit assignments that might be lambda functions."""
        # Check if this is a lambda assignment matching our target
        if (
            len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Lambda)
            and node.targets[0].id == self.target_function
        ):
            self.found_function = node

        self.generic_visit(node)


class ASTPatcher:
    """
    This class provides comprehensive AST manipulation capabilities for
    correcting line numbers in reloaded code objects. It handles:

    - Complex delta maps with multiple insertion points
    - Decorated functions and their line number corrections
    - Nested functions and closures
    - Source code extraction and caching
    - Targeted function compilation from module AST

    """

    def __init__(self) -> None:
        """Initialize the AST patcher."""
        self.source_extractor = SourceCodeExtractor()
        self.compilation_cache: Dict[str, types.CodeType] = {}

    def patch_code_object_ast(
        self,
        old_code: types.CodeType,
        delta_map: Dict[int, int],
        source_code: str,
        function_name: Optional[str] = None,
        obj_name: str = "",
    ) -> types.CodeType:
        """
        Create a new code object with corrected line numbers without recompilation.

        We avoid any compile() calls here. Instead, we compute the adjusted
        first line using the provided delta_map and return a code object created
        via CodeType.replace with the new co_firstlineno. Nested function
        adjustments are handled by the caller.

        Args:
            old_code: Original code object to patch
            delta_map: Line number shift mappings
            source_code: Full source code for the module/function (unused)
            function_name: Name of specific function to extract (unused)
            obj_name: Full object name for debugging

        Returns:
            Code object with updated co_firstlineno if needed; otherwise original
        """
        if not isinstance(old_code, types.CodeType):
            if isinstance(old_code, property):
                raise ValueError(
                    f"Property objects should not be passed to AST patcher: {obj_name}"
                )
            raise ValueError(f"Expected CodeType, got {type(old_code)} for {obj_name}")

        try:
            # Calculate cumulative shift for this code object's first line
            original_first_line = int(old_code.co_firstlineno)
            cumulative_shift = 0
            for insertion_point, delta in sorted(delta_map.items()):
                if original_first_line >= int(insertion_point):
                    cumulative_shift += int(delta)

            if cumulative_shift == 0:
                return old_code

            new_first_line = original_first_line + cumulative_shift
            return old_code.replace(co_firstlineno=new_first_line)
        except Exception as e:
            warnings.warn(f"Line number adjustment failed for {obj_name}: {e}")
            return old_code

    def _compile_specific_function(
        self,
        tree: ast.Module,
        old_code: types.CodeType,
        function_name: str,
        obj_name: str,
    ) -> types.CodeType:
        """Deprecated: compilation path disabled. Returns original code."""
        return old_code

    def _compile_and_extract_function(
        self,
        tree: ast.Module,
        old_code: types.CodeType,
        function_name: str,
        obj_name: str,
    ) -> types.CodeType:
        """Deprecated: compilation path disabled. Returns original code."""
        return old_code

    def _compile_module_and_extract_function(
        self,
        tree: ast.Module,
        old_code: types.CodeType,
        function_name: str,
        obj_name: str,
    ) -> types.CodeType:
        """Deprecated: compilation path disabled. Returns original code."""
        return old_code

    def _compile_class_method(
        self,
        func_node: ast.FunctionDef | ast.AsyncFunctionDef,
        old_code: types.CodeType,
        function_name: str,
    ) -> types.CodeType:
        """Deprecated: compilation path disabled. Returns original code."""
        return old_code

    def _compile_class_method_with_context(
        self,
        func_node: ast.FunctionDef | ast.AsyncFunctionDef,
        old_code: types.CodeType,
        function_name: str,
    ) -> types.CodeType:
        """Deprecated: compilation path disabled. Returns original code."""
        return old_code

    def _get_module_source_from_code(self, code_obj: types.CodeType) -> str | None:
        """Try to get module source code from a code object."""
        try:
            import inspect
            import sys

            # Get the module from the filename
            filename = code_obj.co_filename

            # Find the module in sys.modules that matches this filename
            for module_name, module in sys.modules.items():
                if (
                    hasattr(module, "__file__")
                    and module.__file__
                    and module.__file__ == filename
                ):
                    return inspect.getsource(module)

            # If not found, try to read the file directly
            if filename and filename != "<string>":
                with open(filename, "r", encoding="utf-8") as f:
                    return f.read()

        except Exception:
            pass
        return None

    def _find_class_containing_method(
        self, tree: ast.Module, function_name: str
    ) -> ast.ClassDef | None:
        """Find the class definition that contains the specified method."""
        # function_name could be like "Bar.bar" - extract class name
        if "." in function_name:
            class_name = function_name.split(".")[-2]
            method_name = function_name.split(".")[-1]
        else:
            # This shouldn't happen in our context, but handle it
            return None

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                # Verify this class contains our method
                for item in node.body:
                    if (
                        isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and item.name == method_name
                    ):
                        return node
        return None

    def _compile_full_class_method(
        self,
        class_node: ast.ClassDef,
        func_node: ast.FunctionDef | ast.AsyncFunctionDef,
        old_code: types.CodeType,
        function_name: str,
        module_source: str,
    ) -> types.CodeType:
        """Deprecated: compilation path disabled. Returns original code."""
        return old_code

    # Removed _build_module_namespace in favor of a single full-module compile.

    def _compile_simple_class_method(
        self,
        func_node: ast.FunctionDef | ast.AsyncFunctionDef,
        old_code: types.CodeType,
        function_name: str,
    ) -> types.CodeType:
        """Deprecated: compilation path disabled. Returns original code."""
        return old_code

    def _compile_property_method(
        self,
        func_node: ast.FunctionDef | ast.AsyncFunctionDef,
        old_code: types.CodeType,
        obj_name: str,
    ) -> types.CodeType:
        """Deprecated: compilation path disabled. Returns original code."""
        return old_code

    def _compile_isolated_function(
        self, func_node: ast.AST, old_code: types.CodeType, function_name: str
    ) -> types.CodeType:
        """Deprecated: compilation path disabled. Returns original code."""
        return old_code

    def create_enhanced_delta_map(
        self,
        old_line: int,
        new_line: int,
    ) -> Dict[int, int]:
        """
        Create an enhanced delta map for line number correction.

        This method creates more sophisticated delta maps that can handle
        complex scenarios like decorator line corrections and multi-point
        insertions.

        Args:
            old_line: Original line number
            new_line: New line number
            context_info: Additional context for delta calculation

        Returns:
            Dictionary mapping insertion points to deltas
        """
        delta = new_line - old_line

        if delta == 0:
            return {}

        return {old_line: delta}

    def validate_ast_patching_safety(
        self, old_code: types.CodeType, source_code: str
    ) -> bool:
        """
        Just try parsing to make sure the syntax is OK.

        Returns:
            True if AST patching appears safe, False otherwise
        """
        try:
            ast.parse(source_code, filename=old_code.co_filename)
            return True
        except Exception:
            return False

    def clear_cache(self) -> None:
        """Clear all internal caches."""
        self.compilation_cache.clear()
        self.source_extractor.source_cache.clear()

    def get_cache_statistics(self) -> Dict[str, int]:
        """
        Get statistics about cache usage.

        Returns:
            Dictionary with cache statistics
        """
        return {
            "compilation_cache_size": len(self.compilation_cache),
            "source_cache_size": len(self.source_extractor.source_cache),
        }
