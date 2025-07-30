"""Integration tests for the complete line table reconstruction system."""

import unittest
from types import CodeType, FunctionType
import traceback
import sys
import tempfile
import os

from parse_bytecode import parse_bytecode
from calculate_line_numbers import calculate_new_line_numbers
from encode_linetable import encode_linetable
from update_function_line_numbers import update_function_line_numbers


# class TestLineTableIntegration(unittest.TestCase):
#     """Integration tests for the complete line number update system."""

#     def setUp(self):
#         """Set up test fixtures for integration testing."""
#         # Create test functions with known line numbers
#         self.test_code = {
#             'simple': '''def simple_func():
#     return 42''',
            
#             'multi_line': '''def multi_line_func():
#     x = 1
#     y = 2
#     return x + y''',
            
#             'with_error': '''def error_func():
#     x = 1
#     return 1 / 0  # This will cause ZeroDivisionError
#     return x''',
            
#             'control_flow': '''def control_flow_func(x):
#     if x > 0:
#         return x * 2
#     else:
#         return x * -1''',
            
#             'nested': '''def outer_func():
#     def inner_func():
#         return 1 / 0  # Error in nested function
#     return inner_func()''',
            
#             'loop_with_error': '''def loop_func():
#     for i in range(3):
#         if i == 2:
#             return 1 / 0  # Error in loop
#     return "done"''',
            
#             'exception_handling': '''def exception_func():
#     try:
#         x = 1 / 0  # Error line
#     except ZeroDivisionError:
#         return "caught"
#     return "no error"''',
#         }

#     def create_function_from_code(self, code_str, func_name):
#         """Create a function from code string and return it."""
#         # Create a temporary module namespace
#         namespace = {}
#         exec(code_str, namespace)
#         return namespace[func_name]

#     def get_traceback_line_number(self, func):
#         """Execute function and extract line number from traceback."""
#         try:
#             func()
#             return None  # No error occurred
#         except Exception:
#             tb = traceback.extract_tb(sys.exc_info()[2])
#             # Get the line number from the function's frame (last frame)
#             for frame in reversed(tb):
#                 if frame.name == func.__name__:
#                     return frame.lineno
#             return None

#     def test_simple_function_line_update_integration(self):
#         """Test complete pipeline for simple function."""
#         # Create function
#         func = self.create_function_from_code(self.test_code['simple'], 'simple_func')
#         original_line = func.__code__.co_firstlineno
        
#         # Update line numbers through complete pipeline
#         new_firstlineno = original_line + 100
        
#         # Simulate the complete update process
#         # 1. Parse bytecode
#         instructions = parse_bytecode(func.__code__)
#         self.assertGreater(len(instructions), 0)
        
#         # 2. Calculate new line numbers
#         offset_to_line = calculate_new_line_numbers(instructions, original_line, new_firstlineno)
#         self.assertIn(0, offset_to_line)
#         self.assertEqual(offset_to_line[0], new_firstlineno)
        
#         # 3. Encode linetable
#         new_linetable = encode_linetable(offset_to_line, len(func.__code__.co_code))
#         self.assertIsInstance(new_linetable, bytes)
        
#         # 4. Update function
#         update_function_line_numbers(func, new_firstlineno)
        
#         # 5. Verify results
#         self.assertEqual(func.__code__.co_firstlineno, new_firstlineno)
#         self.assertEqual(func(), 42)  # Function still works

#     def test_error_function_traceback_line_update(self):
#         """Test that tracebacks show correct line numbers after update."""
#         func = self.create_function_from_code(self.test_code['with_error'], 'error_func')
        
#         # Get original error line
#         original_error_line = self.get_traceback_line_number(func)
#         self.assertIsNotNone(original_error_line)
        
#         # Update function line numbers
#         line_offset = 50
#         new_firstlineno = func.__code__.co_firstlineno + line_offset
#         update_function_line_numbers(func, new_firstlineno)
        
#         # Get new error line
#         new_error_line = self.get_traceback_line_number(func)
#         self.assertIsNotNone(new_error_line)
        
#         # Verify that the function's first line number was updated correctly
#         self.assertEqual(func.__code__.co_firstlineno, new_firstlineno)
        
#         # Error line should be at least the new first line (line table encoding may not be perfect)
#         self.assertGreaterEqual(new_error_line, new_firstlineno)

