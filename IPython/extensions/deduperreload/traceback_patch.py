"""
Traceback patching for deduperreload to show correct filenames.
"""

import sys
import traceback
from typing import Any, Optional

_original_extract_tb = None
_original_format_exception = None
_deduperreloader = None

def set_deduperreloader(reloader):
    """Set the deduperreloader instance for traceback correction."""
    global _deduperreloader
    _deduperreloader = reloader

def _patched_extract_tb(tb, limit=None):
    """Patched version of traceback.extract_tb that corrects deduperreload filenames."""
    result = _original_extract_tb(tb, limit)
    if _deduperreloader:
        corrected_result = []
        current_tb = tb
        for entry in result:
            if (
                hasattr(entry, "filename")
                and entry.filename == "<string>"
                and current_tb
            ):
                original_filename = _deduperreloader.get_original_filename(current_tb.tb_frame.f_code)
                if original_filename:
                    import traceback
                    import linecache
                    source_line = linecache.getline(original_filename, entry.lineno)
                    corrected_entry = traceback.FrameSummary(
                        original_filename,
                        entry.lineno,
                        entry.name,
                        line=source_line.rstrip() if source_line else entry.line,
                        locals=getattr(entry, "locals", None),
                    )
                    corrected_result.append(corrected_entry)
                else:
                    corrected_result.append(entry)
            else:
                corrected_result.append(entry)
            current_tb = current_tb.tb_next if current_tb else None
        return corrected_result
    return result

def _patched_format_exception(exc, /, value=None, tb=None, limit=None, chain=True):
    """Patched version of traceback.format_exception that corrects deduperreload filenames."""
    if value is None:
        value = exc
    if tb is None:
        tb = exc.__traceback__

    etype = type(exc)

    if _deduperreloader and tb:
        try:
            import traceback
            extracted = traceback.extract_tb(tb, limit)
            corrected_extracted = []

            current_tb = tb
            for entry in extracted:
                if (
                    hasattr(entry, "filename")
                    and entry.filename == "<string>"
                    and current_tb
                ):
                    original_filename = _deduperreloader.get_original_filename(current_tb.tb_frame.f_code)
                    if original_filename:
                        import linecache
                        source_line = linecache.getline(original_filename, entry.lineno)
                        corrected_entry = traceback.FrameSummary(
                            original_filename,
                            entry.lineno,
                            entry.name,
                            line=source_line.rstrip() if source_line else entry.line,
                            locals=getattr(entry, "locals", None),
                        )
                        corrected_extracted.append(corrected_entry)
                    else:
                        corrected_extracted.append(entry)
                else:
                    corrected_extracted.append(entry)
                current_tb = current_tb.tb_next if current_tb else None

            lines = ["Traceback (most recent call last):\n"]
            lines.extend(traceback.format_list(corrected_extracted))
            lines.extend(traceback.format_exception_only(etype, value))
            return lines
        except:
            pass

    return _original_format_exception(exc, value=value, tb=tb, limit=limit, chain=chain)

def patch_traceback_formatting():
    """Patch Python's traceback formatting to show correct filenames for deduperreload functions."""
    global _original_extract_tb, _original_format_exception

    if _original_extract_tb is None:
        _original_extract_tb = traceback.extract_tb
        traceback.extract_tb = _patched_extract_tb

    if _original_format_exception is None:
        _original_format_exception = traceback.format_exception
        traceback.format_exception = _patched_format_exception

def unpatch_traceback_formatting():
    """Remove traceback formatting patches."""
    global _original_extract_tb, _original_format_exception

    if _original_extract_tb:
        traceback.extract_tb = _original_extract_tb
        _original_extract_tb = None

    if _original_format_exception:
        traceback.format_exception = _original_format_exception
        _original_format_exception = None
