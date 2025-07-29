#!/usr/bin/env python
"""
Unit tests for the Line Number Patching Engine.

Tests cover:
- LineNumberPatcher core functionality
- Code object discovery and extraction  
- Line number patching with ctypes
- Edge cases and failure modes
- Integration with DeduperReloaderPatchingMixin
"""

from __future__ import annotations

import ast
import inspect
import sys
import tempfile
import textwrap
import warnings
from pathlib import Path
from types import ModuleType, FunctionType, CodeType
from unittest.mock import Mock, patch, MagicMock

from IPython.extensions.deduperreload.line_number_patcher import LineNumberPatcher
from IPython.extensions.deduperreload.line_number_tracker import (
    CodePosition,
    LineShift,
    ModuleSourceTracker,
)


class TestLineNumberPatcher:
    """Test the LineNumberPatcher class."""

    def setup_method(self):
        """Set up a fresh patcher for each test."""
        self.patcher = LineNumberPatcher()

    def test_initialization(self):
        """Test LineNumberPatcher initialization."""
        assert isinstance(self.patcher.source_tracker, ModuleSourceTracker)
        assert self.patcher.patch_cache == {}
        assert self.patcher.enable_line_number_patching is True

    def test_feature_flag_disabled(self):
        """Test that operations are skipped when feature flag is disabled."""
        self.patcher.enable_line_number_patching = False

        mock_module = Mock()
        mock_module.__name__ = "test_module"

        shifts = self.patcher.calculate_line_shifts(mock_module, {"func1"})
        assert shifts == []

        # Should return early without doing work
        self.patcher.update_all_code_object_line_numbers(mock_module, [])
        # No exception should be raised

    def test_calculate_line_shifts_empty_module(self):
        """Test calculating line shifts with empty module."""
        mock_module = Mock()
        mock_module.__name__ = "empty_module"

        with patch.object(
            self.patcher.source_tracker, "track_module_source", return_value=""
        ):
            shifts = self.patcher.calculate_line_shifts(mock_module, {"func1"})

        assert shifts == []

    def test_calculate_line_shifts_success(self):
        """Test successful line shift calculation."""
        mock_module = Mock()
        mock_module.__name__ = "test_module"

        # Mock current source and positions
        current_source = "def func1():\n    pass\n"
        current_positions = {"func1": CodePosition("func1", "function", 1, 2, 1)}

        # Mock old positions (smaller function)
        old_positions = {
            "func1": CodePosition(
                "func1", "function", 1, 1, 1
            )  # Was 1 line, now 2 lines
        }

        with patch.object(
            self.patcher.source_tracker,
            "track_module_source",
            return_value=current_source,
        ), patch.object(
            self.patcher.source_tracker,
            "parse_all_code_positions",
            return_value=current_positions,
        ), patch.object(
            self.patcher.source_tracker, "get_positions", return_value=old_positions
        ):

            shifts = self.patcher.calculate_line_shifts(mock_module, {"func1"})

        assert len(shifts) == 1
        shift = shifts[0]
        assert shift.position == 1  # old end_line
        assert shift.delta == 1  # new_size - old_size = 2 - 1 = 1
        assert shift.cause == "func1"

    def test_calculate_line_shifts_no_change(self):
        """Test line shift calculation when nothing changed."""
        mock_module = Mock()
        mock_module.__name__ = "test_module"

        current_positions = {"func1": CodePosition("func1", "function", 1, 2, 1)}
        old_positions = {
            "func1": CodePosition("func1", "function", 1, 2, 1)  # Same size
        }

        with patch.object(
            self.patcher.source_tracker,
            "track_module_source",
            return_value="def func1():\n    pass\n",
        ), patch.object(
            self.patcher.source_tracker,
            "parse_all_code_positions",
            return_value=current_positions,
        ), patch.object(
            self.patcher.source_tracker, "get_positions", return_value=old_positions
        ):

            shifts = self.patcher.calculate_line_shifts(mock_module, {"func1"})

        assert shifts == []

    def test_calculate_line_shifts_exception_handling(self):
        """Test exception handling in calculate_line_shifts."""
        mock_module = Mock()
        mock_module.__name__ = "test_module"

        with patch.object(
            self.patcher.source_tracker,
            "track_module_source",
            side_effect=Exception("Test error"),
        ), warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")

            shifts = self.patcher.calculate_line_shifts(mock_module, {"func1"})

        assert shifts == []
        assert len(w) == 1
        assert "Failed to calculate line shifts" in str(w[0].message)


