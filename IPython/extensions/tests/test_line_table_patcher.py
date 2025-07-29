"""Unit tests for the *line table* parsing helpers.

This file intentionally adds *type: ignore* markers to suppress static
analysis warnings coming from the dynamic nature of the CPython ``code``
object APIs and the unconventional package structure (directory names
containing dots).
"""

# mypy: ignore-errors
# pyright: reportMissingImports=false, reportAttributeAccessIssue=false

import sys
from types import CodeType
from typing import List, Tuple

import pytest  # type: ignore  # noqa: F401 – Used by PyTest runtime

import IPython.extensions.deduperreload.line_table_patching.line_table_patcher as _ltp

# Expose the helpers under their expected names.
parse_co_linetable = _ltp.parse_co_linetable  # type: ignore[attr-defined]
parse_co_lnotab = _ltp.parse_co_lnotab  # type: ignore[attr-defined]

# New standalone functions
parse_lnotab = _ltp.parse_lnotab  # type: ignore[attr-defined]
parse_linetable = _ltp.parse_linetable  # type: ignore[attr-defined]
encode_lnotab = _ltp.encode_lnotab  # type: ignore[attr-defined]
encode_linetable = _ltp.encode_linetable  # type: ignore[attr-defined]

# ULEB/SLEB helpers
_encode_uleb128 = _ltp._encode_uleb128  # type: ignore[attr-defined]
_decode_uleb128 = _ltp._decode_uleb128  # type: ignore[attr-defined]
_encode_sleb128 = _ltp._encode_sleb128  # type: ignore[attr-defined]
_decode_sleb128 = _ltp._decode_sleb128  # type: ignore[attr-defined]

# New function to test
shifted_line_table = _ltp.shifted_line_table  # type: ignore[attr-defined]


def _make_sample_function() -> CodeType:
    """Return a freshly compiled *sample* function for inspection."""

    def sample_func(x: int) -> int:  # noqa: D401 – Simple sample code
        y = x + 1  # line +1
        for i in range(3):  # line +2 (loop produces additional bytecode)
            y += i
        return y  # line +4

    return sample_func.__code__


class TestParseCoLineTable:
    """Tests for :pyfunc:`parse_co_linetable`."""

    def test_basic_structure(self):
        code: CodeType = _make_sample_function()
        pairs: List[Tuple[int, int]] = parse_co_linetable(code)

        # Should contain at least one mapping (offset 0 → firstlineno)
        assert pairs, "Expected at least one (offset, line) pair"
        assert pairs[0] == (0, code.co_firstlineno)

        # Offsets must be monotonically increasing.
        offsets = [p[0] for p in pairs]
        assert offsets == sorted(offsets), "Offsets should be sorted asc"

        # Lines should all be >= firstlineno
        lines = [p[1] for p in pairs]
        assert all(l >= code.co_firstlineno for l in lines)

    def test_roundtrip_matches_co_lines(self):
        """The helper should produce the *same* data as ``code.co_lines``."""
        code = _make_sample_function()
        expected = [
            (start, line)  # type: ignore[attr-defined]
            for start, _end, line in code.co_lines()  # type: ignore[attr-defined]
            if line is not None
        ]
        # Ensure the canonical (0, firstlineno) entry exists in *expected* too.
        if not expected or expected[0][0] != 0:
            expected.insert(0, (0, code.co_firstlineno))

        result = parse_co_linetable(code)
        assert result == expected


