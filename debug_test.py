#!/usr/bin/env python3
"""Debug the line number update functionality"""

import sys
import os
import tempfile
import shutil

# Add paths
sys.path.insert(0, '/Users/jay.sarva/oss/ipython')
sys.path.insert(0, '/Users/jay.sarva/oss/ipython/IPython/extensions/tests')

from test_deduperreload import FakeShell

def debug_line_number_update():
    # Set up temporary test environment
    test_dir = tempfile.mkdtemp()
    old_sys_path = list(sys.path)
    sys.path.insert(0, test_dir)
    
    try:
        shell = FakeShell()
        shell.magic_autoreload("2")
        
        # Create a temporary module
        mod_name = "temp_debug_mod"
        mod_fn = os.path.join(test_dir, f"{mod_name}.py")
        
        # Initial code
        with open(mod_fn, "w", encoding="utf-8") as f:
            f.write("""
def custom_decorator(func):
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)
    return wrapper

@custom_decorator
def decorated_func():
    return "decorated"
""")
        
        # Import and trigger initial loading
        shell.run_code(f"import {mod_name}")
        shell.run_code("pass")  # Trigger autoreload check
        mod = sys.modules[mod_name]
        
        print(f"Initial decorated_func line: {mod.decorated_func.__code__.co_firstlineno}")
        
        # Update with added lines
        with open(mod_fn, "w", encoding="utf-8") as f:
            f.write("""
# Added line
# Added line
def custom_decorator(func):
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)
    return wrapper

@custom_decorator
def decorated_func():
    return "decorated"
""")
        
        # Trigger autoreload
        shell.run_code("pass")
        
        print(f"Updated decorated_func line: {mod.decorated_func.__code__.co_firstlineno}")
        
        # Test function still works
        print(f"Function result: {mod.decorated_func()}")
        
    finally:
        # Cleanup
        for name in list(sys.modules.keys()):
            if name.startswith("temp_debug"):
                sys.modules.pop(name, None)
        shutil.rmtree(test_dir)
        sys.path = old_sys_path

if __name__ == "__main__":
    debug_line_number_update()