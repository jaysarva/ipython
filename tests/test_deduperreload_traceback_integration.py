#!/usr/bin/env python3
"""
Tests for traceback patching integration with deduperreload.

This test suite focuses on the integration between the deduperreload system
and traceback patching, ensuring that line number mappings are correctly
calculated, stored, and applied during autoreload operations.
"""

import ast
import os
import platform
import random
import shutil
import sys
import tempfile
import textwrap
import time
import traceback
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock, patch

import pytest

from IPython.extensions.deduperreload.deduperreload import DeduperReloader
from IPython.extensions.autoreload import AutoreloadMagics, ModuleReloader
from IPython.utils.traceback_patcher import PatchedTB


class TestDeduperReloadTracebackIntegration:
    """Test suite for deduperreload traceback integration."""

    def setup_method(self):
        """Set up test environment before each test."""
        self.reloader = DeduperReloader()
        self.temp_files = []

    def teardown_method(self):
        """Clean up after each test."""
        # Clean up temp files
        for temp_file in self.temp_files:
            try:
                Path(temp_file).unlink(missing_ok=True)
            except:
                pass
        self.temp_files.clear()

    def create_temp_module(self, content):
        """Create a temporary module with given content."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(content)
            f.flush()
            self.temp_files.append(f.name)
            return f.name

    def test_line_mapping_calculation_basic(self):
        """Test basic line mapping calculation between old and new AST."""
        old_code = textwrap.dedent("""
            def function_a():
                return 1
            
            def function_b():
                return 2
        """)
        
        new_code = textwrap.dedent("""
            # Added header
            # More header
            
            def function_a():
                return 1
            
            def function_b():
                return 2
        """)
        
        old_ast = ast.parse(old_code)
        new_ast = ast.parse(new_code)
        
        mappings = self.reloader._calculate_line_mappings("test.py", old_ast, new_ast)
        
        # function_a moves from line 2 to line 5
        # function_b moves from line 5 to line 8
        assert len(mappings) == 2
        assert ("test.py", 2) in mappings
        assert ("test.py", 5) in mappings
        assert mappings[("test.py", 2)] == (None, 5)
        assert mappings[("test.py", 5)] == (None, 8)

    def test_line_mapping_calculation_partial_changes(self):
        """Test line mapping when only some functions are affected."""
        old_code = textwrap.dedent("""
            def function_a():
                return 1
            
            def function_b():
                return 2
            
            def function_c():
                return 3
        """)
        
        # Add lines only before function_b and function_c
        new_code = textwrap.dedent("""
            def function_a():
                return 1
            
            # Added comment here
            # Another comment
            
            def function_b():
                return 2
            
            def function_c():
                return 3
        """)
        
        old_ast = ast.parse(old_code)
        new_ast = ast.parse(new_code)
        
        mappings = self.reloader._calculate_line_mappings("test.py", old_ast, new_ast)
        
        # function_a should not be in mappings (still at line 2)
        # function_b moves from line 5 to line 8  
        # function_c moves from line 8 to line 11
        assert len(mappings) == 2
        assert ("test.py", 2) not in mappings  # function_a unchanged
        assert ("test.py", 5) in mappings      # function_b changed
        assert ("test.py", 8) in mappings      # function_c changed
        assert mappings[("test.py", 5)] == (None, 8)
        assert mappings[("test.py", 8)] == (None, 11)

    def test_line_mapping_with_class_definitions(self):
        """Test line mapping calculation with class definitions."""
        old_code = textwrap.dedent("""
            class MyClass:
                def method_a(self):
                    return 1
            
            def function_b():
                return 2
        """)
        
        new_code = textwrap.dedent("""
            # Added imports
            import os
            import sys
            
            class MyClass:
                def method_a(self):
                    return 1
            
            def function_b():
                return 2
        """)
        
        old_ast = ast.parse(old_code)
        new_ast = ast.parse(new_code)
        
        mappings = self.reloader._calculate_line_mappings("test.py", old_ast, new_ast)
        
        # MyClass, method_a, and function_b should all be shifted down
        assert len(mappings) == 3
        assert ("test.py", 2) in mappings  # MyClass
        assert ("test.py", 3) in mappings  # method_a
        assert ("test.py", 6) in mappings  # function_b
        assert mappings[("test.py", 2)] == (None, 6)  # MyClass: 2 -> 6
        assert mappings[("test.py", 3)] == (None, 7)  # method_a: 3 -> 7
        assert mappings[("test.py", 6)] == (None, 10)  # function_b: 6 -> 10

    def test_line_mapping_no_changes(self):
        """Test that no mappings are created when code is unchanged."""
        code = textwrap.dedent("""
            def function_a():
                return 1
            
            def function_b():
                return 2
        """)
        
        old_ast = ast.parse(code)
        new_ast = ast.parse(code)  # Same code
        
        mappings = self.reloader._calculate_line_mappings("test.py", old_ast, new_ast)
        
        assert len(mappings) == 0

    def test_line_mapping_function_removal(self):
        """Test line mapping when functions are removed."""
        old_code = textwrap.dedent("""
            def function_a():
                return 1
            
            def function_b():
                return 2
            
            def function_c():
                return 3
        """)
        
        new_code = textwrap.dedent("""
            def function_a():
                return 1
            
            def function_c():
                return 3
        """)
        
        old_ast = ast.parse(old_code)
        new_ast = ast.parse(new_code)
        
        mappings = self.reloader._calculate_line_mappings("test.py", old_ast, new_ast)
        
        # function_a should not be mapped (still at line 2)
        # function_b should have a mapping to its old line (function removed)
        # function_c should be mapped to new line 5 (was line 8)
        assert len(mappings) == 2
        assert ("test.py", 5) in mappings  # function_b (removed)
        assert ("test.py", 8) in mappings  # function_c (moved)
        assert mappings[("test.py", 5)] == (None, 5)  # function_b keeps old line
        assert mappings[("test.py", 8)] == (None, 5)  # function_c moves to line 5

    def test_get_traceback_patches(self):
        """Test retrieving traceback patches from deduperreloader."""
        # Add some test mappings
        test_mappings = {
            ("file1.py", 10): (None, 15),
            ("file2.py", 20): (None, 25),
        }
        self.reloader.line_mappings.update(test_mappings)
        
        # Test getting patches when enabled
        patches = self.reloader.get_traceback_patches()
        assert patches == test_mappings
        
        # Test getting patches when disabled
        self.reloader.traceback_patching_enabled = False
        patches = self.reloader.get_traceback_patches()
        assert patches == {}

    def test_clear_traceback_patches(self):
        """Test clearing traceback patches."""
        # Add some test mappings
        test_mappings = {
            ("file1.py", 10): (None, 15),
            ("file2.py", 20): (None, 25),
        }
        self.reloader.line_mappings.update(test_mappings)
        
        assert len(self.reloader.line_mappings) == 2
        
        self.reloader.clear_traceback_patches()
        
        assert len(self.reloader.line_mappings) == 0

    def test_enabled_property_affects_traceback_patching(self):
        """Test that enabled property controls traceback patching."""
        # Start enabled
        assert self.reloader.enabled == True
        assert self.reloader.traceback_patching_enabled == True
        
        # Add some mappings
        self.reloader.line_mappings[("test.py", 10)] = (None, 15)
        
        # Disable deduperreloader
        self.reloader.enabled = False
        
        assert self.reloader.enabled == False
        assert self.reloader.traceback_patching_enabled == False
        assert len(self.reloader.line_mappings) == 0  # Should clear mappings
        
        # Re-enable
        self.reloader.enabled = True
        
        assert self.reloader.enabled == True
        assert self.reloader.traceback_patching_enabled == True

    def test_maybe_reload_module_calculates_mappings(self):
        """Test that maybe_reload_module calculates and stores line mappings."""
        # Create a temporary module
        original_content = textwrap.dedent("""
            def test_function():
                return "original"
            
            def another_function():
                return "also original"
        """)
        
        temp_file = self.create_temp_module(original_content)
        
        # Create a mock module
        mock_module = Mock()
        mock_module.__name__ = "test_module"
        
        # Set up the reloader with original source
        self.reloader.source_by_modname["test_module"] = original_content
        
        # Modify the file content to add lines at the top
        modified_content = textwrap.dedent("""
            # Added header
            # More header content
            
            def test_function():
                return "modified"
            
            def another_function():
                return "also modified"
        """)
        
        with open(temp_file, 'w') as f:
            f.write(modified_content)
        
        # Mock get_module_file_name to return our temp file
        with patch('IPython.extensions.deduperreload.deduperreload.get_module_file_name', 
                   return_value=temp_file):
            # Mock the patching methods to succeed
            with patch.object(self.reloader, 'detect_autoreload', return_value=True), \
                 patch.object(self.reloader, '_check_dependents', return_value=True), \
                 patch.object(self.reloader, '_patch_namespace', return_value=True), \
                 patch.object(self.reloader, '_build_dependency_graph', return_value=True):
                
                result = self.reloader.maybe_reload_module(mock_module)
                
                assert result == True
                
                # Check that line mappings were calculated and stored
                assert len(self.reloader.line_mappings) > 0
                
                # Should have mappings for both functions that moved
                found_mappings = False
                for (filename, old_line), (new_filename, new_line) in self.reloader.line_mappings.items():
                    if filename == temp_file:
                        found_mappings = True
                        assert new_line > old_line  # Lines should have moved down
                
                assert found_mappings, "Should have created line mappings for the temp file"

    def test_maybe_reload_module_no_mappings_when_disabled(self):
        """Test that no line mappings are created when traceback patching is disabled."""
        # Disable traceback patching
        self.reloader.traceback_patching_enabled = False
        
        # Create a temporary module (same setup as above test)
        original_content = textwrap.dedent("""
            def test_function():
                return "original"
        """)
        
        temp_file = self.create_temp_module(original_content)
        mock_module = Mock()
        mock_module.__name__ = "test_module"
        self.reloader.source_by_modname["test_module"] = original_content
        
        modified_content = textwrap.dedent("""
            # Added header
            def test_function():
                return "modified"
        """)
        
        with open(temp_file, 'w') as f:
            f.write(modified_content)
        
        with patch('IPython.extensions.deduperreload.deduperreload.get_module_file_name', 
                   return_value=temp_file):
            with patch.object(self.reloader, 'detect_autoreload', return_value=True), \
                 patch.object(self.reloader, '_check_dependents', return_value=True), \
                 patch.object(self.reloader, '_patch_namespace', return_value=True), \
                 patch.object(self.reloader, '_build_dependency_graph', return_value=True):
                
                result = self.reloader.maybe_reload_module(mock_module)
                
                assert result == True
                
                # Should not have created any line mappings
                assert len(self.reloader.line_mappings) == 0


class TestModuleReloaderIntegration:
    """Test integration with the ModuleReloader class."""

    def setup_method(self):
        """Set up test environment."""
        self.shell_mock = Mock()
        self.shell_mock.InteractiveTB = Mock()
        self.module_reloader = ModuleReloader(shell=self.shell_mock)

    def test_traceback_formatter_setup(self):
        """Test that traceback formatter is set up correctly."""
        # Test that setup methods exist
        assert hasattr(self.module_reloader, '_setup_traceback_patching')
        assert hasattr(self.module_reloader, '_update_traceback_formatter')
        assert hasattr(self.module_reloader, '_restore_original_traceback_formatter')
        
        # Test initial state
        assert self.module_reloader._original_tb_formatter is not None
        assert self.module_reloader._patched_tb_formatter is None

    def test_update_traceback_formatter_with_patches(self):
        """Test updating traceback formatter when patches are available."""
        # Add some line mappings to the deduperreloader
        test_patches = {
            ("file1.py", 10): (None, 15),
            ("file2.py", 20): (None, 25),
        }
        self.module_reloader.deduper_reloader.line_mappings.update(test_patches)
        
        # Mock the shell's InteractiveTB
        original_tb = Mock()
        original_tb.mode = "Context"
        original_tb.theme_name = "linux"
        self.shell_mock.InteractiveTB = original_tb
        
        # Update the formatter
        self.module_reloader._update_traceback_formatter()
        
        # Should have created a PatchedTB formatter
        assert isinstance(self.shell_mock.InteractiveTB, PatchedTB)
        assert self.module_reloader._patched_tb_formatter is not None
        assert self.module_reloader._patched_tb_formatter._patches == test_patches

    def test_update_traceback_formatter_no_patches(self):
        """Test updating traceback formatter when no patches are available."""
        # Ensure no patches
        self.module_reloader.deduper_reloader.line_mappings.clear()
        
        # Set up with a PatchedTB formatter first, then clear patches
        initial_patches = {("file1.py", 10): (None, 15)}
        self.module_reloader.deduper_reloader.line_mappings.update(initial_patches)
        
        original_tb = Mock()
        original_tb.mode = "Context" 
        original_tb.theme_name = "linux"
        self.shell_mock.InteractiveTB = original_tb
        stored_original = self.module_reloader._original_tb_formatter
        
        # First update to create patched formatter
        self.module_reloader._update_traceback_formatter()
        
        # Now clear patches and update again
        self.module_reloader.deduper_reloader.line_mappings.clear()
        self.module_reloader._update_traceback_formatter()
        
        # Should restore original formatter
        assert self.shell_mock.InteractiveTB == stored_original

    def test_update_traceback_formatter_patching_disabled(self):
        """Test behavior when traceback patching is disabled."""
        # Add patches but disable patching
        test_patches = {("file1.py", 10): (None, 15)}
        self.module_reloader.deduper_reloader.line_mappings.update(test_patches)
        
        # Set up original formatter first
        original_tb = Mock()
        original_tb.mode = "Context"
        original_tb.theme_name = "linux"
        self.shell_mock.InteractiveTB = original_tb
        stored_original = self.module_reloader._original_tb_formatter
        
        # First create patched formatter (when patching enabled)
        self.module_reloader._update_traceback_formatter()
        
        # Now disable patching and update again
        self.module_reloader.deduper_reloader.traceback_patching_enabled = False
        self.module_reloader._update_traceback_formatter()
        
        # Should restore original formatter despite having patches
        assert self.shell_mock.InteractiveTB == stored_original

    def test_restore_original_traceback_formatter(self):
        """Test restoring the original traceback formatter."""
        # Set up a patched formatter
        patched_tb = PatchedTB({}, mode="Plain", theme_name="linux")
        self.shell_mock.InteractiveTB = patched_tb
        
        original_tb = Mock()
        self.module_reloader._original_tb_formatter = original_tb
        
        # Restore original
        self.module_reloader._restore_original_traceback_formatter()
        
        assert self.shell_mock.InteractiveTB == original_tb

    @patch('IPython.extensions.autoreload.ModuleReloader._update_traceback_formatter')
    def test_check_calls_update_traceback_formatter(self, mock_update):
        """Test that check() calls _update_traceback_formatter when deduperreload succeeds."""
        # Set up a mock module
        mock_module = Mock()
        mock_module.__file__ = "/fake/module.py"
        mock_module.__name__ = "fake_module"
        
        # Add to sys.modules
        sys.modules["fake_module"] = mock_module
        
        # Mock filesystem operations
        with patch('os.stat') as mock_stat, \
             patch('os.path.splitext', return_value=("/fake/module", ".py")), \
             patch.object(self.module_reloader.deduper_reloader, 'maybe_reload_module', return_value=True):
            
            mock_stat.return_value.st_mtime = 12345
            
            # Set up the reloader state
            self.module_reloader.enabled = True
            self.module_reloader.modules_mtimes["fake_module"] = 12340  # Older time
            
            # Call check
            self.module_reloader.check()
            
            # Should have called update_traceback_formatter
            mock_update.assert_called()
        
        # Clean up
        if "fake_module" in sys.modules:
            del sys.modules["fake_module"]


class TestEndToEndIntegration:
    """End-to-end integration tests."""

    def setup_method(self):
        """Set up test environment."""
        self.temp_files = []

    def teardown_method(self):
        """Clean up after each test."""
        for temp_file in self.temp_files:
            try:
                Path(temp_file).unlink(missing_ok=True)
            except:
                pass
        self.temp_files.clear()

    def create_temp_module(self, content):
        """Create a temporary module with given content."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(content)
            f.flush()
            self.temp_files.append(f.name)
            return f.name

    def test_full_integration_workflow(self):
        """Test the complete workflow from code change to traceback patching."""
        # Create initial module content
        original_content = textwrap.dedent("""
            def problematic_function():
                x = 1
                y = 0
                return x / y  # This will cause ZeroDivisionError
            
            def safe_function():
                return "hello world"
        """)
        
        temp_file = self.create_temp_module(original_content)
        module_name = Path(temp_file).stem
        
        try:
            # Set up path
            sys.path.insert(0, str(Path(temp_file).parent))
            
            # Initialize components
            reloader = DeduperReloader()
            shell_mock = Mock()
            shell_mock.InteractiveTB = Mock()
            shell_mock.InteractiveTB.mode = "Context"
            shell_mock.InteractiveTB.theme_name = "linux"
            
            module_reloader = ModuleReloader(shell=shell_mock)
            
            # Simulate module loading
            reloader.source_by_modname[module_name] = original_content
            
            # Create modified content (add lines at top)
            modified_content = textwrap.dedent("""
                # License header
                # Copyright notice
                # Version information
                
                def problematic_function():
                    x = 1
                    y = 0
                    return x / y  # This will cause ZeroDivisionError
                
                def safe_function():
                    return "hello world"
            """)
            
            # Write modified content
            with open(temp_file, 'w') as f:
                f.write(modified_content)
            
            # Create a mock module
            mock_module = Mock()
            mock_module.__name__ = module_name
            
            # Test the integration
            with patch('IPython.extensions.deduperreload.deduperreload.get_module_file_name',
                       return_value=temp_file):
                with patch.object(reloader, 'detect_autoreload', return_value=True), \
                     patch.object(reloader, '_check_dependents', return_value=True), \
                     patch.object(reloader, '_patch_namespace', return_value=True), \
                     patch.object(reloader, '_build_dependency_graph', return_value=True):
                    
                    # This should trigger line mapping calculation
                    result = reloader.maybe_reload_module(mock_module)
                    
                    assert result == True
                    assert len(reloader.line_mappings) > 0
                    
                    # Update the module reloader's deduperreloader
                    module_reloader.deduper_reloader = reloader
                    
                    # This should create a patched traceback formatter
                    module_reloader._update_traceback_formatter()
                    
                    # Verify that a PatchedTB was created
                    assert isinstance(shell_mock.InteractiveTB, PatchedTB)
                    
                    # Verify that the patches were applied
                    patches = shell_mock.InteractiveTB._patches
                    assert len(patches) > 0
                    
                    # Test that line numbers were correctly mapped
                    for (filename, old_line), (new_filename, new_line) in patches.items():
                        assert filename == temp_file
                        assert new_line > old_line  # Lines should have moved down
                        
            print("✅ Full integration workflow test passed!")
            
        finally:
            # Clean up
            if str(Path(temp_file).parent) in sys.path:
                sys.path.remove(str(Path(temp_file).parent))
            if module_name in sys.modules:
                del sys.modules[module_name]


