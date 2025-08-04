# DeduperReload Extension for IPython

## Overview

The DeduperReload extension provides intelligent, selective code reloading for IPython that preserves object identity and state whenever possible. Instead of reloading entire modules like traditional autoreload, deduperreload performs AST-based analysis to identify exactly what has changed and patches only those specific functions, methods, or classes in-place.

## Key Features

- **Selective Reloading**: Only patches changed functions/classes, preserving object identity
- **AST-Based Analysis**: Compares code structure, not just timestamps
- **Line Number Accuracy**: Maintains correct traceback line numbers after reloading
- **Decorator Dependency Tracking**: Automatically reloads functions that use modified decorators
- **Fallback Safety**: Falls back to traditional autoreload for complex changes
- **CPython Optimization**: Uses ctypes for efficient in-place patching

## Architecture Components

### Core Components

1. **DeduperReloader** - Main orchestrator that coordinates the entire reloading process
2. **ChangeDetector** - AST comparison engine that identifies what has changed
3. **CodeExecutor** - Handles code execution and in-place patching of objects
4. **LineNumberPatcher** - Maintains traceback accuracy by updating line numbers
5. **DependencyGraphManager** - Tracks decorator dependencies for proper reload ordering

### Supporting Components

6. **ASTPatcher** - AST manipulation for line number correction (Python 3.11+)
7. **LineNumberTracker** - Tracks source code positions and calculates line shifts
8. **DeduperReloaderPatchingMixin** - Low-level ctypes-based object patching utilities

## Integration with IPython Autoreload

The deduperreload system integrates seamlessly with IPython's existing autoreload extension:

- **Enabled by default** when using `%autoreload 2` (or other modes)
- **Disabled** when using `%autoreload 2-` or `--full` flag
- **Automatic fallback** to traditional autoreload if deduperreload cannot handle changes
- **Transparent operation** - users experience faster, more reliable reloading

## Control Flow Diagram

```mermaid
graph TD
    %% Entry Points
    A[IPython User Code Execution] --> B{File Changed?}
    B -->|No| Z[Execute Code]
    B -->|Yes| C[AutoreloadMagics.check]
    
    %% Main Autoreload Logic
    C --> D{deduperreload enabled?}
    D -->|No| E[Traditional superreload]
    D -->|Yes| F[DeduperReloader.maybe_reload_module]
    
    %% DeduperReloader Main Flow
    F --> G[Read current source code]
    G --> H{Have cached source?}
    H -->|No| I[Store as baseline for line tracking]
    H -->|Yes| J[Store baseline from OLD source]
    J --> K[Parse old & new source to AST]
    K --> L{AST parsing successful?}
    L -->|No| M[Return False - use superreload]
    L -->|Yes| N[ChangeDetector.detect_autoreload]
    
    %% Change Detection Phase
    N --> O[ASTAnalyzer.compare_ast]
    O --> P[Build AutoreloadTree of changes]
    P --> Q{Simple changes only?}
    Q -->|No| R[Return False - use superreload]
    Q -->|Yes| S[DependencyGraphManager.build_dependency_graph]
    
    %% Dependency Analysis
    S --> T[Scan for decorator usage]
    T --> U[Build decorator dependency graph]
    U --> V[Check for dependent functions]
    V --> W[Add dependents to reload tree]
    
    %% Code Execution & Patching
    W --> X[CodeExecutor.patch_namespace]
    X --> Y[Execute new code in old environment]
    Y --> AA[Extract new function objects]
    AA --> BB[DeduperReloaderPatchingMixin.patch_function]
    BB --> CC[Use ctypes to patch code objects in-place]
    
    %% Line Number Patching
    CC --> DD{Line number patching enabled?}
    DD -->|No| EE[Complete - Return True]
    DD -->|Yes| FF[LineNumberPatcher.update_all_code_object_line_numbers]
    FF --> GG[ModuleSourceTracker.parse_all_positions]
    GG --> HH[Calculate line number shifts]
    HH --> II[Find ALL affected code objects]
    II --> JJ[ASTPatcher.patch_line_numbers]
    JJ --> KK[Use ctypes to update line tables]
    KK --> EE
    
    %% Fallback Flow
    M --> LL[Reset deduperreload state]
    R --> LL
    LL --> MM[Clear line number tracking]
    MM --> NN[Traditional superreload]
    NN --> OO[Complete module replacement]
    
    %% Success Path
    EE --> PP[Update source cache]
    PP --> QQ[Reset change detector]
    QQ --> RR[Clear dependency graph]
    RR --> Z
    
    %% Failure Fallback
    OO --> Z
    E --> Z
    
    %% Exception Handling
    X -.->|Exception| LL
    Y -.->|Exception| LL
    AA -.->|Exception| LL
    BB -.->|Exception| LL
    FF -.->|Exception| SS[Warn but continue]
    SS --> EE
    
    %% Style Classes
    classDef entryPoint fill:#e1f5fe
    classDef decision fill:#fff3e0
    classDef process fill:#f3e5f5
    classDef success fill:#e8f5e8
    classDef fallback fill:#ffebee
    classDef linePatching fill:#e0f2f1
    
    class A,C entryPoint
    class B,D,H,L,Q,DD decision
    class F,G,I,J,K,N,O,P,S,T,U,V,W,X,Y,AA,BB,CC,FF,GG,HH,II,JJ,KK,PP,QQ,RR process
    class EE,Z success
    class E,LL,MM,NN,OO,M,R fallback
    class FF,GG,HH,II,JJ,KK linePatching
```

