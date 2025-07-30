#!/usr/bin/env python3

import sys
import os

# Add the current directory to sys.path
sys.path.insert(0, '/Users/jay.sarva/oss/ipython')

from line_table_reconstruction import enable_reconstruction_logging

# Enable logging to see what's happening
enable_reconstruction_logging()

# Now run the specific test
import subprocess
result = subprocess.run([
    sys.executable, '-m', 'pytest', 
    'IPython/extensions/tests/test_deduperreload.py::TestAutoreloadTraceback::test_traceback_decorator_line_numbers',
    '-xvs'
], capture_output=True, text=True, cwd='/Users/jay.sarva/oss/ipython')

print("STDOUT:")
print(result.stdout)
print("\nSTDERR:")
print(result.stderr)
print(f"\nReturn code: {result.returncode}")