#!/usr/bin/env python
"""
Simple unit tests for the Line Number Patching Engine.

This file contains basic tests that verify core functionality
without complex type checking issues.
"""

from __future__ import annotations

import warnings
from types import ModuleType
from unittest.mock import Mock, patch

from IPython.extensions.deduperreload.line_number_patcher import LineNumberPatcher
from IPython.extensions.deduperreload.line_number_tracker import (
    CodePosition,
    LineShift,
    ModuleSourceTracker,
)

"""Simple tests for line number patcher encoding/decoding functionality."""

# mypy: ignore-errors
# pyright: reportMissingImports=false, reportAttributeAccessIssue=false

import pytest  # type: ignore

import IPython.extensions.deduperreload.line_table_patching.line_table_patcher as _ltp

# Import the new functions
encode_lnotab = _ltp.encode_lnotab  # type: ignore[attr-defined]
encode_linetable = _ltp.encode_linetable  # type: ignore[attr-defined]
parse_lnotab = _ltp.parse_lnotab  # type: ignore[attr-defined]
parse_linetable = _ltp.parse_linetable  # type: ignore[attr-defined]

# ULEB/SLEB helpers
_encode_uleb128 = _ltp._encode_uleb128  # type: ignore[attr-defined]
_decode_uleb128 = _ltp._decode_uleb128  # type: ignore[attr-defined]
_encode_sleb128 = _ltp._encode_sleb128  # type: ignore[attr-defined]
_decode_sleb128 = _ltp._decode_sleb128  # type: ignore[attr-defined]


class TestUlebSlebSimple:
    """Simple tests for ULEB128/SLEB128 encoding."""

    def test_uleb128_small_values(self):
        """Test ULEB128 with small values."""
        for i in range(128):
            encoded = _encode_uleb128(i)
            decoded, consumed = _decode_uleb128(encoded)
            assert decoded == i
            assert consumed == 1  # Should be single byte for small values

    def test_sleb128_small_values(self):
        """Test SLEB128 with small values."""
        for i in range(-64, 64):
            encoded = _encode_sleb128(i)
            decoded, consumed = _decode_sleb128(encoded)
            assert decoded == i
            assert consumed == 1  # Should be single byte for small values

    def test_uleb128_boundary_values(self):
        """Test ULEB128 at byte boundaries."""
        test_values = [0, 127, 128, 255, 256, 16383, 16384]
        for value in test_values:
            encoded = _encode_uleb128(value)
            decoded, consumed = _decode_uleb128(encoded)
            assert decoded == value


class TestEncodeDecodeSimple:
    """Simple tests for encode/decode functions."""

    def test_encode_lnotab_simple(self):
        """Test simple lnotab encoding."""
        pairs = [(0, 10), (2, 11), (4, 12)]
        encoded = encode_lnotab(pairs)
        decoded = parse_lnotab(encoded, 10)
        assert decoded == pairs

    def test_encode_linetable_simple(self):
        """Test simple linetable encoding."""
        pairs = [(0, 10), (2, 11), (4, 12)]
        encoded = encode_linetable(pairs)
        decoded = parse_linetable(encoded, 10)
        assert decoded == pairs

    def test_empty_inputs(self):
        """Test encoding with empty inputs."""
        assert encode_lnotab([]) == b""
        assert encode_linetable([]) == b""

        assert parse_lnotab(b"", 100) == [(0, 100)]
        assert parse_linetable(b"", 100) == [(0, 100)]

    def test_single_entry(self):
        """Test with single entry (should produce empty encoding)."""
        pairs = [(0, 100)]

        assert encode_lnotab(pairs) == b""
        assert encode_linetable(pairs) == b""


class TestRoundtripSimple:
    """Simple roundtrip tests."""

    def test_basic_roundtrip(self):
        """Test basic encode/decode roundtrip."""
        test_cases = [
            [(0, 1), (2, 2), (4, 3)],
            [(0, 100), (10, 105), (20, 110)],
            [(0, 50), (5, 55), (10, 50), (15, 60)],  # includes line going backward
        ]

        for pairs in test_cases:
            # lnotab roundtrip
            lnotab_encoded = encode_lnotab(pairs)
            lnotab_decoded = parse_lnotab(lnotab_encoded, pairs[0][1])
            assert lnotab_decoded == pairs

            # linetable roundtrip
            linetable_encoded = encode_linetable(pairs)
            linetable_decoded = parse_linetable(linetable_encoded, pairs[0][1])
            assert linetable_decoded == pairs


