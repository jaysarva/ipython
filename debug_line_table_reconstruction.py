#!/usr/bin/env python3

import sys
sys.path.insert(0, '/Users/jay.sarva/oss/ipython')

from update_function_line_numbers import update_function_line_numbers
import dis

# Create the test function that matches the failing test case
test_code = """
def decorator(func):
    x = 1
    return func

@decorator  
def decorated_func():
    return 8/0
"""

exec(test_code)

print("BEFORE line table reconstruction:")
print(f"co_firstlineno: {decorated_func.__code__.co_firstlineno}")
print("Disassembly:")
dis.dis(decorated_func)

# Now, simulate what happens when we detect the function should be on line 6
# (this is what the deduperreload system would do)
try:
    update_function_line_numbers(decorated_func, 6)
    print("\nAFTER line table reconstruction:")
    print(f"co_firstlineno: {decorated_func.__code__.co_firstlineno}")
    print("Disassembly:")
    dis.dis(decorated_func)
    
    # Test error location
    try:
        decorated_func()
    except ZeroDivisionError as e:
        import traceback
        tb_str = traceback.format_exc()
        print(f"\nTraceback shows: {tb_str}")
        
        # Extract line number from traceback
        import re
        line_match = re.search(r'line (\d+)', tb_str)
        if line_match:
            line_num = int(line_match.group(1))
            print(f"Error reported on line: {line_num}")
            print(f"Expected line: 8")
            print(f"Off by: {8 - line_num}")
            
except Exception as e:
    print(f"Error during reconstruction: {e}")
    import traceback
    traceback.print_exc()