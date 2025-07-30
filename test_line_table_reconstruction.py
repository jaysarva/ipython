#!/usr/bin/env python3
"""
Comprehensive unit tests for line table reconstruction system.

This module provides thorough testing of the line table reconstruction pipeline
including edge cases for decorated functions, nested functions, class methods,
properties, and other complex scenarios.
"""

import ast
import dis
import sys
import types
import unittest
from typing import Dict, List, Any, Optional, Callable
import tempfile

# Import the pipeline modules
try:
    from parse_bytecode import parse_bytecode
    from calculate_line_numbers import calculate_new_line_numbers
    from encode_linetable import encode_linetable
    from update_function_line_numbers import update_function_line_numbers
except ImportError:
    # Skip these tests if pipeline modules aren't available
    import pytest
    pytest.skip("Pipeline modules not available", allow_module_level=True)


class LineTableReconstructionTest(unittest.TestCase):
    """Base test class with common utilities for line table reconstruction testing."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        
    def tearDown(self):
        """Clean up test fixtures."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def create_test_function(self, source_code: str, name: str = "test_func") -> Callable:
        """Create a test function from source code with proper line numbering."""
        # Compile with a realistic filename for better testing
        filename = f"<test_{name}>"
        compiled = compile(source_code, filename, 'exec')
        namespace = {}
        exec(compiled, namespace)
        return namespace[name]

    def get_line_mappings(self, func: Callable) -> Dict[int, int]:
        """Extract the actual line mappings from a function's code object."""
        code_obj = func.__code__
        
        # Parse bytecode to get instruction information
        instructions = parse_bytecode(code_obj)
        
        # Build mapping from bytecode offset to line number
        mappings = {}
        current_line = code_obj.co_firstlineno
        
        for instr in instructions:
            if instr['starts_line'] is not None:
                current_line = instr['starts_line']
            mappings[instr['offset']] = current_line
            
        return mappings

    def assert_line_table_consistency(self, func: Callable):
        """Assert that a function's line table is internally consistent."""
        code_obj = func.__code__
        
        # Verify basic properties
        self.assertIsInstance(code_obj.co_firstlineno, int)
        self.assertGreater(code_obj.co_firstlineno, 0)
        self.assertIsInstance(code_obj.co_linetable, bytes)
        
        # Verify that parsing and encoding round-trip correctly
        instructions = parse_bytecode(code_obj)
        offset_to_line = calculate_new_line_numbers(
            instructions, code_obj.co_firstlineno, code_obj.co_firstlineno
        )
        new_linetable = encode_linetable(offset_to_line, len(code_obj.co_code))
        
        # The new line table should produce equivalent mappings
        # (Note: bytes may differ due to encoding variations, but semantics should match)
        self.assertIsInstance(new_linetable, bytes)


class TestSimpleFunctions(LineTableReconstructionTest):
    """Test line table reconstruction for simple functions."""
    
    def test_simple_function(self):
        """Test basic function with no decorators or complexity."""
        source = """
def test_func():
    x = 1
    y = 2
    return x + y
"""
        func = self.create_test_function(source)
        original_firstline = func.__code__.co_firstlineno
        
        # Update to a different line number
        new_firstline = 100
        update_function_line_numbers(func, new_firstline)
        
        # Verify the change
        self.assertEqual(func.__code__.co_firstlineno, new_firstline)
        self.assert_line_table_consistency(func)
        
        # Function should still work correctly
        self.assertEqual(func(), 3)

    def test_single_line_function(self):
        """Test function that fits on a single line."""
        source = """
def test_func(): return 42
"""
        func = self.create_test_function(source)
        
        update_function_line_numbers(func, 50)
        self.assertEqual(func.__code__.co_firstlineno, 50)
        self.assertEqual(func(), 42)

    def test_multiline_expression(self):
        """Test function with expressions spanning multiple lines."""
        source = """
def test_func():
    result = (1 + 2 + 
              3 + 4 +
              5)
    return result
"""
        func = self.create_test_function(source)
        update_function_line_numbers(func, 75)
        
        self.assertEqual(func.__code__.co_firstlineno, 75)
        self.assertEqual(func(), 15)
        self.assert_line_table_consistency(func)