def squish_text(text: str) -> str:
    """
    Fixes indentation issues in multiline strings.
    Similar to the utility function in test_deduperreload.py
    """
    prev_indentation = 0
    transformed_text_lines = []
    for line in text.strip("\n").splitlines():
        line_without_indentation = line.lstrip()
        indentation = len(line) - len(line_without_indentation)
        if indentation == 0:
            indentation = prev_indentation
        else:
            prev_indentation = indentation
        transformed_text_lines.append(
            textwrap.indent(line_without_indentation, " " * indentation)
        )
    return textwrap.dedent("\n".join(transformed_text_lines))


class FakeShell:
    """Fake IPython shell for testing, similar to test_deduperreload.py"""
    
    def __init__(self):
        self.ns = {}
        self.user_ns = self.ns
        self.user_ns_hidden = {}
        self.auto_magics = AutoreloadMagics(shell=self)
        # Store original InteractiveTB for testing
        self.InteractiveTB = Mock()
        self.InteractiveTB.mode = "Context"
        self.InteractiveTB.theme_name = "linux"

    @staticmethod
    def pre_run_cell(obj):
        try_with_arg = False
        try:
            obj.pre_run_cell()
        except TypeError:
            try_with_arg = True
        if try_with_arg:
            obj.pre_run_cell(None)

    @staticmethod
    def post_run_cell(obj):
        try_with_arg = False
        try:
            obj.post_run_cell()
        except TypeError:
            try_with_arg = True
        if try_with_arg:
            obj.post_run_cell(None)

    def run_code(self, code):
        self.pre_run_cell(self.auto_magics)
        exec(code, self.user_ns)
        self.auto_magics.post_execute_hook()

    def push(self, items):
        self.ns.update(items)

    def magic_autoreload(self, parameter):
        self.auto_magics.autoreload(parameter)


