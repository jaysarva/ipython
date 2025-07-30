import types
from typing import Any, List, Tuple


def parse_co_linetable(code_object: Any) -> List[Tuple[int, int]]:
    """Parse *PEP 626* style ``co_linetable`` (Python ≥ 3.11).

    Parameters
    ----------
    code_object : types.CodeType
        A code object whose ``co_linetable`` should be decoded.

    Returns
    -------
    List[Tuple[int, int]]
        A list of ``(bytecode_offset, line_number)`` pairs **sorted by**
        *bytecode offset*.  The first entry will always be ``(0, firstlineno)``.

    Notes
    -----
    While ``co_linetable`` is stored as a *ULEB128* stream, Python already
    provides a high-level iterator via :py:meth:`code.co_lines` that yields
    ``(start, end, line)`` triples.  This helper simply re-formats that
    information which is both simpler and far less error-prone than re-
    implementing the binary decoder.
    """

    # ``co_lines`` exists on Python ≥ 3.10 and yields an *ordered* sequence of
    # (start_offset, end_offset, line_number) tuples.  We keep only the start
    # offset and line number, discarding the *end* and any entries where
    # ``line_number`` is *None* (e.g. "no source line").

    pairs: List[Tuple[int, int]] = []

    try:
        for start, _end, line in code_object.co_lines():
            if line is None:
                # ``None`` marks entries that do not correspond to a real
                # source line (e.g. implicit ``return None``).  Skip them.
                continue
            pairs.append((start, line))
    except AttributeError:  # pragma: no cover  – Should never happen on ≥3.10
        raise RuntimeError(
            "code.co_lines() not available; running on an "
            "unsupported Python version?"
        ) from None

    # Ensure we always start with offset 0 → firstlineno for consistency with
    # the *lnotab* version.
    if not pairs or pairs[0][0] != 0:
        pairs.insert(0, (0, code_object.co_firstlineno))

    return pairs


def parse_co_lnotab(code_object: Any) -> List[Tuple[int, int]]:
    """Parse legacy *lnotab* (Python ≤ 3.10) into offset→line pairs.

    This re-implements the algorithm from CPython's ``Objects/lnotab_notes.txt``
    documentation.  Each *lnotab* entry encodes two unsigned 8-bit deltas:

    * **d_addr** – bytecode offset delta (always non-zero)
    * **d_line** – *signed* line number delta (two's-complement; wrap ≥128)

    The running totals start at ``addr = 0`` and ``line = co_firstlineno``.
    The table is interpreted pair-wise to produce the mapping.
    """

    lnotab: bytes = code_object.co_lnotab  # type: ignore[attr-defined]
    first_line: int = code_object.co_firstlineno

    pairs: List[Tuple[int, int]] = [(0, first_line)]

    addr = 0
    line = first_line

    # Iterate two bytes at a time: (d_addr, d_line)
    for i in range(0, len(lnotab), 2):
        try:
            d_addr = lnotab[i]
            d_line_raw = lnotab[i + 1]
        except IndexError:  # pragma: no cover – Defensive; should not happen.
            break

        addr += d_addr

        # Convert unsigned byte to signed integer (two's complement).
        if d_line_raw >= 128:
            d_line = d_line_raw - 256
        else:
            d_line = d_line_raw

        line += d_line

        pairs.append((addr, line))

    return pairs


def parse_lnotab(lnotab: bytes, first_line: int) -> List[Tuple[int, int]]:
    """Parse legacy *lnotab* (Python ≤ 3.10) into offset→line pairs.

    This is a standalone version of parse_co_lnotab that takes raw bytes.

    Parameters
    ----------
    lnotab : bytes
        The raw lnotab bytes from a code object
    first_line : int
        The co_firstlineno value

    Returns
    -------
    List[Tuple[int, int]]
        A list of (bytecode_offset, line_number) pairs
    """
    pairs: List[Tuple[int, int]] = [(0, first_line)]

    addr = 0
    line = first_line

    # Iterate two bytes at a time: (d_addr, d_line)
    for i in range(0, len(lnotab), 2):
        try:
            d_addr = lnotab[i]
            d_line_raw = lnotab[i + 1]
        except IndexError:  # pragma: no cover – Defensive; should not happen.
            break

        addr += d_addr

        # Convert unsigned byte to signed integer (two's complement).
        if d_line_raw >= 128:
            d_line = d_line_raw - 256
        else:
            d_line = d_line_raw

        line += d_line

        pairs.append((addr, line))

    return pairs


