# Line Number Tracking and Patching Workflow in deduperreload

This document describes the complete workflow of how line number tracking and patching works in the deduperreload extension, based on the current implementation.

## Overview

The line number patching system ensures that tracebacks show accurate line numbers even after code has been reloaded multiple times. When functions are added, removed, or modified, all subsequent code objects in the module need their line numbers updated to maintain traceback accuracy.

## Key Components

### 1. ModuleSourceTracker (`IPython/extensions/deduperreload/line_number_tracker.py`)
- **Purpose**: Tracks source code changes and parses AST positions
- **Key Methods**:
  - `track_module_source()`: Caches module source code
  - `parse_all_code_positions()`: Extracts positions of all code constructs via AST

### 2. LineNumberPatcher (`IPython/extensions/deduperreload/line_number_patcher.py`)
- **Purpose**: Main orchestrator for line number patching
- **Key Methods**:
  - `update_all_code_object_line_numbers()`: Entry point for patching
  - `find_matching_position()`: Maps code objects to current source positions
  - `patch_single_code_object_lines()`: Updates individual code object line numbers

### 3. ASTPatcher (`IPython/extensions/deduperreload/ast_patcher.py`)
- **Purpose**: Computes line-number deltas and safely updates code objects via `CodeType.replace`
- **Note**: No AST recompilation/rebinding is performed solely for line fixups in the current implementation

## Detailed Workflow

### Phase 1: Source Tracking and Position Detection

```
Module Reload Trigger
        ↓
ModuleSourceTracker.track_module_source()  [line_number_tracker.py:85]
        ↓
ModuleSourceTracker.parse_all_code_positions()  [line_number_tracker.py:109]
        ↓
AST.parse() + _extract_all_positions()  [line_number_tracker.py:128-152]
        ↓
Creates CodePosition objects for each function/class/method
        ↓
Stores positions in source_tracker.code_positions[module_name]
```

**Key Data Structure**: `CodePosition` (`line_number_tracker.py:18-36`)
```python
@dataclass
class CodePosition:
    name: str           # "MyClass.method" 
    type: str           # "function", "method", "class"
    start_line: int     # Line where construct starts
    end_line: int       # Line where construct ends  
    original_start: int # Original position for debugging
```

### Phase 2: Code Object Discovery and Analysis

```
LineNumberPatcher.update_all_code_object_line_numbers()  [line_number_patcher.py:73]
        ↓
_patch_all_code_objects()  [line_number_patcher.py:150]
        ↓
find_all_code_objects_in_module()  [line_number_patcher.py:169]
        ↓
_extract_code_objects_recursive()  [line_number_patcher.py:203]
        ↓
Creates list of (qualified_name, code_object) tuples
```

**Code Object Discovery Process**:
1. Scans all module attributes (`vars(module)`)
2. Recursively extracts from classes → methods → properties → static/class methods
3. Handles qualified naming: `"module.Class.method"`

### Phase 3: Position Matching and Delta Calculation

```
For each discovered code object:
        ↓
find_matching_position()  [line_number_patcher.py:381]
        ↓
Unified candidate generation approach:
  - Generate all candidate names with _generate_candidate_names()
  - Try candidates in priority order until match found
  - Special handling for lambda expressions with pattern matching
        ↓
Returns current_line from AST positions
        ↓
Compare with old_line = obj.__code__.co_firstlineno  [line_number_patcher.py:676]
        ↓
If current_line != old_line → trigger patching
```

### Phase 4: Line Number Patching

```
patch_single_code_object_lines()  [line_number_patcher.py:499]
        ↓
_create_updated_code_object()  [line_number_patcher.py:550]
        ↓
Calculate line_delta = new_first_line - old_first_line
        ↓
_create_code_via_enhanced_ast_approach()  [line_number_patcher.py:569]
```

