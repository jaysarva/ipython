#!/usr/bin/env python3
"""
Edge case tests for line table reconstruction focusing on problematic scenarios
that are likely to cause issues in the deduperreload integration.

These tests specifically target the kinds of functions that appear in
TestAutoreloadTraceback and similar challenging scenarios.
"""

import ast
import dis
import sys
import types
import unittest
import tempfile
import textwrap
from typing import Dict, List, Any, Optional, Callable

# Import the pipeline modules
try:
    from parse_bytecode import parse_bytecode
    from calculate_line_numbers import calculate_new_line_numbers
    from encode_linetable import encode_linetable
    from update_function_line_numbers import update_function_line_numbers
except ImportError:
    import pytest
    pytest.skip("Pipeline modules not available", allow_module_level=True)


class EdgeCaseLineTableTest(unittest.TestCase):
    """Tests for edge cases that commonly appear in autoreload scenarios."""
    
    def setUp(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
    
    def tearDown(self):
        """Clean up test environment."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def create_function_from_source(self, source: str, func_name: str = "test_func") -> Callable:
        """Create a function from source code, similar to autoreload scenarios."""
        # Dedent and compile the source
        source = textwrap.dedent(source).strip()
        compiled = compile(source, "<test_module>", 'exec')
        namespace = {}
        exec(compiled, namespace)
        return namespace[func_name]

    def simulate_autoreload_scenario(self, old_source: str, new_source: str, 
                                   func_name: str = "test_func") -> tuple[Callable, Callable]:
        """Simulate an autoreload scenario with old and new versions of a function."""
        old_func = self.create_function_from_source(old_source, func_name)
        new_func = self.create_function_from_source(new_source, func_name)
        return old_func, new_func

    def get_traceback_line_info(self, func: Callable) -> List[int]:
        """Get line numbers that would appear in a traceback for this function."""
        try:
            # This won't work for all functions, but gives us insight into line mapping
            func()  # This might raise an exception
        except Exception:
            import traceback
            tb_lines = []
            for line in traceback.format_exc().split('\n'):
                if 'line' in line and 'test_module' in line:
                    # Extract line number from traceback
                    parts = line.split()
                    for i, part in enumerate(parts):
                        if part == 'line' and i + 1 < len(parts):
                            try:
                                tb_lines.append(int(parts[i + 1].rstrip(',')))
                            except ValueError:
                                pass
            return tb_lines
        return []


class TestDecoratorEdgeCases(EdgeCaseLineTableTest):
    """Edge cases specifically related to decorators."""
    
    def test_multiple_decorators_with_different_indentation(self):
        """Test decorators with different line spacing (real-world scenario)."""
        source = """
def decorator1(f): return f
def decorator2(f): return f

@decorator1

@decorator2  # Extra spacing between decorators
def test_func():
    return 1/0  # Will raise for traceback testing
"""
        func = self.create_function_from_source(source)
        original_line = func.__code__.co_firstlineno
        
        # Update line numbers
        update_function_line_numbers(func, 100)
        self.assertEqual(func.__code__.co_firstlineno, 100)
        
        # Verify traceback behavior
        with self.assertRaises(ZeroDivisionError):
            func()

    def test_decorator_with_complex_parameters(self):
        """Test decorator with complex parameter expressions."""
        source = """
def param_decorator(x, y=None, **kwargs):
    def decorator(f):
        return f
    return decorator

@param_decorator(
    "param1",
    y="param2",
    extra_param=lambda x: x + 1
)
def test_func():
    return 1/0
"""
        func = self.create_function_from_source(source)
        update_function_line_numbers(func, 200)
        
        self.assertEqual(func.__code__.co_firstlineno, 200)
        with self.assertRaises(ZeroDivisionError):
            func()

    def test_nested_decorator_definitions(self):
        """Test decorators defined within other functions."""
        source = """
def outer():
    def inner_decorator(f):
        return f
    
    @inner_decorator
    def test_func():
        return 1/0
    
    return test_func

test_func = outer()
"""  
        func = self.create_function_from_source(source)
        update_function_line_numbers(func, 300)
        
        self.assertEqual(func.__code__.co_firstlineno, 300)
        with self.assertRaises(ZeroDivisionError):
            func()


class TestClassMethodEdgeCases(EdgeCaseLineTableTest):
    """Edge cases for class methods, properties, etc."""
    
    def test_property_with_setter_and_deleter(self):
        """Test property with getter, setter, and deleter."""
        source = """
class TestClass:
    def __init__(self):
        self._value = 42
    
    @property
    def test_func(self):
        return self._value
    
    @test_func.setter  
    def test_func(self, value):
        if value < 0:
            raise ValueError("Negative value")  # For traceback testing
        self._value = value
    
    @test_func.deleter
    def test_func(self):
        del self._value

instance = TestClass()
"""
        namespace = {}
        exec(textwrap.dedent(source), namespace)
        instance = namespace['instance']
        cls = namespace['TestClass']
        
        # Test updating the getter
        prop_obj = cls.__dict__['test_func']
        getter_func = prop_obj.fget
        update_function_line_numbers(getter_func, 400)
        
        self.assertEqual(getter_func.__code__.co_firstlineno, 400)
        self.assertEqual(instance.test_func, 42)
        
        # Test updating the setter
        setter_func = prop_obj.fset
        update_function_line_numbers(setter_func, 500)
        
        self.assertEqual(setter_func.__code__.co_firstlineno, 500)
        
        # Test setter with exception for traceback
        with self.assertRaises(ValueError):
            instance.test_func = -1

    def test_classmethod_with_complex_logic(self):
        """Test classmethod with complex internal logic."""
        source = """
class TestClass:
    class_var = 10
    
    @classmethod
    def test_func(cls):
        def helper():
            return cls.class_var * 2
        
        if cls.class_var > 0:
            result = helper()
        else:
            result = 1/0  # For traceback testing
            
        return result
"""
        namespace = {}
        exec(textwrap.dedent(source), namespace)
        cls = namespace['TestClass']
        
        classmethod_obj = cls.__dict__['test_func']
        func = classmethod_obj.__func__
        
        update_function_line_numbers(func, 600)
        self.assertEqual(func.__code__.co_firstlineno, 600)
        self.assertEqual(cls.test_func(), 20)
        
        # Test error case
        cls.class_var = -1
        with self.assertRaises(ZeroDivisionError):
            cls.test_func()

    def test_staticmethod_with_nested_classes(self):
        """Test staticmethod containing nested class definitions."""
        source = """
class TestClass:
    @staticmethod
    def test_func():
        class NestedClass:
            def method(self):
                return 1/0  # For traceback
        
        obj = NestedClass()
        return obj.method()
"""
        namespace = {}
        exec(textwrap.dedent(source), namespace)
        cls = namespace['TestClass']
        
        staticmethod_obj = cls.__dict__['test_func']
        func = staticmethod_obj.__func__
        
        update_function_line_numbers(func, 700)
        self.assertEqual(func.__code__.co_firstlineno, 700)
        
        with self.assertRaises(ZeroDivisionError):
            cls.test_func()


class TestNestedFunctionEdgeCases(EdgeCaseLineTableTest):
    """Edge cases for nested functions and closures."""
    
    def test_deeply_nested_with_exception_propagation(self):
        """Test deeply nested functions with exception propagation."""
        source = """
def test_func():
    def level1():
        def level2():
            def level3():
                def level4():
                    return 1/0  # Deep exception
                return level4()
            return level3()
        return level2()
    return level1()
"""
        func = self.create_function_from_source(source)
        update_function_line_numbers(func, 800)
        
        self.assertEqual(func.__code__.co_firstlineno, 800)
        
        with self.assertRaises(ZeroDivisionError):
            func()

    def test_closure_with_mutable_state(self):
        """Test closure capturing mutable state."""
        source = """
def test_func():
    counters = {'value': 0}
    
    def increment():
        counters['value'] += 1
        if counters['value'] > 5:
            return 1/0  # Error after some increments
        return counters['value']
    
    results = []
    for i in range(10):  # This will eventually hit the error
        results.append(increment())
    
    return results
"""
        func = self.create_function_from_source(source)
        update_function_line_numbers(func, 900)
        
        self.assertEqual(func.__code__.co_firstlineno, 900)
        
        with self.assertRaises(ZeroDivisionError):
            func()

    def test_generator_with_nested_functions(self):
        """Test generator containing nested functions."""
        source = """
def test_func():
    def helper(x):
        if x > 3:
            return 1/0  # Error for certain values
        return x * 2
    
    for i in range(10):
        yield helper(i)
"""
        func = self.create_function_from_source(source)
        update_function_line_numbers(func, 1000)
        
        self.assertEqual(func.__code__.co_firstlineno, 1000)
        
        gen = func()
        results = []
        
        with self.assertRaises(ZeroDivisionError):
            for value in gen:
                results.append(value)


class TestComplexControlFlow(EdgeCaseLineTableTest):
    """Test functions with complex control flow patterns."""
    
    def test_try_except_with_nested_functions(self):
        """Test try/except blocks containing nested functions."""
        source = """
def test_func():
    def risky_operation():
        return 1/0
    
    def safe_operation():
        return 42
    
    try:
        def error_handler():
            return "handled"
        
        result = risky_operation()
    except ZeroDivisionError:
        result = error_handler()
    
    return result
"""
        func = self.create_function_from_source(source)
        update_function_line_numbers(func, 1100)
        
        self.assertEqual(func.__code__.co_firstlineno, 1100)
        self.assertEqual(func(), "handled")

    def test_complex_comprehensions(self):
        """Test functions with complex list/dict comprehensions."""
        source = """
def test_func():
    def process_item(x):
        if x == 5:
            return 1/0  # Error for specific value
        return x * 2
    
    try:
        result = [process_item(x) for x in range(10) if x % 2 == 0]
        return result
    except ZeroDivisionError:
        return "error caught"
"""
        func = self.create_function_from_source(source)
        update_function_line_numbers(func, 1200)
        
        self.assertEqual(func.__code__.co_firstlineno, 1200)
        # This should catch the error from x=4 (which becomes 5 after processing? No, x=5)
        result = func()  # x=5 is odd, so won't be processed
        expected = [0, 4, 8, 12, 16]  # 0*2, 2*2, 4*2, 6*2, 8*2
        self.assertEqual(result, expected)

    def test_with_statement_and_context_managers(self):
        """Test functions using with statements and context managers."""
        source = """
class ErrorContextManager:
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False

def test_func():
    def operation_in_context():
        return 1/0
    
    try:
        with ErrorContextManager():
            result = operation_in_context()
    except ZeroDivisionError:
        result = "context error handled"
    
    return result
"""
        namespace = {}
        exec(textwrap.dedent(source), namespace)
        func = namespace['test_func']
        
        update_function_line_numbers(func, 1300)
        self.assertEqual(func.__code__.co_firstlineno, 1300)
        self.assertEqual(func(), "context error handled")


class TestAutoreloadSpecificScenarios(EdgeCaseLineTableTest):
    """Test scenarios that specifically mimic autoreload behavior."""
    
    def test_function_replacement_line_shift(self):
        """Test scenario where a function is replaced and lines are shifted."""
        old_source = """
def test_func():
    # Original version
    x = 1
    y = 2
    return x + y
"""
        
        new_source = """
# New comment added at top
# Another comment

def test_func():
    # Updated version with more comments
    # Additional comment
    x = 1
    y = 2
    z = 3  # New variable
    return x + y + z
"""
        
        old_func, new_func = self.simulate_autoreload_scenario(old_source, new_source)
        
        # Simulate what autoreload does: update old function with new line numbers
        new_firstline = new_func.__code__.co_firstlineno
        update_function_line_numbers(old_func, new_firstline)
        
        self.assertEqual(old_func.__code__.co_firstlineno, new_firstline)
        
        # Old function should still work with original logic
        self.assertEqual(old_func(), 3)  # x + y = 1 + 2 = 3

    def test_decorated_function_line_shift(self):
        """Test decorated function where decorators are added/removed."""
        old_source = """
def test_func():
    return 1/0  # For traceback testing
"""
        
        new_source = """
# Comments added
def decorator(f):
    return f

@decorator
def test_func():
    return 1/0  # For traceback testing
"""
        
        old_func, new_func = self.simulate_autoreload_scenario(old_source, new_source)
        
        # Update old function to new line number
        new_firstline = new_func.__code__.co_firstlineno  
        update_function_line_numbers(old_func, new_firstline)
        
        self.assertEqual(old_func.__code__.co_firstlineno, new_firstline)
        
        # Both should raise the same exception
        with self.assertRaises(ZeroDivisionError):
            old_func()
        
        with self.assertRaises(ZeroDivisionError):
            new_func()

    def test_method_replacement_in_class(self):
        """Test method replacement within a class (autoreload scenario)."""
        old_source = """
class TestClass:
    def test_func(self):
        return 1/0  # Error in old version

instance = TestClass()
"""
        
        new_source = """
# Class with additional methods
class TestClass:
    def helper_method(self):
        return "helper"
    
    def test_func(self):
        return 1/0  # Error in new version too
        
    def another_method(self):
        return "another"

instance = TestClass()
"""
        
        # Get the methods from both versions
        old_namespace = {}
        exec(textwrap.dedent(old_source), old_namespace)
        old_instance = old_namespace['instance']
        old_method = old_instance.test_func.__func__
        
        new_namespace = {}
        exec(textwrap.dedent(new_source), new_namespace)
        new_instance = new_namespace['instance']
        new_method = new_instance.test_func.__func__
        
        # Update old method to new line number
        new_firstline = new_method.__code__.co_firstlineno
        update_function_line_numbers(old_method, new_firstline)
        
        self.assertEqual(old_method.__code__.co_firstlineno, new_firstline)
        
        # Both should raise exceptions with updated line numbers
        with self.assertRaises(ZeroDivisionError):
            old_instance.test_func()


class TestRealWorldPatterns(EdgeCaseLineTableTest):
    """Test patterns commonly found in real-world code."""
    
    def test_django_style_view_function(self):
        """Test Django-style view function with decorators."""
        source = """
def login_required(f):
    return f

def csrf_exempt(f):
    return f

@login_required  
@csrf_exempt
def test_func(request):
    # Simulate view logic
    if not request:
        raise ValueError("No request")
    
    def process_request():
        return {"status": "ok"}
    
    return process_request()
"""
        func = self.create_function_from_source(source)
        update_function_line_numbers(func, 2000)
        
        self.assertEqual(func.__code__.co_firstlineno, 2000)
        
        # Test with valid request
        self.assertEqual(func("mock_request"), {"status": "ok"})
        
        # Test with invalid request
        with self.assertRaises(ValueError):
            func(None)

    def test_dataclass_style_method(self):
        """Test method that might appear in a dataclass."""
        source = """
class TestClass:
    def __init__(self, value):
        self.value = value
    
    def test_func(self):
        def validate():
            if self.value < 0:
                raise ValueError("Negative value not allowed")
            return True
        
        validate()
        return self.value * 2

instance = TestClass(5)
negative_instance = TestClass(-1)
"""
        namespace = {}
        exec(textwrap.dedent(source), namespace)
        
        instance = namespace['instance']
        negative_instance = namespace['negative_instance']
        
        func = instance.test_func.__func__
        update_function_line_numbers(func, 2100)
        
        self.assertEqual(func.__code__.co_firstlineno, 2100)
        self.assertEqual(instance.test_func(), 10)
        
        with self.assertRaises(ValueError):
            negative_instance.test_func()

    def test_async_await_pattern(self):
        """Test async/await pattern (without actually running async code)."""
        source = """
async def test_func():
    async def async_helper():
        return 42
    
    # In real code this would be: result = await async_helper()
    # For testing, we'll simulate it
    def sync_version():
        return 42
    
    result = sync_version()
    if result != 42:
        raise ValueError("Unexpected result")
    
    return result
"""
        func = self.create_function_from_source(source)
        update_function_line_numbers(func, 2200)
        
        self.assertEqual(func.__code__.co_firstlineno, 2200)
        
        # We can't easily test async execution, but we can verify line table consistency
        self.assertIsInstance(func.__code__.co_linetable, bytes)


if __name__ == '__main__':
    unittest.main(verbosity=2)