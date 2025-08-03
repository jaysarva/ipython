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
        # Apply shift to start line number
        if hasattr(node, "lineno") and node.lineno is not None:
            shift = self._calculate_cumulative_shift(node.lineno)
            node.lineno += shift

        # Apply shift to end line number
        if hasattr(node, "end_lineno") and node.end_lineno is not None:
            shift = self._calculate_cumulative_shift(node.end_lineno)
            node.end_lineno += shift

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
            # Try to get source from inspect
            if hasattr(module, "__file__") and module.__file__:
                filename = module.__file__
                if filename.endswith(".pyc"):
                    filename = filename[:-1]  # Remove 'c' from .pyc

                try:
                    with open(filename, "r", encoding="utf-8") as f:
                        source = f.read()
                        self.source_cache[module.__name__] = source
                        return source
                except (FileNotFoundError, UnicodeDecodeError):
                    pass

            # Try inspect.getsource as fallback
            try:
                source = inspect.getsource(module)
                self.source_cache[module.__name__] = source
                return source
            except (OSError, TypeError):
                pass

        except Exception as e:
            warnings.warn(f"Failed to extract source for module {module.__name__}: {e}")

        return None

    def extract_function_source(self, func: Any) -> Optional[str]:
        """
        Extract source code for a specific function.

        Args:
            func: Function to extract source from

        Returns:
            Function source code or None if not available
        """
        try:
            return inspect.getsource(func)
        except (OSError, TypeError):
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
    """

    def __init__(self, target_function: str):
        """
        Initialize the function extractor.

        Args:
            target_function: Name of the function to extract
        """
        self.target_function = target_function
        self.found_function: Optional[ast.FunctionDef | ast.AsyncFunctionDef] = None
        self.class_context: List[str] = []

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

        # Check for match
        if qualified_name == self.target_function or node.name == self.target_function:
            self.found_function = node

        # Continue visiting nested functions
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Visit an async function definition."""
        # Same logic as regular function def
        if self.class_context:
            qualified_name = f"{'.'.join(self.class_context)}.{node.name}"
        else:
            qualified_name = node.name

        if qualified_name == self.target_function or node.name == self.target_function:
            self.found_function = node

        self.generic_visit(node)


