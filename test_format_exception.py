import traceback
import sys

# Test both old and new signatures
try:
    # Create a simple exception
    try:
        1 / 0
    except Exception as e:
        exc_type, exc_value, exc_tb = sys.exc_info()

        print("Testing old signature (etype, value, tb):")
        try:
            result = traceback.format_exception(exc_type, exc_value, exc_tb)
            print("Old signature works:", len(result), "lines")
        except TypeError as te:
            print("Old signature error:", te)

        print("\nTesting new signature (exc):")
        try:
            result = traceback.format_exception(e)
            print("New signature works:", len(result), "lines")
        except TypeError as te:
            print("New signature error:", te)

        print("\nTesting new signature with all args:")
        try:
            result = traceback.format_exception(e, value=exc_value, tb=exc_tb)
            print("New signature with args works:", len(result), "lines")
        except TypeError as te:
            print("New signature with args error:", te)

except Exception as e:
    print("Test failed:", e)