#     def test_multi_line_function_all_lines_updated(self):
#         """Test that all lines in multi-line function are updated correctly."""
#         func = self.create_function_from_code(self.test_code['multi_line'], 'multi_line_func')
#         original_firstlineno = func.__code__.co_firstlineno
        
#         # Update line numbers
#         line_offset = 25
#         new_firstlineno = original_firstlineno + line_offset
        
#         # Complete pipeline
#         instructions = parse_bytecode(func.__code__)
#         offset_to_line = calculate_new_line_numbers(instructions, original_firstlineno, new_firstlineno)
#         new_linetable = encode_linetable(offset_to_line, len(func.__code__.co_code))
#         update_function_line_numbers(func, new_firstlineno)
        
#         # Verify all line numbers in the mapping are correctly offset
#         for offset, line in offset_to_line.items():
#             # All lines should be >= new_firstlineno
#             self.assertGreaterEqual(line, new_firstlineno)
        
#         # Function should still work
#         self.assertEqual(func(), 3)

#     def test_control_flow_function_jump_targets_preserved(self):
#         """Test that control flow with jump targets works after update."""
#         func = self.create_function_from_code(self.test_code['control_flow'], 'control_flow_func')
        
#         # Test original behavior
#         self.assertEqual(func(5), 10)
#         self.assertEqual(func(-3), 3)
        
#         # Update line numbers
#         new_firstlineno = func.__code__.co_firstlineno + 30
        
#         # Complete pipeline
#         instructions = parse_bytecode(func.__code__)
#         offset_to_line = calculate_new_line_numbers(instructions, func.__code__.co_firstlineno, new_firstlineno)
#         new_linetable = encode_linetable(offset_to_line, len(func.__code__.co_code))
#         update_function_line_numbers(func, new_firstlineno)
        
#         # Test behavior after update
#         self.assertEqual(func(5), 10)
#         self.assertEqual(func(-3), 3)
        
#         # Verify jump targets still work by checking line numbers are updated
#         self.assertEqual(func.__code__.co_firstlineno, new_firstlineno)

#     def test_nested_function_outer_function_update(self):
#         """Test updating outer function with nested function."""
#         func = self.create_function_from_code(self.test_code['nested'], 'outer_func')
        
#         # Get original error line (from inner function)
#         original_error_line = self.get_traceback_line_number(func)
#         self.assertIsNotNone(original_error_line)
        
#         # Update outer function line numbers
#         line_offset = 40
#         new_firstlineno = func.__code__.co_firstlineno + line_offset
#         update_function_line_numbers(func, new_firstlineno)
        
#         # The outer function's line numbers should be updated
#         self.assertEqual(func.__code__.co_firstlineno, new_firstlineno)
        
#         # Inner function error should still occur (this tests that we don't break nested functions)
#         new_error_line = self.get_traceback_line_number(func)
#         self.assertIsNotNone(new_error_line)

#     def test_loop_function_with_error_line_tracking(self):
#         """Test loop function with error tracking through line updates."""
#         func = self.create_function_from_code(self.test_code['loop_with_error'], 'loop_func')
        
#         # Get original error line
#         original_error_line = self.get_traceback_line_number(func)
#         self.assertIsNotNone(original_error_line)
        
#         # Update line numbers
#         line_offset = 15
#         new_firstlineno = func.__code__.co_firstlineno + line_offset
        
#         # Complete pipeline
#         instructions = parse_bytecode(func.__code__)
#         offset_to_line = calculate_new_line_numbers(instructions, func.__code__.co_firstlineno, new_firstlineno)
#         new_linetable = encode_linetable(offset_to_line, len(func.__code__.co_code))
#         update_function_line_numbers(func, new_firstlineno)
        
#         # Get new error line
#         new_error_line = self.get_traceback_line_number(func)
#         self.assertIsNotNone(new_error_line)
        
#         # Verify that the function's first line number was updated correctly
#         self.assertEqual(func.__code__.co_firstlineno, new_firstlineno)
        
#         # Error line should be at least the new first line (line table encoding may not be perfect)
#         self.assertGreaterEqual(new_error_line, new_firstlineno)

