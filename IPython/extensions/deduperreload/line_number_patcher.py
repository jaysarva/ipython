"""
Line Number Patching Engine for deduperreload.

This module provides the core line number patching functionality to fix
traceback accuracy issues when code is reloaded. It patches line numbers
for all code objects in a module, not just the ones that were reloaded.
"""

from __future__ import annotations

import ast
import inspect
import sys
import types
import warnings
from types import ModuleType, FunctionType, MethodType
from typing import Dict, List, Set, Optional, Any, Tuple, Union

from IPython.extensions.deduperreload.deduperreload_patching import (
    DeduperReloaderPatchingMixin,
)
from IPython.extensions.deduperreload.line_number_tracker import (
    ModuleSourceTracker,
    CodePosition,
    LineShift,
)


class LineNumberPatcher(DeduperReloaderPatchingMixin):
    """
    Engine for patching line numbers in code objects after reloading.

    This class handles updating line numbers for ALL code objects in a module
    when any code object changes size, ensuring traceback accuracy.
    """

    def __init__(self) -> None:
        super().__init__()
        self.source_tracker = ModuleSourceTracker()
        self.patch_cache: Dict[int, int] = {}  # obj_id -> offset_used
        self.enable_line_number_patching = True  # Feature flag
        self._current_positions: Dict[str, CodePosition] | None = None

    def calculate_line_shifts(
        self, module: ModuleType, reloaded_functions: Set[str]
    ) -> List[LineShift]:
        """
        Calculate how line numbers have shifted due to reloaded code objects.

        Args:
            module: The module that was reloaded
            reloaded_functions: Set of function names that were reloaded

        Returns:
            List of LineShift objects describing how code has moved
        """
        if not self.enable_line_number_patching:
            return []

        try:
            # Get current source and positions
            current_source = self.source_tracker.track_module_source(module)
            if not current_source.strip():
                return []

            current_positions = self.source_tracker.parse_all_code_positions(
                current_source
            )

            # Get stored positions from previous parsing
            module_name = module.__name__
            old_positions = self.source_tracker.get_positions(module_name)

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

            # Update stored positions
            self.source_tracker.update_positions(module_name, current_positions)

            return shifts

        except Exception as e:
            warnings.warn(f"Failed to calculate line shifts for {module.__name__}: {e}")
            return []

    def update_all_code_object_line_numbers(
        self, module: ModuleType, shifts: List[LineShift], force_update: bool = False
    ) -> None:
        """
        Update line numbers for ALL code objects affected by shifts.

        Args:
            module: The module whose code objects need updating
            shifts: List of line shifts that occurred
            force_update: If True, update all code objects using current source even if no shifts
        """
        if not self.enable_line_number_patching:
            return

        # If no shifts and not forcing update, return early (preserves original behavior)
        #TODO[CLAUDE_COMMENT]: The early return when no shifts and not force_update may miss cases where source positions changed
        if not shifts and not force_update:
            return

        try:
            # Get current source and positions
            current_source = self.source_tracker.track_module_source(module)
            current_positions = self.source_tracker.parse_all_code_positions(
                current_source
            )
            
            # Store current positions for use in nested function patching
            self._current_positions = current_positions

            # Find all code objects in the module
            all_code_objects = self.find_all_code_objects_in_module(module)

            patched_count = 0
            for obj_name, obj in all_code_objects:
                if not hasattr(obj, "__code__"):
                    continue

                # Try to match with current positions
                current_line = self.find_matching_position(
                    obj_name, obj, current_positions
                )
                old_line = obj.__code__.co_firstlineno

                if current_line is not None and current_line != old_line:
                    if self.patch_single_code_object_lines(obj, current_line, obj_name):
                        patched_count += 1
                        
            # Clean up
            self._current_positions = None

        except Exception as e:
            module_name = getattr(module, "__name__", "<unknown module>")
            warnings.warn(f"Failed to update line numbers for {module_name}: {e}")

    def find_all_code_objects_in_module(
        self, module: ModuleType
    ) -> List[Tuple[str, Any]]:
        """
        Find ALL code objects that need line number updates.

        Args:
            module: Module to search for code objects

        Returns:
            List of (name, object) tuples for all code objects found
        """
        code_objects = []

        try:
            for name, obj in vars(module).items():
                if name.startswith("_"):  # Skip private attributes
                    continue
                code_objects.extend(self.extract_code_objects_from_object(obj, name))
        except Exception as e:
            warnings.warn(f"Failed to find code objects in {module.__name__}: {e}")

        return code_objects

    def extract_code_objects_from_object(
        self, obj: Any, name: str
    ) -> List[Tuple[str, Any]]:
        """
        Recursively extract all code objects from an object.

        Args:
            obj: Object to extract code objects from
            name: Name/path of the object

        Returns:
            List of (qualified_name, code_object) tuples
        """
        code_objects = []

        try:
            # Functions and methods
            if hasattr(obj, "__code__"):
                code_objects.append((name, obj))

            # Classes - check methods and nested classes
            if isinstance(obj, type):
                for attr_name, attr_obj in vars(obj).items():
                    if attr_name.startswith("_"):  # Skip private attributes
                        continue

                    qualified_name = f"{name}.{attr_name}"

                    if hasattr(attr_obj, "__code__"):
                        code_objects.append((qualified_name, attr_obj))

                    # Handle properties
                    elif isinstance(attr_obj, property):
                        for prop_part in ("fget", "fset", "fdel"):
                            prop_func = getattr(attr_obj, prop_part)
                            if prop_func and hasattr(prop_func, "__code__"):
                                code_objects.append(
                                    (f"{qualified_name}.{prop_part}", prop_func)
                                )

                    # Handle static/class methods
                    elif isinstance(attr_obj, (staticmethod, classmethod)):
                        if hasattr(attr_obj.__func__, "__code__"):
                            code_objects.append(
                                (f"{qualified_name}.__func__", attr_obj.__func__)
                            )

                    # Recursively handle nested classes
                    elif isinstance(attr_obj, type):
                        code_objects.extend(
                            self.extract_code_objects_from_object(
                                attr_obj, qualified_name
                            )
                        )

            # Static/class methods (for standalone objects)
            elif isinstance(obj, (staticmethod, classmethod)):
                if hasattr(obj.__func__, "__code__"):
                    code_objects.append((f"{name}.__func__", obj.__func__))

        except Exception as e:
            warnings.warn(f"Failed to extract code objects from {name}: {e}")

        return code_objects

    def find_matching_position(
        self, obj_name: str, obj: Any, current_positions: Dict[str, CodePosition]
    ) -> Optional[int]:
        """
        Find the current line position for a code object.

        Args:
            obj_name: Qualified name of the object
            obj: The code object
            current_positions: Current positions from AST parsing

        Returns:
            Current first line number or None if not found
        """
        # Direct name match
        if obj_name in current_positions:
            return current_positions[obj_name].start_line

        # Handle property names: MyClass.bad_property.fget -> MyClass.bad_property
        if obj_name.endswith(('.fget', '.fset', '.fdel')):
            property_name = obj_name.rsplit('.', 1)[0]  # Remove .fget/.fset/.fdel
            if property_name in current_positions:
                # For properties, AST reports the function def line, but co_firstlineno is the decorator line
                # Need to subtract 1 to get the @property decorator line that matches co_firstlineno
                #TODO[CLAUDE_COMMENT]: Property handling assumes decorator is always on line before function - this may not be true for multi-line decorators
                property_pos = current_positions[property_name]
                return property_pos.start_line - 1

        # Handle static/class method names: MyClass.method.__func__ -> MyClass.method  
        if obj_name.endswith('.__func__'):
            method_name = obj_name.rsplit('.', 1)[0]  # Remove .__func__
            if method_name in current_positions:
                #TODO[CLAUDE_COMMENT]: Static/class method handling also assumes single-line decorator - needs more robust parsing
                return current_positions[method_name].start_line - 1

        # Try to match by function name for simple cases
        if hasattr(obj, "__name__"):
            func_name = obj.__name__
            if func_name in current_positions:
                return current_positions[func_name].start_line

        # Try partial matching for nested objects
        for pos_name, position in current_positions.items():
            if obj_name.endswith(pos_name) or pos_name.endswith(
                obj_name.split(".")[-1]
            ):
                return position.start_line

        return None

    def patch_single_code_object_lines(self, obj: Any, new_first_line: int, obj_name: str) -> bool:
        """
        Patch line numbers for any object with __code__ using ctypes.

        Args:
            obj: Object with __code__ attribute to patch
            new_first_line: New first line number

        Returns:
            True if patching succeeded, False otherwise
        """
        try:
            old_code = obj.__code__
            line_offset = new_first_line - old_code.co_firstlineno

            if line_offset == 0:
                return True  # No change needed

            # Create new code object with updated line numbers
            # For now, just update co_firstlineno - complete line table updates
            # would require complex Python 3.11+ co_linetable decoding
            #TODO[CLAUDE_COMMENT]: Only updating co_firstlineno doesn't fix line tables - traceback line numbers within functions will still be wrong
            new_code = old_code.replace(co_firstlineno=new_first_line)
            
            # Also patch nested functions in constants if positions are available
            if self._current_positions is not None:
                new_code = self._patch_nested_functions_in_code(new_code, obj, obj_name, self._current_positions)

            # Use existing patching mechanism from DeduperReloaderPatchingMixin
            self.try_patch_attr(obj, new_code, "__code__", new_is_value=True)

            # Cache the offset used for debugging
            obj_id = id(obj)
            if obj_id not in self.patch_cache:
                offset = self.infer_field_offset(obj, "__code__")
                self.patch_cache[obj_id] = offset

            return True

        except Exception as e:
            # Log but don't fail - line numbers are nice-to-have
            warnings.warn(
                f"Failed to patch line numbers for {getattr(obj, '__name__', obj)}: {e}"
            )
            return False

    def _patch_nested_functions_in_code(self, code_obj, parent_obj, parent_name: str, current_positions: Dict[str, CodePosition]):
        """
        Patch line numbers for nested functions within a code object's constants.
        
        Args:
            code_obj: The code object containing nested functions
            parent_obj: The parent function object (for context)
            parent_name: Name of the parent function
            current_positions: Current AST positions
            
        Returns:
            New code object with patched nested function line numbers
        """
        try:
            new_consts = []
            changed = False
            
            for const in code_obj.co_consts:
                if isinstance(const, types.CodeType) and const.co_name != '<module>':
                    # This is a nested function - find its correct line number
                    nested_name = f"{parent_name}.{const.co_name}"
                    
                    if nested_name in current_positions:
                        new_line = current_positions[nested_name].start_line
                        old_line = const.co_firstlineno
                        
                        if new_line != old_line:
                            new_nested_code = const.replace(co_firstlineno=new_line)
                            # Recursively patch deeper nested functions
                            #TODO[CLAUDE_COMMENT]: Nested function patching is complex - consider if this level of recursion is necessary
                            new_nested_code = self._patch_nested_functions_in_code(
                                new_nested_code, parent_obj, nested_name, current_positions
                            )
                            new_consts.append(new_nested_code)
                            changed = True
                        else:
                            # Recursively check for deeper nesting even if this level doesn't change
                            new_nested_code = self._patch_nested_functions_in_code(
                                const, parent_obj, nested_name, current_positions
                            )
                            new_consts.append(new_nested_code)
                            if new_nested_code != const:
                                changed = True
                    else:
                        new_consts.append(const)
                else:
                    new_consts.append(const)
            
            # Return code object with updated constants if anything changed
            if changed:
                return code_obj.replace(co_consts=tuple(new_consts))
            else:
                return code_obj
                
        except Exception as e:
            # Return original code object if patching fails
            return code_obj

    def patch_function_with_closure(self, func: FunctionType, new_code: Any) -> bool:
        """
        Handle patching functions with closures specially.

        Args:
            func: Function with closure to patch
            new_code: New code object

        Returns:
            True if patching succeeded, False otherwise
        """
        try:
            merged_closure = None
            if func.__closure__:
                # Need to preserve closure variables
                merged_closure = self.merge_closures(
                    func.__closure__, new_code.co_freevars
                )
                new_code = new_code.replace(co_freevars=tuple(merged_closure.keys()))

            # Update closure along with code
            self.try_patch_attr(func, new_code, "__code__", new_is_value=True)

            if func.__closure__ and merged_closure:
                self.try_patch_attr(
                    func,
                    tuple(merged_closure.values()),
                    "__closure__",
                    new_is_value=True,
                )

            return True

        except Exception as e:
            warnings.warn(f"Failed to patch closure function {func.__name__}: {e}")
            return False

    def merge_closures(
        self, old_closure: Tuple[Any, ...], new_freevars: Tuple[str, ...]
    ) -> Dict[str, Any]:
        """
        Merge closures when patching functions with closures.

        Args:
            old_closure: Original closure tuple
            new_freevars: New free variables

        Returns:
            Dictionary mapping variable names to cell objects
        """
        # This is a simplified implementation
        # In practice, this would need more sophisticated logic
        #TODO[CLAUDE_COMMENT]: merge_closures implementation is too simplistic - needs proper variable name matching
        merged = {}

        if old_closure:
            for i, cell in enumerate(old_closure):
                if i < len(new_freevars):
                    merged[new_freevars[i]] = cell

        return merged

    def handle_ctypes_failure(self, obj: Any, new_code: Any) -> bool:
        """
        Fallback when ctypes patching fails.

        Args:
            obj: Object to patch
            new_code: New code object

        Returns:
            True if any fallback succeeded, False otherwise
        """
        try:
            # Try direct assignment first (will fail on read-only)
            obj.__code__ = new_code
            return True
        except (AttributeError, TypeError, ValueError):
            # Try using the existing patching mechanism
            try:
                self.try_patch_attr(obj, new_code, "__code__", new_is_value=True)
                return True
            except Exception:
                # Install traceback hook as last resort (would be implemented separately)
                warnings.warn(
                    f"All patching methods failed for {getattr(obj, '__name__', obj)}"
                )
                return False

    def validate_patch_safety(self, obj: Any, new_code: Any) -> bool:
        """
        Validate that patching is safe before attempting.

        Args:
            obj: Object to patch
            new_code: New code object

        Returns:
            True if patching appears safe, False otherwise
        """
        try:
            # Basic validation checks
            if not hasattr(obj, "__code__"):
                return False

            old_code = obj.__code__

            # Check that code structure is compatible
            if (
                hasattr(old_code, "co_argcount")
                and hasattr(new_code, "co_argcount")
                and old_code.co_argcount != new_code.co_argcount
            ):
                return False

            # Check filename consistency
            if (
                hasattr(old_code, "co_filename")
                and hasattr(new_code, "co_filename")
                and old_code.co_filename != new_code.co_filename
            ):
                return False

            return True

        except Exception:
            return False

    def clear_patch_cache(self) -> None:
        """Clear the patch cache to free memory."""
        self.patch_cache.clear()

    def get_patch_statistics(self) -> Dict[str, Any]:
        """
        Get statistics about patching operations.

        Returns:
            Dictionary with patching statistics
        """
        return {
            "cached_offsets": len(self.patch_cache),
            "feature_enabled": self.enable_line_number_patching,
            "modules_tracked": len(self.source_tracker.module_snapshots),
        }
