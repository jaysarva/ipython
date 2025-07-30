#!/usr/bin/env python3

def decorator(func):
    return func

@decorator
def decorated_func():
    return 8/0

print(f"decorated_func.__code__.co_firstlineno = {decorated_func.__code__.co_firstlineno}")

import dis
print("\nBytecode for decorated_func:")
dis.dis(decorated_func)