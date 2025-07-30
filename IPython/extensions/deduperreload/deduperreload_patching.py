from __future__ import annotations
import ctypes
import sys
from typing import Any

# Import line number update functionality
try:
    import os
    # Add the root directory to sys.path temporarily to import the modules
    root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    if root_dir not in sys.path:
        sys.path.insert(0, root_dir)
    
    from parse_bytecode import parse_bytecode
    from calculate_line_numbers import calculate_new_line_numbers
    from encode_linetable import encode_linetable
    from line_table_reconstruction import (
        LineTableReconstructor, 
        update_function_line_numbers_enhanced,
        FunctionAnalysisError,
        LineTableEncodingError,
        FunctionUpdateError
    )
    LINE_NUMBER_UPDATE_AVAILABLE = True
    LINE_TABLE_RECONSTRUCTION_AVAILABLE = True
    
    # Create a global reconstructor for this module
    _line_table_reconstructor = LineTableReconstructor(enable_logging=False)
    
except ImportError:
    LINE_NUMBER_UPDATE_AVAILABLE = False
    LINE_TABLE_RECONSTRUCTION_AVAILABLE = False

NOT_FOUND: object = object()
_MAX_FIELD_SEARCH_OFFSET = 50

if sys.maxsize > 2**32:
    WORD_TYPE: type[ctypes.c_int32] | type[ctypes.c_int64] = ctypes.c_int64
    WORD_N_BYTES = 8
else:
    WORD_TYPE = ctypes.c_int32
    WORD_N_BYTES = 4