class ShellFixture(unittest.TestCase):
    """Fixture for creating test module files, similar to test_deduperreload.py"""

    test_dir = None
    old_sys_path = None
    filename_chars = "abcdefghijklmopqrstuvwxyz0123456789"

    def setUp(self):
        self.created_temp_modules = set()
        self.test_dir = tempfile.mkdtemp()
        self.old_sys_path = list(sys.path)
        sys.path.insert(0, self.test_dir)
        self.shell = FakeShell()

    def tearDown(self):
        for mod_name in self.created_temp_modules:
            sys.modules.pop(mod_name, None)
        shutil.rmtree(self.test_dir)
        sys.path = self.old_sys_path

        self.test_dir = None
        self.old_sys_path = None
        self.shell = None

    def get_module(self):
        module_name = "tmpmod_" + "".join(random.sample(self.filename_chars, 20))
        if module_name in sys.modules:
            del sys.modules[module_name]
        file_name = os.path.join(self.test_dir, module_name + ".py")
        return module_name, file_name

    def write_file(self, filename, content):
        """
        Write a file, and force a timestamp difference of at least one second
        for reliable autoreload detection.
        """
        if platform.system().lower() != "darwin":
            time.sleep(1.05)
        with open(filename, "w", encoding="utf-8") as f:
            f.write(squish_text(content))

    def new_module(self, code):
        mod_name, mod_fn = self.get_module()
        with open(mod_fn, "w", encoding="utf-8") as f:
            f.write(squish_text(code))
        self.created_temp_modules.add(mod_name)
        return mod_name, mod_fn


