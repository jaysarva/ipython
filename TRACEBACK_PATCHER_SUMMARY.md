# Traceback Patching Integration with Deduperreload

## Summary

This implementation integrates the traceback patching functionality from `IPython/utils/traceback_patcher.py` with the deduperreload system in `IPython/extensions/deduperreload/`. The integration provides automatic traceback correction when deduperreload patches functions, handling both direct changes and trickle-down effects.

## Key Features Implemented

### 1. Line Mapping Tracking
- **Location**: `IPython/extensions/deduperreload/deduperreload.py`
- **Functionality**: Tracks line number changes for all functions/classes when modules are reloaded
- **Handles**: Trickle-down effects where unchanged functions shift line numbers due to changes earlier in the file

### 2. Automatic Traceback Patching
- **Location**: `IPython/extensions/autoreload.py`
- **Functionality**: Automatically applies line number corrections to tracebacks when deduperreload is active
- **Integration**: Seamlessly switches between patched and original formatters

### 3. Enable/Disable Mechanism
- **Behavior**: Automatically enables traceback patching when deduperreload is active
- **Switching**: Restores original traceback formatting when switching back to superreload
- **Control**: Respects the `%autoreload 2` vs `%autoreload 2-` flag syntax

## Implementation Details

### Line Mapping Calculation
```python
def _calculate_line_mappings(self, filename, old_ast, new_ast):
    """Calculate line number mappings between old and new AST."""
    # Extracts all function/class definitions with line numbers
    # Creates mappings for changed line numbers
    # Handles trickle-down effects for unchanged functions
```

### Traceback Formatter Integration
```python
def _update_traceback_formatter(self):
    """Update the traceback formatter with current line mappings."""
    # Gets line mappings from deduperreload
    # Creates or updates PatchedTB formatter
    # Applies to IPython's InteractiveTB
```

### Mode Switching
```python
# In autoreload magic command:
if was_enabled and not enable_deduperreload:
    self._reloader._restore_original_traceback_formatter()
elif not was_enabled and enable_deduperreload:
    self._reloader._setup_traceback_patching()
```

## Usage Examples

### Basic Usage
```python
%load_ext autoreload
%autoreload 2  # Enables deduperreload with traceback patching

# Edit a file to add lines before existing functions
# Tracebacks will automatically show correct line numbers
```

### Disable Traceback Patching
```python
%autoreload 2-  # Use original algorithm, no traceback patching
# OR
%autoreload --full  # Force full reload, no patching
```

## Benefits

1. **Accurate Tracebacks**: Line numbers in tracebacks match the current file content
2. **Automatic**: No manual intervention required
3. **Comprehensive**: Handles both direct changes and trickle-down effects
4. **Backward Compatible**: Falls back gracefully when deduperreload isn't viable
5. **Context Preservation**: Shows correct code context around error lines

## Files Modified

1. **`IPython/utils/traceback_patcher.py`**: Core traceback patching functionality
2. **`IPython/extensions/deduperreload/deduperreload.py`**: Line mapping tracking
3. **`IPython/extensions/autoreload.py`**: Integration and mode switching
4. **`tests/test_traceback_patcher_demo.py`**: Integration demonstration

## Edge Cases Handled

1. **Un-reloaded Files**: Functions that don't change but shift line numbers
2. **Multiple Changes**: Complex modifications with multiple line shifts
3. **Nested Functions**: Proper handling of nested function definitions
4. **Class Methods**: Correct line mapping for methods within classes
5. **Mode Switching**: Clean transitions between deduperreload and superreload

## Future Enhancements

1. **Cross-File Dependencies**: Track line changes across imported modules
2. **More Granular Control**: Per-module enable/disable of traceback patching
3. **Performance Optimization**: Cache line mappings for frequently reloaded modules
4. **IDE Integration**: Export line mappings for external tools

## Testing

The integration includes comprehensive tests demonstrating:
- Line mapping calculation with trickle-down effects
- Traceback formatter creation and updating
- Enable/disable functionality
- Real-world usage scenarios

## Conclusion

This integration provides a seamless experience where traceback line numbers and context automatically stay synchronized with file changes during deduperreload operations, solving a major usability issue with code reloading in IPython/Jupyter environments. 