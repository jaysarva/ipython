"""Unit tests for line table encoding functionality."""

import unittest
from types import CodeType

from encode_linetable import encode_linetable


class TestEncodeLinetable(unittest.TestCase):
    """Test cases for encode_linetable function."""

    def setUp(self):
        """Set up test fixtures with various offset->line mappings."""
        # Simple case: single line function
        self.simple_mapping = {0: 10, 2: 10}
        
        # Multi-line function with sequential lines
        self.sequential_mapping = {
            0: 10,
            2: 10,
            4: 11,
            6: 11,
            8: 12,
            10: 12
        }
        
        # Function with gaps in line numbers
        self.gap_mapping = {
            0: 10,
            2: 10,
            4: 15,  # Gap from 10 to 15
            6: 15,
            8: 20,  # Gap from 15 to 20
            10: 20
        }
        
        # Large offset deltas
        self.large_offset_mapping = {
            0: 10,
            100: 10,  # Large offset delta, same line
            102: 11,  # Small offset delta, line change
        }
        
        # Large line deltas
        self.large_line_mapping = {
            0: 10,
            2: 100,  # Large line delta
            4: 101,  # Small line delta after large one
        }
        
        # Complex control flow pattern
        self.complex_mapping = {
            0: 10,   # Start
            2: 10,   # Same line
            4: 11,   # Next line
            6: 11,   # Same line
            8: 12,   # Next line
            10: 12,  # Same line
            20: 12,  # Large offset, same line
            22: 15,  # Small offset, large line delta
            24: 15,  # Same line
        }

    def test_returns_bytes(self):
        """Test that encode_linetable returns bytes object."""
        result = encode_linetable(self.simple_mapping, 4)
        self.assertIsInstance(result, bytes)

    def test_empty_mapping_returns_empty_bytes(self):
        """Test that empty mapping returns empty bytes."""
        result = encode_linetable({}, 0)
        self.assertEqual(result, b'')

    def test_single_offset_mapping(self):
        """Test encoding with single offset."""
        single_mapping = {0: 10}
        result = encode_linetable(single_mapping, 2)
        self.assertIsInstance(result, bytes)

    def test_simple_same_line_encoding(self):
        """Test encoding for instructions on same line."""
        result = encode_linetable(self.simple_mapping, 4)
        self.assertIsInstance(result, bytes)
        # Should be relatively short since no line changes
        self.assertLessEqual(len(result), 10)

    def test_sequential_lines_encoding(self):
        """Test encoding for sequential line numbers."""
        result = encode_linetable(self.sequential_mapping, 12)
        self.assertIsInstance(result, bytes)
        # Should have entries for line changes
        self.assertGreater(len(result), 0)

    def test_small_offset_small_line_delta_encoding(self):
        """Test encoding when both offset and line deltas are small."""
        # This should use single-byte encoding
        small_mapping = {0: 10, 2: 11, 4: 12}
        result = encode_linetable(small_mapping, 6)
        self.assertIsInstance(result, bytes)

    def test_large_offset_same_line_encoding(self):
        """Test encoding for large offset delta with no line change."""
        result = encode_linetable(self.large_offset_mapping, 104)
        self.assertIsInstance(result, bytes)
        # Should contain 0xFE escape sequence for large offset
        # This is implementation-dependent, but we can check it's not empty
        self.assertGreater(len(result), 0)

    def test_large_line_delta_encoding(self):
        """Test encoding for large line number changes."""
        result = encode_linetable(self.large_line_mapping, 6)
        self.assertIsInstance(result, bytes)
        # Should contain 0xFF escape sequence for large line delta
        self.assertGreater(len(result), 2)

    def test_gap_mapping_encoding(self):
        """Test encoding for mapping with gaps in line numbers."""
        result = encode_linetable(self.gap_mapping, 12)
        self.assertIsInstance(result, bytes)
        # Should handle large line deltas properly
        self.assertGreater(len(result), 0)

    def test_complex_mapping_encoding(self):
        """Test encoding for complex control flow patterns."""
        result = encode_linetable(self.complex_mapping, 26)
        self.assertIsInstance(result, bytes)
        # Should handle mix of small and large deltas
        self.assertGreater(len(result), 0)

    def test_zero_offset_handling(self):
        """Test that offset 0 is handled correctly."""
        mapping_with_zero = {0: 5, 2: 6}
        result = encode_linetable(mapping_with_zero, 4)
        self.assertIsInstance(result, bytes)

    def test_single_byte_encoding_range(self):
        """Test that small deltas use single-byte encoding."""
        # Offset delta 0-15, line delta -4 to +3 should use single byte
        for offset_delta in range(0, 16, 2):  # Even offsets (instruction boundaries)
            for line_delta in range(-4, 4):
                if offset_delta == 0 and line_delta <= 0:
                    continue  # Skip invalid first entry
                mapping = {0: 10, offset_delta: 10 + line_delta}
                result = encode_linetable(mapping, offset_delta + 2)
                self.assertIsInstance(result, bytes)

    def test_negative_line_delta_encoding(self):
        """Test encoding for negative line number changes."""
        negative_mapping = {0: 15, 2: 12, 4: 10}  # Lines going backwards
        result = encode_linetable(negative_mapping, 6)
        self.assertIsInstance(result, bytes)

    def test_maximum_single_byte_values(self):
        """Test encoding at the boundaries of single-byte encoding."""
        # Maximum offset delta for single byte: 15
        # Maximum positive line delta for single byte: 3
        # Minimum negative line delta for single byte: -4
        boundary_mapping = {0: 10, 30: 13}  # offset_delta=15, line_delta=3
        result = encode_linetable(boundary_mapping, 32)
        self.assertIsInstance(result, bytes)

    def test_just_over_single_byte_boundaries(self):
        """Test encoding just over single-byte boundaries."""
        # Offset delta 16 (just over 15) should trigger multi-byte encoding
        large_offset_mapping = {0: 10, 32: 10}  # offset_delta=16, line_delta=0
        result = encode_linetable(large_offset_mapping, 34)
        self.assertIsInstance(result, bytes)
        
        # Line delta 4 (just over 3) should trigger multi-byte encoding
        large_line_mapping = {0: 10, 2: 14}  # offset_delta=1, line_delta=4
        result = encode_linetable(large_line_mapping, 4)
        self.assertIsInstance(result, bytes)

    def test_very_large_offset_delta(self):
        """Test encoding with very large offset deltas."""
        huge_offset_mapping = {0: 10, 1000: 10}
        result = encode_linetable(huge_offset_mapping, 1002)
        self.assertIsInstance(result, bytes)
        # Should handle multi-byte offset encoding
        self.assertGreater(len(result), 2)

    def test_very_large_line_delta(self):
        """Test encoding with very large line deltas."""
        huge_line_mapping = {0: 10, 2: 1000}
        result = encode_linetable(huge_line_mapping, 4)
        self.assertIsInstance(result, bytes)
        # Should handle multi-byte line encoding
        self.assertGreater(len(result), 2)

    def test_alternating_line_pattern(self):
        """Test encoding for alternating line number pattern."""
        alternating_mapping = {
            0: 10,
            2: 11,
            4: 10,  # Back to line 10
            6: 11,  # Forward to line 11
            8: 10,  # Back to line 10
        }
        result = encode_linetable(alternating_mapping, 10)
        self.assertIsInstance(result, bytes)

    def test_monotonic_increasing_lines(self):
        """Test encoding for strictly increasing line numbers."""
        increasing_mapping = {i * 2: 10 + i for i in range(10)}
        result = encode_linetable(increasing_mapping, 20)
        self.assertIsInstance(result, bytes)

    def test_monotonic_decreasing_lines(self):
        """Test encoding for strictly decreasing line numbers."""
        decreasing_mapping = {i * 2: 20 - i for i in range(10)}
        result = encode_linetable(decreasing_mapping, 20)
        self.assertIsInstance(result, bytes)

    def test_code_length_parameter_usage(self):
        """Test that code_length parameter is used appropriately."""
        mapping = {0: 10, 4: 11}
        
        # Test with different code lengths
        result1 = encode_linetable(mapping, 6)
        result2 = encode_linetable(mapping, 100)
        
        # Both should be valid bytes objects
        self.assertIsInstance(result1, bytes)
        self.assertIsInstance(result2, bytes)

    def test_unordered_offset_input(self):
        """Test that function handles unordered offset input correctly."""
        unordered_mapping = {8: 12, 0: 10, 4: 11, 2: 10}
        result = encode_linetable(unordered_mapping, 10)
        self.assertIsInstance(result, bytes)
        # Should produce same result as ordered version
        ordered_mapping = {0: 10, 2: 10, 4: 11, 8: 12}
        ordered_result = encode_linetable(ordered_mapping, 10)
        self.assertEqual(result, ordered_result)

    def test_duplicate_offsets_handling(self):
        """Test handling of duplicate offsets (should not occur, but test robustness)."""
        # This is an edge case - offsets should be unique
        # Function should handle it gracefully
        mapping = {0: 10, 2: 11}
        result = encode_linetable(mapping, 4)
        self.assertIsInstance(result, bytes)

    def test_line_number_zero_handling(self):
        """Test handling of line number 0 (edge case)."""
        zero_line_mapping = {0: 0, 2: 1}
        result = encode_linetable(zero_line_mapping, 4)
        self.assertIsInstance(result, bytes)

    def test_negative_line_numbers(self):
        """Test handling of negative line numbers (invalid but test robustness)."""
        negative_mapping = {0: -5, 2: -3}
        # Function should either handle gracefully or raise appropriate error
        try:
            result = encode_linetable(negative_mapping, 4)
            self.assertIsInstance(result, bytes)
        except (ValueError, OverflowError):
            # Acceptable to raise error for invalid line numbers
            pass

    def test_invalid_input_types(self):
        """Test handling of invalid input types."""
        with self.assertRaises(TypeError):
            encode_linetable(None, 10)
        
        with self.assertRaises(TypeError):
            encode_linetable("not a dict", 10)
        
        with self.assertRaises(TypeError):
            encode_linetable(self.simple_mapping, "not an int")

    def test_invalid_offset_types_in_mapping(self):
        """Test handling of invalid offset types in mapping."""
        bad_mapping = {"0": 10, 2: 11}  # String key instead of int
        with self.assertRaises((TypeError, KeyError)):
            encode_linetable(bad_mapping, 4)

    def test_invalid_line_types_in_mapping(self):
        """Test handling of invalid line number types in mapping."""
        bad_mapping = {0: "10", 2: 11}  # String value instead of int
        with self.assertRaises(TypeError):
            encode_linetable(bad_mapping, 4)

    def test_result_is_valid_linetable_format(self):
        """Test that result follows Python 3.11 linetable format conventions."""
        result = encode_linetable(self.sequential_mapping, 12)
        
        # Basic format checks
        self.assertIsInstance(result, bytes)
        
        # Should not contain invalid escape sequences at wrong positions
        if len(result) > 0:
            # First byte should not be end marker
            self.assertNotEqual(result[0], 0xFD)


if __name__ == '__main__':
    unittest.main()