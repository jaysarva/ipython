"""
Comprehensive tests for the AST-based line number patcher.

This module tests the ASTPatcher class and its integration with the
line number patching system, specifically for Python 3.11+ where
AST-based approaches provide more reliable line number correction.
"""

import ast
import sys
import pytest
import tempfile
import textwrap
import types
import unittest
from typing import Dict, Optional

from IPython.extensions.deduperreload.ast_patcher import (
    ASTPatcher,
    LineNumberShifter,
    SourceCodeExtractor,
    FunctionExtractor,
)


class TestLineNumberShifter(unittest.TestCase):
    """Test the LineNumberShifter AST transformer."""

    def test_simple_shift(self):
        """Test basic line number shifting."""
        source = textwrap.dedent(
            """
        def foo():
            return 42
        
        def bar():
            return 84
        """
        ).strip()

        tree = ast.parse(source)
        shifter = LineNumberShifter({1: 2})  # Insert 2 lines at beginning
        shifted_tree = shifter.visit(tree)

        # Find the functions and check their line numbers
        for node in ast.walk(shifted_tree):
            if isinstance(node, ast.FunctionDef):
                if node.name == "foo":
                    self.assertEqual(node.lineno, 3)  # was 1, now 1+2=3
                elif node.name == "bar":
                    self.assertEqual(node.lineno, 6)  # was 4, now 4+2=6

    def test_complex_delta_map(self):
        """Test complex delta map with multiple insertion points."""
        source = textwrap.dedent(
            """
        def func1():
            pass
        
        def func2():
            pass
            
        def func3():
            pass
        """
        ).strip()

        tree = ast.parse(source)
        # Insert 1 line at line 2, and 2 more lines at line 5
        shifter = LineNumberShifter({2: 1, 5: 2})
        shifted_tree = shifter.visit(tree)

        for node in ast.walk(shifted_tree):
            if isinstance(node, ast.FunctionDef):
                if node.name == "func1":
                    self.assertEqual(node.lineno, 1)  # Before any insertions
                elif node.name == "func2":
                    self.assertEqual(node.lineno, 5)  # was 4, +1 shift = 5
                elif node.name == "func3":
                    self.assertEqual(node.lineno, 10)  # was 7, +1+2 shifts = 10

    def test_end_lineno_handling(self):
        """Test that end_lineno is also shifted correctly."""
        source = textwrap.dedent(
            """
        def multiline_func():
            x = 1
            y = 2
            return x + y
        """
        ).strip()

        tree = ast.parse(source)
        shifter = LineNumberShifter({1: 3})  # Insert 3 lines at beginning
        shifted_tree = shifter.visit(tree)

        func_node = None
        for node in ast.walk(shifted_tree):
            if isinstance(node, ast.FunctionDef) and node.name == "multiline_func":
                func_node = node
                break

        self.assertIsNotNone(func_node)
        self.assertEqual(func_node.lineno, 4)  # was 1, now 4
        if hasattr(func_node, "end_lineno") and func_node.end_lineno:
            self.assertEqual(func_node.end_lineno, 7)  # was 4, now 7


class TestFunctionExtractor(unittest.TestCase):
    """Test the FunctionExtractor AST visitor."""

    def test_extract_simple_function(self):
        """Test extracting a simple function definition."""
        source = textwrap.dedent(
            """
        def target_func():
            return 42
        
        def other_func():
            return 84
        """
        ).strip()

        tree = ast.parse(source)
        extractor = FunctionExtractor("target_func")
        extractor.visit(tree)

        self.assertIsNotNone(extractor.found_function)
        self.assertEqual(extractor.found_function.name, "target_func")

    def test_extract_class_method(self):
        """Test extracting a method from a class."""
        source = textwrap.dedent(
            """
        class TestClass:
            def target_method(self):
                return 42
            
            def other_method(self):
                return 84
        """
        ).strip()

        tree = ast.parse(source)
        extractor = FunctionExtractor("target_method")
        extractor.visit(tree)

        self.assertIsNotNone(extractor.found_function)
        self.assertEqual(extractor.found_function.name, "target_method")

    def test_extract_qualified_method(self):
        """Test extracting a method using qualified name."""
        source = textwrap.dedent(
            """
        class TestClass:
            def target_method(self):
                return 42
        """
        ).strip()

        tree = ast.parse(source)
        extractor = FunctionExtractor("TestClass.target_method")
        extractor.visit(tree)

        self.assertIsNotNone(extractor.found_function)
        self.assertEqual(extractor.found_function.name, "target_method")

    def test_function_not_found(self):
        """Test behavior when target function is not found."""
        source = textwrap.dedent(
            """
        def other_func():
            return 42
        """
        ).strip()

        tree = ast.parse(source)
        extractor = FunctionExtractor("nonexistent_func")
        extractor.visit(tree)

        self.assertIsNone(extractor.found_function)