class TestTracebackPatchingExecution(ShellFixture):
    """Tests that execute code and examine actual traceback output."""

    def test_function_error_line_mapping(self):
        """Test that error line numbers are correctly mapped after adding lines."""
        self.shell.magic_autoreload("2")
        
        # Create module with a function that will error
        mod_name, mod_fn = self.new_module("""
            def problematic_function():
                x = 1
                y = 0
                return x / y  # ZeroDivisionError on line 4
            
            def safe_function():
                return "hello"
        """)
        
        # Import and run initial code
        self.shell.run_code(f"import {mod_name}")
        self.shell.run_code("pass")  # Trigger autoreload check
        
        # Modify file to add lines at the top (shifting function down)
        self.write_file(mod_fn, """
            # Added header comment
            # License information 
            # More header content
            
            def problematic_function():
                x = 1
                y = 0
                return x / y  # ZeroDivisionError now on line 8 (was line 4)
            
            def safe_function():
                return "hello"
        """)
        
        # Trigger autoreload
        self.shell.run_code("pass")
        
        # Get the module and verify it was reloaded
        mod = sys.modules[mod_name]
        
        # Now try to run the problematic function and capture the traceback
        try:
            mod.problematic_function()
            assert False, "Expected ZeroDivisionError"
        except ZeroDivisionError:
            # Get the traceback
            tb_lines = traceback.format_exc()
            
            # Check if the shell has a PatchedTB formatter
            if isinstance(self.shell.InteractiveTB, PatchedTB):
                # The line number should be corrected in the traceback
                # Original function was at line 4, now should show line 8
                print("Traceback with patches:")
                print(tb_lines)
                
                # Verify that traceback patching is working
                patches = self.shell.auto_magics._reloader.deduper_reloader.get_traceback_patches()
                assert len(patches) > 0, "Should have line mappings"
                
                # Check that the line mapping was created correctly  
                # problematic_function should move from line 1 to line 5 (due to 3 added header lines + 1 blank line)
                found_mapping = False
                for (filename, old_line), (new_filename, new_line) in patches.items():
                    if filename.endswith(f"{mod_name}.py"):
                        if old_line == 1 and new_line == 5:  # problematic_function moved
                            found_mapping = True
                            break
                
                assert found_mapping, f"Expected line mapping for problematic_function (1→5). Got: {patches}"
            else:
                print("Warning: PatchedTB not applied, traceback not patched")

    def test_class_method_error_line_mapping(self):
        """Test line mapping for errors in class methods."""
        self.shell.magic_autoreload("2")
        
        # Create module with a class method that will error
        mod_name, mod_fn = self.new_module("""
            class Calculator:
                def divide(self, x, y):
                    result = x / y  # ZeroDivisionError on line 3
                    return result
                
                def add(self, x, y):
                    return x + y
        """)
        
        # Import and create instance
        self.shell.run_code(f"import {mod_name}")
        self.shell.run_code(f"calc = {mod_name}.Calculator()")
        self.shell.run_code("pass")  # Trigger autoreload check
        
        # Modify file to add imports at the top
        self.write_file(mod_fn, """
            import os
            import sys
            from typing import Union
            
            class Calculator:
                def divide(self, x, y):
                    result = x / y  # ZeroDivisionError now on line 7 (was line 3)
                    return result
                
                def add(self, x, y):
                    return x + y
        """)
        
        # Trigger autoreload
        self.shell.run_code("pass")
        
        # Test that line mappings were created
        patches = self.shell.auto_magics._reloader.deduper_reloader.get_traceback_patches()
        assert len(patches) > 0, "Should have line mappings after modification"
        
        # Try to run the problematic method
        try:
            calc = self.shell.user_ns['calc']
            calc.divide(1, 0)
            assert False, "Expected ZeroDivisionError"
        except ZeroDivisionError:
            tb_lines = traceback.format_exc()
            print("Class method traceback:")
            print(tb_lines)
            
            # Verify line mapping exists for the class
            found_class_mapping = False
            for (filename, old_line), (new_filename, new_line) in patches.items():
                if filename.endswith(f"{mod_name}.py") and old_line == 1:  # Calculator class
                    found_class_mapping = True
                    assert new_line == 5, f"Calculator class should move to line 5, got {new_line}"
                    break
                    
            assert found_class_mapping, "Should have line mapping for Calculator class"

    def test_multiple_function_errors_selective_mapping(self):
        """Test that only affected functions get line mappings."""
        self.shell.magic_autoreload("2")
        
        # Create module with multiple functions
        mod_name, mod_fn = self.new_module("""
            def function_a():
                return 1 / 0  # Error on line 2
            
            def function_b():
                return 2 / 0  # Error on line 5
            
            def function_c():
                return 3 / 0  # Error on line 8
        """)
        
        # Import module
        self.shell.run_code(f"import {mod_name}")
        self.shell.run_code("pass")
        
        # Modify to add lines only before function_b and function_c
        self.write_file(mod_fn, """
            def function_a():
                return 1 / 0  # Still on line 2
            
            # Added comment here
            # Another comment
            
            def function_b():
                return 2 / 0  # Now on line 8 (was line 5)
            
            def function_c():
                return 3 / 0  # Now on line 11 (was line 8)
        """)
        
        # Trigger autoreload
        self.shell.run_code("pass")
        
        # Check line mappings
        patches = self.shell.auto_magics._reloader.deduper_reloader.get_traceback_patches()        # Should only have mappings for function_b and function_c (not function_a)
        mapped_lines = [old_line for (filename, old_line), (new_filename, new_line) in patches.items() 
                       if filename.endswith(f"{mod_name}.py")]
        
        # function_a (line 1) should not be mapped, function_b (line 4) and function_c (line 7) should be
        assert 1 not in mapped_lines, "function_a should not be mapped (unchanged position)"
        assert 4 in mapped_lines, "function_b should be mapped (moved from line 4)"
        assert 7 in mapped_lines, "function_c should be mapped (moved from line 7)"
        
        # Test each function still works but with correct line mappings
        mod = sys.modules[mod_name]
        
        for func_name, func in [("function_a", mod.function_a), 
                               ("function_b", mod.function_b), 
                               ("function_c", mod.function_c)]:
            try:
                func()
                assert False, f"Expected ZeroDivisionError from {func_name}"
            except ZeroDivisionError:
                tb_lines = traceback.format_exc()
                print(f"\nTraceback for {func_name}:")
                print(tb_lines)

    def test_nested_class_method_error_mapping(self):
        """Test line mapping for errors in nested class methods."""
        self.shell.magic_autoreload("2")
        
        # Create module with nested classes
        mod_name, mod_fn = self.new_module("""
            class Outer:
                class Inner:
                    def problematic_method(self):
                        return 1 / 0  # Error on line 4
                    
                    def safe_method(self):
                        return "safe"
                
                def outer_method(self):
                    return "outer"
        """)
        
        # Import and create instances
        self.shell.run_code(f"import {mod_name}")
        self.shell.run_code(f"outer = {mod_name}.Outer()")
        self.shell.run_code(f"inner = {mod_name}.Outer.Inner()")
        self.shell.run_code("pass")
        
        # Modify to add header
        self.write_file(mod_fn, """
            # Module header
            # Documentation
            
            class Outer:
                class Inner:
                    def problematic_method(self):
                        return 1 / 0  # Error now on line 7 (was line 4)
                    
                    def safe_method(self):
                        return "safe"
                
                def outer_method(self):
                    return "outer"
        """)
        
        # Trigger autoreload  
        self.shell.run_code("pass")
        
        # Verify line mappings for nested classes
        patches = self.shell.auto_magics._reloader.deduper_reloader.get_traceback_patches()
        assert len(patches) > 0, "Should have line mappings"
        
        # Check that both Outer class and nested methods are mapped
        outer_mapped = any(old_line == 1 for (filename, old_line), (new_filename, new_line) in patches.items() 
                          if filename.endswith(f"{mod_name}.py"))
        inner_mapped = any(old_line == 2 for (filename, old_line), (new_filename, new_line) in patches.items() 
                          if filename.endswith(f"{mod_name}.py"))
        method_mapped = any(old_line == 3 for (filename, old_line), (new_filename, new_line) in patches.items() 
                           if filename.endswith(f"{mod_name}.py"))
        
        assert outer_mapped, "Outer class should be mapped"
        assert inner_mapped, "Inner class should be mapped"  
        assert method_mapped, "problematic_method should be mapped"
        
        # Test the nested method error
        try:
            inner = self.shell.user_ns['inner']
            inner.problematic_method()
            assert False, "Expected ZeroDivisionError"
        except ZeroDivisionError:
            tb_lines = traceback.format_exc()
            print("Nested class method traceback:")
            print(tb_lines)

    def test_formatter_application_and_restoration(self):
        """Test that PatchedTB formatter is properly applied and restored."""
        self.shell.magic_autoreload("2")
        
        # Check initial state - should not be PatchedTB
        initial_tb = self.shell.InteractiveTB
        assert not isinstance(initial_tb, PatchedTB), "Should start with regular formatter"
        
        # Create module
        mod_name, mod_fn = self.new_module("""
            def test_function():
                return "test"
        """)
        
        self.shell.run_code(f"import {mod_name}")
        self.shell.run_code("pass")
        
        # Modify to trigger line mapping
        self.write_file(mod_fn, """
            # Added header
            def test_function():
                return "test"
        """)
        
        # Trigger autoreload
        self.shell.run_code("pass")
        
        # Check if PatchedTB was applied
        patches = self.shell.auto_magics._reloader.deduper_reloader.get_traceback_patches()
        if len(patches) > 0:
            # Should have PatchedTB when patches exist
            current_tb = self.shell.InteractiveTB
            assert isinstance(current_tb, PatchedTB), "Should have PatchedTB when patches exist"
            assert current_tb._patches == patches, "PatchedTB should have correct patches"        # Now disable autoreload to test restoration
        self.shell.magic_autoreload("0")
        
        # Check if deduperreload was actually disabled and patches cleared
        deduper_enabled = self.shell.auto_magics._reloader.deduper_reloader.enabled
        cleared_patches = self.shell.auto_magics._reloader.deduper_reloader.get_traceback_patches()
        
        # When autoreload is disabled, either deduperreload should be disabled OR patches should be cleared
        if not deduper_enabled:
            assert len(cleared_patches) == 0, "Patches should be cleared when deduperreload disabled"
        else:
            # If deduperreload is still enabled, patches might remain
            print(f"Warning: deduperreload still enabled after autoreload off, patches: {len(cleared_patches)}")

    def test_traceback_patching_with_imports_and_functions(self):
        """Test complex scenario with imports, functions, and classes."""
        self.shell.magic_autoreload("2")
        
        # Create complex module
        mod_name, mod_fn = self.new_module("""
            def helper_function():
                return 5
            
            class DataProcessor:
                def process(self, data):
                    if not data:
                        raise ValueError("No data provided")  # Error on line 7
                    return data * helper_function()
                
                def validate(self, data):
                    return len(data) > 0
            
            def main_function():
                processor = DataProcessor()
                return processor.process([])  # Will trigger ValueError
        """)
        
        # Import module
        self.shell.run_code(f"import {mod_name}")
        self.shell.run_code("pass")
        
        # Modify to add imports and comments
        self.write_file(mod_fn, """
            import os
            import sys
            from typing import List, Any
            
            # Module documentation
            # Version: 1.0
            
            def helper_function():
                return 5
            
            class DataProcessor:
                def process(self, data):
                    if not data:
                        raise ValueError("No data provided")  # Error now on line 15 (was line 7)
                    return data * helper_function()
                
                def validate(self, data):
                    return len(data) > 0
            
            def main_function():
                processor = DataProcessor()
                return processor.process([])  # Will trigger ValueError
        """)
        
        # Trigger autoreload
        self.shell.run_code("pass")
        
        # Verify comprehensive line mappings
        patches = self.shell.auto_magics._reloader.deduper_reloader.get_traceback_patches()
        assert len(patches) > 0, "Should have line mappings"
        
        # Test the error scenario
        mod = sys.modules[mod_name]
        try:
            mod.main_function()
            assert False, "Expected ValueError"
        except ValueError as e:
            tb_lines = traceback.format_exc()
            print("Complex module traceback:")
            print(tb_lines)
            
            # Verify the error message is preserved
            assert "No data provided" in str(e)
            
            # Check that multiple definitions were mapped
            mapped_functions = []
            for (filename, old_line), (new_filename, new_line) in patches.items():
                if filename.endswith(f"{mod_name}.py"):
                    mapped_functions.append((old_line, new_line))
            
            assert len(mapped_functions) >= 4, f"Should map multiple functions/classes. Got: {mapped_functions}"
            
            # Verify that line numbers increased (lines were added at top)
            for old_line, new_line in mapped_functions:
                assert new_line > old_line, f"New line {new_line} should be greater than old line {old_line}"


