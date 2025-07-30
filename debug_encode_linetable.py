#!/usr/bin/env python3

import sys
sys.path.insert(0, '/Users/jay.sarva/oss/ipython')

from parse_bytecode import parse_bytecode
from calculate_line_numbers import calculate_new_line_numbers
from encode_linetable import encode_linetable

# Test the pipeline with the decorated function
test_code = """
def decorator(func):
    x = 1
    return func

@decorator  
def decorated_func():
    return 8/0
"""

exec(test_code)

print("Original function:")
print(f"co_firstlineno: {decorated_func.__code__.co_firstlineno}")
print(f"co_linetable: {decorated_func.__code__.co_linetable}")

# Test the pipeline
old_code = decorated_func.__code__
print(f"\nOld co_firstlineno: {old_code.co_firstlineno}")

# Step 1: Parse bytecode
instructions = parse_bytecode(old_code)
print(f"\nInstructions: {instructions}")

# Step 2: Calculate new line numbers (let's keep the same first line for now)
offset_to_line = calculate_new_line_numbers(instructions, old_code.co_firstlineno, old_code.co_firstlineno)
print(f"\nOffset to line mapping: {offset_to_line}")

# Step 3: Encode line table
try:
    new_linetable = encode_linetable(offset_to_line, len(old_code.co_code))
    print(f"\nNew linetable: {new_linetable}")
    print(f"Original linetable: {old_code.co_linetable}")
    
    # Test if the new linetable works
    new_code = old_code.replace(co_linetable=new_linetable)
    decorated_func.__code__ = new_code
    
    import dis
    print("\nDisassembly after reconstruction:")
    dis.dis(decorated_func)
    
except Exception as e:
    print(f"\nError in encode_linetable: {e}")
    import traceback
    traceback.print_exc()