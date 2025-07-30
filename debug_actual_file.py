#!/usr/bin/env python3
"""Debug what's actually in the generated test file."""

import tempfile
import ast

# Create the exact same content as in the test
test_content = """
def decorator(func):
    x = 1
    return func

@decorator
def decorated_func():
    return 8/0
"""

# Write to a temp file
with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
    f.write(test_content)
    temp_path = f.name

print(f"Created temp file: {temp_path}")
print("Content:")
with open(temp_path, 'r') as f:
    lines = f.readlines()
    for i, line in enumerate(lines, 1):
        print(f"Line {i}: {repr(line)}")

# Parse the AST to see what line numbers we get
with open(temp_path, 'r') as f:
    content = f.read()

tree = ast.parse(content)
print("\nAST analysis:")
for node in ast.walk(tree):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        decorator_line = node.decorator_list[0].lineno if node.decorator_list else None
        print(f"Function '{node.name}': def on line {node.lineno}, decorator on line {decorator_line}")
        
        # Find the return 8/0 line
        for child in ast.walk(node):
            if isinstance(child, ast.Return) and hasattr(child.value, 'left'):
                print(f"  Return statement on line {child.lineno}")

import os
os.unlink(temp_path)