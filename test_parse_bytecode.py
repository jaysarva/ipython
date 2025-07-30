"""Unit tests for bytecode parsing functionality."""

import unittest
from types import CodeType, FunctionType
import dis

from parse_bytecode import parse_bytecode


class TestParseBytecode(unittest.TestCase):
    """Test cases for parse_bytecode function."""

    def setUp(self):
        """Set up test fixtures with various function types."""
        # Simple function
        def simple_func():
            return 42
        
        # Function with multiple lines
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
        
        # Function with loop
        def loop_func():
            total = 0
            for i in range(10):
                total += i
            return total
        
        # Function with exception handling
        def exception_func():
            try:
                return 1 / 0
            except ZeroDivisionError:
                return 0
            finally:
                pass
        
        # Nested function
        def outer_func():
            def inner_func():
                return "inner"
            return inner_func()
        
        # Lambda function
        lambda_func = lambda x: x * 2
        
        # Generator function
        def generator_func():
            yield 1
            yield 2
            yield 3
        
        # Async function
        async def async_func():
            return "async"
        
        self.test_functions = {
            'simple': simple_func,
            'multi_line': multi_line_func,
            'control_flow': control_flow_func,
            'loop': loop_func,
            'exception': exception_func,
            'outer': outer_func,
            'lambda': lambda_func,
            'generator': generator_func,
            'async': async_func,
        }

    def test_parse_bytecode_returns_list(self):
        """Test that parse_bytecode returns a list."""
        code_obj = self.test_functions['simple'].__code__
        result = parse_bytecode(code_obj)
        self.assertIsInstance(result, list)

    def test_parse_bytecode_non_empty_for_simple_function(self):
        """Test that parse_bytecode returns non-empty list for simple function."""
        code_obj = self.test_functions['simple'].__code__
        result = parse_bytecode(code_obj)
        self.assertGreater(len(result), 0)

    def test_instruction_structure(self):
        """Test that each instruction has required fields."""
        code_obj = self.test_functions['simple'].__code__
        result = parse_bytecode(code_obj)
        
        for instruction in result:
            self.assertIsInstance(instruction, dict)
            self.assertIn('offset', instruction)
            self.assertIn('opname', instruction)
            self.assertIn('starts_line', instruction)
            self.assertIn('is_jump_target', instruction)

    def test_offset_values_are_integers(self):
        """Test that offset values are integers."""
        code_obj = self.test_functions['multi_line'].__code__
        result = parse_bytecode(code_obj)
        
        for instruction in result:
            self.assertIsInstance(instruction['offset'], int)
            self.assertGreaterEqual(instruction['offset'], 0)

    def test_opname_values_are_strings(self):
        """Test that opname values are strings."""
        code_obj = self.test_functions['multi_line'].__code__
        result = parse_bytecode(code_obj)
        
        for instruction in result:
            self.assertIsInstance(instruction['opname'], str)
            self.assertGreater(len(instruction['opname']), 0)

    def test_starts_line_values(self):
        """Test that starts_line values are None or positive integers."""
        code_obj = self.test_functions['multi_line'].__code__
        result = parse_bytecode(code_obj)
        
        for instruction in result:
            starts_line = instruction['starts_line']
            if starts_line is not None:
                self.assertIsInstance(starts_line, int)
                self.assertGreater(starts_line, 0)

    def test_is_jump_target_is_boolean(self):
        """Test that is_jump_target values are booleans."""
        code_obj = self.test_functions['control_flow'].__code__
        result = parse_bytecode(code_obj)
        
        for instruction in result:
            self.assertIsInstance(instruction['is_jump_target'], bool)

    def test_offsets_are_monotonic(self):
        """Test that instruction offsets are in ascending order."""
        code_obj = self.test_functions['multi_line'].__code__
        result = parse_bytecode(code_obj)
        
        offsets = [instr['offset'] for instr in result]
        self.assertEqual(offsets, sorted(offsets))

    def test_first_instruction_has_line_number(self):
        """Test that the first instruction has a line number."""
        code_obj = self.test_functions['simple'].__code__
        result = parse_bytecode(code_obj)
        
        self.assertIsNotNone(result[0]['starts_line'])
        self.assertEqual(result[0]['starts_line'], code_obj.co_firstlineno)

    def test_control_flow_has_jump_targets(self):
        """Test that control flow functions have jump targets."""
        code_obj = self.test_functions['control_flow'].__code__
        result = parse_bytecode(code_obj)
        
        has_jump_target = any(instr['is_jump_target'] for instr in result)
        self.assertTrue(has_jump_target)

    def test_loop_function_bytecode(self):
        """Test parsing bytecode for loop function."""
        code_obj = self.test_functions['loop'].__code__
        result = parse_bytecode(code_obj)
        
        # Should have multiple line numbers
        line_numbers = [instr['starts_line'] for instr in result if instr['starts_line'] is not None]
        self.assertGreater(len(set(line_numbers)), 1)

    def test_exception_handling_bytecode(self):
        """Test parsing bytecode for function with exception handling."""
        code_obj = self.test_functions['exception'].__code__
        result = parse_bytecode(code_obj)
        
        # Should have instructions and jump targets
        self.assertGreater(len(result), 5)
        has_jump_target = any(instr['is_jump_target'] for instr in result)
        self.assertTrue(has_jump_target)

    def test_generator_function_bytecode(self):
        """Test parsing bytecode for generator function."""
        code_obj = self.test_functions['generator'].__code__
        result = parse_bytecode(code_obj)
        
        # Should contain yield-related opcodes
        opcodes = [instr['opname'] for instr in result]
        self.assertIn('YIELD_VALUE', opcodes)

    def test_async_function_bytecode(self):
        """Test parsing bytecode for async function."""
        code_obj = self.test_functions['async'].__code__
        result = parse_bytecode(code_obj)
        
        self.assertGreater(len(result), 0)
        # Async functions have special characteristics
        self.assertTrue(code_obj.co_flags & 0x80)  # CO_COROUTINE flag

    def test_lambda_function_bytecode(self):
        """Test parsing bytecode for lambda function."""
        code_obj = self.test_functions['lambda'].__code__
        result = parse_bytecode(code_obj)
        
        self.assertGreater(len(result), 0)
        self.assertEqual(code_obj.co_name, '<lambda>')

    def test_empty_code_object(self):
        """Test parsing bytecode for minimal code object."""
        # Create minimal function
        def empty_func():
            pass
        
        code_obj = empty_func.__code__
        result = parse_bytecode(code_obj)
        
        self.assertGreater(len(result), 0)
        # Should at least have LOAD_CONST and RETURN_VALUE
        opcodes = [instr['opname'] for instr in result]
        self.assertIn('RETURN_VALUE', opcodes)

    def test_consistent_with_dis_module(self):
        """Test that results are consistent with dis module."""
        code_obj = self.test_functions['multi_line'].__code__
        result = parse_bytecode(code_obj)
        
        # Compare with dis.get_instructions
        dis_instructions = list(dis.get_instructions(code_obj))
        
        self.assertEqual(len(result), len(dis_instructions))
        
        for parsed, dis_instr in zip(result, dis_instructions):
            self.assertEqual(parsed['offset'], dis_instr.offset)
            self.assertEqual(parsed['opname'], dis_instr.opname)
            self.assertEqual(parsed['starts_line'], dis_instr.starts_line)
            self.assertEqual(parsed['is_jump_target'], dis_instr.is_jump_target)

    def test_invalid_input_handling(self):
        """Test handling of invalid inputs."""
        with self.assertRaises((TypeError, AttributeError)):
            parse_bytecode(None)
        
        with self.assertRaises((TypeError, AttributeError)):
            parse_bytecode("not a code object")
        
        with self.assertRaises((TypeError, AttributeError)):
            parse_bytecode(42)


if __name__ == '__main__':
    unittest.main()