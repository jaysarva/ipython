# Line Table Reconstruction Roadmap

Implementation roadmap for manually reconstructing `co_linetable` in Python 3.11 for deduperreload line number updates.

## Implementation Roadmap

### 1. Parse Bytecode to Get Instruction Offsets

```python
import dis
from types import CodeType

def parse_bytecode(code_obj: CodeType):
    """Extract instruction offsets and their original line numbers."""
    instructions = []
    for instr in dis.get_instructions(code_obj):
        instructions.append({
            'offset': instr.offset,
            'opname': instr.opname,
            'starts_line': instr.starts_line,  # None if same line as previous
            'is_jump_target': instr.is_jump_target
        })
    return instructions
```

### 2. Calculate New Line Numbers

```python
def calculate_new_line_numbers(instructions, old_firstlineno, new_firstlineno):
    """Map each instruction offset to its new line number."""
    line_offset = new_firstlineno - old_firstlineno
    current_line = old_firstlineno
    
    offset_to_line = {}
    for instr in instructions:
        if instr['starts_line'] is not None:
            current_line = instr['starts_line']
        
        new_line = current_line + line_offset
        offset_to_line[instr['offset']] = new_line
    
    return offset_to_line
```

### 3. Python 3.11 Line Table Encoding Format

Python 3.11 uses a compressed encoding in `co_linetable`:

**Encoding Rules:**
- Each entry is 1-2 bytes
- First byte encodes both offset delta and line delta
- If more precision needed, uses escape sequences

**Bit Layout:**
```
First byte: 0bABCDEFGH
- Bits 0-2 (GH + F): Line delta (-4 to +3, encoded as 0-7)
- Bits 3-6 (BCDE): Offset delta (0-15 instructions)  
- Bit 7 (A): Extension bit (0=simple, 1=extended)
```

**Special Cases:**
- `0xFE`: No line number change, large offset delta follows
- `0xFF`: Large line delta follows in next byte(s)
- `0xFD`: End of table marker

### 4. Encode New Line Table

```python
def encode_linetable(offset_to_line, code_length):
    """Encode offset->line mapping into Python 3.11 co_linetable format."""
    linetable = bytearray()
    
    prev_offset = 0
    prev_line = None
    
    for offset in sorted(offset_to_line.keys()):
        line = offset_to_line[offset]
        
        if prev_line is None:
            prev_line = line
            continue
            
        offset_delta = (offset - prev_offset) // 2  # Instructions are 2 bytes
        line_delta = line - prev_line
        
        # Encode based on delta sizes
        if 0 <= offset_delta <= 15 and -4 <= line_delta <= 3:
            # Simple encoding: one byte
            encoded_line = (line_delta + 4) & 0x7  # Map -4..3 to 0..7
            encoded_offset = offset_delta & 0xF
            byte_val = (encoded_offset << 3) | encoded_line
            linetable.append(byte_val)
            
        elif line_delta == 0 and offset_delta > 15:
            # No line change, large offset
            linetable.append(0xFE)
            linetable.append(offset_delta & 0xFF)
            if offset_delta > 255:
                linetable.extend(offset_delta.to_bytes(2, 'little'))
                
        else:
            # Large line delta
            linetable.append(0xFF)
            linetable.append(offset_delta & 0xFF)
            # Encode signed line delta as variable-length
            if -128 <= line_delta <= 127:
                linetable.append(line_delta & 0xFF)
            else:
                linetable.extend(line_delta.to_bytes(2, 'little', signed=True))
        
        prev_offset = offset
        prev_line = line
    
    return bytes(linetable)
```

### 5. Complete Implementation

```python
def update_function_line_numbers(func, new_firstlineno):
    """Update a function's line number information manually."""
    old_code = func.__code__
    old_firstlineno = old_code.co_firstlineno
    
    # Step 1: Parse bytecode
    instructions = parse_bytecode(old_code)
    
    # Step 2: Calculate new line numbers
    offset_to_line = calculate_new_line_numbers(
        instructions, old_firstlineno, new_firstlineno
    )
    
    # Step 3: Encode new line table
    new_linetable = encode_linetable(offset_to_line, len(old_code.co_code))
    
    # Step 4: Create new code object
    new_code = old_code.replace(
        co_firstlineno=new_firstlineno,
        co_linetable=new_linetable
    )
    
    # Step 5: Update function
    func.__code__ = new_code
```

## Major Challenges

1. **Version Dependency**: Encoding format changed significantly in 3.11 and may change again
2. **Exception Handling**: Exception table (`co_exceptiontable`) also needs updating
3. **Jump Targets**: Relative jumps might need adjustment if line structure changes
4. **Nested Functions**: Recursively handling code objects in `co_consts`
5. **Debugging Info**: Other debugging attributes like `co_names`, `co_varnames` positions
6. **Edge Cases**: Lambda functions, comprehensions, generator expressions have special handling

## Conclusion

This is why the "execute individual functions" approach is vastly more practical - it leverages Python's own compiler instead of reimplementing this complex encoding logic.