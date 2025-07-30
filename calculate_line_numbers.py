"""Calculate new line numbers for bytecode instructions.

This module provides functionality to map instruction offsets to new line numbers
when updating a function's line numbering due to code changes or reloading.
"""

from typing import List, Dict, Any, Union


def calculate_new_line_numbers(
    instructions: List[Dict[str, Any]], 
    old_firstlineno: int, 
    new_firstlineno: int
) -> Dict[int, int]:
    """Map each instruction offset to its new line number.
    
    Takes a list of instruction dictionaries (from parse_bytecode) and calculates
    what the new line number should be for each instruction offset, given the
    change from old_firstlineno to new_firstlineno.
    
    The function preserves relative line number differences within the function
    while adjusting the absolute line numbers based on the new starting line.
    
    Args:
        instructions: List of instruction dictionaries from parse_bytecode(),
                     each containing 'offset', 'opname', 'starts_line', 'is_jump_target'
        old_firstlineno: Original first line number of the function
        new_firstlineno: New first line number for the function
        
    Returns:
        Dictionary mapping instruction offsets (int) to new line numbers (int)
        
    Raises:
        TypeError: If instructions is not a list, or line numbers are not integers
        KeyError: If instruction dictionaries are missing required fields
        
    Example:
        >>> instructions = [
        ...     {'offset': 0, 'opname': 'LOAD_CONST', 'starts_line': 10, 'is_jump_target': False},
        ...     {'offset': 2, 'opname': 'STORE_NAME', 'starts_line': None, 'is_jump_target': False},
        ...     {'offset': 4, 'opname': 'LOAD_CONST', 'starts_line': 11, 'is_jump_target': False},
        ... ]
        >>> result = calculate_new_line_numbers(instructions, 10, 20)
        >>> print(result)
        {0: 20, 2: 20, 4: 21}
    """
    if not isinstance(instructions, list):
        raise TypeError(f"Expected list of instructions, got {type(instructions).__name__}")
    
    if not isinstance(old_firstlineno, int):
        raise TypeError(f"old_firstlineno must be int, got {type(old_firstlineno).__name__}")
        
    if not isinstance(new_firstlineno, int):
        raise TypeError(f"new_firstlineno must be int, got {type(new_firstlineno).__name__}")
    
    # Handle empty instructions list
    if not instructions:
        return {}
    
    line_offset = new_firstlineno - old_firstlineno
    current_line = old_firstlineno
    
    offset_to_line = {}
    
    for instr in instructions:
        # Validate instruction structure
        try:
            offset = instr['offset']
            starts_line = instr['starts_line']
        except KeyError as e:
            raise KeyError(f"Instruction dictionary missing required field: {e}") from e
        
        # Update current line if instruction starts a new line
        if starts_line is not None:
            current_line = starts_line
        
        # Calculate new line number with offset
        new_line = current_line + line_offset
        offset_to_line[offset] = new_line
    
    return offset_to_line