class DeduperReloaderPatchingMixin:
    @staticmethod
    def infer_field_offset(
        obj: object,
        field: str,
    ) -> int:
        field_value = getattr(obj, field, NOT_FOUND)
        if field_value is NOT_FOUND:
            return -1
        obj_addr = ctypes.c_void_p.from_buffer(ctypes.py_object(obj)).value
        field_addr = ctypes.c_void_p.from_buffer(ctypes.py_object(field_value)).value
        if obj_addr is None or field_addr is None:
            return -1
        ret = -1
        for offset in range(1, _MAX_FIELD_SEARCH_OFFSET):
            if (
                ctypes.cast(
                    obj_addr + WORD_N_BYTES * offset, ctypes.POINTER(WORD_TYPE)
                ).contents.value
                == field_addr
            ):
                ret = offset
                break
        return ret

    @classmethod
    def try_write_readonly_attr(
        cls,
        obj: object,
        field: str,
        new_value: object,
        offset: int | None = None,
    ) -> None:
        prev_value = getattr(obj, field, NOT_FOUND)
        if prev_value is NOT_FOUND:
            return
        if offset is None:
            offset = cls.infer_field_offset(obj, field)
        if offset == -1:
            return
        obj_addr = ctypes.c_void_p.from_buffer(ctypes.py_object(obj)).value
        new_value_addr = ctypes.c_void_p.from_buffer(ctypes.py_object(new_value)).value
        if obj_addr is None or new_value_addr is None:
            return
        if prev_value is not None:
            ctypes.pythonapi.Py_DecRef(ctypes.py_object(prev_value))
        if new_value is not None:
            ctypes.pythonapi.Py_IncRef(ctypes.py_object(new_value))
        ctypes.cast(
            obj_addr + WORD_N_BYTES * offset, ctypes.POINTER(WORD_TYPE)
        ).contents.value = new_value_addr

    @classmethod
    def try_patch_readonly_attr(
        cls,
        old: object,
        new: object,
        field: str,
        new_is_value: bool = False,
        offset: int = -1,
    ) -> None:

        old_value = getattr(old, field, NOT_FOUND)
        new_value = new if new_is_value else getattr(new, field, NOT_FOUND)
        if old_value is NOT_FOUND or new_value is NOT_FOUND:
            return
        elif old_value is new_value:
            return
        elif old_value is not None and offset < 0:
            offset = cls.infer_field_offset(old, field)
        elif offset < 0:
            assert not new_is_value
            assert new_value is not None
            offset = cls.infer_field_offset(new, field)
        cls.try_write_readonly_attr(old, field, new_value, offset=offset)

    @classmethod
    def try_patch_attr(
        cls,
        old: object,
        new: object,
        field: str,
        new_is_value: bool = False,
        offset: int = -1,
    ) -> None:
        try:
            setattr(old, field, new if new_is_value else getattr(new, field))
        except (AttributeError, TypeError, ValueError):
            cls.try_patch_readonly_attr(old, new, field, new_is_value, offset)

    @classmethod
    def patch_function(
        cls, to_patch_to: Any, to_patch_from: Any, is_method: bool
    ) -> None:
        new_freevars = []
        new_closure = []
        for i, v in enumerate(to_patch_to.__code__.co_freevars):
            if v not in to_patch_from.__code__.co_freevars or v == "__class__":
                new_freevars.append(v)
                new_closure.append(to_patch_to.__closure__[i])
        for i, v in enumerate(to_patch_from.__code__.co_freevars):
            if v not in new_freevars:
                new_freevars.append(v)
                new_closure.append(to_patch_from.__closure__[i])
        
        # Update line numbers and line table from the new function
        new_code_base = to_patch_from.__code__
        
        # Apply comprehensive line number update if available
        if (to_patch_from.__code__.co_firstlineno != to_patch_to.__code__.co_firstlineno):
            
            # Strategy 1: Try enhanced line table reconstruction
            if LINE_TABLE_RECONSTRUCTION_AVAILABLE:
                try:
                    # Analyze function context for better handling
                    function_context = {
                        'is_method': is_method,
                        'is_decorated': hasattr(to_patch_from, '__wrapped__'),
                        'method_type': 'instance' if is_method else 'function'
                    }
                    
                    # Create a temporary function to update
                    temp_func = type(to_patch_from)(
                        new_code_base,
                        to_patch_from.__globals__,
                        to_patch_from.__name__,
                        to_patch_from.__defaults__,
                        to_patch_from.__closure__
                    )
                    
                    # Use enhanced line number update
                    success = _line_table_reconstructor.update_function_line_numbers_comprehensive(
                        temp_func, to_patch_from.__code__.co_firstlineno, function_context
                    )
                    
                    if success:
                        new_code_base = temp_func.__code__
                    else:
                        # Fall back to strategy 2
                        raise FunctionUpdateError("Enhanced reconstruction failed")
                        
                except Exception as e:
                    # Log the specific error for debugging
                    try:
                        print(f"Warning: Enhanced line number update failed: {e}", file=sys.stderr)
                    except Exception:
                        pass
                        
                    # Fall back to strategy 2
                    if LINE_NUMBER_UPDATE_AVAILABLE:
                        try:
                            # Use the basic line number update pipeline
                            old_firstlineno = to_patch_to.__code__.co_firstlineno
                            new_firstlineno = to_patch_from.__code__.co_firstlineno
                            
                            # Parse bytecode to get instruction information
                            instructions = parse_bytecode(new_code_base)
                            
                            # Calculate new line numbers for each instruction  
                            offset_to_line = calculate_new_line_numbers(
                                instructions, new_firstlineno, new_firstlineno
                            )
                            
                            # Encode new line table in Python 3.11 format
                            new_linetable = encode_linetable(offset_to_line, len(new_code_base.co_code))
                            
                            # Create updated code with proper line table
                            new_code_base = new_code_base.replace(co_linetable=new_linetable)
                            
                        except Exception as e2:
                            # Final fallback - just log and continue
                            try:
                                print(f"Warning: Basic line number update also failed: {e2}", file=sys.stderr)
                            except Exception:
                                pass
            
            # Strategy 2: Use basic line number update if enhanced is not available
            elif LINE_NUMBER_UPDATE_AVAILABLE:
                try:
                    # Use the basic line number update pipeline
                    old_firstlineno = to_patch_to.__code__.co_firstlineno
                    new_firstlineno = to_patch_from.__code__.co_firstlineno
                    
                    # Parse bytecode to get instruction information
                    instructions = parse_bytecode(new_code_base)
                    
                    # Calculate new line numbers for each instruction  
                    offset_to_line = calculate_new_line_numbers(
                        instructions, new_firstlineno, new_firstlineno
                    )
                    
                    # Encode new line table in Python 3.11 format
                    new_linetable = encode_linetable(offset_to_line, len(new_code_base.co_code))
                    
                    # Create updated code with proper line table
                    new_code_base = new_code_base.replace(co_linetable=new_linetable)
                    
                except Exception as e:
                    # Fall back to basic line number update
                    try:
                        print(f"Warning: Failed to update line numbers during patching: {e}", file=sys.stderr)
                    except Exception:
                        pass
        
        code_with_new_freevars = new_code_base.replace(
            co_freevars=tuple(new_freevars),
            co_firstlineno=new_code_base.co_firstlineno,
            co_linetable=new_code_base.co_linetable
        )
        # lambdas may complain if there is more than one freevar
        cls.try_patch_attr(
            to_patch_to, code_with_new_freevars, "__code__", new_is_value=True
        )
        offset = -1
        if to_patch_to.__closure__ is None and to_patch_from.__closure__ is not None:
            offset = cls.infer_field_offset(to_patch_from, "__closure__")
        cls.try_patch_readonly_attr(
            to_patch_to,
            tuple(new_closure) or None,
            "__closure__",
            new_is_value=True,
            offset=offset,
        )
        for attr in ("__defaults__", "__kwdefaults__", "__doc__", "__dict__"):
            cls.try_patch_attr(to_patch_to, to_patch_from, attr)
        if is_method:
            cls.try_patch_readonly_attr(to_patch_to, to_patch_from, "__self__")
