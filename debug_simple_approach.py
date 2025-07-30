#!/usr/bin/env python3

import sys
sys.path.insert(0, '/Users/jay.sarva/oss/ipython')

import dis

# Simulate what happens in the test case
# Original code (line 6 for decorator)
test_code1 = """
def decorator(func):
    return func

@decorator  
def decorated_func():
    return 8/0
"""

# Modified code (line 6 for decorator due to added line)
test_code2 = """
def decorator(func):
    x = 1
    return func

@decorator  
def decorated_func():
    return 8/0
"""

print("=== ORIGINAL CODE ===")
exec(test_code1)
original_func = decorated_func
print(f"co_firstlineno: {original_func.__code__.co_firstlineno}")
dis.dis(original_func)

# Test error location
try:
    original_func()
except ZeroDivisionError:
    import traceback
    tb = traceback.format_exc()
    print("Error traceback:", tb.split('\n')[-3])  # Get the error line

print("\n=== MODIFIED CODE (separate execution) ===")
exec(test_code2)
modified_func = decorated_func
print(f"co_firstlineno: {modified_func.__code__.co_firstlineno}")
dis.dis(modified_func)

# Test error location
try:
    modified_func()
except ZeroDivisionError:
    import traceback
    tb = traceback.format_exc()
    print("Error traceback:", tb.split('\n')[-3])  # Get the error line

print("\n=== WHAT DEDUPERRELOAD SHOULD DO ===")
print("The deduperreload system detects that:")
print("- The decorator moved from line 5 to line 6")
print("- So co_firstlineno should change from 5 to 6")
print("- BUT the relative line structure within the function stays the same")
print("- The return 8/0 should still be reported as being 2 lines after the decorator")

# The question is: do we need to reconstruct the entire line table?
# Or can we just adjust the existing line table?

print("\n=== TESTING SIMPLE APPROACH ===")
# What if we just adjust the co_firstlineno and keep the original line table?
# This should work if the relative structure is the same

# Reset to original
exec(test_code1)
print(f"Before adjustment: co_firstlineno = {decorated_func.__code__.co_firstlineno}")

# Simulate moving the decorator from line 5 to line 6
new_firstlineno = 6  # This is what the AST parsing would detect
old_code = decorated_func.__code__

# Simple approach: just update co_firstlineno
simple_new_code = old_code.replace(co_firstlineno=new_firstlineno)
decorated_func.__code__ = simple_new_code

print(f"After simple adjustment: co_firstlineno = {decorated_func.__code__.co_firstlineno}")
dis.dis(decorated_func)

try:
    decorated_func()
except ZeroDivisionError:
    import traceback
    tb = traceback.format_exc()
    print("Error traceback:", tb.split('\n')[-3])  # Get the error line
    
    import re
    line_match = re.search(r'line (\d+)', tb)
    if line_match:
        print(f"Error on line {line_match.group(1)} (expected: 8)")