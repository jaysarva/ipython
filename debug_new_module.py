#!/usr/bin/env python3
"""Debug new_module function"""

import sys
import os
import tempfile
import shutil
import textwrap

# Add paths
sys.path.insert(0, '/Users/jay.sarva/oss/ipython')
sys.path.insert(0, '/Users/jay.sarva/oss/ipython/IPython/extensions/tests')

from test_deduperreload import ShellFixture

def squish_text(text: str) -> str:
    """Copy of the squish_text function from the test file"""
    prev_indentation = 0
    transformed_text_lines = []
    for line in text.strip("\n").splitlines():
        line_without_indentation = line.lstrip()
        indentation = len(line) - len(line_without_indentation)
        if indentation == 0:
            indentation = prev_indentation
        else:
            prev_indentation = indentation
        transformed_text_lines.append(
            textwrap.indent(line_without_indentation, " " * indentation)
        )
    return textwrap.dedent("\n".join(transformed_text_lines))

def test_new_module_output():
    # Create a test fixture
    fixture = ShellFixture()
    fixture.setUp()
    
    try:
        code = """
def custom_decorator(func):
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)
    return wrapper

@custom_decorator
def decorated_func():
    return "decorated"
        """
        
        print("=== Input code ===")
        print(repr(code))
        
        print("\n=== After squish_text ===")
        squished = squish_text(code)
        print(repr(squished))
        
        print("\n=== Line by line ===")
        for i, line in enumerate(squished.splitlines(), 1):
            print(f"{i:2d}: {repr(line)}")
        
        # Now test with new_module
        print("\n=== Using new_module ===")
        mod_name, mod_fn = fixture.new_module(code)
        
        # Read the actual file content
        with open(mod_fn, 'r') as f:
            file_content = f.read()
        
        print("File content:")
        print(repr(file_content))
        
        print("\nFile content line by line:")
        for i, line in enumerate(file_content.splitlines(), 1):
            print(f"{i:2d}: {repr(line)}")
    
    finally:
        fixture.tearDown()

if __name__ == "__main__":
    test_new_module_output()