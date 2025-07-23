#!/usr/bin/env python
"""
Unit tests for the line number tracking system.

Tests cover:
- CodePosition and LineShift data structures
- ModuleSourceTracker functionality
- AST parsing for different code constructs
- Error handling and edge cases
"""

from __future__ import annotations

import ast
import sys
import tempfile
import textwrap
import warnings
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock, patch

import pytest

from IPython.extensions.deduperreload.line_number_tracker import (
    CodePosition,
    LineShift,
    ModuleSourceTracker,
)


class TestCodePosition:
    """Test the CodePosition dataclass."""

    def test_creation(self):
        """Test basic CodePosition creation."""
        pos = CodePosition(
            name="test_func",
            type="function",
            start_line=10,
            end_line=15,
            original_start=10,
        )
        assert pos.name == "test_func"
        assert pos.type == "function"
        assert pos.start_line == 10
        assert pos.end_line == 15
        assert pos.original_start == 10
        assert pos.size == 6  # 15 - 10 + 1

    def test_end_line_correction(self):
        """Test that end_line is corrected if less than start_line."""
        pos = CodePosition(
            name="test_func",
            type="function",
            start_line=10,
            end_line=5,  # Invalid: less than start_line
            original_start=10,
        )
        assert pos.end_line == 10  # Should be corrected to start_line
        assert pos.size == 1

    def test_size_calculation(self):
        """Test size calculation for different ranges."""
        # Single line
        pos1 = CodePosition("func1", "function", 10, 10, 10)
        assert pos1.size == 1

        # Multiple lines
        pos2 = CodePosition("func2", "function", 10, 20, 10)
        assert pos2.size == 11

        # Large function
        pos3 = CodePosition("func3", "function", 1, 100, 1)
        assert pos3.size == 100