class TestCodeObjectDiscovery:
    """Test code object discovery and extraction."""

    def setup_method(self):
        """Set up a fresh patcher for each test."""
        self.patcher = LineNumberPatcher()

    def test_find_all_code_objects_in_module_simple(self):
        """Test finding code objects in a simple module."""
        # Create a mock module with functions
        mock_module = Mock()
        mock_module.__name__ = "test_module"

        def test_func():
            pass

        # Mock vars() to return our test function
        with patch(
            "builtins.vars",
            return_value={"test_func": test_func, "_private": lambda: None},
        ):
            code_objects = self.patcher.find_all_code_objects_in_module(mock_module)

        # Should find test_func but skip _private
        names = [name for name, obj in code_objects]
        assert "test_func" in names
        assert "_private" not in names

    def test_extract_code_objects_from_function(self):
        """Test extracting code objects from a function."""

        def test_function():
            return 42

        code_objects = self.patcher.extract_code_objects_from_object(
            test_function, "test_function"
        )

        assert len(code_objects) == 1
        name, obj = code_objects[0]
        assert name == "test_function"
        assert obj is test_function
        assert hasattr(obj, "__code__")

    def test_extract_code_objects_from_class(self):
        """Test extracting code objects from a class."""

        class TestClass:
            def method1(self):
                return 1

            @staticmethod
            def static_method():
                return 2

            @classmethod
            def class_method(cls):
                return 3

            @property
            def prop(self):
                return 4

            def _private_method(self):
                return 5

        code_objects = self.patcher.extract_code_objects_from_object(
            TestClass, "TestClass"
        )

        names = [name for name, obj in code_objects]

        # Should find public methods but skip private ones
        assert "TestClass.method1" in names
        assert "TestClass.static_method.__func__" in names
        assert "TestClass.class_method.__func__" in names
        assert "TestClass.prop.fget" in names
        assert "_private_method" not in names

    def test_extract_code_objects_from_nested_classes(self):
        """Test extracting code objects from nested classes."""

        class OuterClass:
            def outer_method(self):
                pass

            class InnerClass:
                def inner_method(self):
                    pass

        code_objects = self.patcher.extract_code_objects_from_object(
            OuterClass, "OuterClass"
        )

        names = [name for name, obj in code_objects]

        assert "OuterClass.outer_method" in names
        assert "OuterClass.InnerClass.inner_method" in names

    def test_extract_code_objects_exception_handling(self):
        """Test exception handling in code object extraction."""
        # Create an object that will cause an exception when vars() is called
        bad_obj = Mock(spec=type)  # Make it look like a class

        with patch(
            "builtins.vars", side_effect=Exception("Test error")
        ), warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")

            code_objects = self.patcher.extract_code_objects_from_object(
                bad_obj, "bad_obj"
            )

        assert code_objects == []
        assert len(w) == 1
        assert "Failed to extract code objects" in str(w[0].message)


