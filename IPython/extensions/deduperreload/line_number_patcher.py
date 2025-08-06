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
from typing import Dict, List, Optional, Any, Tuple, Callable, cast

from IPython.extensions.deduperreload.deduperreload_patching import (
    DeduperReloaderPatchingMixin,
)
from IPython.extensions.deduperreload.line_number_tracker import (
    ModuleSourceTracker,
    CodePosition,
)

from IPython.extensions.deduperreload.ast_patcher import (
    ASTPatcher,
    SourceCodeExtractor,
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

        # AST-based patcher
        self.ast_patcher = ASTPatcher()

        # Enhanced source code extractor
        self.source_extractor = SourceCodeExtractor()

    def update_all_code_object_line_numbers(self, module: ModuleType) -> None:
        """Update line numbers for ALL code objects affected by shifts.

        This is the main entry point for line number patching. It updates
        line numbers for all code objects in a module, not just the ones
        that were directly modified.

        Args:
            module: The module whose code objects need updating
            shifts: List of line shifts that occurred (currently unused)
        """
        if not self.enable_line_number_patching:
            return

        try:
            self._perform_line_number_update(module)
        except Exception as e:
            module_name = getattr(module, "__name__", "<unknown module>")
            warnings.warn(f"Failed to update line numbers for {module_name}: {e}")

    def _perform_line_number_update(self, module: ModuleType) -> None:
        """Perform the actual line number update process."""
        module_name = module.__name__

        # Get current source and parse all code positions
        current_source = self.source_tracker.track_module_source(module)
        current_positions = self.source_tracker.parse_all_code_positions(current_source)

        # Store positions for nested function patching
        self._current_positions = current_positions

        try:
            # Find and patch all code objects
            self._patch_all_code_objects(module, current_positions)
        finally:
            # Store current positions as the new baseline for future comparisons
            # Do this AFTER patching so we have them available for the next reload
            self.source_tracker.code_positions[module_name] = current_positions

            # Always clean up the temporary positions
            self._current_positions = None

    def store_baseline_from_source(self, module_name: str, source_code: str) -> None:
        """Store baseline positions from specific source code.

        This method stores the positions parsed from the provided source code
        as the baseline for future line number delta calculations.

        Args:
            module_name: Name of the module
            source_code: Source code to parse positions from
        """
        # Parse positions from the provided source
        baseline_positions = self.source_tracker.parse_all_code_positions(source_code)

        # Store as baseline for future comparisons
        self.source_tracker.code_positions[module_name] = baseline_positions

    def ensure_module_positions_tracked(self, module: ModuleType) -> None:
        """Ensure that a module's positions are tracked, even if no changes are detected.

        This method should be called proactively to establish baseline positions
        for modules that haven't been processed by the line patcher yet.
        """
        module_name = module.__name__

        # Only track if we haven't seen this module before
        if module_name not in self.source_tracker.code_positions:
            # Get current source and parse positions
            current_source = self.source_tracker.track_module_source(module)
            current_positions = self.source_tracker.parse_all_code_positions(
                current_source
            )

            # Store positions for future comparisons
            self.source_tracker.code_positions[module_name] = current_positions

    def _patch_all_code_objects(
        self, module: ModuleType, current_positions: Dict[str, CodePosition]
    ) -> None:
        """Find and patch all code objects in the module."""
        all_code_objects = self.find_all_code_objects_in_module(module)

        patched_count = 0
        for obj_name, obj in all_code_objects:
            if not hasattr(obj, "__code__"):
                continue

            current_line = self.find_matching_position(obj_name, obj, current_positions)
            old_line = self._get_original_line_number(obj)

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
            module_name = getattr(module, "__name__", "<unknown>")
            # Search through all module attributes
            for name, obj in vars(module).items():
                if name.startswith("_"):  # Skip private attributes
                    continue
                # Prefix object names with module name for proper identification
                qualified_name = f"{module_name}.{name}"
                code_objects.extend(
                    self._extract_code_objects_recursive(obj, qualified_name)
                )
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
        try:
            return self._extract_code_objects_by_type(obj, name, _compat_mode)
        except Exception as e:
            if _compat_mode:
                raise
            else:
                warnings.warn(f"Failed to extract code objects from {name}: {e}")
                return []

    def _extract_code_objects_by_type(
        self, obj: Any, name: str, _compat_mode: bool
    ) -> List[Tuple[str, Any]]:
        """Extract code objects using type-based dispatch pattern.

        Args:
            obj: Object to extract from
            name: Qualified name
            _compat_mode: Compatibility flag

        Returns:
            List of code object tuples
        """
        # Unified dispatch table for object types
        extractors = {
            "direct_code": (lambda o: hasattr(o, "__code__"), lambda o, n: [(n, o)]),
            "class_type": (
                lambda o: isinstance(o, type),
                lambda o, n: self._extract_from_class(o, n, _compat_mode),
            ),
            "method_wrapper": (
                lambda o: isinstance(o, (staticmethod, classmethod)),
                lambda o, n: self._extract_from_method_wrapper(o, n),
            ),
        }

        for _, (condition, extractor) in extractors.items():
            if condition(obj):
                return extractor(obj, name)

        return []

    def _extract_from_class(
        self, cls: type, class_name: str, _compat_mode: bool = False
    ) -> List[Tuple[str, Any]]:
        """Extract code objects from a class (methods, properties, nested classes)."""
        try:
            return self._extract_from_class_attributes(cls, class_name)
        except Exception as e:
            if _compat_mode:
                raise
            else:
                warnings.warn(f"Failed to extract from class {class_name}: {e}")
                return []

    def _extract_from_class_attributes(
        self, cls: type, class_name: str
    ) -> List[Tuple[str, Any]]:
        """Extract code objects from class attributes using unified extraction."""
        code_objects = []

        # Define attribute extractors in order of specificity
        extractors = [
            (
                "direct_code",
                lambda attr: hasattr(attr, "__code__"),
                self._extract_direct_code_object,
            ),
            (
                "property",
                lambda attr: isinstance(attr, property),
                self._extract_from_property,
            ),
            (
                "method_wrapper",
                lambda attr: isinstance(attr, (staticmethod, classmethod)),
                self._extract_from_method_wrapper,
            ),
            (
                "nested_class",
                lambda attr: isinstance(attr, type),
                self._extract_code_objects_recursive,
            ),
        ]

        for attr_name, attr_obj in vars(cls).items():
            if attr_name.startswith("_"):  # Skip private attributes
                continue

            qualified_name = f"{class_name}.{attr_name}"

            # Try each extractor until one matches
            for _, condition, extractor in extractors:
                if condition(attr_obj):
                    if extractor == self._extract_direct_code_object:
                        code_objects.append((qualified_name, attr_obj))
                    else:
                        code_objects.extend(
                            cast(
                                Callable[[Any, str], List[Tuple[str, Any]]], extractor
                            )(attr_obj, qualified_name)
                        )
                    break

        return code_objects

    def _extract_direct_code_object(
        self, attr_obj: Any, qualified_name: str
    ) -> List[Tuple[str, Any]]:
        """Extract direct code object (used for consistency with other extractors)."""
        return [(qualified_name, attr_obj)]

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

        This method uses a unified strategy pattern to match code objects with their
        positions in the current source code.

        Args:
            obj_name: Qualified name of the object
            obj: The code object
            current_positions: Current positions from AST parsing

        Returns:
            Current first line number or None if not found
        """
        # Define position finding strategies in order of preference
        strategies = [
            self._try_direct_name_match,
            self._try_special_pattern_match,
            self._try_object_name_match,
            self._try_module_prefix_removal,
            self._try_lambda_match,
        ]

        # Execute strategies until one succeeds
        for strategy in strategies:
            result = strategy(obj_name, obj, current_positions)
            if result is not None:
                return result

        return None

    def _try_direct_name_match(
        self, obj_name: str, _obj: Any, current_positions: Dict[str, CodePosition]
    ) -> Optional[int]:
        """Try direct name match strategy."""
        if obj_name in current_positions:
            return current_positions[obj_name].start_line
        return None

    def _try_special_pattern_match(
        self, obj_name: str, _obj: Any, current_positions: Dict[str, CodePosition]
    ) -> Optional[int]:
        """Try special naming patterns (properties and method wrappers) strategy."""
        base_name = self._get_base_name_for_special_patterns(obj_name)
        if base_name and base_name in current_positions:
            # For properties and static/class methods, use decorator line (one line before)
            return current_positions[base_name].start_line - 1
        return None

    def _try_object_name_match(
        self, _obj_name: str, obj: Any, current_positions: Dict[str, CodePosition]
    ) -> Optional[int]:
        """Try function name from object attribute strategy."""
        if hasattr(obj, "__name__"):
            func_name = obj.__name__
            if func_name in current_positions:
                return current_positions[func_name].start_line
        return None

    def _try_module_prefix_removal(
        self, obj_name: str, _obj: Any, current_positions: Dict[str, CodePosition]
    ) -> Optional[int]:
        """Try removing module prefix from regular method names strategy."""
        if "." not in obj_name:
            return None

        parts = obj_name.split(".")
        # Try progressively longer prefixes to find the module name
        for i in range(1, len(parts)):
            potential_module = ".".join(parts[:i])
            if potential_module in self.source_tracker.module_snapshots:
                # Found the module prefix, try the rest as position key
                remaining_name = ".".join(parts[i:])
                if remaining_name in current_positions:
                    return current_positions[remaining_name].start_line
        return None

    def _try_lambda_match(
        self, _obj_name: str, obj: Any, current_positions: Dict[str, CodePosition]
    ) -> Optional[int]:
        """Try lambda expression matching strategy."""
        if not (hasattr(obj, "__code__") and obj.__code__.co_name == "<lambda>"):
            return None

        original_line = obj.__code__.co_firstlineno
        for pos_name, position in current_positions.items():
            if (
                position.type == "lambda"
                and pos_name.startswith("lambda_")
                and str(original_line) in pos_name
            ):
                return position.start_line
        return None

    def _get_base_name_for_special_patterns(self, obj_name: str) -> Optional[str]:
        """Extract base name for special naming patterns like properties and method wrappers."""
        base_name = None
        if obj_name.endswith((".fget", ".fset", ".fdel")):
            base_name = obj_name.rsplit(".", 1)[0]
        elif obj_name.endswith(".__func__"):
            base_name = obj_name.rsplit(".", 1)[0]

        if base_name:
            # Remove module prefix if present
            if "." in base_name:
                parts = base_name.split(".")
                # Try progressively longer prefixes to find the module name
                for i in range(1, len(parts)):
                    potential_module = ".".join(parts[:i])
                    if potential_module in self.source_tracker.module_snapshots:
                        # Found the module prefix, return the rest
                        return ".".join(parts[i:])
            return base_name

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

            # Check if this is a decorated function with wrapper closures
            # Check if this is a decorated function with wrapper closures
            if self._has_wrapper_closures(obj):
                return self._patch_decorated_function_with_closures(
                    obj, new_first_line, obj_name
                )

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
        """Create a new code object with updated line numbers."""
        # Calculate the line shift delta
        old_first_line = old_code.co_firstlineno
        line_delta = new_first_line - old_first_line

        # If no change needed, return original
        if line_delta == 0:
            return old_code

        new_code = self._create_code_via_enhanced_ast_approach(
            old_code, new_first_line, obj_name
        )
        if new_code != old_code:
            return self._apply_nested_function_patches(new_code, obj_name)
        return old_code

    def _create_code_via_enhanced_ast_approach(
        self, old_code: types.CodeType, new_first_line: int, obj_name: str
    ) -> types.CodeType:
        """Create updated code object using enhanced AST approach for Python 3.11+."""
        # Get source code for the object
        source_code = self._get_enhanced_source_code(old_code, obj_name)
        if not source_code:
            return old_code

        # TODO -- is this necessary? seems like we can omit this.
        if not self.ast_patcher.validate_ast_patching_safety(old_code, source_code):
            return old_code

        old_first_line = old_code.co_firstlineno
        delta_map = self.ast_patcher.create_enhanced_delta_map(
            old_first_line,
            new_first_line,
        )
        function_name = self._extract_function_name_from_obj_name(obj_name)
        try:
            new_code = self.ast_patcher.patch_code_object_ast(
                old_code, delta_map, source_code, function_name, obj_name
            )
            return new_code

        except Exception as e:
            warnings.warn(f"AST patch_code_object_ast failed for {obj_name}: {e}")
            return old_code

    def _apply_nested_function_patches(
        self, code_obj: types.CodeType, obj_name: str
    ) -> types.CodeType:
        """Apply nested function patches if position information is available."""
        if self._current_positions is not None:
            return self._patch_nested_functions_in_code(
                code_obj, None, obj_name, self._current_positions
            )
        return code_obj

    def _get_enhanced_source_code(
        self, code: types.CodeType, _obj_name: str
    ) -> Optional[str]:
        """Get source code using enhanced extraction methods."""
        try:
            filename = code.co_filename

            # Try source tracker first
            for (
                module_name,
                cached_source,
            ) in self.source_tracker.module_snapshots.items():
                if filename in module_name or module_name in filename:
                    return cached_source

            # TODO -- delete this...? seems unnecessary.
            # Try AST patcher's source extractor
            # for module_name in self.source_extractor.source_cache:
            #     if filename in module_name or module_name in filename:
            #         return self.source_extractor.get_cached_source(module_name)

        except Exception:
            pass

        return None

    def _extract_function_name_from_obj_name(self, obj_name: str) -> Optional[str]:
        """Extract the actual function name from the qualified object name.

        For nested class methods (e.g., 'C.D.foo'), we need to preserve the full
        qualified path since the function lookup in _find_function_in_namespace
        handles dotted names correctly via attribute traversal.
        """
        if not obj_name or obj_name == "<module>":
            return None

        # First, handle special suffixes and store the cleaned name
        cleaned_name = obj_name
        if obj_name.endswith(".fget"):
            cleaned_name = obj_name[:-5]  # Remove '.fget'
        elif obj_name.endswith(".fset"):
            cleaned_name = obj_name[:-5]  # Remove '.fset'
        elif obj_name.endswith(".fdel"):
            cleaned_name = obj_name[:-5]  # Remove '.fdel'
        elif obj_name.endswith(".__func__"):
            cleaned_name = obj_name[:-9]  # Remove '.__func__'

        # Now remove module prefix if present, but preserve class structure
        # e.g., "module.MyClass.method" -> "MyClass.method"
        # e.g., "module.my_function" -> "my_function"
        if "." in cleaned_name:
            parts = cleaned_name.split(".")
            # Try progressively longer prefixes to find the module name
            for i in range(1, len(parts)):
                potential_module = ".".join(parts[:i])
                if potential_module in self.source_tracker.module_snapshots:
                    # Found the module prefix, return the rest
                    return ".".join(parts[i:])

        # For nested class methods, preserve the full qualified name
        # The _find_function_in_namespace method handles dotted lookups correctly
        return cleaned_name

    def _get_original_line_number(self, obj: Any) -> int:
        return obj.__code__.co_firstlineno

    def _cache_patch_offset(self, obj: Any) -> None:
        """Cache the ctypes offset for faster future patching."""
        obj_id = id(obj)
        if obj_id not in self.patch_cache:
            offset = self.infer_field_offset(obj, "__code__")
            self.patch_cache[obj_id] = offset

    def _patch_nested_functions_in_code(
        self,
        code_obj: types.CodeType,
        _parent_obj: Any,
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
        return isinstance(obj, types.CodeType) and obj.co_name != "<module>"

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

    def _has_wrapper_closures(self, func: FunctionType) -> bool:
        """Detect if function has wrapper closures from decorators."""
        if not hasattr(func, "__closure__") or not func.__closure__:
            return False

        # Look for nested function code objects in closure
        for cell in func.__closure__:
            try:
                content = cell.cell_contents
                if hasattr(content, "__code__") and hasattr(content, "__name__"):
                    # Found a function closure - likely a wrapper
                    return True
            except ValueError:
                continue
        return False

    def _patch_decorated_function_with_closures(
        self, func: Any, new_first_line: int, obj_name: str
    ) -> bool:
        """Patch a decorated function by recursively updating all closure code objects."""
        try:
            old_line = func.__code__.co_firstlineno

            # For decorated functions, the new_first_line from AST tracking points to the function definition,
            # but this function object is actually a wrapper. We need to calculate the correct wrapper position.
            if func.__code__.co_name == "wrapper":
                # This is a wrapper function - calculate position based on simple line delta from module changes
                # Get the line delta from module-level changes (how many lines were added/removed at the top)
                line_delta = self._calculate_simple_line_delta(obj_name)
                corrected_new_line = old_line + line_delta
            else:
                # Use the AST-calculated position
                line_delta = new_first_line - old_line
                corrected_new_line = new_first_line

            # Patch the main function first
            old_code = func.__code__
            new_code = old_code.replace(co_firstlineno=corrected_new_line)
            self.try_patch_attr(func, new_code, "__code__", new_is_value=True)

            # Then recursively patch all closures with the same delta
            self._patch_closure_hierarchy_recursive(func, line_delta, obj_name, depth=0)

            return True
        except Exception as e:
            warnings.warn(f"Failed to patch decorated function {obj_name}: {e}")
            return False

    def _patch_closure_hierarchy_recursive(
        self, func: Any, line_delta: int, obj_name: str, depth: int
    ) -> None:
        """Recursively patch code objects in function closures."""
        try:
            # Only process closure functions, not the current function (already patched)
            if hasattr(func, "__closure__") and func.__closure__:
                for i, cell in enumerate(func.__closure__):
                    try:
                        content = cell.cell_contents
                        if hasattr(content, "__code__") and hasattr(
                            content, "__name__"
                        ):
                            # Patch this closure function
                            old_code = content.__code__
                            new_first_line = old_code.co_firstlineno + line_delta
                            new_code = old_code.replace(co_firstlineno=new_first_line)
                            self.try_patch_attr(
                                content, new_code, "__code__", new_is_value=True
                            )

                            # Recursively patch deeper closures
                            self._patch_closure_hierarchy_recursive(
                                content,
                                line_delta,
                                f"{obj_name}.closure[{i}]",
                                depth + 1,
                            )
                    except ValueError:
                        # Empty cell, skip
                        pass

        except Exception as e:
            warnings.warn(
                f"Failed to patch closure at depth {depth} for {obj_name}: {e}"
            )
            raise

    def _calculate_simple_line_delta(self, obj_name: str) -> int:
        """Calculate line delta based on actual module source changes.

        This computes how many lines were added/removed at the module level
        by comparing the current and previous source snapshots.
        """
        try:
            # Find the module this object belongs to
            module_name = self._extract_module_name_from_obj_name(obj_name)
            if not module_name:
                return 0

            # Get current and previous positions
            previous_positions = self.source_tracker.code_positions.get(module_name, {})
            if not previous_positions or not self._current_positions:
                return 0

            # Find the earliest function position in previous snapshot
            # and compare with current snapshot to estimate line additions
            earliest_func_name = None
            earliest_line = 999999

            for pos_name, position in previous_positions.items():
                if "." not in pos_name and position.start_line < earliest_line:
                    earliest_line = position.start_line
                    earliest_func_name = pos_name

            if earliest_func_name and earliest_func_name in self._current_positions:
                new_position = self._current_positions[earliest_func_name].start_line
                return new_position - earliest_line

            return 0

        except Exception:
            return 0

    def _extract_module_name_from_obj_name(self, obj_name: str) -> Optional[str]:
        """Extract module name from object name, if possible."""
        if "." not in obj_name:
            return None

        # Try progressively longer prefixes to handle package.module cases
        parts = obj_name.split(".")
        for i in range(
            len(parts) - 1, 0, -1
        ):  # Start from longest possible module name
            potential_module = ".".join(parts[:i])
            if potential_module in self.source_tracker.module_snapshots:
                return potential_module

        return None