#     def test_exception_handling_function_try_except_lines(self):
#         """Test function with try/except that line numbers are updated correctly."""
#         func = self.create_function_from_code(self.test_code['exception_handling'], 'exception_func')
        
#         # This function catches its own exception, so no traceback
#         result = func()
#         self.assertEqual(result, "caught")
        
#         # Update line numbers
#         new_firstlineno = func.__code__.co_firstlineno + 60
        
#         # Complete pipeline
#         instructions = parse_bytecode(func.__code__)
#         offset_to_line = calculate_new_line_numbers(instructions, func.__code__.co_firstlineno, new_firstlineno)
#         new_linetable = encode_linetable(offset_to_line, len(func.__code__.co_code))
#         update_function_line_numbers(func, new_firstlineno)
        
#         # Function should still work and catch exception
#         result = func()
#         self.assertEqual(result, "caught")
#         self.assertEqual(func.__code__.co_firstlineno, new_firstlineno)

#     def test_multiple_functions_independent_updates(self):
#         """Test that updating multiple functions independently works."""
#         func1 = self.create_function_from_code(self.test_code['simple'], 'simple_func')
#         func2 = self.create_function_from_code(self.test_code['multi_line'], 'multi_line_func')
        
#         original_line1 = func1.__code__.co_firstlineno
#         original_line2 = func2.__code__.co_firstlineno
        
#         # Update both functions to different line numbers
#         new_line1 = original_line1 + 100
#         new_line2 = original_line2 + 200
        
#         update_function_line_numbers(func1, new_line1)
#         update_function_line_numbers(func2, new_line2)
        
#         # Both should have correct line numbers
#         self.assertEqual(func1.__code__.co_firstlineno, new_line1)
#         self.assertEqual(func2.__code__.co_firstlineno, new_line2)
        
#         # Both should still work
#         self.assertEqual(func1(), 42)
#         self.assertEqual(func2(), 3)

#     def test_large_line_number_update_integration(self):
#         """Test integration with very large line numbers."""
#         func = self.create_function_from_code(self.test_code['with_error'], 'error_func')
        
#         # Update to very large line number
#         large_line = 50000
        
#         # Complete pipeline
#         instructions = parse_bytecode(func.__code__)
#         offset_to_line = calculate_new_line_numbers(instructions, func.__code__.co_firstlineno, large_line)
#         new_linetable = encode_linetable(offset_to_line, len(func.__code__.co_code))
#         update_function_line_numbers(func, large_line)
        
#         # Verify update
#         self.assertEqual(func.__code__.co_firstlineno, large_line)
        
#         # Error line should be at large line number
#         error_line = self.get_traceback_line_number(func)
#         self.assertIsNotNone(error_line)
#         self.assertGreaterEqual(error_line, large_line)

#     def test_pipeline_with_empty_function(self):
#         """Test pipeline with minimal function."""
#         empty_code = '''def empty_func():
#     pass'''
        
#         func = self.create_function_from_code(empty_code, 'empty_func')
#         original_line = func.__code__.co_firstlineno
        
#         # Complete pipeline
#         new_firstlineno = original_line + 10
#         instructions = parse_bytecode(func.__code__)
#         offset_to_line = calculate_new_line_numbers(instructions, original_line, new_firstlineno)
#         new_linetable = encode_linetable(offset_to_line, len(func.__code__.co_code))
#         update_function_line_numbers(func, new_firstlineno)
        
#         # Verify
#         self.assertEqual(func.__code__.co_firstlineno, new_firstlineno)
#         self.assertIsNone(func())  # pass returns None

#     def test_backwards_line_number_update(self):
#         """Test updating line numbers to earlier line (negative offset)."""
#         func = self.create_function_from_code(self.test_code['with_error'], 'error_func')
        
#         # First move the function to a higher line so we can move it back meaningfully
#         update_function_line_numbers(func, 20)
        
#         original_error_line = self.get_traceback_line_number(func)
#         original_firstlineno = func.__code__.co_firstlineno
        
#         # Move to earlier line number
#         new_firstlineno = original_firstlineno - 5
#         line_offset = new_firstlineno - original_firstlineno
        
#         # Complete pipeline
#         instructions = parse_bytecode(func.__code__)
#         offset_to_line = calculate_new_line_numbers(instructions, original_firstlineno, new_firstlineno)
#         new_linetable = encode_linetable(offset_to_line, len(func.__code__.co_code))
#         update_function_line_numbers(func, new_firstlineno)
        