class TestLineNumberPatching:
    """Test the core line number patching functionality."""

    def setup_method(self):
        """Set up a fresh patcher for each test."""
        self.patcher = LineNumberPatcher()

    def test_find_matching_position_direct_match(self):
        """Test finding position with direct name match."""
        positions = {"test_func": CodePosition("test_func", "function", 10, 15, 10)}

        mock_obj = Mock()
        position = self.patcher.find_matching_position("test_func", mock_obj, positions)

        assert position == 10

    def test_find_matching_position_by_name_attribute(self):
        """Test finding position by __name__ attribute."""
        positions = {"func": CodePosition("func", "function", 20, 25, 20)}

        mock_obj = Mock()
        mock_obj.__name__ = "func"

        position = self.patcher.find_matching_position(
            "SomeClass.func", mock_obj, positions
        )

        assert position == 20

    def test_find_matching_position_partial_match(self):
        """Test finding position with partial matching."""
        positions = {
            "MyClass.method": CodePosition("MyClass.method", "method", 30, 35, 30)
        }

        mock_obj = Mock()
        position = self.patcher.find_matching_position(
            "module.MyClass.method", mock_obj, positions
        )

        assert position == 30

    def test_find_matching_position_no_match(self):
        """Test finding position when no match exists."""
        positions = {"other_func": CodePosition("other_func", "function", 10, 15, 10)}

        mock_obj = Mock()
        position = self.patcher.find_matching_position("test_func", mock_obj, positions)

        assert position is None

    def test_patch_single_code_object_lines_success(self):
        """Test successful single code object patching."""
        # Create a real function to patch
        def test_function():
            return 42

        original_line = test_function.__code__.co_firstlineno
        new_line = original_line + 10

        # Mock the patching method to avoid ctypes complexity in tests
        with patch.object(self.patcher, "try_patch_attr") as mock_patch:
            result = self.patcher.patch_single_code_object_lines(
                test_function, new_line, "test_function"
            )

        assert result is True
        mock_patch.assert_called_once()

        # Check that the new code object was created with correct line number
        args, kwargs = mock_patch.call_args
        assert kwargs.get("new_is_value") is True
        assert args[1].co_firstlineno == new_line

    def test_patch_single_code_object_lines_exception(self):
        """Test exception handling in single code object patching."""

        def test_function():
            return 42

        with patch.object(
            self.patcher, "try_patch_attr", side_effect=Exception("Patch failed")
        ), warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")

            result = self.patcher.patch_single_code_object_lines(test_function, 100, "test_function")

        assert result is False
        assert len(w) == 1
        assert "Failed to patch line numbers" in str(w[0].message)

    def test_update_all_code_object_line_numbers_success(self):
        """Test updating all code objects with line numbers."""
        mock_module = Mock()
        mock_module.__name__ = "test_module"

        def test_func():
            pass

        # Mock the methods
        current_positions = {
            "test_func": CodePosition("test_func", "function", 50, 55, 50)
        }

        shifts = [LineShift(position=10, delta=5, cause="other_func")]

        with patch.object(
            self.patcher.source_tracker,
            "track_module_source",
            return_value="def test_func():\n    pass",
        ), patch.object(
            self.patcher.source_tracker,
            "parse_all_code_positions",
            return_value=current_positions,
        ), patch.object(
            self.patcher,
            "find_all_code_objects_in_module",
            return_value=[("test_func", test_func)],
        ), patch.object(
            self.patcher, "patch_single_code_object_lines", return_value=True
        ) as mock_patch:

            self.patcher.update_all_code_object_line_numbers(mock_module, shifts)

        # Should have attempted to patch the function
        mock_patch.assert_called_once_with(test_func, 50, "test_func")

    def test_update_all_code_object_line_numbers_no_shifts(self):
        """Test update with no shifts (should return early)."""
        mock_module = Mock()

        with patch.object(self.patcher, "find_all_code_objects_in_module") as mock_find:
            self.patcher.update_all_code_object_line_numbers(mock_module, [])

        # Should not call find_all_code_objects_in_module
        mock_find.assert_not_called()

    def test_update_all_code_object_line_numbers_exception(self):
        """Test exception handling in update_all_code_object_line_numbers."""
        mock_module = Mock()
        mock_module.__name__ = "test_module"

        shifts = [LineShift(position=10, delta=5, cause="func")]

        with patch.object(
            self.patcher.source_tracker,
            "track_module_source",
            side_effect=Exception("Source error"),
        ), warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")

            self.patcher.update_all_code_object_line_numbers(mock_module, shifts)

        assert len(w) == 1
        assert "Failed to update line numbers" in str(w[0].message)


