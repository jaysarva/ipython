#!/usr/bin/env python3

import sys
sys.path.insert(0, '/Users/jay.sarva/oss/ipython')

import dis

# Create the exact test function
test_code = """
def decorator(func):
    x = 1
    return func

@decorator  
def decorated_func():
    return 8/0
"""

exec(test_code)

print("=== ORIGINAL FUNCTION ANALYSIS ===")
print(f"co_firstlineno: {decorated_func.__code__.co_firstlineno}")
print("Detailed disassembly:")

# Get detailed instruction info
code = decorated_func.__code__
instructions = list(dis.get_instructions(code))

for instr in instructions:
    print(f"Offset {instr.offset:2d}: {instr.opname:15s} starts_line={instr.starts_line}")

print(f"\nOriginal co_linetable: {code.co_linetable.hex()}")

# The key insight: what line should the error actually be on?
print("\n=== EXPECTED BEHAVIOR ===")
print("The return 8/0 statement is on line 8")
print("After reconstruction, the error should still be on line 8")
print("But our line table reconstruction maps it to line 7")

# Let's check what happens when we manually create the right line table
print("\n=== TESTING MANUAL FIX ===") 

# Simple approach: just keep the original line table but update co_firstlineno
new_code = code.replace(co_firstlineno=6)
decorated_func.__code__ = new_code

print("After updating only co_firstlineno (keeping original linetable):")
dis.dis(decorated_func)

# Test the error
try:
    decorated_func()
except ZeroDivisionError as e:
    import traceback
    tb_str = traceback.format_exc()
    print(f"\nTraceback: {tb_str}")
    
    # Extract line number
    import re
    line_match = re.search(r'line (\d+)', tb_str)
    if line_match:
        line_num = int(line_match.group(1))
        print(f"Error reported on line: {line_num} (should be 8)")