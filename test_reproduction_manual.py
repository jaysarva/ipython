#!/usr/bin/env python3
"""
Manual test of the traceback fix reproduction case.
"""
import tempfile
import os
import sys
import traceback
import subprocess

tmpdir = os.path.join(tempfile.gettempdir(), "autoreload_demo")
os.makedirs(tmpdir, exist_ok=True)
sys.path.insert(0, tmpdir)
mod_path = os.path.join(tmpdir, "mymod.py")


def write(src: str):
    with open(mod_path, "w") as f:
        f.write(src)


print("=== Testing traceback fix reproduction case ===")

print("\n--- Cell 1: Setup and first failure ---")
write("def buggy():\n    return 1/0\n")

ipython_script = f"""
import sys
sys.path.insert(0, "{tmpdir}")

from IPython import get_ipython
ip = get_ipython()
if ip is None:
    from IPython.core.interactiveshell import InteractiveShell
    ip = InteractiveShell.instance()

ip.run_line_magic("load_ext", "autoreload")
ip.run_line_magic("autoreload", "2")

import mymod

print("Original traceback (should show correct filename):")
try:
    mymod.buggy()
except Exception:
    import traceback
    traceback.print_exc()

with open("{mod_path}", "w") as f:
    f.write("def buggy():\\n    return 42/0\\n")

print("\\nAfter reload traceback (should show correct filename and source):")
try:
    mymod.buggy()
except Exception:
    import traceback
    traceback.print_exc()
"""

with open("/tmp/test_ipython_traceback.py", "w") as f:
    f.write(ipython_script)

print("Running IPython test script...")
result = subprocess.run(
    [sys.executable, "-c", f"exec(open('/tmp/test_ipython_traceback.py').read())"],
    capture_output=True,
    text=True,
    cwd="/home/ubuntu/ipython",
)

print("STDOUT:")
print(result.stdout)
if result.stderr:
    print("STDERR:")
    print(result.stderr)
print(f"Return code: {result.returncode}")

import shutil

shutil.rmtree(tmpdir, ignore_errors=True)
os.remove("/tmp/test_ipython_traceback.py")