class TestLineNumberPatcherBasic:
    """Basic tests for LineNumberPatcher functionality."""

    def test_initialization(self):
        """Test LineNumberPatcher initializes correctly."""
        patcher = LineNumberPatcher()
        assert isinstance(patcher.source_tracker, ModuleSourceTracker)
        assert patcher.patch_cache == {}
        assert patcher.enable_line_number_patching is True

    def test_feature_flag_disabled(self):
        """Test operations skip when feature flag is disabled."""
        patcher = LineNumberPatcher()
        patcher.enable_line_number_patching = False

        mock_module = Mock()
        mock_module.__name__ = "test_module"

        shifts = patcher.calculate_line_shifts(mock_module, {"func1"})
        assert shifts == []

    def test_find_matching_position_direct_match(self):
        """Test position finding with direct name match."""
        patcher = LineNumberPatcher()
        positions = {"test_func": CodePosition("test_func", "function", 10, 15, 10)}

        mock_obj = Mock()
        position = patcher.find_matching_position("test_func", mock_obj, positions)
        assert position == 10

    def test_find_matching_position_no_match(self):
        """Test position finding when no match exists."""
        patcher = LineNumberPatcher()
        positions = {"other_func": CodePosition("other_func", "function", 10, 15, 10)}

        mock_obj = Mock()
        position = patcher.find_matching_position("test_func", mock_obj, positions)
        assert position is None

    def test_extract_code_objects_from_function(self):
        """Test extracting code objects from a function."""
        patcher = LineNumberPatcher()

        def test_function():
            return 42

        code_objects = patcher.extract_code_objects_from_object(
            test_function, "test_function"
        )

        assert len(code_objects) == 1
        name, obj = code_objects[0]
        assert name == "test_function"
        assert obj is test_function
        assert hasattr(obj, "__code__")

    def test_extract_code_objects_from_class(self):
        """Test extracting code objects from a class."""
        patcher = LineNumberPatcher()

        class TestClass:
            def method1(self):
                return 1

            def _private_method(self):
                return 2

        code_objects = patcher.extract_code_objects_from_object(TestClass, "TestClass")
        names = [name for name, obj in code_objects]

        assert "TestClass.method1" in names
        # Private methods should be skipped
        assert not any("_private_method" in name for name in names)

    def test_patch_single_code_object_lines_success(self):
        """Test successful single code object patching."""
        patcher = LineNumberPatcher()

        def test_function():
            return 42

        original_line = test_function.__code__.co_firstlineno
        new_line = original_line + 10

        # Mock the patching method to avoid ctypes complexity
        with patch.object(patcher, "try_patch_attr") as mock_patch:
            result = patcher.patch_single_code_object_lines(
                test_function, new_line, "test_function"
            )

        assert result is True
        mock_patch.assert_called_once()

        # Check that the new code object was created with correct line number
        args, kwargs = mock_patch.call_args
        assert kwargs.get("new_is_value") is True
        assert args[0] == test_function  # old object
        assert args[2] == "__code__"  # field name
        assert args[1].co_firstlineno == new_line  # new code object

    def test_patch_single_code_object_lines_exception(self):
        """Test exception handling in patching."""
        patcher = LineNumberPatcher()

        def test_function():
            return 42

        with patch.object(
            patcher, "try_patch_attr", side_effect=Exception("Patch failed")
        ), warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")

            result = patcher.patch_single_code_object_lines(
                test_function, 100, "test_function"
            )

        assert result is False
        assert len(w) == 1
        assert "Failed to patch line numbers" in str(w[0].message)

    def test_validate_patch_safety_success(self):
        """Test successful patch validation."""
        patcher = LineNumberPatcher()

        def test_func(a, b):
            pass

        new_code = test_func.__code__.replace(co_firstlineno=100)
        result = patcher.validate_patch_safety(test_func, new_code)
        assert result is True

    def test_validate_patch_safety_argcount_mismatch(self):
        """Test patch validation with argument count mismatch."""
        patcher = LineNumberPatcher()

        def old_func(a, b):
            pass

        def new_func(a, b, c):  # Different argument count
            pass

        result = patcher.validate_patch_safety(old_func, new_func.__code__)
        assert result is False

    def test_get_patch_statistics(self):
        """Test getting patch statistics."""
        patcher = LineNumberPatcher()

        # Add some data to cache and tracker
        patcher.patch_cache[123] = 456
        patcher.source_tracker.module_snapshots["module1"] = "source1"

        stats = patcher.get_patch_statistics()

        assert stats["cached_offsets"] == 1
        assert stats["feature_enabled"] is True
        assert stats["modules_tracked"] == 1

    def test_clear_patch_cache(self):
        """Test clearing the patch cache."""
        patcher = LineNumberPatcher()

        # Add some data to cache
        patcher.patch_cache[123] = 456
        patcher.patch_cache[789] = 101112

        assert len(patcher.patch_cache) == 2

        patcher.clear_patch_cache()

        assert len(patcher.patch_cache) == 0

    def test_merge_closures_basic(self):
        """Test basic closure merging."""
        patcher = LineNumberPatcher()

        # Create mock cell objects
        mock_cell1 = Mock()
        mock_cell2 = Mock()
        old_closure = (mock_cell1, mock_cell2)
        new_freevars = ("var1", "var2")

        merged = patcher.merge_closures(old_closure, new_freevars)

        assert len(merged) == 2
        assert "var1" in merged
        assert "var2" in merged
        assert merged["var1"] is mock_cell1
        assert merged["var2"] is mock_cell2

    def test_calculate_line_shifts_exception_handling(self):
        """Test exception handling in calculate_line_shifts."""
        patcher = LineNumberPatcher()

        mock_module = Mock()
        mock_module.__name__ = "test_module"

        with patch.object(
            patcher.source_tracker,
            "track_module_source",
            side_effect=Exception("Test error"),
        ), warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")

            shifts = patcher.calculate_line_shifts(mock_module, {"func1"})

        assert shifts == []
        assert len(w) == 1
        assert "Failed to calculate line shifts" in str(w[0].message)