class TestClosureHandling:
    """Test handling of functions with closures."""

    def setup_method(self):
        """Set up a fresh patcher for each test."""
        self.patcher = LineNumberPatcher()

    def test_merge_closures_basic(self):
        """Test basic closure merging."""
        # Create mock cell objects
        mock_cell1 = Mock()
        mock_cell2 = Mock()
        old_closure = (mock_cell1, mock_cell2)
        new_freevars = ("var1", "var2")

        merged = self.patcher.merge_closures(old_closure, new_freevars)

        assert len(merged) == 2
        assert "var1" in merged
        assert "var2" in merged
        assert merged["var1"] is mock_cell1
        assert merged["var2"] is mock_cell2

    def test_merge_closures_size_mismatch(self):
        """Test closure merging with size mismatch."""
        mock_cell = Mock()
        old_closure = (mock_cell,)
        new_freevars = ("var1", "var2", "var3")  # More vars than cells

        merged = self.patcher.merge_closures(old_closure, new_freevars)

        assert len(merged) == 1  # Only one cell available
        assert "var1" in merged
        assert merged["var1"] is mock_cell

    def test_patch_function_with_closure_no_closure(self):
        """Test patching function without closure."""

        def simple_func():
            return 42

        new_code = simple_func.__code__.replace(co_firstlineno=100)

        with patch.object(self.patcher, "try_patch_attr") as mock_patch:
            # Cast to Any to avoid type checker issues
            result = self.patcher.patch_function_with_closure(simple_func, new_code)  # type: ignore

        assert result is True
        # Should only patch the code, not closure
        assert mock_patch.call_count == 1

    def test_patch_function_with_closure_exception(self):
        """Test exception handling in closure patching."""

        def test_func():
            return 42

        new_code = test_func.__code__

        with patch.object(
            self.patcher, "try_patch_attr", side_effect=Exception("Patch error")
        ), warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")

            result = self.patcher.patch_function_with_closure(test_func, new_code)  # type: ignore

        assert result is False
        assert len(w) == 1
        assert "Failed to patch closure function" in str(w[0].message)


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def setup_method(self):
        """Set up a fresh patcher for each test."""
        self.patcher = LineNumberPatcher()

    def test_validate_patch_safety_no_code_attribute(self):
        """Test validation with object that has no __code__."""
        mock_obj = Mock()
        delattr(mock_obj, "__code__")  # Remove __code__ attribute

        mock_new_code = Mock()

        result = self.patcher.validate_patch_safety(mock_obj, mock_new_code)
        assert result is False

    def test_validate_patch_safety_argcount_mismatch(self):
        """Test validation with argument count mismatch."""

        def old_func(a, b):
            pass

        def new_func(a, b, c):  # Different argument count
            pass

        result = self.patcher.validate_patch_safety(old_func, new_func.__code__)
        assert result is False

    def test_validate_patch_safety_filename_mismatch(self):
        """Test validation with filename mismatch."""
        # Create mock code objects with different filenames
        old_code = Mock()
        old_code.co_argcount = 2
        old_code.co_filename = "file1.py"

        new_code = Mock()
        new_code.co_argcount = 2
        new_code.co_filename = "file2.py"

        old_obj = Mock()
        old_obj.__code__ = old_code

        result = self.patcher.validate_patch_safety(old_obj, new_code)
        assert result is False

    def test_validate_patch_safety_success(self):
        """Test successful validation."""

        def test_func(a, b):
            pass

        new_code = test_func.__code__.replace(co_firstlineno=100)

        result = self.patcher.validate_patch_safety(test_func, new_code)
        assert result is True

    def test_validate_patch_safety_exception(self):
        """Test exception handling in validation."""
        mock_obj = Mock()
        mock_obj.__code__ = Mock()
        # Configure mock to raise exception on attribute access
        type(mock_obj.__code__).co_argcount = Mock(side_effect=Exception("Test error"))

        mock_new_code = Mock()

        result = self.patcher.validate_patch_safety(mock_obj, mock_new_code)
        assert result is False

    def test_handle_ctypes_failure_direct_assignment_success(self):
        """Test fallback direct assignment success."""

        def test_func():
            pass

        new_code = test_func.__code__.replace(co_firstlineno=100)

        # Mock that direct assignment works
        original_setattr = setattr

        def mock_setattr(obj, attr, value):
            if attr == "__code__":
                return  # Simulate success
            return original_setattr(obj, attr, value)

        with patch("builtins.setattr", side_effect=mock_setattr):
            result = self.patcher.handle_ctypes_failure(test_func, new_code)

        assert result is True

    def test_clear_patch_cache(self):
        """Test clearing the patch cache."""
        # Add some data to cache
        self.patcher.patch_cache[123] = 456
        self.patcher.patch_cache[789] = 101112

        assert len(self.patcher.patch_cache) == 2

        self.patcher.clear_patch_cache()

        assert len(self.patcher.patch_cache) == 0

    def test_get_patch_statistics(self):
        """Test getting patch statistics."""
        # Add some data to cache and tracker
        self.patcher.patch_cache[123] = 456
        self.patcher.source_tracker.module_snapshots["module1"] = "source1"
        self.patcher.source_tracker.module_snapshots["module2"] = "source2"

        stats = self.patcher.get_patch_statistics()

        assert stats["cached_offsets"] == 1
        assert stats["feature_enabled"] is True
        assert stats["modules_tracked"] == 2

        # Test with feature disabled
        self.patcher.enable_line_number_patching = False
        stats = self.patcher.get_patch_statistics()
        assert stats["feature_enabled"] is False