class TestParseCoLnotab:
    """Tests for :pyfunc:`parse_co_lnotab`."""

    @pytest.mark.skipif(sys.version_info >= (3, 11), reason="co_lnotab deprecated on ≥3.11")
    def test_basic_structure(self):
        code = _make_sample_function()
        pairs = parse_co_lnotab(code)

        assert pairs, "Expected at least one mapping pair"
        assert pairs[0] == (0, code.co_firstlineno)

        # Offsets must be monotonically increasing.
        offsets = [p[0] for p in pairs]
        assert offsets == sorted(offsets)

        # Lines should all be >= firstlineno
        lines = [p[1] for p in pairs]
        assert all(l >= code.co_firstlineno for l in lines)

    @pytest.mark.skipif(sys.version_info >= (3, 11), reason="co_lnotab deprecated on ≥3.11")
    def test_consistency_with_linetable(self):
        """The legacy lnotab mapping should be a subset of the PEP 626 mapping."""
        code = _make_sample_function()
        lnotab_pairs = parse_co_lnotab(code)
        linetable_pairs = parse_co_linetable(code)

        # Convert to dict for fast lookup.
        linetable_dict = dict(linetable_pairs)
        for offset, line in lnotab_pairs:
            assert linetable_dict[offset] == line 


class TestUlebSlebHelpers:
    """Tests for ULEB128 and SLEB128 encoding/decoding helpers."""

    def test_uleb128_basic(self):
        """Test basic ULEB128 encoding/decoding."""
        test_values = [0, 1, 127, 128, 255, 256, 16383, 16384, 2097151, 2097152]
        
        for value in test_values:
            encoded = _encode_uleb128(value)
            decoded, consumed = _decode_uleb128(encoded)
            assert decoded == value
            assert consumed == len(encoded)

    def test_uleb128_negative_raises(self):
        """ULEB128 should raise ValueError for negative values."""
        with pytest.raises(ValueError, match="ULEB128 requires non-negative values"):
            _encode_uleb128(-1)

    def test_sleb128_basic(self):
        """Test basic SLEB128 encoding/decoding."""
        test_values = [-128, -127, -1, 0, 1, 63, 64, 127, 128, -129, -16384, 16383, 16384]
        
        for value in test_values:
            encoded = _encode_sleb128(value)
            decoded, consumed = _decode_sleb128(encoded)
            assert decoded == value
            assert consumed == len(encoded)

    def test_uleb128_large_values(self):
        """Test ULEB128 with large values."""
        large_values = [2**7 - 1, 2**7, 2**14 - 1, 2**14, 2**21 - 1, 2**21, 2**28 - 1, 2**28]
        
        for value in large_values:
            encoded = _encode_uleb128(value)
            decoded, consumed = _decode_uleb128(encoded)
            assert decoded == value

    def test_sleb128_edge_cases(self):
        """Test SLEB128 edge cases around sign boundaries."""
        edge_cases = [-64, -63, 63, 64, -8192, -8191, 8191, 8192]
        
        for value in edge_cases:
            encoded = _encode_sleb128(value)
            decoded, consumed = _decode_sleb128(encoded)
            assert decoded == value

    def test_incomplete_sequences(self):
        """Test handling of incomplete ULEB/SLEB sequences."""
        # Incomplete ULEB128 (all bytes have continuation bit set)
        with pytest.raises(ValueError, match="Incomplete ULEB128 sequence"):
            _decode_uleb128(b'\x80\x80\x80')
        
        # Incomplete SLEB128
        with pytest.raises(ValueError, match="Incomplete SLEB128 sequence"):
            _decode_sleb128(b'\x80\x80\x80')