def _encode_uleb128(value: int) -> bytes:
    """Encode an unsigned integer as ULEB128 (Variable Length Encoding)."""
    if value < 0:
        raise ValueError("ULEB128 requires non-negative values")

    result = bytearray()
    while value >= 0x80:
        result.append((value & 0x7F) | 0x80)
        value >>= 7
    result.append(value & 0x7F)
    return bytes(result)


def _decode_uleb128(data: bytes, offset: int = 0) -> Tuple[int, int]:
    """Decode a ULEB128 value from bytes.

    Returns (value, bytes_consumed)
    """
    result = 0
    shift = 0
    pos = offset

    while pos < len(data):
        byte = data[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if (byte & 0x80) == 0:
            break
        shift += 7
    else:
        raise ValueError("Incomplete ULEB128 sequence")

    return result, pos - offset


def _encode_sleb128(value: int) -> bytes:
    """Encode a signed integer as SLEB128."""
    result = bytearray()

    while True:
        byte = value & 0x7F
        value >>= 7

        # Check if we need more bytes
        if (value == 0 and (byte & 0x40) == 0) or (value == -1 and (byte & 0x40) != 0):
            result.append(byte)
            break
        else:
            result.append(byte | 0x80)

    return bytes(result)


def _decode_sleb128(data: bytes, offset: int = 0) -> Tuple[int, int]:
    """Decode a SLEB128 value from bytes.

    Returns (value, bytes_consumed)
    """
    result = 0
    shift = 0
    pos = offset

    while pos < len(data):
        byte = data[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        shift += 7

        if (byte & 0x80) == 0:
            # Sign extend if negative
            if shift < 64 and (byte & 0x40) != 0:
                result |= -1 << shift
            break
    else:
        raise ValueError("Incomplete SLEB128 sequence")

    return result, pos - offset


def parse_linetable(linetable: bytes, first_line: int) -> List[Tuple[int, int]]:
    """Parse PEP 626 style linetable (Python ≥ 3.11) into offset→line pairs.

    Parameters
    ----------
    linetable : bytes
        The raw linetable bytes from a code object
    first_line : int
        The co_firstlineno value

    Returns
    -------
    List[Tuple[int, int]]
        A list of (bytecode_offset, line_number) pairs
    """
    pairs: List[Tuple[int, int]] = [(0, first_line)]

    addr = 0
    line = first_line
    offset = 0

    while offset < len(linetable):
        # Read address delta (ULEB128)
        try:
            d_addr, consumed = _decode_uleb128(linetable, offset)
            offset += consumed
        except ValueError:
            break

        if d_addr == 0:
            # Zero address delta signals end or file table switch - skip for now
            break

        addr += d_addr

        # Read line delta (SLEB128)
        try:
            d_line, consumed = _decode_sleb128(linetable, offset)
            offset += consumed
        except ValueError:
            break

        line += d_line
        pairs.append((addr, line))

    return pairs


def encode_lnotab(pairs: List[Tuple[int, int]]) -> bytes:
    """Encode offset→line pairs as legacy lnotab format.

    Parameters
    ----------
    pairs : List[Tuple[int, int]]
        List of (bytecode_offset, line_number) pairs, should start with (0, firstlineno)

    Returns
    -------
    bytes
        Encoded lnotab bytes
    """
    if not pairs:
        return b""

    result = bytearray()
    prev_addr = 0
    prev_line = pairs[0][1]  # First line number

    # Skip the first (0, firstlineno) entry as it's implicit
    for addr, line in pairs[1:]:
        d_addr = addr - prev_addr
        d_line = line - prev_line

        # Handle large address deltas by splitting
        while d_addr > 255:
            result.extend([255, 0])  # Max addr delta with no line change
            d_addr -= 255

        # Handle large line deltas by splitting
        while d_line > 127 or d_line < -128:
            if d_line > 127:
                result.extend([d_addr if d_addr > 0 else 0, 127])
                d_line -= 127
                d_addr = 0  # Only use address delta on first split
            else:  # d_line < -128
                result.extend(
                    [d_addr if d_addr > 0 else 0, 128]
                )  # 128 = -128 in unsigned
                d_line += 128
                d_addr = 0

        # Encode final delta pair
        if d_addr > 0 or d_line != 0:
            # Convert signed line delta to unsigned byte
            if d_line < 0:
                d_line_unsigned = d_line + 256
            else:
                d_line_unsigned = d_line

            result.extend([d_addr, d_line_unsigned])

        prev_addr = addr
        prev_line = line

    return bytes(result)


def encode_linetable(pairs: List[Tuple[int, int]]) -> bytes:
    """Encode offset→line pairs as PEP 626 linetable format.

    Parameters
    ----------
    pairs : List[Tuple[int, int]]
        List of (bytecode_offset, line_number) pairs, should start with (0, firstlineno)

    Returns
    -------
    bytes
        Encoded linetable bytes
    """
    if not pairs:
        return b""

    result = bytearray()
    prev_addr = 0
    prev_line = pairs[0][1]  # First line number

    # Skip the first (0, firstlineno) entry as it's implicit
    for addr, line in pairs[1:]:
        d_addr = addr - prev_addr
        d_line = line - prev_line

        # Encode address delta as ULEB128
        result.extend(_encode_uleb128(d_addr))

        # Encode line delta as SLEB128
        result.extend(_encode_sleb128(d_line))

        prev_addr = addr
        prev_line = line

    return bytes(result)


def shifted_line_table(
    code: types.CodeType, delta_map: dict[int, int]
) -> types.CodeType:
    """Create a new CodeType with shifted line numbers based on delta_map.

    This function implements the core line table patching algorithm described
    in section 4.3 of the deduperreload line table patching guide.

    Parameters
    ----------
    code : types.CodeType
        The code object to patch
    delta_map : dict[int, int]
        Mapping from line number to delta (shift amount).
        For each line >= insertion_point, line += delta

    Returns
    -------
    types.CodeType
        New code object with shifted line table

    Examples
    --------
    >>> # Shift all lines >= 50 by +5 (5 lines inserted at line 50)
    >>> delta_map = {50: 5}
    >>> new_code = shifted_line_table(old_code, delta_map)
    """
    from sys import version_info as _v

    # If no deltas, return original code object unchanged
    if not delta_map:
        return code

    first = code.co_firstlineno

    # Parse the line table based on Python version
    if _v < (3, 11):
        pairs = parse_lnotab(code.co_lnotab, first)
    else:
        pairs = parse_linetable(code.co_linetable, first)

    # Apply shifts - for each line, find the appropriate delta
    new_pairs = []
    any_changes = False
    for addr, line in pairs:
        new_line = line
        # Apply all deltas for insertion points <= this line
        for insertion_point, delta in delta_map.items():
            if line >= insertion_point:
                new_line += delta

        if new_line != line:
            any_changes = True
        new_pairs.append((addr, new_line))

    # If no actual changes were made, return original code object
    if not any_changes:
        return code

    # Re-encode based on Python version
    if _v < (3, 11):
        new_tab = encode_lnotab(new_pairs)
        # Update co_firstlineno to match the new first line
        new_first_line = new_pairs[0][1] if new_pairs else first
        return code.replace(co_lnotab=new_tab, co_firstlineno=new_first_line)
    else:
        new_tab = encode_linetable(new_pairs)
        # Update co_firstlineno to match the new first line
        new_first_line = new_pairs[0][1] if new_pairs else first
        return code.replace(co_linetable=new_tab, co_firstlineno=new_first_line)