class ASTPatcher:
    """
    Main AST-based line number patcher for Python 3.11+.

    This class provides comprehensive AST manipulation capabilities for
    correcting line numbers in reloaded code objects. It handles:

    - Complex delta maps with multiple insertion points
    - Decorated functions and their line number corrections
    - Nested functions and closures
    - Source code extraction and caching
    - Targeted function compilation from module AST
    - Error handling and fallbacks

    The AST approach is more reliable than direct bytecode manipulation
    for Python 3.11+ due to changes in the line number table format.
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
        Create a new code object with corrected line numbers using AST manipulation.

        This is the main entry point for AST-based line number correction.
        It parses the source code, applies line number shifts, and recompiles
        to produce a code object with accurate line numbers.

        Args:
            old_code: Original code object to patch
            delta_map: Line number shift mappings
            source_code: Full source code for the module/function
            function_name: Name of specific function to extract (optional)
            obj_name: Full object name for debugging

        Returns:
            New code object with corrected line numbers

        Raises:
            SyntaxError: If source code cannot be parsed
            CompileError: If AST cannot be compiled
        """
        try:
            # Parse source code into AST
            tree = ast.parse(source_code, filename=old_code.co_filename)
            if not isinstance(tree, ast.Module):
                raise ValueError(f"Expected Module AST, got {type(tree)}")

            # For reloaded functions, we compile the current source as-is
            # The AST already has the correct line numbers from the current source
            # We don't need to apply additional shifts to the AST itself
            compiled_tree = tree

            # Handle function extraction if needed
            if function_name and function_name != "<module>":
                return self._compile_specific_function(
                    compiled_tree, old_code, function_name, obj_name
                )
            else:
                # Compile entire module
                return compile(compiled_tree, old_code.co_filename, "exec")

        except SyntaxError as e:
            warnings.warn(f"AST parsing failed for {obj_name}: {e}")
            raise
        except Exception as e:
            warnings.warn(f"AST patching failed for {obj_name}: {e}")
            raise

    def _compile_specific_function(
        self,
        tree: ast.Module,
        old_code: types.CodeType,
        function_name: str,
        obj_name: str,
    ) -> types.CodeType:
        """
        Compile a specific function from the module AST.

        For decorated functions and complex cases, it's safer to compile the entire
        module and extract the function rather than trying to compile in isolation.

        Args:
            tree: Module AST with shifted line numbers
            old_code: Original code object
            function_name: Name of function to extract
            obj_name: Full object name for debugging

        Returns:
            Code object for the specific function
        """
        try:
            # Always use the full module compilation approach for decorated functions
            # since they depend on decorators being available in the namespace
            return self._compile_and_extract_function(
                tree, old_code, function_name, obj_name
            )

        except Exception as e:
            warnings.warn(f"Function-specific compilation failed for {obj_name}: {e}")
            # Return the original code as final fallback
            return old_code

    def _compile_and_extract_function(
        self,
        tree: ast.Module,
        old_code: types.CodeType,
        function_name: str,
        obj_name: str,
    ) -> types.CodeType:
        """
        Compile entire module and extract specific function code.

        This is a fallback method when direct function extraction fails.
        It compiles the entire module and then extracts the specific
        function's code object.

        Args:
            tree: Module AST
            old_code: Original code object
            function_name: Name of function to extract
            obj_name: Full object name for debugging

        Returns:
            Code object for the specific function
        """
        try:
            # Compile entire module
            compiled_module = compile(tree, old_code.co_filename, "exec")

            # Execute to create namespace
            namespace: Dict[str, Any] = {}
            exec(compiled_module, namespace)

            # Extract function using various strategies
            func = self._find_function_in_namespace(namespace, function_name)

            if func:
                # Handle property objects specially
                if isinstance(func, property):
                    return self._extract_code_from_property(func, obj_name, old_code)
                elif hasattr(func, "__code__"):
                    return func.__code__

            # If all else fails, return the original code
            warnings.warn(f"Could not extract function {function_name} from {obj_name}")
            return old_code

        except Exception as e:
            warnings.warn(
                f"Module compilation and extraction failed for {obj_name}: {e}"
            )
            return old_code

    def _find_function_in_namespace(
        self, namespace: Dict[str, Any], function_name: str
    ) -> Optional[Any]:
        """
        Find a function in a namespace using various strategies.

        This method handles different naming patterns:
        - Direct name lookup
        - Class.method lookup
        - Nested function lookup
        - Property object handling (for .fget, .fset, .fdel)

        Args:
            namespace: Namespace to search
            function_name: Function name to find

        Returns:
            Function object or None if not found
        """
        # first try direct lookup
        if function_name in namespace:
            return namespace[function_name]

        # then try class.method patterns
        if "." in function_name:
            parts = function_name.split(".")
            obj = namespace

            for part in parts:
                if hasattr(obj, part):
                    obj = getattr(obj, part)
                elif part in obj:
                    obj = obj[part]
                else:
                    return None
            if isinstance(obj, property):
                return obj

            return obj

        # then try searching through all objects in namespace
        base_name = function_name.split(".")[-1]
        for name, obj in namespace.items():
            if hasattr(obj, "__name__") and obj.__name__ == base_name:
                return obj
            if hasattr(obj, "__dict__"):
                for attr_name, attr_obj in vars(obj).items():
                    if hasattr(attr_obj, "__name__") and attr_obj.__name__ == base_name:
                        return attr_obj
                    elif isinstance(attr_obj, property) and attr_name == base_name:
                        return attr_obj

        return None

    def _extract_code_from_property(
        self, prop: property, obj_name: str, old_code: types.CodeType
    ) -> types.CodeType:
        """
        Extract code object from property component based on obj_name.

        Args:
            prop: Property object containing fget/fset/fdel
            obj_name: Full object name (e.g., "MyClass.bad_property.fget")
            old_code: Original code object as fallback

        Returns:
            Code object for the specific property component
        """
        try:
            # Determine which property component we need based on obj_name
            if obj_name.endswith(".fget"):
                if prop.fget and hasattr(prop.fget, "__code__"):
                    return prop.fget.__code__
            elif obj_name.endswith(".fset"):
                if prop.fset and hasattr(prop.fset, "__code__"):
                    return prop.fset.__code__
            elif obj_name.endswith(".fdel"):
                if prop.fdel and hasattr(prop.fdel, "__code__"):
                    return prop.fdel.__code__
            else:
                # TODO maybe return out here.
                if prop.fget and hasattr(prop.fget, "__code__"):
                    return prop.fget.__code__

            # Fallback to original code if we can't find the right component
            warnings.warn(f"Could not extract property component from {obj_name}")
            return old_code

        except Exception as e:
            warnings.warn(f"Property code extraction failed for {obj_name}: {e}")
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
