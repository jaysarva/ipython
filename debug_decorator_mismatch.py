#!/usr/bin/env python3
"""Debug decorator line number mismatch"""

import ast

code = """# Line 1
def regular_func():
    return "regular"

class TestClass:
    def method(self):
        return "method"
        
    @staticmethod  
    def static_func():
        return "static"
        
    @classmethod
    def class_method(cls):
        return "class_method"
        
    def outer_method(self):
        def nested_func():
            return "nested"
        return nested_func()
        
    @property
    def class_prop(self):
        return "class_prop"
"""

# Create a real Python module to test
with open("/tmp/test_comprehensive.py", "w") as f:
    f.write(code)

# Import it
import sys
sys.path.insert(0, "/tmp")
import test_comprehensive

print("=== co_firstlineno values ===")
print(f"regular_func: {test_comprehensive.regular_func.__code__.co_firstlineno}")
print(f"method: {test_comprehensive.TestClass.method.__code__.co_firstlineno}")
print(f"static_func: {test_comprehensive.TestClass.static_func.__code__.co_firstlineno}")
print(f"class_method: {test_comprehensive.TestClass.class_method.__func__.__code__.co_firstlineno}")
print(f"outer_method: {test_comprehensive.TestClass.outer_method.__code__.co_firstlineno}")
print(f"class_prop: {test_comprehensive.TestClass.class_prop.fget.__code__.co_firstlineno}")

# Parse the AST to see what the AST thinks
print("\n=== AST analysis ===")
tree = ast.parse(code)
for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef):
        print(f"AST: {node.name} at line {node.lineno}")

print("\n=== File content with line numbers ===")
for i, line in enumerate(code.splitlines(), 1):
    print(f"{i:2d}: {line}")

# Cleanup
import os
os.remove("/tmp/test_comprehensive.py")
sys.modules.pop('test_comprehensive', None)