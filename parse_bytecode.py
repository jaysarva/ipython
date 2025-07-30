"""Parse bytecode to extract instruction offsets and line numbers.

This module provides functionality to parse Python 3.11 bytecode instructions
and extract their offsets, opcodes, line numbers, and jump target information.
"""

import dis
from types import CodeType
from typing import List, Dict, Any, Optional


def parse_bytecode(code_obj: CodeType) -> List[Dict[str, Any]]:
    """Extract instruction offsets and their original line numbers.
    
    Parses a Python code object's bytecode to extract detailed information
    about each instruction, including offsets, operation names, line number
    information, and jump target status.
    
    Args:
        code_obj: A Python code object to parse
        
    Returns:
        List of dictionaries, each containing:
        - 'offset': int - Byte offset of the instruction
        - 'opname': str - Name of the operation (e.g., 'LOAD_CONST')  
        - 'starts_line': int or None - Line number if instruction starts a new line
        - 'is_jump_target': bool - True if instruction is a jump target
        
    Raises:
        TypeError: If code_obj is not a CodeType object
        AttributeError: If code_obj lacks required attributes
        
    Example:
        >>> def example_func():
        ...     x = 1
        ...     return x
        >>> instructions = parse_bytecode(example_func.__code__)
        >>> print(instructions[0])
        {'offset': 0, 'opname': 'LOAD_CONST', 'starts_line': 2, 'is_jump_target': False}
    """
    if not isinstance(code_obj, CodeType):
        raise TypeError(f"Expected CodeType object, got {type(code_obj).__name__}")
    
    instructions = []
    
    try:
        # Use dis.get_instructions to parse the bytecode
        for instr in dis.get_instructions(code_obj):
            instructions.append({
                'offset': instr.offset,
                'opname': instr.opname,
                'starts_line': instr.starts_line,  # None if same line as previous
                'is_jump_target': instr.is_jump_target
            })
    except AttributeError as e:
        raise AttributeError(f"Invalid code object: {e}") from e
        
    return instructions