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
        # Validate input - old_code must be a CodeType
        if not isinstance(old_code, types.CodeType):
            # Special handling for property objects that shouldn't reach here
            if isinstance(old_code, property):
                raise ValueError(
                    f"Property objects should not be passed to AST patcher: {obj_name}"
                )
            raise ValueError(f"Expected CodeType, got {type(old_code)} for {obj_name}")
        try:
            # Parse source code into AST
            tree = ast.parse(source_code, filename=old_code.co_filename)
            if not isinstance(tree, ast.Module):
                raise ValueError(f"Expected Module AST, got {type(tree)}")

            # The AST already has the correct line numbers from the current source
            # We don't need to apply additional shifts to the AST itself

            if function_name:
                return self._compile_specific_function(
                    tree, old_code, function_name, obj_name
                )
            return old_code

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
            return self._compile_and_extract_function(
                tree, old_code, function_name, obj_name
            )
        except Exception as e:
            warnings.warn(f"Function-specific compilation failed for {obj_name}: {e}")
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
            return self._compile_module_and_extract_function(
                tree, old_code, function_name, obj_name
            )
        except Exception as e:
            warnings.warn(
                f"Module compilation and extraction failed for {obj_name}: {e}"
            )
            return old_code

    def _compile_module_and_extract_function(
        self,
        tree: ast.Module,
        old_code: types.CodeType,
        function_name: str,
        obj_name: str,
    ) -> types.CodeType:
        """Extract function AST and compile it directly without executing entire module.

        Args:
            tree: Module AST
            old_code: Original code object
            function_name: Function name to extract
            obj_name: Object name for debugging

        Returns:
            Extracted function code object

        Raises:
            Exception: If compilation or extraction fails
        """
        # Extract the specific function AST node
        extractor = FunctionExtractor(function_name)
        extractor.visit(tree)

        if not extractor.found_function:
            raise ValueError(f"Function {function_name} not found in AST")

        func_node = extractor.found_function

        # Handle different types of functions
        if extractor.found_class_context and isinstance(
            func_node, (ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            # Check if this is a property method (fget, fset, fdel) - use obj_name for detection
            if any(obj_name.endswith(suffix) for suffix in [".fget", ".fset", ".fdel"]):
                return self._compile_property_method(func_node, old_code, obj_name)
            else:
                return self._compile_class_method(func_node, old_code, function_name)
        else:
            return self._compile_isolated_function(func_node, old_code, function_name)

    def _compile_class_method(
        self,
        func_node: ast.FunctionDef | ast.AsyncFunctionDef,
        old_code: types.CodeType,
        function_name: str,
    ) -> types.CodeType:
        """Compile a class method wrapped in a temporary class."""
        # All class methods should be compiled with full context approach
        return self._compile_class_method_with_context(
            func_node, old_code, function_name
        )

    def _compile_class_method_with_context(
        self,
        func_node: ast.FunctionDef | ast.AsyncFunctionDef,
        old_code: types.CodeType,
        function_name: str,
    ) -> types.CodeType:
        """Compile a class method with full module and class context."""
        # We need to get the full module AST and extract the class containing this method
        # The extractor already found the class context for us
        extractor = FunctionExtractor(function_name)

        # Parse the module again to get full context
        # We need the module source to get the full class definition with inheritance
        module_source = self._get_module_source_from_code(old_code)
        if not module_source:
            # Fall back to simple compilation if we can't get module source
            return self._compile_simple_class_method(func_node, old_code, function_name)

        try:
            full_tree = ast.parse(module_source, filename=old_code.co_filename)

            # Find the class containing our method
            class_node = self._find_class_containing_method(full_tree, function_name)
            if not class_node:
                # Fall back to simple compilation
                return self._compile_simple_class_method(
                    func_node, old_code, function_name
                )

            # Compile the full class with proper context
            return self._compile_full_class_method(
                class_node, func_node, old_code, function_name, module_source
            )

        except Exception:
            # Fall back to simple compilation on any error
            return self._compile_simple_class_method(func_node, old_code, function_name)

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
        """Compile a method from its full class context with inheritance support."""
        # Create a module containing only the class and its dependencies
        isolated_module = ast.Module(body=[class_node], type_ignores=[])
        ast.fix_missing_locations(isolated_module)

        # Compile the class
        compiled_class = compile(isolated_module, old_code.co_filename, "exec")

        # Execute with module namespace to get all context (variables, imports, etc.)
        namespace = self._build_module_namespace(module_source, old_code.co_filename)
        exec(compiled_class, namespace)

        # Get the method from the compiled class
        class_obj = namespace[class_node.name]
        method = getattr(class_obj, func_node.name)

        return method.__code__

    def _build_module_namespace(self, module_source: str, filename: str) -> dict:
        """Build a namespace containing all module-level definitions."""
        try:
            # Parse the full module
            tree = ast.parse(module_source, filename=filename)

            # Create namespace with builtins
            namespace = {"__builtins__": __builtins__}

            # Execute all top-level definitions except the class we're compiling
            # This gives us imports, global variables, other classes, etc.
            for node in tree.body:
                if isinstance(
                    node,
                    (
                        ast.Import,
                        ast.ImportFrom,
                        ast.Assign,
                        ast.AugAssign,
                        ast.AnnAssign,
                        ast.FunctionDef,
                        ast.AsyncFunctionDef,
                    ),
                ):
                    # Execute individual statements to build namespace
                    single_stmt = ast.Module(body=[node], type_ignores=[])
                    ast.fix_missing_locations(single_stmt)
                    compiled_stmt = compile(single_stmt, filename, "exec")
                    exec(compiled_stmt, namespace)
                elif isinstance(node, ast.ClassDef):
                    # Include other classes for inheritance
                    single_stmt = ast.Module(body=[node], type_ignores=[])
                    ast.fix_missing_locations(single_stmt)
                    compiled_stmt = compile(single_stmt, filename, "exec")
                    exec(compiled_stmt, namespace)

            return namespace
        except Exception:
            # Return minimal namespace on error
            return {"__builtins__": __builtins__}

    def _compile_simple_class_method(
        self,
        func_node: ast.FunctionDef | ast.AsyncFunctionDef,
        old_code: types.CodeType,
        function_name: str,
    ) -> types.CodeType:
        """Compile a simple class method (no super() calls) using temporary class."""
        # Create a temporary class wrapper (similar to code_execution.py approach)
        temp_class = ast.ClassDef(
            name="__autoreload_class__",
            bases=[],
            keywords=[],
            decorator_list=[],
            body=[func_node],
            lineno=1,
            col_offset=0,
        )

        # Create module with the temporary class
        isolated_module = ast.Module(body=[temp_class], type_ignores=[])
        ast.fix_missing_locations(isolated_module)

        # Compile the class
        compiled_class = compile(isolated_module, old_code.co_filename, "exec")

        # Execute with empty namespace (sufficient for simple class methods)
        namespace: dict[str, Any] = {}
        exec(compiled_class, namespace)

        # Get the method from the temporary class
        temp_class_obj = namespace["__autoreload_class__"]
        method = getattr(temp_class_obj, func_node.name)

        return method.__code__

    def _compile_property_method(
        self,
        func_node: ast.FunctionDef | ast.AsyncFunctionDef,
        old_code: types.CodeType,
        obj_name: str,
    ) -> types.CodeType:
        """Compile a property method (fget, fset, fdel) wrapped in a temporary class."""
        # We need to extract the property getter function

        # Add the @property decorator to the function for proper compilation
        property_decorator = ast.Name(id="property", ctx=ast.Load())
        # Set decorator line number
        property_decorator.lineno = func_node.lineno - 1 if func_node.lineno > 1 else 1
        property_decorator.col_offset = 0

        decorated_func = ast.FunctionDef(
            name=func_node.name,
            args=func_node.args,
            body=func_node.body,
            decorator_list=[property_decorator],
            returns=func_node.returns,
            type_comment=func_node.type_comment,
            lineno=func_node.lineno,
            col_offset=func_node.col_offset,
        )

        # Copy end_lineno if it exists
        if hasattr(func_node, "end_lineno"):
            decorated_func.end_lineno = func_node.end_lineno
        if hasattr(func_node, "end_col_offset"):
            decorated_func.end_col_offset = func_node.end_col_offset

        # Create a temporary class wrapper
        temp_class = ast.ClassDef(
            name="__autoreload_class__",
            bases=[],
            keywords=[],
            decorator_list=[],
            body=[decorated_func],
            lineno=1,
            col_offset=0,
        )

        # Create module with the temporary class
        isolated_module = ast.Module(body=[temp_class], type_ignores=[])
        ast.fix_missing_locations(isolated_module)

        # Compile the class
        compiled_class = compile(isolated_module, old_code.co_filename, "exec")

        # Execute with empty namespace
        namespace: dict[str, Any] = {}
        exec(compiled_class, namespace)

        # Get the property from the temporary class
        temp_class_obj = namespace["__autoreload_class__"]
        prop = getattr(temp_class_obj, func_node.name)

        # Extract the appropriate component based on obj_name suffix
        if obj_name.endswith(".fget"):
            return prop.fget.__code__
        elif obj_name.endswith(".fset"):
            if prop.fset:
                return prop.fset.__code__
            else:
                raise ValueError(f"Property {obj_name} has no setter")
        elif obj_name.endswith(".fdel"):
            if prop.fdel:
                return prop.fdel.__code__
            else:
                raise ValueError(f"Property {obj_name} has no deleter")
        else:
            raise ValueError(f"Unknown property component: {obj_name}")

    def _compile_isolated_function(
        self, func_node: ast.AST, old_code: types.CodeType, function_name: str
    ) -> types.CodeType:
        """Compile a function in isolation."""
        # Create a new module containing only the function
        if isinstance(func_node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Assign)):
            isolated_module = ast.Module(body=[func_node], type_ignores=[])
        else:
            raise ValueError(f"Unsupported function node type: {type(func_node)}")
        ast.fix_missing_locations(isolated_module)

        # Compile the isolated function
        compiled_func = compile(isolated_module, old_code.co_filename, "exec")

        # Extract the function code object from the compiled module
        if isinstance(func_node, ast.Assign) and isinstance(
            func_node.value, ast.Lambda
        ):
            # For lambda assignments, look for the lambda code object
            for const in compiled_func.co_consts:
                if isinstance(const, types.CodeType) and const.co_name == "<lambda>":
                    return const
        else:
            # For regular functions, look for function name match
            if isinstance(func_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                expected_name = func_node.name
            else:
                expected_name = function_name
            for const in compiled_func.co_consts:
                if isinstance(const, types.CodeType) and const.co_name == expected_name:
                    return const

        # If we can't find it in constants, raise exception
        raise ValueError(
            f"Could not extract compiled code for function {function_name}"
        )

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