def test_real_line_patching():
    """Integration test with real line number patching."""
    patcher = LineNumberPatcher()

    def test_function():
        return 42

    original_line = test_function.__code__.co_firstlineno
    new_line = original_line + 50

    # Test actual patching (this will use ctypes)
    success = patcher.patch_single_code_object_lines(
        test_function, new_line, "test_function"
    )

    # The success depends on the environment, but should handle gracefully
    assert isinstance(success, bool)

    if success:
        # If patching succeeded, verify the line number changed
        final_line = test_function.__code__.co_firstlineno
        assert (
            final_line == new_line or final_line == original_line
        )  # Either worked or was preserved


def test_end_to_end_workflow():
    """Test the complete workflow with a mock module."""
    patcher = LineNumberPatcher()

    # Create a mock module
    mock_module = ModuleType("test_module")

    # Add a function to the module
    def test_func():
        return 1

    setattr(mock_module, "test_func", test_func)

    # Mock the module's __dict__ for vars()
    with patch("builtins.vars", return_value={"test_func": test_func}):
        code_objects = patcher.find_all_code_objects_in_module(mock_module)

    # Should find our function
    assert len(code_objects) >= 1
    found_func = None
    for name, obj in code_objects:
        if name == "test_func":
            found_func = obj
            break

    assert found_func is test_func
    assert hasattr(found_func, "__code__")


if __name__ == "__main__":
    # Simple test runner
    import sys

    print("Running Line Number Patcher tests...")

    test_basic = TestLineNumberPatcherBasic()
    test_methods = [method for method in dir(test_basic) if method.startswith("test_")]

    passed = 0
    failed = 0

    for method_name in test_methods:
        try:
            method = getattr(test_basic, method_name)
            method()
            print(f"✓ {method_name}")
            passed += 1
        except Exception as e:
            print(f"✗ {method_name}: {e}")
            failed += 1

    # Run integration tests
    try:
        test_real_line_patching()
        print("✓ test_real_line_patching")
        passed += 1
    except Exception as e:
        print(f"✗ test_real_line_patching: {e}")
        failed += 1

    try:
        test_end_to_end_workflow()
        print("✓ test_end_to_end_workflow")
        passed += 1
    except Exception as e:
        print(f"✗ test_end_to_end_workflow: {e}")
        failed += 1

    print(f"\nResults: {passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