## Detailed Component Interactions

### 1. Change Detection Pipeline

```mermaid
sequenceDiagram
    participant AR as AutoreloadMagics
    participant DR as DeduperReloader
    participant CD as ChangeDetector
    participant AA as ASTAnalyzer
    participant AT as AutoreloadTree

    AR->>DR: maybe_reload_module(module)
    DR->>DR: Read current & cached source
    DR->>CD: detect_autoreload(old_ast, new_ast)
    CD->>AA: compare_ast() for each definition
    AA-->>CD: Structure comparison results
    CD->>AT: Build tree of changes
    AT-->>CD: Reloadable change tree
    CD-->>DR: Can handle changes?
    DR-->>AR: Success/Failure
```

### 2. Dependency Tracking & Patching

```mermaid
sequenceDiagram
    participant DR as DeduperReloader
    participant DGM as DependencyGraphManager
    participant CE as CodeExecutor
    participant PM as PatchingMixin

    DR->>DGM: build_dependency_graph(new_ast)
    DGM->>DGM: Scan for decorator usage
    DGM-->>DR: Dependency graph built
    DR->>DR: _check_dependents()
    DR->>CE: patch_namespace(module)
    CE->>CE: Execute new code
    CE->>PM: patch_function(old_obj, new_obj)
    PM->>PM: Use ctypes to patch code objects
    PM-->>CE: Patching complete
    CE-->>DR: Namespace patched
```

### 3. Line Number Patching Pipeline

```mermaid
sequenceDiagram
    participant CE as CodeExecutor
    participant LNP as LineNumberPatcher
    participant MST as ModuleSourceTracker
    participant AP as ASTPatcher

    CE->>LNP: update_all_code_object_line_numbers(module)
    LNP->>MST: parse_all_positions(current_source)
    MST-->>LNP: Current code positions
    LNP->>LNP: Compare with cached positions
    LNP->>LNP: Calculate line number shifts
    LNP->>LNP: Find all affected code objects
    LNP->>AP: patch_line_numbers(code_obj, shifts)
    AP->>AP: Use ctypes to update line tables
    AP-->>LNP: Line numbers updated
    LNP-->>CE: All objects updated
```

## Usage Examples

### Basic Usage
```python
# In IPython
%load_ext autoreload
%autoreload 2  # deduperreload enabled by default

# Edit your Python files - only changed functions are reloaded
# Object identity and state are preserved
```

### Disable DeduperReload
```python
%autoreload 2-     # Disable deduperreload, use traditional autoreload
%autoreload 2 --full  # Same as above
```

### Enable/Disable Line Number Patching
```python
# Access the deduperreload instance
reloader = get_ipython().magic_mgr.registry.get_plugin("AutoreloadMagics")._reloader.deduper_reloader
reloader.enable_line_number_patching = False  # Disable for performance
```

## When DeduperReload is Used vs Fallback

### DeduperReload Handles:
- Function body changes
- Method modifications
- Simple class changes
- Decorator applications (with dependency tracking)
- Constant assignments
- Import additions/modifications

### Falls Back to Traditional Autoreload:
- Complex structural changes (inheritance modifications)
- Class signature changes
- Module-level control flow changes
- Non-constant expressions
- AST parsing failures

## Performance Benefits

1. **Faster Reloading**: Only changed functions are processed
2. **State Preservation**: Object identity maintained, avoiding reference invalidation
3. **Memory Efficiency**: No complete module recreation
4. **Debugger Friendly**: Breakpoints and watchers remain valid
5. **Hot Reloading**: Changes apply immediately without losing context

## Compatibility

- **Python Version**: 3.8+ (optimal on 3.11+ with enhanced AST support)
- **Platform**: CPython only (uses ctypes for low-level patching)
- **IPython**: Integrated with standard autoreload extension
- **Jupyter**: Full compatibility with Jupyter notebooks

## Troubleshooting

### Common Issues

1. **Complex Changes Not Reloading**: Check if deduperreload fell back to traditional autoreload
2. **Line Number Mismatches**: Enable line number patching if disabled
3. **Decorator Dependencies**: Ensure decorator functions are properly tracked
4. **Memory Leaks**: Rarely, ctypes patching may create reference cycles

### Debug Mode
```python
# Enable verbose logging to see what deduperreload is doing
import logging
logging.getLogger('autoreload').setLevel(logging.INFO)
```

## Technical Implementation Notes

### ctypes-based Patching
DeduperReload uses ctypes to directly modify Python object structures in memory, enabling true in-place updates that preserve object identity. This is much faster than recreating objects but requires careful memory management.

### AST Analysis
The system parses Python source code into Abstract Syntax Trees and performs structural comparisons to identify changes. This approach is more reliable than timestamp-based checking and enables intelligent change classification.

### Line Number Correction
When functions change size, all subsequent line numbers in the module shift. The line number patcher tracks these changes and updates ALL affected code objects to maintain traceback accuracy.

### Decorator Dependency Tracking
The system builds a dependency graph of decorator usage, ensuring that when a decorator function changes, all functions using that decorator are also reloaded automatically.

## Future Enhancements

- **PyPy Support**: Investigate compatibility with alternative Python implementations
- **Enhanced AST Analysis**: Support for more complex code patterns
- **Performance Optimizations**: Further reduce latency for large codebases
- **IDE Integration**: Better integration with development environments
- **Distributed Systems**: Support for reloading in distributed Python applications