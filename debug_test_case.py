#!/usr/bin/env python3

# First case - this should put the error on line 6
code1 = """
def decorator(func):
    return func

@decorator
def decorated_func():
    return 8/0
"""

# Second case - this should put the error on line 8
code2 = """
def decorator(func):
    x = 1
    return func

@decorator
def decorated_func():
    return 8/0
"""

exec(code1)
print("First case - decorated_func.__code__.co_firstlineno =", decorated_func.__code__.co_firstlineno)

try:
    decorated_func()
except ZeroDivisionError as e:
    import traceback
    traceback.print_exc()

print("\n" + "="*50 + "\n")

exec(code2)
print("Second case - decorated_func.__code__.co_firstlineno =", decorated_func.__code__.co_firstlineno)

try:
    decorated_func()
except ZeroDivisionError as e:
    import traceback
    traceback.print_exc()