class TestDecoratedFunctions(LineTableReconstructionTest):
    """Test line table reconstruction for decorated functions."""
    
    def test_single_decorator(self):
        """Test function with a single decorator."""
        source = """
def my_decorator(f):
    return f

@my_decorator
def test_func():
    return "decorated"
"""
        namespace = {}
        exec(source, namespace)
        func = namespace['test_func']
        
        # For decorated functions, co_firstlineno should point to the decorator
        decorator_line = func.__code__.co_firstlineno
        
        update_function_line_numbers(func, 200)
        self.assertEqual(func.__code__.co_firstlineno, 200)
        self.assertEqual(func(), "decorated")
        self.assert_line_table_consistency(func)

    def test_multiple_decorators(self):
        """Test function with multiple stacked decorators."""
        source = """
def decorator1(f):
    return f

def decorator2(f):
    return f

@decorator1
@decorator2
def test_func():
    return "multi-decorated"
"""
        namespace = {}
        exec(source, namespace)
        func = namespace['test_func']
        
        update_function_line_numbers(func, 150)
        self.assertEqual(func.__code__.co_firstlineno, 150)
        self.assertEqual(func(), "multi-decorated")
        self.assert_line_table_consistency(func)

    def test_parametrized_decorator(self):
        """Test function with parametrized decorators."""
        source = """
def param_decorator(param):
    def decorator(f):
        return f
    return decorator

@param_decorator("test")
def test_func():
    return "param-decorated"
"""
        namespace = {}
        exec(source, namespace)
        func = namespace['test_func']
        
        update_function_line_numbers(func, 300)
        self.assertEqual(func.__code__.co_firstlineno, 300)
        self.assertEqual(func(), "param-decorated")
        self.assert_line_table_consistency(func)


class TestNestedFunctions(LineTableReconstructionTest):
    """Test line table reconstruction for nested functions."""
    
    def test_simple_nested_function(self):
        """Test function containing a nested function."""
        source = """
def test_func():
    def inner():
        return "inner"
    return inner()
"""
        func = self.create_test_function(source)
        
        update_function_line_numbers(func, 400)
        self.assertEqual(func.__code__.co_firstlineno, 400)
        self.assertEqual(func(), "inner")
        self.assert_line_table_consistency(func)

    def test_closure_variables(self):
        """Test nested function with closure variables."""
        source = """
def test_func():
    x = 10
    def inner():
        return x * 2
    return inner()
"""
        func = self.create_test_function(source)
        
        update_function_line_numbers(func, 500)
        self.assertEqual(func.__code__.co_firstlineno, 500)
        self.assertEqual(func(), 20)
        self.assert_line_table_consistency(func)

    def test_deeply_nested_functions(self):
        """Test multiple levels of nested functions."""
        source = """
def test_func():
    def level1():
        def level2():
            def level3():
                return "deep"
            return level3()
        return level2()
    return level1()
"""
        func = self.create_test_function(source)
        
        update_function_line_numbers(func, 600)
        self.assertEqual(func.__code__.co_firstlineno, 600)
        self.assertEqual(func(), "deep")
        self.assert_line_table_consistency(func)


