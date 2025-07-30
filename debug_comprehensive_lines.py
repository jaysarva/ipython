#!/usr/bin/env python3
"""Debug comprehensive line numbers"""

import sys
import os
import tempfile
import shutil

# Add paths
sys.path.insert(0, '/Users/jay.sarva/oss/ipython')
sys.path.insert(0, '/Users/jay.sarva/oss/ipython/IPython/extensions/tests')

from test_deduperreload import ShellFixture

def debug_comprehensive_line_numbers():
    # Set up temporary test environment
    fixture = ShellFixture()
    fixture.setUp()
    
    try:
        fixture.shell.magic_autoreload("2")
        
        # Create module with identical code to test
        mod_name, mod_fn = fixture.new_module("""
            # Line 1
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
        )
        
        # Read the actual generated file
        with open(mod_fn, 'r') as f:
            original_content = f.read()
        
        print("=== Original file content ===")
        for i, line in enumerate(original_content.splitlines(), 1):
            print(f"{i:2d}: {line}")
        
        # Import and get initial line numbers
        fixture.shell.run_code(f"import {mod_name}")
        fixture.shell.run_code("pass")
        mod = sys.modules[mod_name]
        
        original_lines = {
            'regular_func': mod.regular_func.__code__.co_firstlineno,
            'method': mod.TestClass.method.__code__.co_firstlineno,
            'static_func': mod.TestClass.static_func.__code__.co_firstlineno,
            'class_method': mod.TestClass.class_method.__func__.__code__.co_firstlineno,
            'outer_method': mod.TestClass.outer_method.__code__.co_firstlineno,
            'class_prop': mod.TestClass.class_prop.fget.__code__.co_firstlineno,
        }
        
        print("\n=== Original co_firstlineno values ===")
        for name, line in original_lines.items():
            print(f"{name}: {line}")
        
        # Update file
        fixture.write_file(mod_fn, """
            # Added line 1
            # Added line 2
            # Added line 3
            # Line 1 (now line 4)
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
        )
        
        # Read the updated file
        with open(mod_fn, 'r') as f:
            updated_content = f.read()
        
        print("\n=== Updated file content ===")
        for i, line in enumerate(updated_content.splitlines(), 1):
            print(f"{i:2d}: {line}")
        
        # Trigger autoreload and get new line numbers
        fixture.shell.run_code("pass")
        
        updated_lines = {
            'regular_func': mod.regular_func.__code__.co_firstlineno,
            'method': mod.TestClass.method.__code__.co_firstlineno,
            'static_func': mod.TestClass.static_func.__code__.co_firstlineno,
            'class_method': mod.TestClass.class_method.__func__.__code__.co_firstlineno,
            'outer_method': mod.TestClass.outer_method.__code__.co_firstlineno,
            'class_prop': mod.TestClass.class_prop.fget.__code__.co_firstlineno,
        }
        
        print("\n=== Updated co_firstlineno values ===")
        for name, line in updated_lines.items():
            print(f"{name}: {line}")
        
        print("\n=== Analysis ===")
        for name in original_lines:
            original = original_lines[name]
            updated = updated_lines[name]
            expected = original + 3
            print(f"{name}: {original} -> {updated} (expected {expected}, diff={updated-original})")
        
    finally:
        fixture.tearDown()

if __name__ == "__main__":
    debug_comprehensive_line_numbers()