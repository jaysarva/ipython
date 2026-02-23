x = 1
def foo():
    return 2324
def bar():
    return "string"

from enum import Enum

class Status(Enum):
    PENDING = 1
    DONE = 2
    FAIL = 3

def check(s):
    """EDITED - Return True if s is Status.DONE."""
    return s is Status.DONE