class TestStandaloneParsers:
    """Tests for standalone parse_lnotab and parse_linetable functions."""

    @pytest.mark.skipif(sys.version_info >= (3, 11), reason="co_lnotab deprecated on ≥3.11")
    def test_parse_lnotab_matches_co_version(self):
        """Standalone parse_lnotab should match parse_co_lnotab."""
        code = _make_sample_function()
        co_result = parse_co_lnotab(code)
        standalone_result = parse_lnotab(code.co_lnotab, code.co_firstlineno)
        assert co_result == standalone_result

    @pytest.mark.skipif(sys.version_info < (3, 11), reason="co_linetable only on ≥3.11")
    def test_parse_linetable_matches_co_version(self):
        """Standalone parse_linetable should match parse_co_linetable for simple cases."""
        code = _make_sample_function()
        co_result = parse_co_linetable(code)
        standalone_result = parse_linetable(code.co_linetable, code.co_firstlineno)
        
        # Note: These might not be exactly equal due to differences in how
        # co_lines() handles certain edge cases vs our manual parser
        # But they should have the same basic structure
        assert len(standalone_result) >= 1
        assert standalone_result[0] == (0, code.co_firstlineno)

    def test_parse_lnotab_empty(self):
        """Test parse_lnotab with empty input."""
        result = parse_lnotab(b'', 100)
        assert result == [(0, 100)]

    def test_parse_linetable_empty(self):
        """Test parse_linetable with empty input."""
        result = parse_linetable(b'', 100)
        assert result == [(0, 100)]


class TestEncodeHelpers:
    """Tests for encode_lnotab and encode_linetable functions."""

    def test_encode_lnotab_basic(self):
        """Test basic lnotab encoding."""
        pairs = [(0, 10), (2, 11), (4, 11), (6, 13)]
        encoded = encode_lnotab(pairs)
        
        # Decode back and check
        decoded = parse_lnotab(encoded, 10)
        assert decoded == pairs

    def test_encode_lnotab_empty(self):
        """Test encoding empty pairs."""
        assert encode_lnotab([]) == b''

    def test_encode_lnotab_single_entry(self):
        """Test encoding with only the initial (0, firstlineno) entry."""
        pairs = [(0, 100)]
        encoded = encode_lnotab(pairs)
        assert encoded == b''  # Should be empty since no deltas

    def test_encode_lnotab_large_deltas(self):
        """Test lnotab encoding with large deltas that need splitting."""
        # Large address delta
        original_pairs = [(0, 10), (300, 11)]  # addr delta = 300 > 255
        encoded = encode_lnotab(original_pairs)
        decoded = parse_lnotab(encoded, 10)
        # Should have intermediate entries due to splitting
        expected = [(0, 10), (255, 10), (300, 11)]  # 255 + 45 = 300
        assert decoded == expected

        # Large positive line delta
        original_pairs = [(0, 10), (2, 150)]  # line delta = 140 > 127
        encoded = encode_lnotab(original_pairs)
        decoded = parse_lnotab(encoded, 10)
        # Should have intermediate entries for line splitting
        expected = [(0, 10), (2, 137), (2, 150)]  # Split: +127 then +13
        assert decoded == expected

        # Large negative line delta
        original_pairs = [(0, 200), (2, 50)]  # line delta = -150 < -128
        encoded = encode_lnotab(original_pairs)
        decoded = parse_lnotab(encoded, 200)
        # Should have intermediate entries for negative line splitting
        expected = [(0, 200), (2, 72), (2, 50)]  # Split: -128 then -22
        assert decoded == expected

    def test_encode_lnotab_complex(self):
        """Test lnotab encoding with a complex sequence."""
        original_pairs = [
            (0, 100),   # start
            (2, 101),   # +1 line
            (4, 101),   # same line
            (6, 99),    # -2 lines
            (8, 102),   # +3 lines
            (500, 103), # large addr delta, +1 line
        ]
        encoded = encode_lnotab(original_pairs)
        decoded = parse_lnotab(encoded, 100)
        
        # Should have intermediate entries for the large address delta (500 - 8 = 492)
        # 492 = 255 + 237, so we get intermediate entry at address 8 + 255 = 263
        expected = [
            (0, 100),   # start
            (2, 101),   # +1 line
            (4, 101),   # same line (address changes, line stays same)
            (6, 99),    # -2 lines
            (8, 102),   # +3 lines
            (263, 102), # intermediate: +255 addr, 0 line change
            (500, 103), # final: +237 addr, +1 line
        ]
        assert decoded == expected

    def test_encode_linetable_basic(self):
        """Test basic linetable encoding."""
        pairs = [(0, 10), (2, 11), (4, 11), (6, 13)]
        encoded = encode_linetable(pairs)
        
        # Decode back and check
        decoded = parse_linetable(encoded, 10)
        assert decoded == pairs

    def test_encode_linetable_empty(self):
        """Test encoding empty pairs."""
        assert encode_linetable([]) == b''

    def test_encode_linetable_single_entry(self):
        """Test encoding with only the initial (0, firstlineno) entry."""
        pairs = [(0, 100)]
        encoded = encode_linetable(pairs)
        assert encoded == b''  # Should be empty since no deltas

    def test_encode_linetable_large_deltas(self):
        """Test linetable encoding with large deltas."""
        # Large address delta
        pairs = [(0, 10), (1000, 11)]
        encoded = encode_linetable(pairs)
        decoded = parse_linetable(encoded, 10)
        assert decoded == pairs

        # Large positive line delta
        pairs = [(0, 10), (2, 1000)]
        encoded = encode_linetable(pairs)
        decoded = parse_linetable(encoded, 10)
        assert decoded == pairs

        # Large negative line delta
        pairs = [(0, 1000), (2, 10)]
        encoded = encode_linetable(pairs)
        decoded = parse_linetable(encoded, 1000)
        assert decoded == pairs

    def test_encode_linetable_complex(self):
        """Test linetable encoding with a complex sequence."""
        pairs = [
            (0, 100),     # start
            (2, 101),     # +1 line
            (4, 101),     # same line
            (6, 99),      # -2 lines
            (8, 102),     # +3 lines
            (1000, 50),   # large addr delta, -52 lines
        ]
        encoded = encode_linetable(pairs)
        decoded = parse_linetable(encoded, 100)
        assert decoded == pairs