**Current Approach**:
```
_get_enhanced_source_code()
        ↓
Special handling for co_filename="<string>"
  - Extract module name from qualified object name
  - Lookup in source_tracker.module_snapshots
        ↓
Create enhanced delta map (old_line → new_line)
        ↓
Use CodeType.replace to update co_firstlineno
        ↓
Recursively apply to nested functions via co_consts
```

## Critical Code Paths

### Source Code Lookup (current)

The function handles two scenarios:

1. **Normal files**: Match `co_filename` with cached module names
2. **`<string>` code objects**: Extract module from qualified object name and use snapshot cache

```python
def _get_enhanced_source_code(self, code: types.CodeType, obj_name: str):
    filename = code.co_filename
    
    # Special handling for <string> filename 
    if filename == "<string>" and "." in obj_name:
        # Extract "tmpmod_xyz" from "tmpmod_xyz.SpacedClass.spaced_method"
        parts = obj_name.split(".")
        for i in range(1, len(parts)):
            potential_module = ".".join(parts[:i])
            if potential_module in self.source_tracker.module_snapshots:
                return self.source_tracker.module_snapshots[potential_module]
```

### Position Augmentation for Fully-Qualified Names

After parsing positions for a module, we augment the map with `module_name.<name>` keys. This ensures exact matching for fully-qualified object names (e.g., `tmpmod_abc.MyClass.method`), especially for synthetic `<string>` code objects. This replaces earlier ad-hoc matching.

## Position Matching Strategies

The system uses a unified candidate generation approach to match code objects with their current source positions (`line_number_patcher.py:381-408`):

### Unified Position Matching Process

The `find_matching_position()` method generates all possible candidate names using `_generate_candidate_names()` and tries them in priority order until one matches in the position dictionary.

**Core Algorithm**:
```python
# Generate all possible candidate names to try
candidate_names = self._generate_candidate_names(obj_name, obj)

# Try each candidate name in the positions dict
for candidate, adjustment in candidate_names:
    if candidate in current_positions:
        return current_positions[candidate].start_line + adjustment
```

### Candidate Generation Strategies

The system generates candidates using these strategies in priority order:

#### 1. Direct Name Match (Priority 1)
- **Strategy**: Exact match between `obj_name` and position keys
- **Example**: `"MyClass.method"` → `positions["MyClass.method"]`
- **Line Adjustment**: 0 (use exact position)
- **Use Case**: Most common scenario for regular functions and methods

#### 2. Special Pattern Match (Priority 2)
- **Strategy**: Extract base names from property and method wrapper patterns
- **Example**: `"MyClass.prop.fget"` → `positions["MyClass.prop"]` 
- **Line Adjustment**: -1 (use decorator line, one line before)
- **Use Case**: Properties (`.fget/.fset/.fdel`), static/class methods (`.__func__`)
- **Implementation**: `_extract_base_name_from_special_patterns()`

#### 3. Object Name Match (Priority 3)
- **Strategy**: Use `obj.__name__` attribute for matching
- **Example**: Function object with `__name__ = "method"` → `positions["method"]`
- **Line Adjustment**: 0
- **Use Case**: When qualified naming fails but object has useful `__name__`

#### 4. Module Prefix Removal (Priority 4)
- **Strategy**: Strip module prefixes from qualified names
- **Example**: `"tmpmod_xyz.Class.method"` → `positions["Class.method"]`
- **Line Adjustment**: 0  
- **Use Case**: Dynamically generated modules with temporary names
- **Implementation**: `_generate_module_prefix_variants()`

#### 5. Lambda Matching (Special Case)
- **Strategy**: Pattern matching for lambda expressions using original line numbers
- **Example**: Lambda originally at line 10 → match `positions["lambda_10"]`
- **Implementation**: `_find_lambda_position()` (fallback after candidate generation)
- **Use Case**: Anonymous functions and lambda expressions

### Unified Helper Functions

**Module Prefix Removal Logic**: 
- `_remove_module_prefix_if_present()`: Unified logic for stripping module prefixes
- Used by both special pattern matching and module prefix removal strategies
- Eliminates code duplication that previously existed