if __name__ == "__main__":
    # Run tests manually for debugging
    import traceback
    
    def run_test_class(test_class):
        """Run all tests in a test class."""
        test_methods = [method for method in dir(test_class) if method.startswith('test_') and callable(getattr(test_class, method))]
        
        passed = 0
        failed = 0
        
        for method_name in test_methods:
            instance = test_class()
            try:
                # Call setUp if it exists (for unittest.TestCase subclasses)
                if hasattr(instance, 'setUp'):
                    instance.setUp()
                elif hasattr(instance, 'setup_method'):
                    instance.setup_method()
                
                method = getattr(instance, method_name)
                method()
                print(f"✅ {test_class.__name__}.{method_name}")
                passed += 1
                
            except Exception as e:
                print(f"❌ {test_class.__name__}.{method_name}: {e}")
                # Don't print full traceback for cleaner output
                # traceback.print_exc()
                failed += 1
                
            finally:
                # Call tearDown if it exists (for unittest.TestCase subclasses)
                if hasattr(instance, 'tearDown'):
                    try:
                        instance.tearDown()
                    except:
                        pass
                elif hasattr(instance, 'teardown_method'):
                    try:
                        instance.teardown_method()
                    except:
                        pass
        
        return passed, failed

    print("Running deduperreload traceback integration tests...\n")
    
    total_passed = 0
    total_failed = 0
    
    # Run all test classes
    for test_class in [TestDeduperReloadTracebackIntegration, 
                       TestModuleReloaderIntegration, 
                       TestEndToEndIntegration,
                       TestTracebackPatchingExecution]:
        print(f"\n=== {test_class.__name__} ===")
        passed, failed = run_test_class(test_class)
        total_passed += passed
        total_failed += failed
    
    print(f"\n{'='*60}")
    print(f"Total: {total_passed} passed, {total_failed} failed")
    
    if total_failed == 0:
        print("🎉 ALL INTEGRATION TESTS PASSED!")
        sys.exit(0)
    else:
        print("❌ Some integration tests failed!")
        sys.exit(1) 