"""Update function line numbers using line table reconstruction.

This module provides the main functionality to update a function's line number
information by reconstructing its co_linetable using the complete pipeline of
bytecode parsing, line number calculation, and line table encoding.
"""

from types import CodeType, FunctionType
from typing import Union, Callable

# Import the pipeline functions
from parse_bytecode import parse_bytecode
from calculate_line_numbers import calculate_new_line_numbers
from encode_linetable import encode_linetable


def update_function_line_numbers(func: Callable, new_firstlineno: int) -> None:
    """Update a function's line number information manually.
    
    Reconstructs the function's co_linetable by parsing its bytecode,
    calculating new line numbers, encoding the new line table, and
    creating a new code object with updated line number information.
    
    This is the main entry point that orchestrates the complete pipeline:
    1. Parse bytecode to extract instruction information
    2. Calculate new line numbers for each instruction
    3. Encode the new line table in Python 3.11 format
    4. Create and assign a new code object with updated information
    
    Args:
        func: Function object to update (must have __code__ attribute)
        new_firstlineno: New first line number for the function
        
    Raises:
        AttributeError: If func doesn't have __code__ attribute or is invalid
        TypeError: If new_firstlineno is not an integer
        ValueError: If new_firstlineno is invalid (negative or zero)
        
    Example:
        >>> def example_func():
        ...     return 42
        >>> print(example_func.__code__.co_firstlineno)
        1
        >>> update_function_line_numbers(example_func, 100)
        >>> print(example_func.__code__.co_firstlineno)
        100
        >>> example_func()  # Function still works
        42
    """
    # Validate inputs
    if not hasattr(func, '__code__'):
        raise AttributeError(f"Object {type(func).__name__} does not have __code__ attribute")
    
    if not isinstance(new_firstlineno, int):
        raise TypeError(f"new_firstlineno must be int, got {type(new_firstlineno).__name__}")
    
    if new_firstlineno <= 0:
        raise ValueError(f"new_firstlineno must be positive, got {new_firstlineno}")
    
    old_code = func.__code__
    if not isinstance(old_code, CodeType):
        raise AttributeError("Function __code__ is not a valid CodeType object")
    
    old_firstlineno = old_code.co_firstlineno
    
    try:
        # Step 1: Parse bytecode to get instruction information  
        instructions = parse_bytecode(old_code)
        
        # Step 2: Calculate new line numbers for each instruction
        offset_to_line = calculate_new_line_numbers(
            instructions, old_firstlineno, new_firstlineno
        )
        
        # Step 3: Encode new line table in Python 3.11 format
        new_linetable = encode_linetable(offset_to_line, len(old_code.co_code))
        
        # Step 4: Create new code object with updated line information
        # Use code.replace() method available in Python 3.8+
        new_code = old_code.replace(
            co_firstlineno=new_firstlineno,
            co_linetable=new_linetable
        )
        
        # Step 5: Update the function's code object
        func.__code__ = new_code
        
    except Exception as e:
        # Re-raise with more context about which step failed
        step_info = "unknown step"
        if "parse_bytecode" in str(e) or "instructions" in str(e):
            step_info = "bytecode parsing"
        elif "calculate_new_line_numbers" in str(e) or "offset_to_line" in str(e):
            step_info = "line number calculation"  
        elif "encode_linetable" in str(e) or "linetable" in str(e):
            step_info = "line table encoding"
        elif "replace" in str(e) or "CodeType" in str(e):
            step_info = "code object creation"
            
        raise type(e)(f"Failed during {step_info}: {e}") from e