**Base Name Extraction**:
- `_extract_base_name_from_special_patterns()`: Handles `.fget/.fset/.fdel` and `.__func__` patterns
- Automatically applies module prefix removal to extracted base names

## Data Structures and Storage

### CodePosition Storage
```python
# source_tracker.code_positions structure:
{
    "module_name": {
        "function_name": CodePosition(...),
        "ClassName": CodePosition(...),
        "ClassName.method": CodePosition(...),
        "ClassName.property": CodePosition(...),
        "lambda_42": CodePosition(...),
    }
}
```

### Module Source Cache
```python
# source_tracker.module_snapshots structure:
{
    "module_name": "def function():\n    return 1\n...",
    "tmpmod_abc123": "class MyClass:\n    def method(self):\n...",
}
```

## Error Handling and Edge Cases

### 1. Source Code Unavailable
- **Scenario**: `_get_enhanced_source_code()` returns `None`
- **Fallback**: Return original code object unchanged
- **Impact**: Line numbers remain incorrect, but no crashes

### 2. AST Compilation Failure
- **Scenario**: Syntax errors or compilation issues in `ast_patcher`
- **Fallback**: Return original code object, emit warning
- **Impact**: Graceful degradation with original line numbers

### 3. Position Matching Failure
- **Scenario**: No matching strategy succeeds in `find_matching_position()`
- **Result**: `current_line = None`, no patching attempted
- **Impact**: Original line numbers preserved

### 4. `<string>` Filename Handling
- **Scenario**: Code objects from AST compilation have `co_filename="<string>"`
- **Solution**: Extract module name from qualified object name
- **Critical**: This was the main bug that was fixed

## Performance Considerations

### Caching Mechanisms
1. **Source Code Cache**: `source_tracker.module_snapshots` prevents re-reading files
2. **Position Cache**: `source_tracker.code_positions` avoids re-parsing AST
3. **Patch Offset Cache**: `patch_cache` stores ctypes offsets for faster patching

### Optimization Strategies
1. **Early Returns**: Skip patching when `line_delta == 0`
2. **Lazy Evaluation**: Only parse AST when source changes detected
3. **Incremental Updates**: Update positions per-module, not globally

## Testing and Validation

### Test Coverage Areas
1. **Basic Line Number Updates**: Simple function additions/removals
2. **Class Method Handling**: Methods, properties, static/class methods
3. **Complex Scenarios**: Decorators, nested functions, inheritance
4. **Edge Cases**: Lambda functions, dynamic code generation, syntax errors

### Key Test Cases
- `test_traceback_mod_other_functions`: The failing test that revealed the `<string>` filename bug
- Property method line number tests
- Decorator line number preservation
- Multiple reload cycle accuracy

## Future Improvements

### Potential Enhancements
1. **Better Source Mapping**: More robust filename-to-module matching
2. **Performance Optimization**: Reduce AST parsing overhead
3. **Error Recovery**: Better handling of partially corrupted line number state
4. **Debugging Tools**: Enhanced logging and introspection capabilities

### Known Limitations
1. **Dynamic Code**: Generated code may have inconsistent line mappings
2. **Complex Inheritance**: Deep inheritance hierarchies may cause issues
3. **Concurrent Modifications**: Race conditions in multi-threaded scenarios
4. **Name Normalization**: Space-normalized duplicate keys exist only to make name matching resilient to whitespace; original keys are preserved.

## Summary

The line number patching system is a sophisticated mechanism that maintains traceback accuracy across code reloads through:

1. **Comprehensive Tracking**: AST-based position detection for all code constructs
2. **Flexible Matching**: Multiple strategies to map code objects to source positions  
3. **Robust Patching**: Precise `co_firstlineno` updates using `CodeType.replace`, including nested code
4. **Error Resilience**: Graceful degradation when patching fails

The system handles complex scenarios including class methods, properties, decorators, and dynamically generated modules while maintaining high performance through strategic caching and lazy evaluation.