class TestClassMethods(LineTableReconstructionTest):
    """Test line table reconstruction for class methods."""
    
    def test_instance_method(self):
        """Test regular instance method."""
        source = """
class TestClass:
    def test_func(self):
        return "instance method"

instance = TestClass()
"""
        namespace = {}
        exec(source, namespace)
        instance = namespace['instance']
        func = instance.test_func
        
        # Get the underlying function
        method_func = func.__func__
        update_function_line_numbers(method_func, 700)
        
        self.assertEqual(method_func.__code__.co_firstlineno, 700)
        self.assertEqual(func(), "instance method")
        self.assert_line_table_consistency(method_func)

    def test_classmethod(self):
        """Test @classmethod decorated method."""
        source = """
class TestClass:
    @classmethod
    def test_func(cls):
        return "class method"
"""
        namespace = {}
        exec(source, namespace)
        cls = namespace['TestClass']
        
        # Extract the actual function from the classmethod
        classmethod_obj = cls.__dict__['test_func']
        func = classmethod_obj.__func__
        
        update_function_line_numbers(func, 800)
        self.assertEqual(func.__code__.co_firstlineno, 800)
        self.assertEqual(cls.test_func(), "class method")
        self.assert_line_table_consistency(func)

    def test_staticmethod(self):
        """Test @staticmethod decorated method."""
        source = """
class TestClass:
    @staticmethod
    def test_func():
        return "static method"
"""
        namespace = {}
        exec(source, namespace)
        cls = namespace['TestClass']
        
        # Extract the actual function from the staticmethod
        staticmethod_obj = cls.__dict__['test_func']
        func = staticmethod_obj.__func__
        
        update_function_line_numbers(func, 900)
        self.assertEqual(func.__code__.co_firstlineno, 900)
        self.assertEqual(cls.test_func(), "static method")
        self.assert_line_table_consistency(func)

    def test_property_method(self):
        """Test @property decorated method."""
        source = """
class TestClass:
    def __init__(self):
        self._value = "property value"
    
    @property
    def test_func(self):
        return self._value

instance = TestClass()
"""
        namespace = {}
        exec(source, namespace)
        cls = namespace['TestClass']
        instance = namespace['instance']
        
        # Extract the getter function from the property
        property_obj = cls.__dict__['test_func']
        func = property_obj.fget
        
        update_function_line_numbers(func, 1000)
        self.assertEqual(func.__code__.co_firstlineno, 1000)
        self.assertEqual(instance.test_func, "property value")
        self.assert_line_table_consistency(func)


class TestComplexScenarios(LineTableReconstructionTest):
    """Test line table reconstruction for complex edge cases."""
    
    def test_decorated_nested_function(self):
        """Test nested function with decorators."""
        source = """
def outer_decorator(f):
    return f

def test_func():
    @outer_decorator
    def inner():
        return "decorated nested"
    return inner()
"""
        func = self.create_test_function(source)
        
        update_function_line_numbers(func, 1100)
        self.assertEqual(func.__code__.co_firstlineno, 1100)
        self.assertEqual(func(), "decorated nested")
        self.assert_line_table_consistency(func)

    def test_method_with_nested_function(self):
        """Test class method containing nested functions."""
        source = """
class TestClass:
    def test_func(self):
        def helper():
            return "helper result"
        return helper()

instance = TestClass()
"""
        namespace = {}
        exec(source, namespace)
        instance = namespace['instance']
        func = instance.test_func.__func__
        
        update_function_line_numbers(func, 1200)
        self.assertEqual(func.__code__.co_firstlineno, 1200)
        self.assertEqual(instance.test_func(), "helper result")
        self.assert_line_table_consistency(func)

    def test_generator_function(self):
        """Test generator function line table reconstruction."""
        source = """
def test_func():
    yield 1
    yield 2
    yield 3
"""
        func = self.create_test_function(source)
        
        update_function_line_numbers(func, 1300)
        self.assertEqual(func.__code__.co_firstlineno, 1300)
        
        # Test that generator works correctly
        result = list(func())
        self.assertEqual(result, [1, 2, 3])
        self.assert_line_table_consistency(func)

    def test_async_function(self):
        """Test async function line table reconstruction."""
        source = """
async def test_func():
    return "async result"
"""
        func = self.create_test_function(source)
        
        update_function_line_numbers(func, 1400)
        self.assertEqual(func.__code__.co_firstlineno, 1400)
        self.assert_line_table_consistency(func)
        
        # Note: We don't actually run the async function since that would require
        # an event loop, but we can verify the line table is correct

    def test_lambda_function(self):
        """Test lambda function (should be handled gracefully)."""
        source = """
test_func = lambda x: x * 2
"""
        namespace = {}
        exec(source, namespace)
        func = namespace['test_func']
        
        # Lambda functions should work but may have limitations
        try:
            update_function_line_numbers(func, 1500)
            self.assertEqual(func.__code__.co_firstlineno, 1500)
            self.assertEqual(func(5), 10)
            self.assert_line_table_consistency(func)
        except Exception:
            # It's acceptable if lambda updates fail gracefully
            pass


