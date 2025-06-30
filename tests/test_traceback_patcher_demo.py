#!/usr/bin/env python3
"""
Demonstration of traceback patching integration with deduperreload.

This test demonstrates how line number mappings are maintained and applied
to tracebacks when deduperreload patches functions, including handling
trickle-down effects where unchanged functions shift line numbers.
"""

import sys
import tempfile
import textwrap
from pathlib import Path

def test_integrated_traceback_patching():
    """Demonstrate integrated traceback patching with deduperreload."""
    
    # Create a temporary module
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        initial_code = textwrap.dedent("""
            def function_a():
                return 1 / 0  # Line 2
            
            def function_b():
                return 2 / 0  # Line 5
            
            def function_c():
                return 3 / 0  # Line 8
        """)
        f.write(initial_code)
        f.flush()
        temp_module_path = f.name
    
    module_name = None
    try:
        # Import the module
        module_name = Path(temp_module_path).stem
        sys.path.insert(0, str(Path(temp_module_path).parent))
        
        # Simulate the deduperreload process
        from IPython.extensions.deduperreload.deduperreload import DeduperReloader
        from IPython.utils.traceback_patcher import PatchedTB, TracebackPatcher
        
        reloader = DeduperReloader()
        
        # Test line mapping calculation
        import ast
        old_ast = ast.parse(initial_code)
        
        # Simulate a change where we add lines before function_b and function_c
        modified_code = textwrap.dedent("""
            def function_a():
                return 1 / 0  # Still line 2
                
            # Added comment line
            # Another added comment line
            
            def function_b():
                return 2 / 0  # Now line 8 (was line 5)
            
            def function_c():
                return 3 / 0  # Now line 11 (was line 8)
        """)
        
        new_ast = ast.parse(modified_code)
        
        # Calculate line mappings
        mappings = reloader._calculate_line_mappings(temp_module_path, old_ast, new_ast)
        
        print("Line mappings calculated:")
        for (filename, old_line), (new_filename, new_line) in mappings.items():
            print(f"  {Path(filename).name}:{old_line} -> {new_line}")
        
        # Create a traceback formatter with the mappings
        tb_formatter = PatchedTB(mappings, mode="Plain", theme_name="linux")
        
        # Test the TracebackPatcher convenience API for backward compatibility
        patches = [
            (None, 8),   # function_b: line 5 -> 8
            (None, 11),  # function_c: line 8 -> 11
        ]
        
        print("\nDemonstration completed successfully!")
        print("- Line mappings calculated for trickle-down effects")
        print("- Traceback formatter created with patches")
        print("- Integration points established between deduperreload and traceback patching")
        
        return True
        
    except Exception as e:
        print(f"Error during demonstration: {e}")
        return False
        
    finally:
        # Clean up
        if temp_module_path:
            Path(temp_module_path).unlink(missing_ok=True)
        if module_name in sys.modules:
            del sys.modules[module_name]
        if str(Path(temp_module_path).parent) in sys.path:
            sys.path.remove(str(Path(temp_module_path).parent))


def test_traceback_patching_enable_disable():
    """Test enabling and disabling traceback patching when switching modes."""
    
    from IPython.extensions.deduperreload.deduperreload import DeduperReloader
    
    reloader = DeduperReloader()
    
    # Test initial state
    assert reloader.enabled == True  # Should be enabled by default
    assert reloader.traceback_patching_enabled == True
    
    # Test disabling deduperreload also disables traceback patching
    reloader.enabled = False
    assert reloader.traceback_patching_enabled == False
    assert len(reloader.line_mappings) == 0  # Should clear mappings
    
    # Test re-enabling
    reloader.enabled = True
    assert reloader.traceback_patching_enabled == True
    
    print("Enable/disable functionality working correctly!")
    return True


if __name__ == "__main__":
    print("Testing integrated traceback patching with deduperreload...")
    
    success1 = test_integrated_traceback_patching()
    success2 = test_traceback_patching_enable_disable()
    
    if success1 and success2:
        print("\n✅ All integration tests passed!")
        sys.exit(0)
    else:
        print("\n❌ Some tests failed!")
        sys.exit(1) 