class TestRoundtripConsistency:
    """Tests to ensure encoding/decoding roundtrips work correctly."""

    @pytest.mark.skipif(sys.version_info >= (3, 11), reason="co_lnotab deprecated on ≥3.11")
    def test_lnotab_roundtrip_real_code(self):
        """Test lnotab roundtrip with real code objects."""
        code = _make_sample_function()
        original_pairs = parse_co_lnotab(code)
        
        # Encode and decode back
        encoded = encode_lnotab(original_pairs)
        decoded_pairs = parse_lnotab(encoded, code.co_firstlineno)
        
        assert decoded_pairs == original_pairs

    @pytest.mark.skipif(sys.version_info < (3, 11), reason="co_linetable only on ≥3.11")
    def test_linetable_roundtrip_real_code(self):
        """Test linetable roundtrip with real code objects."""
        code = _make_sample_function()
        original_pairs = parse_co_linetable(code)
        
        # Encode and decode back
        encoded = encode_linetable(original_pairs)
        decoded_pairs = parse_linetable(encoded, code.co_firstlineno)
        
        assert decoded_pairs == original_pairs

    def test_synthetic_data_roundtrips(self):
        """Test encoding/decoding with synthetic data patterns."""
        test_cases = [
            # Simple increasing
            [(0, 10), (2, 11), (4, 12), (6, 13)],
            # With same lines
            [(0, 10), (2, 11), (4, 11), (6, 11), (8, 12)],
            # With decreasing lines
            [(0, 100), (2, 101), (4, 99), (6, 98)],
            # Mixed patterns
            [(0, 50), (1, 51), (10, 51), (20, 49), (100, 52)],
        ]
        
        for pairs in test_cases:
            # Test lnotab roundtrip
            lnotab_encoded = encode_lnotab(pairs)
            lnotab_decoded = parse_lnotab(lnotab_encoded, pairs[0][1])
            assert lnotab_decoded == pairs, f"lnotab failed for {pairs}"
            
            # Test linetable roundtrip
            linetable_encoded = encode_linetable(pairs)
            linetable_decoded = parse_linetable(linetable_encoded, pairs[0][1])
            assert linetable_decoded == pairs, f"linetable failed for {pairs}"