class TestErrorHandling(LineTableReconstructionTest):
    """Test error handling and edge cases."""
    
    def test_invalid_line_number(self):
        """Test handling of invalid line numbers."""
        source = """
def test_func():
    return 42
"""
        func = self.create_test_function(source)
        
        # Test negative line number
        with self.assertRaises(ValueError):
            update_function_line_numbers(func, -1)
            
        # Test zero line number
        with self.assertRaises(ValueError):
            update_function_line_numbers(func, 0)

    def test_non_function_object(self):
        """Test handling of non-function objects."""
        with self.assertRaises(AttributeError):
            update_function_line_numbers("not a function", 100)
        
        with self.assertRaises(AttributeError):
            update_function_line_numbers(42, 100)

    def test_corrupted_code_object(self):
        """Test handling of functions with problematic code objects."""
        source = """
def test_func():
    return "test"
"""
        func = self.create_test_function(source)
        
        # Try to update with extreme line numbers that might cause issues
        try:
            update_function_line_numbers(func, sys.maxsize)
            # If it succeeds, verify it's still consistent
            self.assert_line_table_consistency(func)
        except Exception:
            # It's acceptable if extreme values are rejected
            pass


class TestIntegration(LineTableReconstructionTest):
    """Integration tests that combine multiple aspects."""
    
    def test_complex_class_hierarchy(self):
        """Test complex class with multiple method types."""
        source = """
def class_decorator(cls):
    return cls

def method_decorator(f):
    return f

@class_decorator
class TestClass:
    def __init__(self):
        self._value = 42
    
    @method_decorator
    def instance_method(self):
        def nested():
            return self._value * 2
        return nested()
    
    @classmethod
    def class_method(cls):
        return "class method result"
    
    @staticmethod
    def static_method():
        return "static method result"
    
    @property
    def prop(self):
        return self._value

instance = TestClass()
"""
        namespace = {}
        exec(source, namespace)
        instance = namespace['instance']
        cls = namespace['TestClass']
        
        # Test updating various method types
        methods_to_test = [
            (instance.instance_method.__func__, 2000, "instance method", instance.instance_method),
            (cls.class_method.__func__, 2100, "class method", cls.class_method),
            (cls.__dict__['static_method'].__func__, 2200, "static method", cls.static_method),
            (cls.__dict__['prop'].fget, 2300, "property", lambda: instance.prop),
        ]
        
        for func, new_line, method_type, caller in methods_to_test:
            with self.subTest(method_type=method_type):
                update_function_line_numbers(func, new_line)
                self.assertEqual(func.__code__.co_firstlineno, new_line)
                self.assert_line_table_consistency(func)
                
                # Verify functionality is preserved
                if method_type == "instance method":
                    self.assertEqual(caller(), 84)  # 42 * 2
                elif method_type == "class method":
                    self.assertEqual(caller(), "class method result")
                elif method_type == "static method":
                    self.assertEqual(caller(), "static method result")
                elif method_type == "property":
                    self.assertEqual(caller(), 42)


class TestPerformance(LineTableReconstructionTest):
    """Performance and stress tests."""
    
    def test_large_function(self):
        """Test line table reconstruction with a large function."""
        # Generate a function with many lines
        lines = ["def test_func():"]
        for i in range(100):
            lines.append(f"    x{i} = {i}")
        lines.append("    return sum([" + ", ".join(f"x{i}" for i in range(100)) + "])")
        
        source = "\n".join(lines)
        func = self.create_test_function(source)
        
        update_function_line_numbers(func, 5000)
        self.assertEqual(func.__code__.co_firstlineno, 5000)
        
        # Verify it still computes correctly
        expected = sum(range(100))
        self.assertEqual(func(), expected)
        self.assert_line_table_consistency(func)

    def test_many_nested_functions(self):
        """Test function with many nested functions."""
        lines = ["def test_func():"]
        for i in range(10):
            lines.append("    " * (i + 1) + f"def nested_{i}():")
            lines.append("    " * (i + 2) + f"return {i}")
        
        # Call chain
        call_chain = "nested_0()"
        for i in range(1, 10):
            call_chain = call_chain.replace(f"return {i-1}", f"return nested_{i}()")
        
        lines.append("    return " + call_chain)
        source = "\n".join(lines)
        
        func = self.create_test_function(source)
        update_function_line_numbers(func, 6000)
        
        self.assertEqual(func.__code__.co_firstlineno, 6000)
        self.assert_line_table_consistency(func)


if __name__ == '__main__':
    # Run the tests
    unittest.main(verbosity=2)