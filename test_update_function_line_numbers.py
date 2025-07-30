"""Unit tests for complete function line number update functionality."""

import unittest
from types import CodeType, FunctionType
import sys

from update_function_line_numbers import update_function_line_numbers


class TestUpdateFunctionLineNumbers(unittest.TestCase):
    """Test cases for update_function_line_numbers function."""

    def setUp(self):
        """Set up test fixtures with various function types."""
        # Simple function
        def simple_func():
            return 42
        
        # Multi-line function
        def multi_line_func():
            x = 1
            y = 2
            return x + y
        
        # Function with control flow
        def control_flow_func(x):
            if x > 0:
                return x * 2
            else:
                return x * -1
        
        # Function with nested function
        def outer_func():
            def inner_func():
                return "inner"
            return inner_func()
        
        # Function with loop
        def loop_func():
            total = 0
            for i in range(3):
                total += i
            return total
        
        # Function with exception handling
        def exception_func():
            try:
                return 1 / 0
            except ZeroDivisionError:
                return 0
        
        # Generator function
        def generator_func():
            yield 1
            yield 2
            yield 3
        
        # Function with decorators (simulated)
        def decorated_func():
            return "decorated"
        
        # Lambda function
        lambda_func = lambda x: x * 2
        
        self.test_functions = {
            'simple': simple_func,
            'multi_line': multi_line_func,
            'control_flow': control_flow_func,
            'outer': outer_func,
            'loop': loop_func,
            'exception': exception_func,
            'generator': generator_func,
            'decorated': decorated_func,
            'lambda': lambda_func,
        }

    def test_function_code_object_is_updated(self):
        """Test that the function's __code__ object is updated."""
        func = self.test_functions['simple']
        original_code = func.__code__
        original_firstlineno = original_code.co_firstlineno
        
        new_firstlineno = original_firstlineno + 10
        update_function_line_numbers(func, new_firstlineno)
        
        # Code object should be different
        self.assertIsNot(func.__code__, original_code)
        # First line number should be updated
        self.assertEqual(func.__code__.co_firstlineno, new_firstlineno)

    def test_positive_line_offset(self):
        """Test updating function with positive line offset."""
        func = self.test_functions['multi_line']
        original_firstlineno = func.__code__.co_firstlineno
        new_firstlineno = original_firstlineno + 25
        
        update_function_line_numbers(func, new_firstlineno)
        
        self.assertEqual(func.__code__.co_firstlineno, new_firstlineno)

    def test_negative_line_offset(self):
        """Test updating function with negative line offset."""
        func = self.test_functions['multi_line']
        original_firstlineno = func.__code__.co_firstlineno
        new_firstlineno = max(1, original_firstlineno - 5)  # Ensure positive line number
        
        update_function_line_numbers(func, new_firstlineno)
        
        self.assertEqual(func.__code__.co_firstlineno, new_firstlineno)

    def test_zero_offset(self):
        """Test updating function with same line number (zero offset)."""
        func = self.test_functions['simple']
        original_firstlineno = func.__code__.co_firstlineno
        original_code = func.__code__
        
        update_function_line_numbers(func, original_firstlineno)
        
        # Should still update the code object (new linetable)
        self.assertIsNot(func.__code__, original_code)
        self.assertEqual(func.__code__.co_firstlineno, original_firstlineno)

    def test_linetable_is_updated(self):
        """Test that the function's linetable is updated."""
        func = self.test_functions['multi_line']
        original_linetable = func.__code__.co_linetable
        new_firstlineno = func.__code__.co_firstlineno + 20
        
        update_function_line_numbers(func, new_firstlineno)
        
        # Linetable should be different
        self.assertNotEqual(func.__code__.co_linetable, original_linetable)

    def test_other_code_attributes_preserved(self):
        """Test that other code object attributes are preserved."""
        func = self.test_functions['control_flow']
        original_code = func.__code__
        
        # Store original attributes
        original_attrs = {
            'co_argcount': original_code.co_argcount,
            'co_posonlyargcount': original_code.co_posonlyargcount,
            'co_kwonlyargcount': original_code.co_kwonlyargcount,
            'co_nlocals': original_code.co_nlocals,
            'co_stacksize': original_code.co_stacksize,
            'co_flags': original_code.co_flags,
            'co_code': original_code.co_code,
            'co_consts': original_code.co_consts,
            'co_names': original_code.co_names,
            'co_varnames': original_code.co_varnames,
            'co_filename': original_code.co_filename,
            'co_name': original_code.co_name,
            'co_freevars': original_code.co_freevars,
            'co_cellvars': original_code.co_cellvars,
        }
        
        new_firstlineno = original_code.co_firstlineno + 15
        update_function_line_numbers(func, new_firstlineno)
        
        new_code = func.__code__
        
        # Check that non-line-related attributes are preserved
        for attr, original_value in original_attrs.items():
            self.assertEqual(getattr(new_code, attr), original_value, 
                           f"Attribute {attr} was not preserved")

    def test_function_still_callable(self):
        """Test that function remains callable after update."""
        func = self.test_functions['simple']
        original_result = func()
        
        new_firstlineno = func.__code__.co_firstlineno + 10
        update_function_line_numbers(func, new_firstlineno)
        
        # Function should still work
        new_result = func()
        self.assertEqual(new_result, original_result)

    def test_function_with_arguments_still_works(self):
        """Test that function with arguments still works after update."""
        func = self.test_functions['control_flow']
        
        # Test original behavior
        self.assertEqual(func(5), 10)
        self.assertEqual(func(-3), 3)
        
        new_firstlineno = func.__code__.co_firstlineno + 20
        update_function_line_numbers(func, new_firstlineno)
        
        # Test behavior after update
        self.assertEqual(func(5), 10)
        self.assertEqual(func(-3), 3)

    def test_generator_function_still_works(self):
        """Test that generator function still works after update."""
        func = self.test_functions['generator']
        
        # Test original behavior
        original_values = list(func())
        self.assertEqual(original_values, [1, 2, 3])
        
        new_firstlineno = func.__code__.co_firstlineno + 15
        update_function_line_numbers(func, new_firstlineno)
        
        # Test behavior after update
        new_values = list(func())
        self.assertEqual(new_values, [1, 2, 3])

    def test_function_with_loop_still_works(self):
        """Test that function with loop still works after update."""
        func = self.test_functions['loop']
        original_result = func()
        
        new_firstlineno = func.__code__.co_firstlineno + 12
        update_function_line_numbers(func, new_firstlineno)
        
        new_result = func()
        self.assertEqual(new_result, original_result)

    def test_function_with_exception_handling_still_works(self):
        """Test that function with exception handling still works after update."""
        func = self.test_functions['exception']
        original_result = func()
        
        new_firstlineno = func.__code__.co_firstlineno + 8
        update_function_line_numbers(func, new_firstlineno)
        
        new_result = func()
        self.assertEqual(new_result, original_result)

    def test_lambda_function_update(self):
        """Test updating lambda function line numbers."""
        func = self.test_functions['lambda']
        original_result = func(5)
        
        new_firstlineno = func.__code__.co_firstlineno + 5
        update_function_line_numbers(func, new_firstlineno)
        
        # Lambda should still work
        new_result = func(5)
        self.assertEqual(new_result, original_result)
        self.assertEqual(func.__code__.co_firstlineno, new_firstlineno)

    def test_large_line_number_update(self):
        """Test updating to very large line number."""
        func = self.test_functions['simple']
        large_line_number = 10000
        
        update_function_line_numbers(func, large_line_number)
        
        self.assertEqual(func.__code__.co_firstlineno, large_line_number)
        # Function should still work
        self.assertEqual(func(), 42)

    def test_line_number_one_update(self):
        """Test updating to line number 1."""
        func = self.test_functions['simple']
        
        update_function_line_numbers(func, 1)
        
        self.assertEqual(func.__code__.co_firstlineno, 1)
        # Function should still work
        self.assertEqual(func(), 42)

    def test_multiple_updates_on_same_function(self):
        """Test multiple line number updates on the same function."""
        func = self.test_functions['multi_line']
        original_result = func()
        
        # First update
        update_function_line_numbers(func, 100)
        self.assertEqual(func.__code__.co_firstlineno, 100)
        self.assertEqual(func(), original_result)
        
        # Second update
        update_function_line_numbers(func, 200)
        self.assertEqual(func.__code__.co_firstlineno, 200)
        self.assertEqual(func(), original_result)
        
        # Third update
        update_function_line_numbers(func, 50)
        self.assertEqual(func.__code__.co_firstlineno, 50)
        self.assertEqual(func(), original_result)

    def test_nested_function_code_objects(self):
        """Test that nested functions are handled correctly."""
        func = self.test_functions['outer']
        original_result = func()
        
        new_firstlineno = func.__code__.co_firstlineno + 30
        update_function_line_numbers(func, new_firstlineno)
        
        # Outer function should work
        self.assertEqual(func.__code__.co_firstlineno, new_firstlineno)
        new_result = func()
        self.assertEqual(new_result, original_result)

    def test_function_identity_preserved(self):
        """Test that function identity is preserved."""
        func = self.test_functions['simple']
        original_id = id(func)
        
        new_firstlineno = func.__code__.co_firstlineno + 5
        update_function_line_numbers(func, new_firstlineno)
        
        # Function object itself should be the same
        self.assertEqual(id(func), original_id)

    def test_function_name_preserved(self):
        """Test that function name is preserved."""
        func = self.test_functions['control_flow']
        original_name = func.__name__
        
        new_firstlineno = func.__code__.co_firstlineno + 7
        update_function_line_numbers(func, new_firstlineno)
        
        self.assertEqual(func.__name__, original_name)

    def test_function_docstring_preserved(self):
        """Test that function docstring is preserved."""
        def documented_func():
            """This is a test function."""
            return "test"
        
        original_doc = documented_func.__doc__
        
        new_firstlineno = documented_func.__code__.co_firstlineno + 3
        update_function_line_numbers(documented_func, new_firstlineno)
        
        self.assertEqual(documented_func.__doc__, original_doc)

    def test_function_defaults_preserved(self):
        """Test that function defaults are preserved."""
        def func_with_defaults(a=1, b=2):
            return a + b
        
        original_defaults = func_with_defaults.__defaults__
        original_result = func_with_defaults()
        
        new_firstlineno = func_with_defaults.__code__.co_firstlineno + 4
        update_function_line_numbers(func_with_defaults, new_firstlineno)
        
        self.assertEqual(func_with_defaults.__defaults__, original_defaults)
        self.assertEqual(func_with_defaults(), original_result)

    def test_function_annotations_preserved(self):
        """Test that function annotations are preserved."""
        def annotated_func(x: int) -> int:
            return x * 2
        
        original_annotations = annotated_func.__annotations__
        
        new_firstlineno = annotated_func.__code__.co_firstlineno + 6
        update_function_line_numbers(annotated_func, new_firstlineno)
        
        self.assertEqual(annotated_func.__annotations__, original_annotations)

    def test_closure_variables_preserved(self):
        """Test that closure variables are preserved."""
        def make_closure():
            x = 10
            def closure_func():
                return x
            return closure_func
        
        closure_func = make_closure()
        original_result = closure_func()
        original_closure = closure_func.__closure__
        
        new_firstlineno = closure_func.__code__.co_firstlineno + 8
        update_function_line_numbers(closure_func, new_firstlineno)
        
        self.assertEqual(closure_func.__closure__, original_closure)
        self.assertEqual(closure_func(), original_result)

    def test_invalid_function_input(self):
        """Test handling of invalid function input."""
        with self.assertRaises(AttributeError):
            update_function_line_numbers(None, 10)
        
        with self.assertRaises(AttributeError):
            update_function_line_numbers("not a function", 10)
        
        with self.assertRaises(AttributeError):
            update_function_line_numbers(42, 10)

    def test_invalid_line_number_input(self):
        """Test handling of invalid line number input."""
        func = self.test_functions['simple']
        
        with self.assertRaises(TypeError):
            update_function_line_numbers(func, "not a number")
        
        with self.assertRaises(TypeError):
            update_function_line_numbers(func, None)

    def test_zero_line_number(self):
        """Test handling of zero line number (edge case)."""
        func = self.test_functions['simple']
        
        # Zero line number might be invalid
        try:
            update_function_line_numbers(func, 0)
            # If it succeeds, check that function still works
            self.assertEqual(func(), 42)
        except (ValueError, OverflowError):
            # It's acceptable to reject zero line numbers
            pass

    def test_negative_line_number(self):
        """Test handling of negative line number."""
        func = self.test_functions['simple']
        
        # Negative line numbers should be rejected
        with self.assertRaises((ValueError, OverflowError)):
            update_function_line_numbers(func, -1)

    def test_builtin_function_handling(self):
        """Test handling of built-in functions."""
        # Built-in functions don't have modifiable code objects
        with self.assertRaises(AttributeError):
            update_function_line_numbers(len, 10)

    def test_method_function_update(self):
        """Test updating method functions."""
        class TestClass:
            def test_method(self):
                return "method result"
        
        obj = TestClass()
        method_func = obj.test_method
        
        # This might not be directly applicable to bound methods
        # but we should test unbound method behavior
        unbound_method = TestClass.test_method
        original_result = unbound_method(obj)
        
        new_firstlineno = unbound_method.__code__.co_firstlineno + 5
        update_function_line_numbers(unbound_method, new_firstlineno)
        
        # Method should still work
        new_result = unbound_method(obj)
        self.assertEqual(new_result, original_result)


if __name__ == '__main__':
    unittest.main()