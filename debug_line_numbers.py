#!/usr/bin/env python3
"""Debug script to understand line number updates"""

import ast
import sys
import os

# Add the root directory to sys.path temporarily to import the modules
root_dir = '/Users/jay.sarva/oss/ipython'
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from parse_bytecode import parse_bytecode
from calculate_line_numbers import calculate_new_line_numbers
from encode_linetable import encode_linetable

# Test code similar to what's in the test
code1 = """
def custom_decorator(func):
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)
    return wrapper

@custom_decorator
def decorated_func():
    return "decorated"
"""

code2 = """
# Added line
# Added line
def custom_decorator(func):
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)
    return wrapper

@custom_decorator
def decorated_func():
    return "decorated"
"""

def collect_function_line_numbers(body, line_map, prefixes=None):
    """Debug version of the function line number collection"""
    prefixes = prefixes or []
    
    for node in body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Regular function or async function
            qualified_name = ".".join(prefixes + [node.name])
            line_map[qualified_name] = node.lineno
            print(f"Found function {qualified_name} at line {node.lineno}")
            
            # Process nested functions
            collect_function_line_numbers(node.body, line_map, prefixes + [node.name])
        elif isinstance(node, ast.ClassDef):
            # Class - process its methods
            class_prefixes = prefixes + [node.name]
            for class_node in node.body:
                if isinstance(class_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    qualified_name = ".".join(class_prefixes + [class_node.name])
                    line_map[qualified_name] = class_node.lineno
                    print(f"Found method {qualified_name} at line {class_node.lineno}")
                    
                    # Process nested functions within methods
                    collect_function_line_numbers(class_node.body, line_map, 
                                              class_prefixes + [class_node.name])
            
            # Process nested classes
            collect_function_line_numbers(node.body, line_map, class_prefixes)

def debug_line_numbers():
    print("=== Original code ===")
    ast1 = ast.parse(code1)
    line_map1 = {}
    collect_function_line_numbers(ast1.body, line_map1)
    print(f"Line map 1: {line_map1}")
    
    print("\n=== Updated code ===")
    ast2 = ast.parse(code2)
    line_map2 = {}
    collect_function_line_numbers(ast2.body, line_map2)
    print(f"Line map 2: {line_map2}")
    
    print("\n=== Expected difference ===")
    for name in line_map1:
        if name in line_map2:
            print(f"{name}: {line_map1[name]} -> {line_map2[name]} (diff: +{line_map2[name] - line_map1[name]})")

if __name__ == "__main__":
    debug_line_numbers()