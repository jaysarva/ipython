#!/usr/bin/env python
import asyncio
import sys
import traceback


from IPython.extensions.tests.deduperreload_test_utils import (
    ShellFixture,
)


class TestAutoreloadTraceback(ShellFixture):
    def test_traceback_line_numbers(self):
        self.shell.magic_autoreload("2")
        mod_name, mod_fn = self.new_module(
            """
            def foo():
                return 42/0
            """,
        )
        self.shell.run_code("import %s" % mod_name)
        self.shell.run_code("pass")
        mod = sys.modules[mod_name]
        try:
            mod.foo()
            assert False  # Should not reach here.
        except ZeroDivisionError as e:
            exception_string = traceback.format_exc()
            assert "line 2" in exception_string

        self.write_file(
            mod_fn,
            """
            def bar():
                return 42
            def foo():
                return 42/0
            """,
        )
        self.shell.run_code("pass")  # Trigger autoreload check
        try:
            mod.foo()
            assert False  # Should not reach here.
        except ZeroDivisionError as e:
            exception_string = traceback.format_exc()
            assert "line 4" in exception_string

    def test_traceback_multiple_function_additions(self):
        """Test line numbers remain accurate when multiple functions are added."""
        self.shell.magic_autoreload("2")
        mod_name, mod_fn = self.new_module(
            """
            def original_func():
                return 42/0
            """,
        )
        self.shell.run_code("import %s" % mod_name)
        self.shell.run_code("pass")
        mod = sys.modules[mod_name]

        # Verify original line number
        try:
            mod.original_func()
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            assert "line 2" in exception_string

        # Add multiple functions before the original
        self.write_file(
            mod_fn,
            """
            def new_func1():
                x = 1
                return x
            
            def new_func2():
                y = 2
                return y
                
            def new_func3():
                z = 3
                return z
            
            def original_func():
                return 42/0
            """,
        )
        self.shell.run_code("pass")

        # Original function should now be at line 14 (was line 2, moved down 12 lines)
        try:
            mod.original_func()
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            assert "line 14" in exception_string

    def test_traceback_class_method_line_numbers(self):
        """Test line numbers for class methods after reloading."""
        self.shell.magic_autoreload("2")
        mod_name, mod_fn = self.new_module(
            """
            class TestClass:
                def method_with_error(self):
                    return 1/0
            """,
        )
        self.shell.run_code("import %s" % mod_name)
        self.shell.run_code("obj = %s.TestClass()" % mod_name)
        self.shell.run_code("pass")

        # Test original line number
        try:
            self.shell.run_code("obj.method_with_error()")
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            assert "line 3" in exception_string

        # Add content before the class
        self.write_file(
            mod_fn,
            """
            # New comment line
            x = 42
            y = 43
            
            class TestClass:
                def method_with_error(self):
                    return 1/0
            """,
        )
        self.shell.run_code("pass")
        # Method should now be at line 7 (was line 3, moved down 4 lines)
        try:
            self.shell.run_code("obj.method_with_error()")
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            assert "line 7" in exception_string

    def test_traceback_function_size_change(self):
        """Test line numbers when a function changes size."""
        self.shell.magic_autoreload("2")
        mod_name, mod_fn = self.new_module(
            """
            def func1():
                return 1
                
            def func2():
                return 2/0
            """,
        )
        self.shell.run_code("import %s" % mod_name)
        self.shell.run_code("pass")
        mod = sys.modules[mod_name]

        # Test original func2 line number
        try:
            mod.func2()
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            assert "line 5" in exception_string

        # Make func1 larger, which should shift func2
        self.write_file(
            mod_fn,
            """
            def func1():
                x = 1
                y = 2
                z = 3
                w = 4
                return x + y + z + w
                
            def func2():
                return 2/0
            """,
        )
        self.shell.run_code("pass")

        # func2 should now be at line 9 (was line 5, func1 expanded by 4 lines)
        try:
            mod.func2()
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            assert "line 9" in exception_string

    def test_traceback_no_line_patching_on_syntax_errors(self):
        """Test that syntax errors don't break line patching."""
        self.shell.magic_autoreload("2")
        mod_name, mod_fn = self.new_module(
            """
            def working_func():
                return 6/0
            """,
        )
        self.shell.run_code("import %s" % mod_name)
        self.shell.run_code("pass")
        mod = sys.modules[mod_name]

        # Test original function works and has correct line number
        try:
            mod.working_func()
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            assert "line 2" in exception_string

        # Introduce syntax error
        self.write_file(
            mod_fn,
            """
            def syntax error here!
            def working_func():
                return 6/0
            """,
        )
        self.shell.run_code("pass")

        # Function should still work with original line number (line patching should be gracefully skipped)
        try:
            mod.working_func()
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            # May still show line 2 if patching was skipped due to syntax error
            assert "line 2" in exception_string or "line 3" in exception_string

    def test_traceback_error_in_different_functions(self):
        """Test that line numbers are accurate for errors in different functions."""
        self.shell.magic_autoreload("2")
        mod_name, mod_fn = self.new_module(
            """
            def func_a():
                return 1/0  # line 2
                
            def func_b():
                return 2/0  # line 5
                
            def func_c():
                return 3/0  # line 8
            """,
        )
        self.shell.run_code("import %s" % mod_name)
        self.shell.run_code("pass")
        mod = sys.modules[mod_name]

        # Test all functions have correct original line numbers
        for func_name, expected_line in [("func_a", 2), ("func_b", 5), ("func_c", 8)]:
            try:
                getattr(mod, func_name)()
                assert False
            except ZeroDivisionError:
                exception_string = traceback.format_exc()
                assert f"line {expected_line}" in exception_string

        # Add content before all functions
        self.write_file(
            mod_fn,
            """
            # Header comment
            VERSION = 1
            DEBUG = True
            
            def func_a():
                return 1/0  # now line 6
                
            def func_b():
                return 2/0  # now line 9
                
            def func_c():
                return 3/0  # now line 12
            """,
        )
        self.shell.run_code("pass")

        # Test all functions have updated line numbers (each moved down 4 lines)
        for func_name, expected_line in [("func_a", 6), ("func_b", 9), ("func_c", 12)]:
            try:
                getattr(mod, func_name)()
                assert False
            except ZeroDivisionError:
                exception_string = traceback.format_exc()
                assert f"line {expected_line}" in exception_string

    def test_traceback_comprehension_line_numbers(self):
        """Test line numbers for comprehensions after reloading."""
        self.shell.magic_autoreload("2")
        mod_name, mod_fn = self.new_module(
            """
            def func_with_comprehension():
                result = [1/(x-2) for x in [1, 2, 3]]
                return result
            """,
        )
        self.shell.run_code("import %s" % mod_name)
        self.shell.run_code("pass")
        mod = sys.modules[mod_name]

        # Test original comprehension line number
        try:
            mod.func_with_comprehension()
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            assert "line 2" in exception_string

        # Add content before the function
        self.write_file(
            mod_fn,
            """
            # Comment line
            import itertools
            
            def func_with_comprehension():
                result = [1/(x-2) for x in [1, 2, 3]]
                return result
            """,
        )
        self.shell.run_code("pass")

        # Comprehension should now be at line 5 (was line 2, moved down 3 lines)
        try:
            mod.func_with_comprehension()
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            assert "line 5" in exception_string

    def test_traceback_property_line_numbers(self):
        """Test line numbers for property methods after reloading."""
        self.shell.magic_autoreload("2")
        mod_name, mod_fn = self.new_module(
            """
            class MyClass:
                @property
                def bad_property(self):
                    return 10/0
            """,
        )
        self.shell.run_code("import %s" % mod_name)
        self.shell.run_code("obj = %s.MyClass()" % mod_name)
        self.shell.run_code("pass")

        # Test original property line number
        try:
            self.shell.run_code("obj.bad_property")
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            assert "line 4" in exception_string

        # Add content before the class
        self.write_file(
            mod_fn,
            """
            import math
            
            class MyClass:
                @property
                def bad_property(self):
                    return 10/0
            """,
        )
        self.shell.run_code("pass")

        # Property should now be at line 6 (was line 4, moved down 2 lines)
        try:
            self.shell.run_code("obj.bad_property")
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            assert "line 6" in exception_string

    def test_traceback_static_method_line_number_add_comments(self):
        """Test line numbers for static methods after reloading."""
        self.shell.magic_autoreload("2")
        mod_name, mod_fn = self.new_module(
            """
            class Utils:
                @staticmethod
                def bad_static():
                    return 7/0
            """,
        )
        self.shell.run_code("import %s" % mod_name)
        self.shell.run_code("pass")
        mod = sys.modules[mod_name]

        # Test original static method line number
        try:
            mod.Utils.bad_static()
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            assert "line 4" in exception_string

        # Add content and expand the class
        self.write_file(
            mod_fn,
            """
            # New content
            VERSION = "1.0"
            
            class Utils:
                def __init__(self):
                    pass
                    
                @staticmethod
                def bad_static():
                    return 7/0
            """,
        )
        self.shell.run_code("pass")

        try:
            mod.Utils.bad_static()
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            assert "line 10" in exception_string

    def test_traceback_static_method_line_numbers(self):
        """Test line numbers for static methods after reloading."""
        self.shell.magic_autoreload("2")
        mod_name, mod_fn = self.new_module(
            """
            class Utils:
                @staticmethod
                def bad_static():
                    return 7/0
            """,
        )
        self.shell.run_code("import %s" % mod_name)
        self.shell.run_code("pass")
        mod = sys.modules[mod_name]

        # Test original static method line number
        try:
            mod.Utils.bad_static()
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            assert "line 4" in exception_string

        # Add content and expand the class
        self.write_file(
            mod_fn,
            """
            VERSION = "1.0"
            
            class Utils:
                def __init__(self):
                    pass
                    
                @staticmethod
                def bad_static():
                    return 7/0
            """,
        )
        self.shell.run_code("pass")

        # Static method should now be at line 9 (was line 4, moved down 5 lines)
        try:
            mod.Utils.bad_static()
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            assert "line 9" in exception_string

    def test_traceback_class_method_line_numbers(self):
        """Test line numbers for class methods after reloading."""
        self.shell.magic_autoreload("2")
        mod_name, mod_fn = self.new_module(
            """
            class Worker:
                @classmethod
                def bad_classmethod(cls):
                    return 3/0
            """,
        )
        self.shell.run_code("import %s" % mod_name)
        self.shell.run_code("pass")
        mod = sys.modules[mod_name]

        # Test original class method line number
        try:
            mod.Worker.bad_classmethod()
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            assert "line 4" in exception_string

        # Insert content before and expand the class
        self.write_file(
            mod_fn,
            """
            from typing import Any
            
            class Worker:
                instance_count = 0
                
                @classmethod
                def bad_classmethod(cls):
                    return 3/0
            """,
        )
        self.shell.run_code("pass")

        # Class method should now be at line 8 (was line 4, moved down 4 lines)
        try:
            mod.Worker.bad_classmethod()
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            assert "line 8" in exception_string

    def test_traceback_static_method_line_numbers(self):
        """Test line numbers for static methods after reloading."""
        self.shell.magic_autoreload("2")
        mod_name, mod_fn = self.new_module(
            """
            class Utils:
                @staticmethod
                def bad_static():
                    return 7/0
            """,
        )
        self.shell.run_code("import %s" % mod_name)
        self.shell.run_code("pass")
        mod = sys.modules[mod_name]

        # Test original static method line number
        try:
            mod.Utils.bad_static()
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            assert "line 4" in exception_string

        # Add content and expand the class
        self.write_file(
            mod_fn,
            """
            VERSION = "1.0"
            
            class Utils:
                def __init__(self):
                    pass
                    
                @staticmethod
                def bad_static():
                    return 7/0
            """,
        )
        self.shell.run_code("pass")

        # Static method should now be at line 9 (was line 4, moved down 5 lines)
        try:
            mod.Utils.bad_static()
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            assert "line 9" in exception_string

    def test_traceback_static_method_line_numbers_extra_space(self):
        """Test line numbers for static methods after reloading."""
        self.shell.magic_autoreload("2")
        mod_name, mod_fn = self.new_module(
            """
            class Utils:
                @staticmethod
                def bad_static():
                    return 7/0
            """,
        )
        self.shell.run_code("import %s" % mod_name)
        self.shell.run_code("pass")
        mod = sys.modules[mod_name]

        # Test original static method line number
        try:
            mod.Utils.bad_static()
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            assert "line 4" in exception_string

        # Add content and expand the class
        self.write_file(
            mod_fn,
            """
            VERSION = "1.0"
            
            class Utils:
                def __init__(self):
                    pass
                    
                @staticmethod

                def bad_static():
                    return 7/0
            """,
        )
        self.shell.run_code("pass")

        # Static method should now be at line 9 (was line 4, moved down 5 lines)
        try:
            mod.Utils.bad_static()
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            assert "line 10" in exception_string

    def test_traceback_class_method_line_numbers(self):
        """Test line numbers for class methods after reloading."""
        self.shell.magic_autoreload("2")
        mod_name, mod_fn = self.new_module(
            """
            class Worker:
                @classmethod
                def bad_classmethod(cls):
                    return 3/0
            """,
        )
        self.shell.run_code("import %s" % mod_name)
        self.shell.run_code("pass")
        mod = sys.modules[mod_name]

        # Test original class method line number
        try:
            mod.Worker.bad_classmethod()
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            assert "line 4" in exception_string

        # Insert content before and expand the class
        self.write_file(
            mod_fn,
            """
            from typing import Any
            
            class Worker:
                instance_count = 0
                
                @classmethod
                def bad_classmethod(cls):
                    return 3/0
            """,
        )
        self.shell.run_code("pass")

        # Class method should now be at line 8 (was line 4, moved down 4 lines)
        try:
            mod.Worker.bad_classmethod()
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            assert "line 8" in exception_string

    def test_traceback_line_numbers_add_comments(self):
        """Test that original line numbers are preserved when patching fails."""
        self.shell.magic_autoreload("2")
        mod_name, mod_fn = self.new_module(
            """
            def simple_func():
                return 11/0
            """,
        )
        self.shell.run_code("import %s" % mod_name)
        self.shell.run_code("pass")
        mod = sys.modules[mod_name]

        # Test original line number in traceback
        try:
            mod.simple_func()
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            assert f"line 2" in exception_string

        # Modify the file to shift lines
        self.write_file(
            mod_fn,
            """
            # New content            
            def simple_func():
                return 11/0
            """,
        )
        self.shell.run_code("pass")
        try:
            mod.simple_func()
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            assert "line 3" in exception_string

    def test_traceback_line_numbers_preserved_on_patch_failure(self):
        """Test that original line numbers are preserved when patching fails."""
        self.shell.magic_autoreload("2")
        mod_name, mod_fn = self.new_module(
            """
            def simple_func():
                return 11/0
            """,
        )
        self.shell.run_code("import %s" % mod_name)
        self.shell.run_code("pass")
        mod = sys.modules[mod_name]
        try:
            mod.simple_func()
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            assert f"line 2" in exception_string

        # Modify the file to shift lines
        self.write_file(
            mod_fn,
            """
            # New content
            x = 1
            y = 2
            
            def simple_func():
                return 11/0
            """,
        )
        self.shell.run_code("pass")

        try:
            mod.simple_func()
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            assert "line 6" in exception_string

    def test_traceback_mixed_function_types(self):
        """Test line numbers for mixed function types in one module."""
        self.shell.magic_autoreload("2")
        mod_name, mod_fn = self.new_module(
            """
            def regular_func():
                return 1

            async def async_func():
                return 2/0

            class TestClass:
                def method(self):
                    return 3
                    
                @staticmethod
                def static_error():
                    return 4/0
            """,
        )
        self.shell.run_code("import %s" % mod_name)
        self.shell.run_code("pass")
        mod = sys.modules[mod_name]

        # Test original static method line number
        try:
            mod.TestClass.static_error()
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            assert "line 13" in exception_string

        # Expand the regular function, which should shift everything after it
        self.write_file(
            mod_fn,
            """
            def regular_func():
                # Added comments and lines
                x = 1
                y = 2
                z = 3
                return x + y + z

            async def async_func():
                return 2/0

            class TestClass:
                def method(self):
                    return 3
                    
                @staticmethod
                def static_error():
                    return 4/0
            """,
        )
        self.shell.run_code("pass")

        # Static method should now be at line 16 (was line 12, moved down 4 lines)
        try:
            mod.TestClass.static_error()
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            assert "line 17" in exception_string

    def test_traceback_nested_function_line_numbers(self):
        """Test line numbers for nested functions after reloading."""
        self.shell.magic_autoreload("2")
        mod_name, mod_fn = self.new_module(
            """
            def outer_func():
                def inner_func():
                    return 5/0
                return inner_func()
            """,
        )
        self.shell.run_code("import %s" % mod_name)
        self.shell.run_code("pass")
        mod = sys.modules[mod_name]

        # Test original nested function line number
        try:
            mod.outer_func()
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            print(exception_string)
            print("!!!!!!!!!")
            assert "line 3" in exception_string

        # Add lines before the function
        self.write_file(
            mod_fn,
            """
            import sys
            import os
            
            def outer_func():
                def inner_func():
                    return 5/0
                return inner_func()
            """,
        )
        self.shell.run_code("pass")

        # Inner function should now be at line 6 (was line 3, moved down 3 lines)
        try:
            mod.outer_func()
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            assert "line 6" in exception_string

    def test_traceback_decorator_line_numbers(self):
        """Test line numbers for decorated functions after reloading."""
        self.shell.magic_autoreload("2")
        mod_name, mod_fn = self.new_module(
            """
            def decorator(func):
                return func
                
            @decorator
            def decorated_func():
                return 8/0
            """,
        )
        self.shell.run_code("import %s" % mod_name)
        self.shell.run_code("pass")
        mod = sys.modules[mod_name]

        # Test original decorated function line number
        try:
            mod.decorated_func()
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            assert "line 6" in exception_string

        # Add content before the decorator
        self.write_file(
            mod_fn,
            """
            def decorator(func):
                x = 1
                return func
                
            @decorator
            def decorated_func():
                return 8/0
            """,
        )
        self.shell.run_code("pass")
        try:
            mod.decorated_func()
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            assert "line 7" in exception_string

    def test_traceback_double_decorator_line_numbers(self):
        """Test line numbers for decorated functions after reloading."""
        self.shell.magic_autoreload("2")
        mod_name, mod_fn = self.new_module(
            """
            def decorator(func):
                return func
                
            @decorator
            def decorated_func():
                return 8/0
            """,
        )
        self.shell.run_code("import %s" % mod_name)
        self.shell.run_code("pass")
        mod = sys.modules[mod_name]

        # Test original decorated function line number
        try:
            mod.decorated_func()
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            assert "line 6" in exception_string

        # Add content before the decorator
        self.write_file(
            mod_fn,
            """
            def decorator(func):
                x = 1
                return func
                
            @decorator
            @decorator
            def decorated_func():
                return 8/0
            """,
        )
        self.shell.run_code("pass")
        try:
            mod.decorated_func()
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            assert "line 8" in exception_string

    def test_traceback_decorator_line_numbers_space(self):
        """Test line numbers for decorated functions after reloading."""
        self.shell.magic_autoreload("2")
        mod_name, mod_fn = self.new_module(
            """
            def decorator(func):
                return func

            @decorator
            def decorated_func():
                return 8/0
            """,
        )
        self.shell.run_code("import %s" % mod_name)
        mod = sys.modules[mod_name]
        print(
            f"[DEBUG] After import decorated_func co_firstlineno: {mod.decorated_func.__code__.co_firstlineno}"
        )

        self.shell.run_code("pass")
        print(
            f"[DEBUG] After first 'pass' decorated_func co_firstlineno: {mod.decorated_func.__code__.co_firstlineno}"
        )

        # Test original decorated function line number
        print(
            f"[DEBUG] Original decorated_func co_firstlineno: {mod.decorated_func.__code__.co_firstlineno}"
        )
        try:
            mod.decorated_func()
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            print(f"[DEBUG] Original exception: {exception_string}")
            assert "line 6" in exception_string

        # Add content before the decorator
        self.write_file(
            mod_fn,
            """
            def decorator(func):
                x = 1
                return func

            @decorator

            def decorated_func():
                z = 1
                return 8/0
            """,
        )  ##

        print("reloading time")
        print(
            f"[DEBUG] Before reload: mod.decorated_func id={id(mod.decorated_func)} co_firstlineno={mod.decorated_func.__code__.co_firstlineno}"
        )
        self.shell.run_code("pass")
        print(
            f"[DEBUG] After reload: mod.decorated_func id={id(mod.decorated_func)} co_firstlineno={mod.decorated_func.__code__.co_firstlineno}"
        )
        try:
            mod.decorated_func()
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            assert "line 9" in exception_string

    def test_traceback_decorator_line_numbers_space_in_new_func(self):
        """Test line numbers for decorated functions after reloading."""
        self.shell.magic_autoreload("2")
        mod_name, mod_fn = self.new_module(
            """
            def decorator(func):
                return func

            @decorator
            def decorated_func():
                return 8/0
            """,
        )
        self.shell.run_code("import %s" % mod_name)
        self.shell.run_code("pass")
        mod = sys.modules[mod_name]

        # Test original decorated function line number
        try:
            mod.decorated_func()
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            assert "line 6" in exception_string

        # Add content before the decorator
        self.write_file(
            mod_fn,
            """
            def decorator(func):
                x = 1
                return func

            @decorator
            def decorated_func():

                z = 1
                return 8/0
            """,
        )
        self.shell.run_code("pass")
        try:
            mod.decorated_func()
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            assert "line 9" in exception_string

    def test_traceback_lambda_line_numbers(self):
        """Test line numbers for lambdas after reloading."""
        self.shell.magic_autoreload("2")
        mod_name, mod_fn = self.new_module(
            """
            bad_lambda = lambda: 9/0

            def call_lambda():
                return bad_lambda()
            """,
        )
        self.shell.run_code("import %s" % mod_name)
        self.shell.run_code("pass")
        mod = sys.modules[mod_name]

        # Test original lambda line number
        try:
            mod.call_lambda()
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            assert "line 1" in exception_string

        # Add content before the lambda
        self.write_file(
            mod_fn,
            """
            x = 1
            bad_lambda = lambda: 9/0
            def call_lambda():
                return bad_lambda()
            """,
        )
        self.shell.run_code("pass")

        try:
            mod.call_lambda()
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            assert "line 2" in exception_string

    def test_traceback_nested_functions_with_closure(self):
        """Test line numbers for nested functions with closures after reloading."""
        self.shell.magic_autoreload("2")
        mod_name, mod_fn = self.new_module(
            """
            def outer_func(x):
                def inner_func():
                    return x / 0  # Error in closure
                return inner_func
            """,
        )
        self.shell.run_code("import %s" % mod_name)
        self.shell.run_code("pass")
        mod = sys.modules[mod_name]

        # Test original nested function line number
        func = mod.outer_func(42)
        try:
            func()
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            assert "line 3" in exception_string

        # Add content before and modify
        self.write_file(
            mod_fn,
            """
            # Comment line 1
            # Comment line 2
            def outer_func(x):
                # Comment in function
                def inner_func():
                    # Another comment
                    return x / 0  # Error in closure
                return inner_func
            """,
        )
        self.shell.run_code("pass")

        func = mod.outer_func(42)
        try:
            func()
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            assert "line 7" in exception_string

    def test_traceback_multiple_decorators_complex(self):
        """Test line numbers with multiple decorators and complex scenarios."""
        self.shell.magic_autoreload("2")
        mod_name, mod_fn = self.new_module(
            """
            def decorator1(func):
                def wrapper(*args, **kwargs):
                    return func(*args, **kwargs)
                return wrapper
                
            def decorator2(func):
                def wrapper(*args, **kwargs):
                    return func(*args, **kwargs)
                return wrapper
            
            @decorator1
            @decorator2
            def decorated_error_func():
                return 1 / 0
            """,
        )
        self.shell.run_code("import %s" % mod_name)
        self.shell.run_code("pass")
        mod = sys.modules[mod_name]

        try:
            mod.decorated_error_func()
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            assert "line 14" in exception_string

        # Add more content and verify line numbers adjust
        self.write_file(
            mod_fn,
            """
            # Line 1
            # Line 2
            a = 1
            def decorator1(func):
                def wrapper(*args, **kwargs):
                    return func(*args, **kwargs)
                return wrapper
                
            def decorator2(func):
                def wrapper(*args, **kwargs):
                    return func(*args, **kwargs)
                return wrapper
            
            @decorator1
            @decorator2
            def decorated_error_func():
                return 1 / 0
            """,
        )
        self.shell.run_code("pass")

        try:
            mod.decorated_error_func()
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            print(f"[DEBUG] Exception string: {exception_string}")
            assert "line 17" in exception_string

    def test_traceback_exception_handling_in_reloaded_code(self):
        """Test exception handling within reloaded code maintains correct line numbers."""
        self.shell.magic_autoreload("2")
        mod_name, mod_fn = self.new_module(
            """
            def handle_error():
                try:
                    return 1 / 0
                except ZeroDivisionError:
                    raise ValueError("Custom error")
            """,
        )
        self.shell.run_code("import %s" % mod_name)
        self.shell.run_code("pass")
        mod = sys.modules[mod_name]

        try:
            mod.handle_error()
            assert False
        except ValueError:
            exception_string = traceback.format_exc()
            assert "line 5" in exception_string

        # Modify the function with more lines
        self.write_file(
            mod_fn,
            """
            def some_other_func():
                pass
                
            def handle_error():
                x = 1
                y = 2
                try:
                    return 1 / 0
                except ZeroDivisionError:
                    z = 3
                    raise ValueError("Custom error")
            """,
        )
        self.shell.run_code("pass")

        try:
            mod.handle_error()
            assert False
        except ValueError:
            exception_string = traceback.format_exc()
            assert "line 11" in exception_string

    def test_traceback_multiple_reload_cycles(self):
        """Test line numbers remain accurate through multiple reload cycles."""
        self.shell.magic_autoreload("2")
        mod_name, mod_fn = self.new_module(
            """
            def error_func():
                return 1 / 0
            """,
        )
        self.shell.run_code("import %s" % mod_name)
        self.shell.run_code("pass")
        mod = sys.modules[mod_name]

        # First reload cycle
        self.write_file(
            mod_fn,
            """
            def new_func():
                pass
            def error_func():
                return 1 / 0
            """,
        )
        self.shell.run_code("pass")

        try:
            mod.error_func()
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            assert "line 4" in exception_string

        # Second reload cycle
        self.write_file(
            mod_fn,
            """
            def another_new_func():
                x = 1
                return x
                
            def new_func():
                pass
                
            def error_func():
                return 1 / 0
            """,
        )
        self.shell.run_code("pass")

        try:
            mod.error_func()
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            assert "line 9" in exception_string

        # Third reload cycle - remove functions
        self.write_file(
            mod_fn,
            """
            def error_func():
                return 1 / 0
            """,
        )
        self.shell.run_code("pass")

        try:
            mod.error_func()
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            assert "line 2" in exception_string

    def test_traceback_error_propagation_through_modules(self):
        """Test error propagation maintains line numbers across module boundaries."""
        self.shell.magic_autoreload("2")

        # Create helper module
        helper_mod_name, helper_mod_fn = self.new_module(
            """
            def helper_func():
                return 1 / 0
            """,
        )

        # Create main module that imports helper
        mod_name, mod_fn = self.new_module(
            """
            from {} import helper_func
            
            def main_func():
                return helper_func()
            """.format(
                helper_mod_name
            ),
        )

        self.shell.run_code("import %s" % mod_name)
        self.shell.run_code("pass")
        mod = sys.modules[mod_name]

        try:
            mod.main_func()
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            # Check both modules appear in traceback with correct lines
            assert "line 4" in exception_string  # main_func call
            assert "line 2" in exception_string  # helper_func error

        # Modify helper module
        self.write_file(
            helper_mod_fn,
            """
            def some_new_helper():
                pass
                
            def helper_func():
                x = 42
                return 1 / 0
            """,
        )
        self.shell.run_code("pass")

        try:
            mod.main_func()
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            assert "line 4" in exception_string  # main_func call
            assert "line 6" in exception_string  # helper_func error (moved line)

    def test_traceback_complex_call_stack(self):
        """Test complex call stacks with reloaded functions maintain line numbers."""
        self.shell.magic_autoreload("2")
        mod_name, mod_fn = self.new_module(
            """
            def func_a():
                return func_b()
                
            def func_b():
                return func_c()
                
            def func_c():
                return 1 / 0
            """,
        )
        self.shell.run_code("import %s" % mod_name)
        self.shell.run_code("pass")
        mod = sys.modules[mod_name]

        try:
            mod.func_a()
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            assert "line 2" in exception_string  # func_a
            assert "line 5" in exception_string  # func_b
            assert "line 8" in exception_string  # func_c

        # Add functions in between
        self.write_file(
            mod_fn,
            """
            def new_func_1():
                pass
                
            def func_a():
                return func_b()
                
            def new_func_2():
                pass
                
            def func_b():
                return func_c()
                
            def new_func_3():
                pass
                
            def func_c():
                return 1 / 0
            """,
        )
        self.shell.run_code("pass")

        try:
            mod.func_a()
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            assert "line 5" in exception_string  # func_a (moved)
            assert "line 11" in exception_string  # func_b (moved)
            assert "line 17" in exception_string  # func_c (moved)

    def test_traceback_empty_lines_and_whitespace(self):
        """Test line numbers with functions containing many empty lines."""
        self.shell.magic_autoreload("2")
        mod_name, mod_fn = self.new_module(
            """
            def func_with_empty_lines():
                x = 1
                
                
                y = 2
                
                
                
                z = 3
                
                return x / 0
            """,
        )
        self.shell.run_code("import %s" % mod_name)
        self.shell.run_code("pass")
        mod = sys.modules[mod_name]

        try:
            mod.func_with_empty_lines()
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            assert "line 11" in exception_string

        # Add more empty lines before the function
        self.write_file(
            mod_fn,
            """
            
            
            
            def func_with_empty_lines():
                x = 1
                
                
                y = 2
                
                
                
                z = 3
                
                return x / 0
            """,
        )
        self.shell.run_code("pass")

        try:
            mod.func_with_empty_lines()
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            assert "line 14" in exception_string

    def test_traceback_class_inheritance_complex(self):
        """Test line numbers in complex class inheritance scenarios."""
        self.shell.magic_autoreload("2")
        mod_name, mod_fn = self.new_module(
            """
            class BaseClass:
                def base_method(self):
                    return self.child_method()
                    
            class ChildClass(BaseClass):
                def child_method(self):
                    return 1 / 0
            """,
        )
        self.shell.run_code("import %s" % mod_name)
        self.shell.run_code("obj = %s.ChildClass()" % mod_name)
        self.shell.run_code("pass")
        mod = sys.modules[mod_name]

        try:
            mod.ChildClass().base_method()
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            assert "line 3" in exception_string  # base_method
            assert "line 7" in exception_string  # child_method

        # Add methods and verify line tracking
        self.write_file(
            mod_fn,
            """
            class BaseClass:
                def new_base_method(self):
                    pass
                    
                def base_method(self):
                    return self.child_method()
                    
            class ChildClass(BaseClass):
                def new_child_method(self):
                    pass
                    
                def child_method(self):
                    return 1 / 0
            """,
        )
        self.shell.run_code("pass")

        try:
            mod.ChildClass().base_method()
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            assert "line 6" in exception_string  # base_method (moved)
            assert "line 13" in exception_string  # child_method (moved)

    def test_traceback_generator_functions(self):
        """Test line numbers in generator functions after reloading."""
        self.shell.magic_autoreload("2")
        mod_name, mod_fn = self.new_module(
            """
            def error_generator():
                yield 1
                yield 2
                yield 1 / 0
            """,
        )
        self.shell.run_code("import %s" % mod_name)
        self.shell.run_code("pass")
        mod = sys.modules[mod_name]

        gen = mod.error_generator()
        next(gen)  # 1
        next(gen)  # 2
        try:
            next(gen)  # Error
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            assert "line 4" in exception_string

        # Add content before generator
        self.write_file(
            mod_fn,
            """
            def regular_func():
                pass
                
            def error_generator():
                yield 1
                yield 2
                yield 1 / 0
            """,
        )
        self.shell.run_code("pass")

        gen = mod.error_generator()
        next(gen)  # 1
        next(gen)  # 2
        try:
            next(gen)  # Error
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            assert "line 7" in exception_string

    def test_traceback_async_functions(self):
        """Test line numbers in async functions after reloading."""
        self.shell.magic_autoreload("2")
        mod_name, mod_fn = self.new_module(
            """
            import asyncio
            
            async def async_error_func():
                await asyncio.sleep(0)
                return 1 / 0
            """,
        )
        self.shell.run_code("import %s" % mod_name)
        self.shell.run_code("import asyncio")
        self.shell.run_code("pass")
        mod = sys.modules[mod_name]

        try:
            asyncio.run(mod.async_error_func())
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            assert "line 5" in exception_string

        # Add content and verify line numbers
        self.write_file(
            mod_fn,
            """
            import asyncio
            
            async def another_async_func():
                pass
                
            async def async_error_func():
                await asyncio.sleep(0)
                x = 42
                return 1 / 0
            """,
        )
        self.shell.run_code("pass")

        try:
            asyncio.run(mod.async_error_func())
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            assert "line 9" in exception_string

    def test_traceback_comprehension_errors_complex(self):
        """Test line numbers in complex comprehension scenarios."""
        self.shell.magic_autoreload("2")
        mod_name, mod_fn = self.new_module(
            """
            def comprehension_error():
                return [1/x for x in [1, 2, 0, 3]]
            """,
        )
        self.shell.run_code("import %s" % mod_name)
        self.shell.run_code("pass")
        mod = sys.modules[mod_name]

        try:
            mod.comprehension_error()
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            assert "line 2" in exception_string

        # Test nested comprehensions
        self.write_file(
            mod_fn,
            """
            def nested_comprehension_error():
                return [[1/(x*y) for y in [1, 0]] for x in [1, 2]]
            """,
        )
        self.shell.run_code("pass")

        try:
            mod.nested_comprehension_error()
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            assert "line 2" in exception_string

    def test_traceback_context_manager_errors(self):
        """Test line numbers in context manager scenarios."""
        self.shell.magic_autoreload("2")
        mod_name, mod_fn = self.new_module(
            """
            class ErrorContextManager:
                def __enter__(self):
                    return self
                def __exit__(self, exc_type, exc_val, exc_tb):
                    return 1 / 0  # Error in __exit__
                    
            def use_context_manager():
                with ErrorContextManager():
                    pass
            """,
        )
        self.shell.run_code("import %s" % mod_name)
        self.shell.run_code("pass")
        mod = sys.modules[mod_name]

        try:
            mod.use_context_manager()
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            assert "line 5" in exception_string  # __exit__ method

        # Test error in __enter__
        self.write_file(
            mod_fn,
            """
            class ErrorContextManager:
                def __enter__(self):
                    return 1 / 0  # Error in __enter__
                def __exit__(self, exc_type, exc_val, exc_tb):
                    return False
                    
            def use_context_manager():
                with ErrorContextManager():
                    pass
            """,
        )
        self.shell.run_code("pass")

        try:
            mod.use_context_manager()
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            assert "line 3" in exception_string  # __enter__ method
            assert "line 8" in exception_string  # use_context_manager

    def test_traceback_multiline_lambda(self):
        """Test line numbers for multi-line lambda expressions after reloading."""
        self.shell.magic_autoreload("2")
        mod_name, mod_fn = self.new_module(
            """
            bad_lambda = (lambda x, y, z: 
                         x / (y - z) if x > 0 
                         else 1 / 0)
            
            def call_lambda():
                return bad_lambda(10, 2, 2)  # Will cause division by zero
            """,
        )
        self.shell.run_code("import %s" % mod_name)
        self.shell.run_code("pass")
        mod = sys.modules[mod_name]

        # Test original lambda line number
        try:
            mod.call_lambda()
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            assert "line 2" in exception_string

        # Add content before lambda and test line tracking
        self.write_file(
            mod_fn,
            """
            import math
            PI = 3.14159
            
            bad_lambda = (lambda x, y, z: 
                         x / (y - z) if x > 0 
                         else 1 / 0)
            
            def helper_func():
                pass
            
            def call_lambda():
                return bad_lambda(10, 2, 2)  # Will cause division by zero
            """,
        )
        self.shell.run_code("pass")

        try:
            mod.call_lambda()
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            assert "line 5" in exception_string  # lambda moved down 3 lines

    def test_traceback_recursive_function_error(self):
        """Test line numbers for errors in recursive functions after reloading."""
        self.shell.magic_autoreload("2")
        mod_name, mod_fn = self.new_module(
            """
            def recursive_factorial(n):
                if n == 0:
                    return 1 / 0  # Error in base case
                return n * recursive_factorial(n - 1)
            
            def call_recursive():
                return recursive_factorial(0)
            """,
        )
        self.shell.run_code("import %s" % mod_name)
        self.shell.run_code("pass")
        mod = sys.modules[mod_name]

        try:
            mod.call_recursive()
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            assert "line 3" in exception_string  # error in base case

        # Add content before and test line tracking
        self.write_file(
            mod_fn,
            """
            import sys
            MAX_RECURSION = 1000
            
            def helper_func():
                pass
            
            def recursive_countdown(n):
                if n <= 0:
                    return 1 / 0  # Error at end of recursion
                return recursive_countdown(n - 1)
            
            def call_recursive():
                return recursive_countdown(3)
            """,
        )
        self.shell.run_code("pass")

        try:
            mod.call_recursive()
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            print(f"[DEBUG] Exception string2222: {exception_string}")
            assert "line 9" in exception_string

    def test_traceback_recursive_function_error_toplevel_change(self):
        """Test line numbers for errors in recursive functions after reloading."""
        self.shell.magic_autoreload("2")
        mod_name, mod_fn = self.new_module(
            """
            def recursive_factorial(n):
                if n == 0:
                    return 1 / 0  # Error in base case
                return n * recursive_factorial(n - 1)
            
            def call_recursive():
                return recursive_factorial(0)
            """,
        )
        self.shell.run_code("import %s" % mod_name)
        self.shell.run_code("pass")
        mod = sys.modules[mod_name]

        try:
            mod.call_recursive()
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            assert "line 3" in exception_string  # error in base case

        # Test recursive error after several calls
        self.write_file(
            mod_fn,
            """
            def recursive_countdown(n):
                if n <= 0:
                    return 1 / 0  # Error at end of recursion
                return recursive_countdown(n - 1)
            
            def call_recursive():
                return recursive_countdown(3)
            """,
        )
        self.shell.run_code("pass")
        try:
            mod.call_recursive()
            assert False
        except ZeroDivisionError:
            exception_string = traceback.format_exc()
            print(f"[DEBUG] Exception string1111: {exception_string}")
            assert "line 7, in call_recursive" in exception_string
            assert "line 3" in exception_string  # error in base case
            # Should also see multiple recursive calls in traceback


if __name__ == "__main__":
    unittest.main()