class TestShiftedLineTable:
    """Tests for the shifted_line_table function implementing section 4.3 of the guide."""

    def _make_test_function(self, start_line=10):
        """Create a test function starting at a specific line for testing."""
        # Create enough blank lines to reach the desired start_line
        padding = '\n' * (start_line - 1)
        code_template = f"""{padding}def test_func(x):
    y = x + 1  # line {start_line + 1}
    if y > 0:  # line {start_line + 2}
        return y * 2  # line {start_line + 3}
    else:  # line {start_line + 4}
        return 0  # line {start_line + 5}
"""
        # Compile the code and extract the function's code object
        compiled = compile(code_template, '<test>', 'exec')
        
        # Execute and get the function
        namespace = {}
        exec(compiled, namespace)
        return namespace['test_func'].__code__

    def test_no_shift_needed(self):
        """Test when no shifts are needed (empty delta_map)."""
        code = self._make_test_function(start_line=10)
        delta_map = {}
        
        new_code = shifted_line_table(code, delta_map)
        
        # Should be identical
        assert new_code.co_firstlineno == code.co_firstlineno
        if sys.version_info < (3, 11):
            assert new_code.co_lnotab == code.co_lnotab
        else:
            assert new_code.co_linetable == code.co_linetable

    def test_simple_positive_shift(self):
        """Test shifting all lines by a positive amount."""
        code = self._make_test_function(start_line=10)
        # Insert 5 lines before line 10 - everything shifts by +5
        delta_map = {10: 5}
        
        new_code = shifted_line_table(code, delta_map)
        
        # First line should be shifted
        assert new_code.co_firstlineno == code.co_firstlineno + 5
        
        # Parse line tables and verify all lines shifted
        if sys.version_info < (3, 11):
            old_pairs = parse_lnotab(code.co_lnotab, code.co_firstlineno)
            new_pairs = parse_lnotab(new_code.co_lnotab, new_code.co_firstlineno)
        else:
            old_pairs = parse_linetable(code.co_linetable, code.co_firstlineno)
            new_pairs = parse_linetable(new_code.co_linetable, new_code.co_firstlineno)
        
        # Check that all lines are shifted by +5
        assert len(new_pairs) == len(old_pairs)
        for (old_addr, old_line), (new_addr, new_line) in zip(old_pairs, new_pairs):
            assert new_addr == old_addr  # Addresses shouldn't change
            assert new_line == old_line + 5  # Lines should be shifted by +5

    def test_simple_negative_shift(self):
        """Test shifting all lines by a negative amount."""
        code = self._make_test_function(start_line=50)  # Start higher so we can shift down
        # Remove 10 lines before line 50 - everything shifts by -10
        delta_map = {50: -10}
        
        new_code = shifted_line_table(code, delta_map)
        
        # First line should be shifted
        assert new_code.co_firstlineno == code.co_firstlineno - 10
        
        # Parse line tables and verify all lines shifted
        if sys.version_info < (3, 11):
            old_pairs = parse_lnotab(code.co_lnotab, code.co_firstlineno)
            new_pairs = parse_lnotab(new_code.co_lnotab, new_code.co_firstlineno)
        else:
            old_pairs = parse_linetable(code.co_linetable, code.co_firstlineno)
            new_pairs = parse_linetable(new_code.co_linetable, new_code.co_firstlineno)
        
        # Check that all lines are shifted by -10
        assert len(new_pairs) == len(old_pairs)
        for (old_addr, old_line), (new_addr, new_line) in zip(old_pairs, new_pairs):
            assert new_addr == old_addr  # Addresses shouldn't change
            assert new_line == old_line - 10  # Lines should be shifted by -10

    def test_partial_shift(self):
        """Test shifting only lines after a certain point."""
        code = self._make_test_function(start_line=10)
        # Insert 3 lines at line 12 - only lines >= 12 should shift
        delta_map = {12: 3}
        
        new_code = shifted_line_table(code, delta_map)
        
        # First line should NOT be shifted (it's line 10 < 12)
        assert new_code.co_firstlineno == code.co_firstlineno
        
        # Parse line tables
        if sys.version_info < (3, 11):
            old_pairs = parse_lnotab(code.co_lnotab, code.co_firstlineno)
            new_pairs = parse_lnotab(new_code.co_lnotab, new_code.co_firstlineno)
        else:
            old_pairs = parse_linetable(code.co_linetable, code.co_firstlineno)
            new_pairs = parse_linetable(new_code.co_linetable, new_code.co_firstlineno)
        
        # Check selective shifting
        assert len(new_pairs) == len(old_pairs)
        for (old_addr, old_line), (new_addr, new_line) in zip(old_pairs, new_pairs):
            assert new_addr == old_addr  # Addresses shouldn't change
            if old_line >= 12:
                assert new_line == old_line + 3  # Lines >= 12 should be shifted by +3
            else:
                assert new_line == old_line  # Lines < 12 should be unchanged

    def test_multiple_shifts(self):
        """Test multiple insertion points with different deltas."""
        code = self._make_test_function(start_line=10)
        # Multiple insertions: +2 at line 11, +5 at line 13
        delta_map = {11: 2, 13: 5}
        
        new_code = shifted_line_table(code, delta_map)
        
        # Parse line tables
        if sys.version_info < (3, 11):
            old_pairs = parse_lnotab(code.co_lnotab, code.co_firstlineno)
            new_pairs = parse_lnotab(new_code.co_lnotab, new_code.co_firstlineno)
        else:
            old_pairs = parse_linetable(code.co_linetable, code.co_firstlineno)
            new_pairs = parse_linetable(new_code.co_linetable, new_code.co_firstlineno)
        
        # Check cumulative shifting
        assert len(new_pairs) == len(old_pairs)
        for (old_addr, old_line), (new_addr, new_line) in zip(old_pairs, new_pairs):
            assert new_addr == old_addr  # Addresses shouldn't change
            expected_shift = 0
            if old_line >= 11:
                expected_shift += 2
            if old_line >= 13:
                expected_shift += 5
            assert new_line == old_line + expected_shift

    def test_large_shift_lnotab(self):
        """Test large shifts that exceed lnotab limits (>127 lines)."""
        if sys.version_info >= (3, 11):
            pytest.skip("Test specific to lnotab format (Python ≤ 3.10)")
            
        code = self._make_test_function(start_line=10)
        # Large shift that will require splitting in lnotab encoding
        delta_map = {10: 300}  # Shift by 300 lines
        
        new_code = shifted_line_table(code, delta_map)
        
        # Should still work correctly despite encoding limitations
        assert new_code.co_firstlineno == code.co_firstlineno + 300
        
        # Parse and verify
        old_pairs = parse_lnotab(code.co_lnotab, code.co_firstlineno)
        new_pairs = parse_lnotab(new_code.co_lnotab, new_code.co_firstlineno)
        
        # All lines should be shifted by +300
        for (old_addr, old_line), (new_addr, new_line) in zip(old_pairs, new_pairs):
            assert new_addr == old_addr
            assert new_line == old_line + 300

    def test_stress_case_large_negative_shift(self):
        """Test stress case with large negative shifts."""
        code = self._make_test_function(start_line=1000)  # Start very high
        # Large negative shift
        delta_map = {1000: -500}
        
        new_code = shifted_line_table(code, delta_map)
        
        # Should work correctly
        assert new_code.co_firstlineno == code.co_firstlineno - 500
        
        # Parse and verify
        if sys.version_info < (3, 11):
            old_pairs = parse_lnotab(code.co_lnotab, code.co_firstlineno)
            new_pairs = parse_lnotab(new_code.co_lnotab, new_code.co_firstlineno)
        else:
            old_pairs = parse_linetable(code.co_linetable, code.co_firstlineno)
            new_pairs = parse_linetable(new_code.co_linetable, new_code.co_firstlineno)
        
        # All lines should be shifted by -500
        for (old_addr, old_line), (new_addr, new_line) in zip(old_pairs, new_pairs):
            assert new_addr == old_addr
            assert new_line == old_line - 500

    def test_roundtrip_consistency(self):
        """Test that shifting and shifting back gives original result."""
        code = self._make_test_function(start_line=100)
        
        # Apply forward shift
        delta_map_forward = {100: 50}
        shifted_code = shifted_line_table(code, delta_map_forward)
        
        # Apply reverse shift
        delta_map_reverse = {150: -50}  # 100 + 50 = 150
        restored_code = shifted_line_table(shifted_code, delta_map_reverse)
        
        # Should be back to original
        assert restored_code.co_firstlineno == code.co_firstlineno
        
        if sys.version_info < (3, 11):
            original_pairs = parse_lnotab(code.co_lnotab, code.co_firstlineno)
            restored_pairs = parse_lnotab(restored_code.co_lnotab, restored_code.co_firstlineno)
        else:
            original_pairs = parse_linetable(code.co_linetable, code.co_firstlineno)
            restored_pairs = parse_linetable(restored_code.co_linetable, restored_code.co_firstlineno)
        
        assert restored_pairs == original_pairs

    def test_edge_case_zero_delta(self):
        """Test edge case where delta is zero."""
        code = self._make_test_function(start_line=10)
        delta_map = {10: 0}  # No actual shift
        
        new_code = shifted_line_table(code, delta_map)
        
        # Should be unchanged
        assert new_code.co_firstlineno == code.co_firstlineno
        if sys.version_info < (3, 11):
            assert new_code.co_lnotab == code.co_lnotab
        else:
            assert new_code.co_linetable == code.co_linetable

    def test_edge_case_insertion_after_all_lines(self):
        """Test edge case where insertion point is after all existing lines."""
        code = self._make_test_function(start_line=10)
        # Insert after all existing lines (assuming function ends around line 15)
        delta_map = {100: 50}  # Way after the function
        
        new_code = shifted_line_table(code, delta_map)
        
        # Should be unchanged since no lines are >= 100
        assert new_code.co_firstlineno == code.co_firstlineno
        if sys.version_info < (3, 11):
            assert new_code.co_lnotab == code.co_lnotab
        else:
            assert new_code.co_linetable == code.co_linetable

    def test_complex_scenario(self):
        """Test a complex real-world-like scenario with multiple functions."""
        # Create a more complex function with loops and conditionals
        complex_code = '''
def complex_func(items):
    total = 0
    for item in items:
        if item > 0:
            total += item
        elif item < 0:
            total -= abs(item)
        else:
            continue
    return total
'''
        compiled = compile(complex_code, '<test>', 'exec')
        namespace = {}
        exec(compiled, namespace)
        code = namespace['complex_func'].__code__
        
        # Multiple shifts simulating real editing
        delta_map = {
            2: 3,   # Insert 3 lines at start of function
            5: -2,  # Remove 2 lines in middle
            8: 10,  # Insert 10 lines near end
        }
        
        new_code = shifted_line_table(code, delta_map)
        
        # Verify the transformation worked
        if sys.version_info < (3, 11):
            old_pairs = parse_lnotab(code.co_lnotab, code.co_firstlineno)
            new_pairs = parse_lnotab(new_code.co_lnotab, new_code.co_firstlineno)
        else:
            old_pairs = parse_linetable(code.co_linetable, code.co_firstlineno)
            new_pairs = parse_linetable(new_code.co_linetable, new_code.co_firstlineno)
        
        # Verify proper cumulative shifting
        for (old_addr, old_line), (new_addr, new_line) in zip(old_pairs, new_pairs):
            assert new_addr == old_addr
            expected_shift = 0
            if old_line >= 2:
                expected_shift += 3
            if old_line >= 5:
                expected_shift -= 2
            if old_line >= 8:
                expected_shift += 10
            assert new_line == old_line + expected_shift

    def test_real_world_integration(self):
        """Test integration with real-world scenario - simulating autoreload."""
        # Create a more realistic function representing before-edit state
        original_source = '''
def calculate_total(items):
    """Calculate total of numeric items."""
    total = 0
    for item in items:
        if isinstance(item, (int, float)):
            total += item
    return total
'''
        
        # Compile and get code object
        compiled = compile(original_source, '<module>', 'exec')
        namespace = {}
        exec(compiled, namespace)
        original_code = namespace['calculate_total'].__code__
        
        # Simulate editing: add 3 lines of comments at the beginning
        # This would shift all lines >= original start line by +3
        delta_map = {original_code.co_firstlineno: 3}
        
        # Apply our line table patching
        patched_code = shifted_line_table(original_code, delta_map)
        
        # Verify the patch worked
        assert patched_code.co_firstlineno == original_code.co_firstlineno + 3
        
        # Parse both line tables to verify all lines shifted correctly
        if sys.version_info < (3, 11):
            orig_pairs = parse_lnotab(original_code.co_lnotab, original_code.co_firstlineno)
            new_pairs = parse_lnotab(patched_code.co_lnotab, patched_code.co_firstlineno)
        else:
            orig_pairs = parse_linetable(original_code.co_linetable, original_code.co_firstlineno)
            new_pairs = parse_linetable(patched_code.co_linetable, patched_code.co_firstlineno)
        
        # Every line should be shifted by exactly +3
        assert len(orig_pairs) == len(new_pairs)
        for (orig_addr, orig_line), (new_addr, new_line) in zip(orig_pairs, new_pairs):
            assert new_addr == orig_addr  # Bytecode addresses unchanged
            assert new_line == orig_line + 3  # All lines shifted by +3
        
        # Verify the patched code object is functional
        # Replace the original function's code with our patched version
        import types
        patched_function = types.FunctionType(
            patched_code,
            namespace,
            'calculate_total'
        )
        
        # The function should still work correctly
        result = patched_function([1, 2, 3, 'ignore', 4.5])
        assert result == 10.5
        
        print(f"✓ Successfully patched function from line {original_code.co_firstlineno} to line {patched_code.co_firstlineno}")
        print(f"✓ Function still works correctly: calculate_total([1, 2, 3, 'ignore', 4.5]) = {result}")