class TestLineShift:
    """Test the LineShift dataclass."""

    def test_creation(self):
        """Test basic LineShift creation."""
        shift = LineShift(position=50, delta=5, cause="func_expansion")
        assert shift.position == 50
        assert shift.delta == 5
        assert shift.cause == "func_expansion"

    def test_zero_delta_warning(self):
        """Test that creating a LineShift with delta=0 raises a warning."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            LineShift(position=50, delta=0, cause="no_change")
            assert len(w) == 1
            assert "delta=0" in str(w[0].message)

    def test_negative_delta(self):
        """Test LineShift with negative delta (code removal)."""
        shift = LineShift(position=50, delta=-3, cause="func_shrink")
        assert shift.delta == -3
        # Should not warn for non-zero delta
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            LineShift(position=50, delta=-3, cause="func_shrink")
            assert len(w) == 0


class TestModuleSourceTracker:
    """Test the ModuleSourceTracker class."""

    def setup_method(self):
        """Set up a fresh tracker for each test."""
        self.tracker = ModuleSourceTracker()

    def test_initialization(self):
        """Test tracker initialization."""
        assert self.tracker.module_snapshots == {}
        assert self.tracker.code_positions == {}

    def test_track_module_source_success(self):
        """Test successful module source tracking."""
        # Create a mock module with source
        mock_module = Mock()
        mock_module.__name__ = "test_module"

        test_source = "def hello():\n    pass\n"

        with patch("inspect.getsource", return_value=test_source):
            result = self.tracker.track_module_source(mock_module)

        assert result == test_source
        assert self.tracker.module_snapshots["test_module"] == test_source

    def test_track_module_source_failure_with_cache(self):
        """Test module source tracking failure with cached fallback."""
        mock_module = Mock()
        mock_module.__name__ = "test_module"

        # Pre-populate cache
        cached_source = "def cached_func():\n    pass\n"
        self.tracker.module_snapshots["test_module"] = cached_source

        with patch("inspect.getsource", side_effect=OSError("Source not available")):
            result = self.tracker.track_module_source(mock_module)

        assert result == cached_source

    def test_track_module_source_failure_no_cache(self):
        """Test module source tracking failure without cache."""
        mock_module = Mock()
        mock_module.__name__ = "test_module"

        with patch("inspect.getsource", side_effect=OSError("Source not available")):
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                result = self.tracker.track_module_source(mock_module)

        assert result == ""
        assert len(w) == 1
        assert "Could not retrieve source" in str(w[0].message)

    def test_parse_empty_source(self):
        """Test parsing empty or whitespace-only source."""
        positions = self.tracker.parse_all_code_positions("")
        assert positions == {}

        positions = self.tracker.parse_all_code_positions("   \n  \t  \n")
        assert positions == {}

    def test_parse_simple_function(self):
        """Test parsing a simple function."""
        source = textwrap.dedent(
            """
            def hello_world():
                print("Hello, World!")
                return True
        """
        ).strip()

        positions = self.tracker.parse_all_code_positions(source)

        assert "hello_world" in positions
        pos = positions["hello_world"]
        assert pos.name == "hello_world"
        assert pos.type == "function"
        assert pos.start_line == 1
        assert pos.end_line == 3
        assert pos.original_start == 1

    def test_parse_async_function(self):
        """Test parsing async functions."""
        source = textwrap.dedent(
            """
            async def async_hello():
                await some_coroutine()
                return "async result"
        """
        ).strip()

        positions = self.tracker.parse_all_code_positions(source)

        assert "async_hello" in positions
        pos = positions["async_hello"]
        assert pos.name == "async_hello"
        assert pos.type == "async_function"
        assert pos.start_line == 1

    def test_parse_class_with_methods(self):
        """Test parsing classes with methods."""
        source = textwrap.dedent(
            """
            class MyClass:
                def __init__(self):
                    self.value = 42
                
                def method1(self):
                    return self.value
                
                async def async_method(self):
                    return await self.get_async_value()
        """
        ).strip()

        positions = self.tracker.parse_all_code_positions(source)

        # Should have class and methods
        assert "MyClass" in positions
        assert "MyClass.__init__" in positions
        assert "MyClass.method1" in positions
        assert "MyClass.async_method" in positions

        # Check class position
        class_pos = positions["MyClass"]
        assert class_pos.type == "class"
        assert class_pos.start_line == 1

        # Check method positions
        init_pos = positions["MyClass.__init__"]
        assert init_pos.type == "method"
        assert init_pos.start_line == 2

        async_method_pos = positions["MyClass.async_method"]
        assert async_method_pos.type == "method"

    def test_parse_nested_functions(self):
        """Test parsing nested functions."""
        source = textwrap.dedent(
            """
            def outer_function():
                def inner_function():
                    def deeply_nested():
                        return "deep"
                    return deeply_nested()
                return inner_function()
        """
        ).strip()

        positions = self.tracker.parse_all_code_positions(source)

        assert "outer_function" in positions
        assert "outer_function.inner_function" in positions
        assert "outer_function.inner_function.deeply_nested" in positions

        # Check nesting structure
        outer_pos = positions["outer_function"]
        inner_pos = positions["outer_function.inner_function"]
        deep_pos = positions["outer_function.inner_function.deeply_nested"]

        assert outer_pos.start_line < inner_pos.start_line
        assert inner_pos.start_line < deep_pos.start_line

    def test_parse_nested_classes(self):
        """Test parsing nested classes."""
        source = textwrap.dedent(
            """
            class OuterClass:
                def outer_method(self):
                    pass
                
                class InnerClass:
                    def inner_method(self):
                        pass
                    
                    class DeepClass:
                        def deep_method(self):
                            pass
        """
        ).strip()

        positions = self.tracker.parse_all_code_positions(source)

        assert "OuterClass" in positions
        assert "OuterClass.outer_method" in positions
        assert "OuterClass.InnerClass" in positions
        assert "OuterClass.InnerClass.inner_method" in positions
        assert "OuterClass.InnerClass.DeepClass" in positions
        assert "OuterClass.InnerClass.DeepClass.deep_method" in positions

    def test_parse_lambda_functions(self):
        """Test parsing lambda functions."""
        source = textwrap.dedent(
            """
            func1 = lambda x: x * 2
            data = [1, 2, 3]
            result = map(lambda y: y + 1, data)
        """
        ).strip()

        positions = self.tracker.parse_all_code_positions(source)

        # Should find lambda functions (identified by line and column)
        lambda_keys = [k for k in positions.keys() if k.startswith("lambda_")]
        assert len(lambda_keys) == 2

        for key in lambda_keys:
            pos = positions[key]
            assert pos.type == "lambda"

    def test_parse_comprehensions(self):
        """Test parsing comprehensions."""
        source = textwrap.dedent(
            """
            list_comp = [x * 2 for x in range(10)]
            dict_comp = {k: v for k, v in items.items()}
            set_comp = {x for x in range(5)}
            gen_exp = (x for x in range(3))
        """
        ).strip()

        positions = self.tracker.parse_all_code_positions(source)

        # Should find comprehensions
        comp_keys = [k for k in positions.keys() if "comp" in k or "exp" in k]
        assert len(comp_keys) == 4

        for key in comp_keys:
            pos = positions[key]
            assert pos.type == "comprehension"

    def test_parse_syntax_error(self):
        """Test parsing source with syntax errors."""
        source = "def broken_function(\n    # Missing closing parenthesis"

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            positions = self.tracker.parse_all_code_positions(source)

        assert positions == {}
        assert len(w) == 1
        assert "Syntax error" in str(w[0].message)

    def test_calculate_line_shifts_empty(self):
        """Test calculating line shifts with no data."""
        shifts = self.tracker.calculate_line_shifts("test_module", set())
        assert shifts == []

    def test_update_and_get_positions(self):
        """Test updating and retrieving positions."""
        module_name = "test_module"
        positions = {
            "func1": CodePosition("func1", "function", 1, 5, 1),
            "func2": CodePosition("func2", "function", 10, 15, 10),
        }

        # Update positions
        self.tracker.update_positions(module_name, positions)

        # Retrieve positions
        retrieved = self.tracker.get_positions(module_name)

        assert len(retrieved) == 2
        assert "func1" in retrieved
        assert "func2" in retrieved

        # Should be a copy, not the same object
        assert retrieved is not positions
        assert retrieved["func1"] is not positions["func1"]

    def test_clear_module(self):
        """Test clearing module data."""
        module_name = "test_module"

        # Add some data
        self.tracker.module_snapshots[module_name] = "def test(): pass"
        self.tracker.code_positions[module_name] = {
            "test": CodePosition("test", "function", 1, 1, 1)
        }

        # Clear the module
        self.tracker.clear_module(module_name)

        # Should be removed
        assert module_name not in self.tracker.module_snapshots
        assert module_name not in self.tracker.code_positions

    def test_complex_source_parsing(self):
        """Test parsing complex source with multiple constructs."""
        source = textwrap.dedent(
            """
            # Module level code
            import os
            
            CONSTANT = 42
            
            def module_function():
                return "module level"
            
            class ComplexClass:
                class_var = "class variable"
                
                def __init__(self):
                    self.instance_var = [x for x in range(5)]
                
                @property
                def prop(self):
                    return self.instance_var
                
                @staticmethod
                def static_method():
                    def nested_in_static():
                        return lambda x: x * 2
                    return nested_in_static()
                
                @classmethod
                def class_method(cls):
                    return cls.class_var
                
                async def async_method(self):
                    async def nested_async():
                        return await some_call()
                    return await nested_async()
            
            async def module_async_function():
                return "async module level"
            
            # Lambda and comprehensions
            transform = lambda data: {k: v for k, v in data.items() if v > 0}
        """
        ).strip()

        positions = self.tracker.parse_all_code_positions(source)

        # Check that we found all major constructs
        expected_names = [
            "module_function",
            "ComplexClass",
            "ComplexClass.__init__",
            "ComplexClass.prop",
            "ComplexClass.static_method",
            "ComplexClass.static_method.nested_in_static",
            "ComplexClass.class_method",
            "ComplexClass.async_method",
            "ComplexClass.async_method.nested_async",
            "module_async_function",
        ]

        for name in expected_names:
            assert name in positions, f"Missing {name} in positions"

        # Check lambda and comprehension detection
        lambda_keys = [k for k in positions.keys() if "lambda_" in k]
        comp_keys = [k for k in positions.keys() if "comp" in k]

        assert len(lambda_keys) >= 1  # At least the lambda in transform
        assert len(comp_keys) >= 1  # At least the dict comp in lambda


class TestIntegration:
    """Integration tests for the complete tracking system."""

    def test_real_module_integration(self):
        """Test tracking with a real module (using tempfile)."""
        tracker = ModuleSourceTracker()

        # Create a temporary module file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(
                textwrap.dedent(
                    """
                def function1():
                    return 1
                
                class TestClass:
                    def method1(self):
                        return "method1"
                    
                    def method2(self):
                        return "method2"
                
                async def async_function():
                    return "async"
            """
                )
            )
            temp_file = f.name

        try:
            # Create a mock module
            mock_module = Mock()
            mock_module.__name__ = "temp_module"

            # Read the file content
            with open(temp_file, "r") as f:
                content = f.read()

            with patch("inspect.getsource", return_value=content):
                source = tracker.track_module_source(mock_module)
                positions = tracker.parse_all_code_positions(source)

            # Verify we found the expected constructs
            expected = [
                "function1",
                "TestClass",
                "TestClass.method1",
                "TestClass.method2",
                "async_function",
            ]

            for name in expected:
                assert name in positions

            # Update positions and verify storage
            tracker.update_positions("temp_module", positions)
            stored = tracker.get_positions("temp_module")

            assert len(stored) == len(positions)

        finally:
            # Clean up
            Path(temp_file).unlink()

    def test_workflow_simulation(self):
        """Test simulating the complete workflow of tracking changes."""
        tracker = ModuleSourceTracker()

        # Initial source
        initial_source = textwrap.dedent(
            """
            def func1():
                return 1
            
            def func2():
                return 2
        """
        ).strip()

        # Modified source (func1 expanded)
        modified_source = textwrap.dedent(
            """
            def func1():
                # Added comment
                x = calculate_something()
                y = process(x)
                return x + y
            
            def func2():
                return 2
        """
        ).strip()

        # Parse initial positions
        initial_positions = tracker.parse_all_code_positions(initial_source)
        tracker.update_positions("test_module", initial_positions)

        # Parse modified positions
        modified_positions = tracker.parse_all_code_positions(modified_source)

        # Check that positions changed
        initial_func1 = initial_positions["func1"]
        modified_func1 = modified_positions["func1"]

        assert initial_func1.size < modified_func1.size
        assert initial_func1.end_line < modified_func1.end_line


if __name__ == "__main__":
    pytest.main([__file__])
