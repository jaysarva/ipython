#!/usr/bin/env python3
"""Debug actual line numbers in generated files"""

import sys
import os
import tempfile
import shutil

# Add paths
sys.path.insert(0, '/Users/jay.sarva/oss/ipython')
sys.path.insert(0, '/Users/jay.sarva/oss/ipython/IPython/extensions/tests')

from test_deduperreload import ShellFixture

def debug_actual_line_numbers():
    # Set up temporary test environment
    fixture = ShellFixture()
    fixture.setUp()
    
    try:
        fixture.shell.magic_autoreload("2")
        
        # Create module with identical code to test
        mod_name, mod_fn = fixture.new_module("""
            def custom_decorator(func):
                def wrapper(*args, **kwargs):
                    return func(*args, **kwargs)
                return wrapper

            @custom_decorator
            def decorated_func():
                return "decorated"
            """
        )
        
        # Read the actual generated file
        with open(mod_fn, 'r') as f:
            original_content = f.read()
        
        print("=== Original file content ===")
        for i, line in enumerate(original_content.splitlines(), 1):
            print(f"{i:2d}: {line}")
        
        # Import and get initial line number
        fixture.shell.run_code(f"import {mod_name}")
        fixture.shell.run_code("pass")
        mod = sys.modules[mod_name]
        
        original_line = mod.decorated_func.__code__.co_firstlineno
        print(f"\nOriginal decorated_func line: {original_line}")
        
        # Update file
        fixture.write_file(mod_fn, """
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
        )
        
        # Read the updated file
        with open(mod_fn, 'r') as f:
            updated_content = f.read()
        
        print("\n=== Updated file content ===")
        for i, line in enumerate(updated_content.splitlines(), 1):
            print(f"{i:2d}: {line}")
        
        # Trigger autoreload and get new line number
        fixture.shell.run_code("pass")
        updated_line = mod.decorated_func.__code__.co_firstlineno
        print(f"\nUpdated decorated_func line: {updated_line}")
        print(f"Difference: {updated_line - original_line}")
        
    finally:
        fixture.tearDown()

if __name__ == "__main__":
    debug_actual_line_numbers()