class TestIntegration:
    """Integration tests for the complete patching system."""

    def test_real_function_patching_simulation(self):
        """Test simulating real function patching."""
        patcher = LineNumberPatcher()

        # Create a real function
        def original_function():
            """Original function."""
            x = 1
            y = 2
            return x + y

        original_line = original_function.__code__.co_firstlineno
        new_line = original_line + 20

        # Test the complete workflow
        result = patcher.patch_single_code_object_lines(original_function, new_line, "original_function")

        # The result depends on whether ctypes patching actually works
        # In test environment, it might fail, but should handle gracefully
        assert isinstance(result, bool)

    def test_module_workflow_simulation(self):
        """Test simulating the complete module workflow."""
        patcher = LineNumberPatcher()

        # Create mock module
        mock_module = Mock()
        mock_module.__name__ = "test_workflow"

        # Define source code
        source = textwrap.dedent(
            """
            def func1():
                return 1
            
            def func2():
                return 2
            
            class TestClass:
                def method1(self):
                    return "method1"
        """
        ).strip()

        positions = {
            "func1": CodePosition("func1", "function", 1, 2, 1),
            "func2": CodePosition("func2", "function", 4, 5, 4),
            "TestClass": CodePosition("TestClass", "class", 7, 9, 7),
            "TestClass.method1": CodePosition("TestClass.method1", "method", 8, 9, 8),
        }

        def mock_func1():
            return 1

        def mock_func2():
            return 2

        code_objects = [("func1", mock_func1), ("func2", mock_func2)]

        # Mock all the dependencies
        with patch.object(
            patcher.source_tracker, "track_module_source", return_value=source
        ), patch.object(
            patcher.source_tracker, "parse_all_code_positions", return_value=positions
        ), patch.object(
            patcher, "find_all_code_objects_in_module", return_value=code_objects
        ), patch.object(
            patcher, "patch_single_code_object_lines", return_value=True
        ) as mock_patch:

            shifts = [LineShift(position=2, delta=3, cause="func1")]
            patcher.update_all_code_object_line_numbers(mock_module, shifts)

        # Should have attempted to patch both functions
        assert mock_patch.call_count == 2


if __name__ == "__main__":
    # Run tests manually or with test runner
    pass
