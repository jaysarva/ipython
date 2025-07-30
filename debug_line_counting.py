#!/usr/bin/env python3

# Test the exact code from the test case to see line numbers
test_code = """
def decorator(func):
    x = 1
    return func

@decorator
def decorated_func():
    return 8/0
"""

print("Line-by-line breakdown:")
lines = test_code.split('\n')
for i, line in enumerate(lines, 1):
    print(f"Line {i}: {repr(line)}")

print("\nExpected:")
print("- @decorator should be line 6")
print("- def decorated_func(): should be line 7") 
print("- return 8/0 should be line 8")

# Test by executing
exec(test_code)
print(f"\nActual co_firstlineno: {decorated_func.__code__.co_firstlineno}")

import dis
print("\nDisassembly:")
dis.dis(decorated_func)