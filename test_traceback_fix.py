import sys
import os

sys.path.insert(0, ".")

from IPython.core.interactiveshell import InteractiveShell
import tempfile
import traceback
import shutil

ip = InteractiveShell.instance()

tmpdir = os.path.join(tempfile.gettempdir(), "autoreload_demo")
os.makedirs(tmpdir, exist_ok=True)
sys.path.insert(0, tmpdir)
mod_path = os.path.join(tmpdir, "mymod.py")


def write(src: str):
    with open(mod_path, "w") as f:
        f.write(src)


print("=== Cell 1: Setup and first failure ===")
write("def buggy():\n    return 1/0\n")

ip.run_line_magic("load_ext", "autoreload")
ip.run_line_magic("autoreload", "2")

import mymod

try:
    mymod.buggy()
except Exception:
    print("Original traceback:")
    traceback.print_exc()

print("\n=== Cell 2: Change the code ===")
write("def buggy():\n    return 42/0\n")

print("\n=== Cell 3: Call function again ===")
try:
    mymod.buggy()
except Exception:
    print("After reload traceback:")
    traceback.print_exc()

shutil.rmtree(tmpdir, ignore_errors=True)