class TestASTPatcher(unittest.TestCase):
    """Test the main ASTPatcher class."""

    def setUp(self):
        """Set up test fixtures."""
        self.patcher = ASTPatcher()

    def test_validation_basic_function(self):
        """Test validation for basic function source."""
        source = textwrap.dedent(
            """
        def test_func():
            return 42
        """
        ).strip()

        # Create a mock code object
        compiled = compile(source, "<string>", "exec")
        code_obj = None

        # Extract the function code
        namespace = {}
        exec(compiled, namespace)
        if "test_func" in namespace:
            code_obj = namespace["test_func"].__code__

        self.assertIsNotNone(code_obj)
        self.assertTrue(self.patcher.validate_ast_patching_safety(code_obj, source))

    def test_validation_syntax_error(self):
        """Test validation with invalid syntax."""
        invalid_source = "def invalid_func( # missing closing paren"

        # Create a dummy code object
        valid_source = "def dummy(): pass"
        compiled = compile(valid_source, "<string>", "exec")
        namespace = {}
        exec(compiled, namespace)
        code_obj = namespace["dummy"].__code__

        self.assertFalse(
            self.patcher.validate_ast_patching_safety(code_obj, invalid_source)
        )

    def test_patch_simple_function(self):
        """Test patching a simple function."""
        source = textwrap.dedent(
            """
        def decorated_func():
            return 8/0
        """
        ).strip()

        # Compile original
        compiled = compile(source, "<test>", "exec")
        namespace = {}
        exec(compiled, namespace)
        original_code = namespace["decorated_func"].__code__

        # Test patching (delta_map is not used in current implementation)
        delta_map = {1: 0}  # No actual shift needed for this test

        patched_code = self.patcher.patch_code_object_ast(
            original_code, delta_map, source, "decorated_func", "test_func"
        )
        self.assertIsNotNone(patched_code)
        self.assertEqual(patched_code.co_name, "decorated_func")

    def test_patch_decorated_function(self):
        """Test patching a decorated function (the main use case)."""
        source = textwrap.dedent(
            """
        def decorator(func):
            return func
        
        @decorator
        def decorated_func():
            return 8/0
        """
        ).strip()

        # Compile original
        compiled = compile(source, "<test>", "exec")
        namespace = {}
        exec(compiled, namespace)
        original_code = namespace["decorated_func"].__code__

        # Test patching
        delta_map = {1: 0}  # No shift for this test

        patched_code = self.patcher.patch_code_object_ast(
            original_code, delta_map, source, "decorated_func", "decorated_func"
        )

        self.assertIsNotNone(patched_code)
        self.assertEqual(patched_code.co_name, "decorated_func")

    def test_cache_management(self):
        """Test cache management functionality."""
        initial_stats = self.patcher.get_cache_statistics()
        self.assertIsInstance(initial_stats, dict)
        self.assertIn("compilation_cache_size", initial_stats)
        self.assertIn("source_cache_size", initial_stats)

        # Clear cache
        self.patcher.clear_cache()

        # Verify cache is cleared
        stats_after_clear = self.patcher.get_cache_statistics()
        self.assertEqual(stats_after_clear["compilation_cache_size"], 0)
        self.assertEqual(stats_after_clear["source_cache_size"], 0)

    def test_enhanced_delta_map(self):
        """Test enhanced delta map creation."""
        delta_map = self.patcher.create_enhanced_delta_map(10, 15)
        expected = {10: 5}  # 15 - 10 = 5
        self.assertEqual(delta_map, expected)

        # Test no change
        no_change_map = self.patcher.create_enhanced_delta_map(10, 10)
        self.assertEqual(no_change_map, {})


class TestIntegration(unittest.TestCase):
    """Integration tests for AST patcher with line number patcher."""

    def test_ast_patcher_integration(self):
        """Test that AST patcher integrates correctly with line number patcher."""
        from IPython.extensions.deduperreload.line_number_patcher import (
            LineNumberPatcher,
        )

        patcher = LineNumberPatcher()

        # Verify AST patcher is available
        self.assertIsNotNone(patcher.ast_patcher)
        self.assertIsInstance(patcher.ast_patcher, ASTPatcher)

        # Verify source extractor is available
        self.assertIsNotNone(patcher.source_extractor)
        self.assertIsInstance(patcher.source_extractor, SourceCodeExtractor)


if __name__ == "__main__":
    unittest.main()