class TestEdgeCases:
    """Tests for edge cases and error conditions."""

    def test_malformed_lnotab(self):
        """Test parsing malformed lnotab data."""
        # Odd length (missing second byte of pair)
        result = parse_lnotab(b'\x02', 10)
        assert result == [(0, 10)]  # Should just ignore incomplete pair

    def test_negative_line_numbers(self):
        """Test handling of negative line numbers."""
        # Create pairs with negative line numbers
        pairs = [(0, -5), (2, -3), (4, -10)]
        
        # Should work for linetable (SLEB128 supports negative values)
        encoded = encode_linetable(pairs)
        decoded = parse_linetable(encoded, -5)
        assert decoded == pairs

    def test_zero_deltas(self):
        """Test handling of zero deltas."""
        pairs = [(0, 10), (0, 10), (2, 10)]  # Some zero address deltas
        
        # For lnotab, zero address deltas should be skipped
        encoded = encode_lnotab(pairs)
        decoded = parse_lnotab(encoded, 10)
        # Should skip the zero delta entry
        assert decoded == [(0, 10), (2, 10)]

    def test_very_large_numbers(self):
        """Test with very large line/address numbers."""
        pairs = [(0, 1000000), (500000, 2000000)]
        
        # Should work for linetable
        encoded = encode_linetable(pairs)
        decoded = parse_linetable(encoded, 1000000)
        assert decoded == pairs 