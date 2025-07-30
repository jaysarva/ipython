"""Unit tests for line number calculation functionality."""

import unittest
from types import CodeType

from calculate_line_numbers import calculate_new_line_numbers


class TestCalculateNewLineNumbers(unittest.TestCase):
    """Test cases for calculate_new_line_numbers function."""

    def setUp(self):
        """Set up test fixtures with various instruction patterns."""
        # Mock instruction data for testing
        self.simple_instructions = [
            {'offset': 0, 'opname': 'LOAD_CONST', 'starts_line': 10, 'is_jump_target': False},
            {'offset': 2, 'opname': 'RETURN_VALUE', 'starts_line': None, 'is_jump_target': False},
        ]
        
        self.multi_line_instructions = [
            {'offset': 0, 'opname': 'LOAD_CONST', 'starts_line': 10, 'is_jump_target': False},
            {'offset': 2, 'opname': 'STORE_NAME', 'starts_line': None, 'is_jump_target': False},
            {'offset': 4, 'opname': 'LOAD_CONST', 'starts_line': 11, 'is_jump_target': False},
            {'offset': 6, 'opname': 'STORE_NAME', 'starts_line': None, 'is_jump_target': False},
            {'offset': 8, 'opname': 'LOAD_NAME', 'starts_line': 12, 'is_jump_target': False},
            {'offset': 10, 'opname': 'LOAD_NAME', 'starts_line': None, 'is_jump_target': False},
            {'offset': 12, 'opname': 'BINARY_ADD', 'starts_line': None, 'is_jump_target': False},
            {'offset': 14, 'opname': 'RETURN_VALUE', 'starts_line': None, 'is_jump_target': False},
        ]
        
        self.control_flow_instructions = [
            {'offset': 0, 'opname': 'LOAD_FAST', 'starts_line': 10, 'is_jump_target': False},
            {'offset': 2, 'opname': 'LOAD_CONST', 'starts_line': None, 'is_jump_target': False},
            {'offset': 4, 'opname': 'COMPARE_OP', 'starts_line': None, 'is_jump_target': False},
            {'offset': 6, 'opname': 'POP_JUMP_IF_FALSE', 'starts_line': None, 'is_jump_target': False},
            {'offset': 8, 'opname': 'LOAD_FAST', 'starts_line': 11, 'is_jump_target': False},
            {'offset': 10, 'opname': 'LOAD_CONST', 'starts_line': None, 'is_jump_target': False},
            {'offset': 12, 'opname': 'BINARY_MULTIPLY', 'starts_line': None, 'is_jump_target': False},
            {'offset': 14, 'opname': 'RETURN_VALUE', 'starts_line': None, 'is_jump_target': False},
            {'offset': 16, 'opname': 'LOAD_FAST', 'starts_line': 13, 'is_jump_target': True},
            {'offset': 18, 'opname': 'LOAD_CONST', 'starts_line': None, 'is_jump_target': False},
            {'offset': 20, 'opname': 'BINARY_MULTIPLY', 'starts_line': None, 'is_jump_target': False},
            {'offset': 22, 'opname': 'RETURN_VALUE', 'starts_line': None, 'is_jump_target': False},
        ]
        
        self.gap_instructions = [
            {'offset': 0, 'opname': 'LOAD_CONST', 'starts_line': 10, 'is_jump_target': False},
            {'offset': 2, 'opname': 'STORE_NAME', 'starts_line': None, 'is_jump_target': False},
            {'offset': 4, 'opname': 'LOAD_CONST', 'starts_line': 15, 'is_jump_target': False},  # Gap from 10 to 15
            {'offset': 6, 'opname': 'RETURN_VALUE', 'starts_line': None, 'is_jump_target': False},
        ]

    def test_returns_dictionary(self):
        """Test that function returns a dictionary."""
        result = calculate_new_line_numbers(self.simple_instructions, 10, 20)
        self.assertIsInstance(result, dict)

    def test_simple_positive_offset(self):
        """Test line number calculation with positive offset."""
        result = calculate_new_line_numbers(self.simple_instructions, 10, 20)
        expected = {0: 20, 2: 20}  # Both instructions should be at line 20
        self.assertEqual(result, expected)

    def test_simple_negative_offset(self):
        """Test line number calculation with negative offset."""
        result = calculate_new_line_numbers(self.simple_instructions, 20, 10)
        expected = {0: 0, 2: 0}  # Both instructions should be at line 0 (10 + (10-20) = 0)
        self.assertEqual(result, expected)

    def test_zero_offset(self):
        """Test line number calculation with zero offset."""
        result = calculate_new_line_numbers(self.simple_instructions, 10, 10)
        expected = {0: 10, 2: 10}  # Both instructions should remain at line 10
        self.assertEqual(result, expected)

    def test_multi_line_positive_offset(self):
        """Test multi-line function with positive offset."""
        result = calculate_new_line_numbers(self.multi_line_instructions, 10, 15)
        expected = {
            0: 15,   # Line 10 -> 15
            2: 15,   # Same line as previous
            4: 16,   # Line 11 -> 16
            6: 16,   # Same line as previous
            8: 17,   # Line 12 -> 17
            10: 17,  # Same line as previous
            12: 17,  # Same line as previous
            14: 17,  # Same line as previous
        }
        self.assertEqual(result, expected)

    def test_multi_line_negative_offset(self):
        """Test multi-line function with negative offset."""
        result = calculate_new_line_numbers(self.multi_line_instructions, 15, 10)
        expected = {
            0: 5,    # Line 10 -> 5 (15 - 5 = 10, but original was 10, so 10 - 5 = 5)
            2: 5,    # Same line as previous
            4: 6,    # Line 11 -> 6
            6: 6,    # Same line as previous
            8: 7,    # Line 12 -> 7
            10: 7,   # Same line as previous
            12: 7,   # Same line as previous
            14: 7,   # Same line as previous
        }
        self.assertEqual(result, expected)

    def test_control_flow_with_jump_targets(self):
        """Test control flow function with jump targets."""
        result = calculate_new_line_numbers(self.control_flow_instructions, 10, 20)
        
        # Check that all offsets are mapped
        expected_offsets = {0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22}
        self.assertEqual(set(result.keys()), expected_offsets)
        
        # Check specific line mappings
        self.assertEqual(result[0], 20)   # Line 10 -> 20
        self.assertEqual(result[8], 21)   # Line 11 -> 21
        self.assertEqual(result[16], 23)  # Line 13 -> 23

    def test_instructions_with_gaps(self):
        """Test instructions with gaps in line numbers."""
        result = calculate_new_line_numbers(self.gap_instructions, 10, 30)
        expected = {
            0: 30,   # Line 10 -> 30
            2: 30,   # Same line as previous
            4: 35,   # Line 15 -> 35 (gap preserved)
            6: 35,   # Same line as previous
        }
        self.assertEqual(result, expected)

    def test_all_offsets_present(self):
        """Test that all instruction offsets are in the result."""
        instructions = self.multi_line_instructions
        result = calculate_new_line_numbers(instructions, 10, 20)
        
        expected_offsets = {instr['offset'] for instr in instructions}
        actual_offsets = set(result.keys())
        self.assertEqual(actual_offsets, expected_offsets)

    def test_line_number_consistency(self):
        """Test that consecutive instructions without starts_line have same line number."""
        result = calculate_new_line_numbers(self.multi_line_instructions, 10, 20)
        
        # Instructions at offsets 0 and 2 should have same line number
        self.assertEqual(result[0], result[2])
        # Instructions at offsets 4 and 6 should have same line number
        self.assertEqual(result[4], result[6])

    def test_large_positive_offset(self):
        """Test with large positive offset."""
        result = calculate_new_line_numbers(self.simple_instructions, 10, 1000)
        expected = {0: 1000, 2: 1000}
        self.assertEqual(result, expected)

    def test_large_negative_offset_resulting_in_negative_lines(self):
        """Test with large negative offset that could result in negative line numbers."""
        # This might be an edge case - negative line numbers aren't valid
        result = calculate_new_line_numbers(self.simple_instructions, 10, 1)
        expected = {0: 1, 2: 1}
        self.assertEqual(result, expected)

    def test_empty_instructions_list(self):
        """Test with empty instructions list."""
        result = calculate_new_line_numbers([], 10, 20)
        self.assertEqual(result, {})

    def test_single_instruction(self):
        """Test with single instruction."""
        single_instruction = [
            {'offset': 0, 'opname': 'RETURN_VALUE', 'starts_line': 5, 'is_jump_target': False}
        ]
        result = calculate_new_line_numbers(single_instruction, 5, 10)
        expected = {0: 10}
        self.assertEqual(result, expected)

    def test_instructions_with_none_starts_line_at_beginning(self):
        """Test instructions where first instruction has None starts_line."""
        problematic_instructions = [
            {'offset': 0, 'opname': 'LOAD_CONST', 'starts_line': None, 'is_jump_target': False},
            {'offset': 2, 'opname': 'RETURN_VALUE', 'starts_line': 10, 'is_jump_target': False},
        ]
        result = calculate_new_line_numbers(problematic_instructions, 10, 20)
        
        # First instruction should use old_firstlineno
        self.assertEqual(result[0], 20)  # Should be mapped to new_firstlineno
        self.assertEqual(result[2], 20)  # Line 10 -> 20

    def test_all_instructions_have_none_starts_line_except_first(self):
        """Test case where only first instruction has line number."""
        instructions = [
            {'offset': 0, 'opname': 'LOAD_CONST', 'starts_line': 10, 'is_jump_target': False},
            {'offset': 2, 'opname': 'STORE_NAME', 'starts_line': None, 'is_jump_target': False},
            {'offset': 4, 'opname': 'LOAD_CONST', 'starts_line': None, 'is_jump_target': False},
            {'offset': 6, 'opname': 'RETURN_VALUE', 'starts_line': None, 'is_jump_target': False},
        ]
        result = calculate_new_line_numbers(instructions, 10, 25)
        
        # All instructions should have the same line number
        expected = {0: 25, 2: 25, 4: 25, 6: 25}
        self.assertEqual(result, expected)

    def test_offset_zero_handling(self):
        """Test that offset 0 is handled correctly."""
        result = calculate_new_line_numbers(self.simple_instructions, 10, 20)
        self.assertIn(0, result)
        self.assertEqual(result[0], 20)

    def test_preserves_relative_line_differences(self):
        """Test that relative line number differences are preserved."""
        # Original lines: 10, 11, 12 -> New lines should be: 20, 21, 22
        result = calculate_new_line_numbers(self.multi_line_instructions, 10, 20)
        
        # Find instructions that start new lines
        line_10_instr = result[0]  # First instruction at line 10
        line_11_instr = result[4]  # First instruction at line 11
        line_12_instr = result[8]  # First instruction at line 12
        
        self.assertEqual(line_10_instr, 20)
        self.assertEqual(line_11_instr, 21)
        self.assertEqual(line_12_instr, 22)

    def test_invalid_input_types(self):
        """Test handling of invalid input types."""
        with self.assertRaises(TypeError):
            calculate_new_line_numbers(None, 10, 20)
        
        with self.assertRaises(TypeError):
            calculate_new_line_numbers(self.simple_instructions, "10", 20)
        
        with self.assertRaises(TypeError):
            calculate_new_line_numbers(self.simple_instructions, 10, "20")

    def test_instructions_missing_required_fields(self):
        """Test handling of instructions missing required fields."""
        bad_instructions = [
            {'offset': 0, 'opname': 'LOAD_CONST'},  # Missing starts_line
        ]
        
        with self.assertRaises(KeyError):
            calculate_new_line_numbers(bad_instructions, 10, 20)


if __name__ == '__main__':
    unittest.main()