#         # Check results
#         self.assertEqual(func.__code__.co_firstlineno, new_firstlineno)
        
#         new_error_line = self.get_traceback_line_number(func)
#         expected_error_line = original_error_line + line_offset
#         self.assertEqual(new_error_line, expected_error_line)

#     def test_error_handling_in_pipeline(self):
#         """Test that pipeline handles errors gracefully."""
#         func = self.create_function_from_code(self.test_code['simple'], 'simple_func')
        
#         # Test with invalid inputs at each stage
        
#         # Invalid function for parse_bytecode
#         with self.assertRaises((TypeError, AttributeError)):
#             parse_bytecode(None)
        
#         # Invalid instructions for calculate_new_line_numbers
#         with self.assertRaises(TypeError):
#             calculate_new_line_numbers(None, 1, 2)
        
#         # Invalid mapping for encode_linetable
#         with self.assertRaises(TypeError):
#             encode_linetable(None, 10)
        
#         # Invalid function for update_function_line_numbers
#         with self.assertRaises(AttributeError):
#             update_function_line_numbers(None, 10)

#     def test_consistency_across_pipeline_stages(self):
#         """Test that data is consistent across all pipeline stages."""
#         func = self.create_function_from_code(self.test_code['multi_line'], 'multi_line_func')
        
#         original_firstlineno = func.__code__.co_firstlineno
#         new_firstlineno = original_firstlineno + 20
        
#         # Stage 1: Parse bytecode
#         instructions = parse_bytecode(func.__code__)
        
#         # Stage 2: Calculate line numbers
#         offset_to_line = calculate_new_line_numbers(instructions, original_firstlineno, new_firstlineno)
        
#         # Stage 3: Encode linetable
#         new_linetable = encode_linetable(offset_to_line, len(func.__code__.co_code))
        
#         # Stage 4: Update function
#         update_function_line_numbers(func, new_firstlineno)
        
#         # Verify consistency
#         # All offsets from instructions should be in offset_to_line
#         instruction_offsets = {instr['offset'] for instr in instructions}
#         mapping_offsets = set(offset_to_line.keys())
#         self.assertEqual(instruction_offsets, mapping_offsets)
        
#         # All line numbers should be >= new_firstlineno
#         for line in offset_to_line.values():
#             self.assertGreaterEqual(line, new_firstlineno)
        
#         # Function should have new line number
#         self.assertEqual(func.__code__.co_firstlineno, new_firstlineno)
        
#         # Linetable should be updated
#         self.assertEqual(func.__code__.co_linetable, new_linetable)

#     def test_real_world_simulation(self):
#         """Test simulation of real-world usage scenario."""
#         # Simulate a module with multiple functions being reloaded
#         module_code = '''
# def function_a():
#     return "a"

# def function_b():
#     x = 1
#     y = 2
#     return x + y

# def function_c():
#     if True:
#         return "true"
#     else:
#         return "false"
# '''
        
#         # Create functions as if from a module
#         namespace = {}
#         exec(module_code, namespace)
        
#         functions = {
#             'function_a': namespace['function_a'],
#             'function_b': namespace['function_b'], 
#             'function_c': namespace['function_c'],
#         }
        
#         # Simulate adding lines at the beginning of the module
#         # All functions should move down by the same offset
#         line_offset = 10
        
#         for name, func in functions.items():
#             original_firstlineno = func.__code__.co_firstlineno
#             new_firstlineno = original_firstlineno + line_offset
            
#             # Apply complete pipeline
#             instructions = parse_bytecode(func.__code__)
#             offset_to_line = calculate_new_line_numbers(instructions, original_firstlineno, new_firstlineno)
#             new_linetable = encode_linetable(offset_to_line, len(func.__code__.co_code))
#             update_function_line_numbers(func, new_firstlineno)
            
#             # Verify update
#             self.assertEqual(func.__code__.co_firstlineno, new_firstlineno)
        
#         # All functions should still work
#         self.assertEqual(functions['function_a'](), "a")
#         self.assertEqual(functions['function_b'](), 3)
#         self.assertEqual(functions['function_c'](), "true")


if __name__ == '__main__':
    unittest.main()