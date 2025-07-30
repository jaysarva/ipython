"""
Line Number Patching Engine for deduperreload.

This module provides the core line number patching functionality to fix
traceback accuracy issues when code is reloaded. It patches line numbers
for all code objects in a module, not just the ones that were reloaded.
"""

from __future__ import annotations

import types
import warnings
from types import ModuleType, FunctionType
from typing import Dict, List, Set, Optional, Any, Tuple

from IPython.extensions.deduperreload.deduperreload_patching import (
    DeduperReloaderPatchingMixin,
)
from IPython.extensions.deduperreload.line_number_tracker import (
    ModuleSourceTracker,
    CodePosition,
    LineShift,
)


class LineNumberPatcher(DeduperReloaderPatchingMixin):
    """Engine for patching line numbers in code objects after reloading.

    This class is responsible for maintaining traceback accuracy when code is
    reloaded. When functions change size (add/remove lines), it affects the
    line numbers of ALL subsequent code objects in the module.

    Key responsibilities:
    - Track source code positions of all functions and classes
    - Calculate line number shifts when code objects change size
    - Patch line numbers in ALL affected code objects (not just changed ones)
    - Handle nested functions, methods, properties, etc.
    - Preserve closure variables and other function attributes

    The patching process:
    1. Parse current module source to get all code positions
    2. Compare with previously cached positions to detect changes
    3. Calculate line shifts for all code that moved
    4. Find ALL code objects in the module that need updating
    5. Patch each code object's line numbers using ctypes
    """

    def __init__(self) -> None:
        super().__init__()

        # Tracks source code and positions for all modules
        self.source_tracker = ModuleSourceTracker()

        # Cache of ctypes offsets for faster patching
        self.patch_cache: Dict[int, int] = {}  # obj_id -> offset_used

        # Feature flag to enable/disable line number patching
        self.enable_line_number_patching = True

        # Temporary storage for current positions during patching
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
        """Update line numbers for ALL code objects affected by shifts.

        This is the main entry point for line number patching. It updates
        line numbers for all code objects in a module, not just the ones
        that were directly modified.

        Args:
            module: The module whose code objects need updating
            shifts: List of line shifts that occurred (currently unused)
            force_update: If True, update all code objects using current source
        """
        if not self.enable_line_number_patching:
            return

        # Early return optimization - but force_update overrides this
        if not shifts and not force_update:
            return

        try:
            self._perform_line_number_update(module)
        except Exception as e:
            module_name = getattr(module, "__name__", "<unknown module>")
            warnings.warn(f"Failed to update line numbers for {module_name}: {e}")

    def _perform_line_number_update(self, module: ModuleType) -> None:
        """Perform the actual line number update process."""
        # Get current source and parse all code positions
        current_source = self.source_tracker.track_module_source(module)
        current_positions = self.source_tracker.parse_all_code_positions(current_source)

        # Store positions for nested function patching
        self._current_positions = current_positions

        try:
            # Find and patch all code objects
            self._patch_all_code_objects(module, current_positions)
        finally:
            # Always clean up the temporary positions
            self._current_positions = None

    def _patch_all_code_objects(
        self, module: ModuleType, current_positions: Dict[str, CodePosition]
    ) -> None:
        """Find and patch all code objects in the module."""
        all_code_objects = self.find_all_code_objects_in_module(module)

        patched_count = 0
        for obj_name, obj in all_code_objects:
            if not hasattr(obj, "__code__"):
                continue

            # Find the correct line number for this object
            current_line = self.find_matching_position(obj_name, obj, current_positions)
            old_line = obj.__code__.co_firstlineno

            # Patch if line number has changed
            if current_line is not None and current_line != old_line:
                if self.patch_single_code_object_lines(obj, current_line, obj_name):
                    patched_count += 1

    def find_all_code_objects_in_module(
        self, module: ModuleType
    ) -> List[Tuple[str, Any]]:
        """Find ALL code objects that need line number updates.

        This method searches through the entire module namespace to find
        all objects with __code__ attributes that might need line number updates.
        It handles functions, methods, classes, properties, etc.

        Args:
            module: Module to search for code objects

        Returns:
            List of (qualified_name, object) tuples for all code objects found
        """
        code_objects = []

        try:
            # Search through all module attributes
            for name, obj in vars(module).items():
                if name.startswith("_"):  # Skip private attributes
                    continue
                code_objects.extend(self._extract_code_objects_recursive(obj, name))
        except Exception as e:
            module_name = getattr(module, "__name__", "<unknown>")
            warnings.warn(f"Failed to find code objects in {module_name}: {e}")

        return code_objects

    def _extract_code_objects_recursive(
        self, obj: Any, name: str, _compat_mode: bool = False
    ) -> List[Tuple[str, Any]]:
        """Recursively extract all code objects from an object.

        This method handles the complexity of finding code objects in various
        Python constructs including functions, methods, classes, properties,
        static methods, class methods, and nested structures.

        Args:
            obj: Object to extract code objects from
            name: Qualified name/path of the object
            _compat_mode: Internal flag for compatibility with test expectations

        Returns:
            List of (qualified_name, code_object) tuples
        """
        code_objects = []

        try:
            # Handle direct code objects (functions, methods)
            if hasattr(obj, "__code__"):
                code_objects.append((name, obj))

            # Handle classes
            elif isinstance(obj, type):
                code_objects.extend(self._extract_from_class(obj, name, _compat_mode))

            # Handle static/class methods (when encountered directly)
            elif isinstance(obj, (staticmethod, classmethod)):
                code_objects.extend(self._extract_from_method_wrapper(obj, name))

        except Exception as e:
            if _compat_mode:
                # Re-raise for compatibility method to handle
                raise
            else:
                warnings.warn(f"Failed to extract code objects from {name}: {e}")

        return code_objects

    def _extract_from_class(
        self, cls: type, class_name: str, _compat_mode: bool = False
    ) -> List[Tuple[str, Any]]:
        """Extract code objects from a class (methods, properties, nested classes)."""
        code_objects = []

        try:
            for attr_name, attr_obj in vars(cls).items():
                if attr_name.startswith("_"):  # Skip private attributes
                    continue

                qualified_name = f"{class_name}.{attr_name}"

                # Direct code objects (methods)
                if hasattr(attr_obj, "__code__"):
                    code_objects.append((qualified_name, attr_obj))

                # Properties (getter, setter, deleter)
                elif isinstance(attr_obj, property):
                    code_objects.extend(
                        self._extract_from_property(attr_obj, qualified_name)
                    )

                # Static/class methods
                elif isinstance(attr_obj, (staticmethod, classmethod)):
                    code_objects.extend(
                        self._extract_from_method_wrapper(attr_obj, qualified_name)
                    )

                # Nested classes (recursively process)
                elif isinstance(attr_obj, type):
                    code_objects.extend(
                        self._extract_code_objects_recursive(attr_obj, qualified_name)
                    )

        except Exception as e:
            if _compat_mode:
                # Re-raise for compatibility method to handle
                raise
            else:
                warnings.warn(f"Failed to extract from class {class_name}: {e}")

        return code_objects

    def _extract_from_property(
        self, prop: property, prop_name: str
    ) -> List[Tuple[str, Any]]:
        """Extract code objects from a property (fget, fset, fdel)."""
        code_objects = []

        for part_name in ("fget", "fset", "fdel"):
            part_func = getattr(prop, part_name)
            if part_func and hasattr(part_func, "__code__"):
                qualified_name = f"{prop_name}.{part_name}"
                code_objects.append((qualified_name, part_func))

        return code_objects

    def _extract_from_method_wrapper(
        self, wrapper: staticmethod | classmethod, wrapper_name: str
    ) -> List[Tuple[str, Any]]:
        """Extract code objects from static/class method wrappers."""
        code_objects = []

        if hasattr(wrapper.__func__, "__code__"):
            qualified_name = f"{wrapper_name}.__func__"
            code_objects.append((qualified_name, wrapper.__func__))

        return code_objects

    def extract_code_objects_from_object(
        self, obj: Any, obj_name: str
    ) -> List[Tuple[str, Any]]:
        """
        Extract code objects from an object - compatibility method for tests.

        This method provides backward compatibility with the original API while
        using the new simplified extraction methods.

        Args:
            obj: Object to extract code objects from
            obj_name: Name/path of the object

        Returns:
            List of (qualified_name, code_object) tuples
        """
        try:
            return self._extract_code_objects_recursive(
                obj, obj_name, _compat_mode=True
            )
        except Exception as e:
            warnings.warn(f"Failed to extract code objects from {obj_name}: {e}")
            return []

    def find_matching_position(
        self, obj_name: str, obj: Any, current_positions: Dict[str, CodePosition]
    ) -> Optional[int]:
        """Find the current line position for a code object.

        This method tries various strategies to match a code object with its
        position in the current source code:
        1. Direct name matching
        2. Property component matching (.fget, .fset, .fdel)
        3. Method wrapper matching (.__func__)
        4. Function name matching
        5. Partial/fuzzy matching

        Args:
            obj_name: Qualified name of the object
            obj: The code object
            current_positions: Current positions from AST parsing

        Returns:
            Current first line number or None if not found
        """
        # Strategy 1: Direct name match
        direct_match = self._try_direct_match(obj_name, current_positions)
        if direct_match is not None:
            return direct_match

        # Strategy 2: Handle special naming patterns
        special_match = self._try_special_name_patterns(obj_name, current_positions)
        if special_match is not None:
            return special_match

        # Strategy 3: Function name fallback
        func_name_match = self._try_function_name_match(obj, current_positions)
        if func_name_match is not None:
            return func_name_match

        # Strategy 4: Partial matching (last resort)
        return self._try_partial_match(obj_name, current_positions)

    def _try_direct_match(
        self, obj_name: str, positions: Dict[str, CodePosition]
    ) -> Optional[int]:
        """Try direct name matching."""
        if obj_name in positions:
            return positions[obj_name].start_line
        return None

    def _try_special_name_patterns(
        self, obj_name: str, positions: Dict[str, CodePosition]
    ) -> Optional[int]:
        """Handle special naming patterns for properties and method wrappers."""
        # Handle property components: MyClass.prop.fget -> MyClass.prop
        if obj_name.endswith((".fget", ".fset", ".fdel")):
            property_name = obj_name.rsplit(".", 1)[0]
            if property_name in positions:
                # For properties, we need the decorator line which is typically
                # one line before the function definition
                property_pos = positions[property_name]
                return property_pos.start_line - 1

        # Handle method wrappers: MyClass.method.__func__ -> MyClass.method
        if obj_name.endswith(".__func__"):
            method_name = obj_name.rsplit(".", 1)[0]
            if method_name in positions:
                # For static/class methods, also need the decorator line
                return positions[method_name].start_line - 1

        return None

    def _try_function_name_match(
        self, obj: Any, positions: Dict[str, CodePosition]
    ) -> Optional[int]:
        """Try matching by the object's __name__ attribute."""
        if hasattr(obj, "__name__"):
            func_name = obj.__name__
            if func_name in positions:
                return positions[func_name].start_line
        return None

    def _try_partial_match(
        self, obj_name: str, positions: Dict[str, CodePosition]
    ) -> Optional[int]:
        """Try partial/fuzzy matching as a last resort."""
        obj_basename = obj_name.split(".")[-1]

        for pos_name, position in positions.items():
            # Check if names have some overlap
            if (
                obj_name.endswith(pos_name)
                or pos_name.endswith(obj_basename)
                or obj_basename == pos_name.split(".")[-1]
            ):
                return position.start_line

        return None

    def patch_single_code_object_lines(
        self, obj: Any, new_first_line: int, obj_name: str
    ) -> bool:
        """Patch line numbers for any object with __code__ using ctypes.

        This method creates a new code object with updated line numbers and
        patches it into the existing object using ctypes memory manipulation.
        It also handles nested functions recursively.

        Args:
            obj: Object with __code__ attribute to patch
            new_first_line: New first line number
            obj_name: Name of the object (for debugging)

        Returns:
            True if patching succeeded, False otherwise
        """
        try:
            old_code = obj.__code__

            # Early return if no change needed
            if new_first_line == old_code.co_firstlineno:
                return True

            # Create updated code object
            new_code = self._create_updated_code_object(
                old_code, new_first_line, obj_name
            )

            # Patch the object using ctypes
            self.try_patch_attr(obj, new_code, "__code__", new_is_value=True)

            # Cache offset for performance
            self._cache_patch_offset(obj)

            return True

        except Exception as e:
            # Line number patching is optional - don't break functionality
            obj_display_name = getattr(obj, "__name__", str(obj))
            warnings.warn(f"Failed to patch line numbers for {obj_display_name}: {e}")
            return False

    def _create_updated_code_object(
        self, old_code: types.CodeType, new_first_line: int, obj_name: str
    ) -> types.CodeType:
        """Create a new code object with updated line numbers.

        Note: This currently only updates co_firstlineno. Full line table
        patching would require complex decoding of co_linetable (Python 3.11+)
        or co_lnotab (older versions).
        """
        # Start with basic line number update
        new_code = old_code.replace(co_firstlineno=new_first_line)

        # Also patch nested functions if we have position information
        if self._current_positions is not None:
            new_code = self._patch_nested_functions_in_code(
                new_code, None, obj_name, self._current_positions
            )

        return new_code

    def _cache_patch_offset(self, obj: Any) -> None:
        """Cache the ctypes offset for faster future patching."""
        obj_id = id(obj)
        if obj_id not in self.patch_cache:
            offset = self.infer_field_offset(obj, "__code__")
            self.patch_cache[obj_id] = offset

    def _patch_nested_functions_in_code(
        self,
        code_obj: types.CodeType,
        parent_obj: Any,
        parent_name: str,
        current_positions: Dict[str, CodePosition],
    ) -> types.CodeType:
        """Patch line numbers for nested functions within a code object's constants.

        Nested functions are stored as code objects in the parent function's
        co_consts tuple. This method recursively finds and patches them.

        Args:
            code_obj: The code object containing nested functions
            parent_obj: The parent function object (for context)
            parent_name: Name of the parent function
            current_positions: Current AST positions

        Returns:
            New code object with patched nested function line numbers
        """
        try:
            new_constants = []
            has_changes = False

            for constant in code_obj.co_consts:
                if self._is_nested_function_code(constant):
                    patched_constant, changed = self._patch_single_nested_function(
                        constant, parent_name, current_positions
                    )
                    new_constants.append(patched_constant)
                    if changed:
                        has_changes = True
                else:
                    new_constants.append(constant)

            # Return updated code object if any changes were made
            if has_changes:
                return code_obj.replace(co_consts=tuple(new_constants))
            else:
                return code_obj

        except Exception:
            # Return original code object if patching fails
            return code_obj

    def _is_nested_function_code(self, obj: Any) -> bool:
        """Check if an object is a nested function code object."""
        return (
            isinstance(obj, types.CodeType)
            and obj.co_name != "<module>"
            and obj.co_name != "<lambda>"
        )

    def _patch_single_nested_function(
        self,
        nested_code: types.CodeType,
        parent_name: str,
        current_positions: Dict[str, CodePosition],
    ) -> Tuple[types.CodeType, bool]:
        """Patch a single nested function's line numbers.

        Returns:
            Tuple of (patched_code, changed_flag)
        """
        nested_name = f"{parent_name}.{nested_code.co_name}"

        if nested_name not in current_positions:
            # No position info, check for deeper nesting
            deeper_patched = self._patch_nested_functions_in_code(
                nested_code, None, nested_name, current_positions
            )
            return deeper_patched, deeper_patched != nested_code

        # We have position info for this function
        new_line = current_positions[nested_name].start_line
        old_line = nested_code.co_firstlineno

        if new_line != old_line:
            # Line changed, create new code object
            patched_code = nested_code.replace(co_firstlineno=new_line)
            # Recursively patch any deeper nested functions
            final_code = self._patch_nested_functions_in_code(
                patched_code, None, nested_name, current_positions
            )
            return final_code, True
        else:
            # Line didn't change, but check deeper nesting
            deeper_patched = self._patch_nested_functions_in_code(
                nested_code, None, nested_name, current_positions
            )
            return deeper_patched, deeper_patched != nested_code

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
        """Merge closures when patching functions with closures.

        This is a simplified implementation that maps closure cells to
        free variables by position. A more sophisticated version would
        match by variable name to handle reordering.

        Args:
            old_closure: Original closure tuple
            new_freevars: New free variables

        Returns:
            Dictionary mapping variable names to cell objects
        """
        merged = {}

        if old_closure:
            # Simple position-based mapping
            # Note: This assumes free variables haven't been reordered
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
