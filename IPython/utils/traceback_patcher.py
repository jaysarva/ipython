"""
Traceback patching utilities for IPython.

This module provides a way to modify how tracebacks are displayed by
intercepting the formatting process rather than modifying the traceback
objects themselves.

The main entry point is ``PatchedTB``, a subclass of ``FormattedTB`` that
can rewrite filenames and line numbers during formatting:

    try:
        1 / 0
    except ZeroDivisionError as exc:
        patches = {
            (__file__, exc.__traceback__.tb_lineno): ("/fake/file.py", 1234)
        }
        tb_formatter = PatchedTB(patches, mode="Plain", theme_name="linux")
        print(tb_formatter.text(*sys.exc_info()))

This approach is safe, portable, and works across all Python implementations.
"""

from __future__ import annotations

import linecache
import sys
from types import TracebackType
from typing import Dict, List, Optional, Tuple

from IPython.core.ultratb import FormattedTB
from IPython.core.tbtools import FrameInfo


# Type alias for patch mapping
PatchMapping = Dict[Tuple[str, int], Tuple[Optional[str], Optional[int]]]


def _get_context_lines(filename: str, lineno: int, context: int = 5) -> List[str]:
    """
    Get context lines around a specific line number from a file.

    Parameters
    ----------
    filename : str
        Path to the file
    lineno : int
        Line number (1-indexed)
    context : int
        Number of context lines to include on each side

    Returns
    -------
    List[str]
        List of lines with context around the target line
    """
    try:
        # Get all lines from the file
        lines = linecache.getlines(filename)
        if not lines:
            return [f"<Unable to read file: {filename}>"]

        # Calculate range (convert to 0-indexed)
        start = max(0, lineno - 1 - context)
        end = min(len(lines), lineno + context)

        return lines[start:end]
    except Exception:
        return [f"<Error reading file: {filename}>"]


class PatchedTB(FormattedTB):
    """
    A traceback formatter that rewrites filenames and line numbers on the fly.

    This subclass of FormattedTB intercepts the formatting process and applies
    patches to change how filenames and line numbers are displayed, without
    modifying the original traceback objects.

    Parameters
    ----------
    patches : dict
        A mapping from (original_filename, original_lineno) to
        (new_filename, new_lineno). Use None to leave a field unchanged.
    *args, **kwargs
        Passed to the parent FormattedTB constructor.

    Examples
    --------
    >>> patches = {
    ...     ("/path/to/file.py", 42): ("/fake/file.py", 1234),
    ...     ("/other/file.py", 10): (None, 999)  # Only change line number
    ... }
    >>> tb_formatter = PatchedTB(patches, mode="Plain", theme_name="linux")
    >>> print(tb_formatter.text(exc_type, exc_value, exc_traceback))
    """

    def __init__(self, patches: PatchMapping, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._patches = patches

    def _format_list(self, extracted_list):
        """Override to apply patches in Plain mode."""
        patched_list = []
        for filename, lineno, func_name, line in extracted_list:
            key = (filename, lineno)
            if key in self._patches:
                new_fname, new_lineno = self._patches[key]
                if new_fname is not None:
                    filename = new_fname
                if new_lineno is not None:
                    lineno = new_lineno
            patched_list.append((filename, lineno, func_name, line))

        # Delegate to the original implementation to build colored text
        return super()._format_list(patched_list)

    def format_record(self, frame_info: FrameInfo) -> str:
        """Override to apply patches in Verbose/Context modes."""
        # Only create key if we have non-None values
        if frame_info.filename is not None and frame_info.lineno is not None:
            key = (frame_info.filename, frame_info.lineno)
            if key in self._patches:
                new_fname, new_lineno = self._patches[key]
                original_filename = frame_info.filename
                original_lineno = frame_info.lineno

                # Modify the frame_info attributes
                if new_fname is not None:
                    frame_info.filename = new_fname
                if new_lineno is not None:
                    frame_info.lineno = new_lineno

                # If we changed filename or line number, we need to update context
                if new_fname is not None or new_lineno is not None:
                    target_filename = (
                        new_fname if new_fname is not None else original_filename
                    )
                    target_lineno = (
                        new_lineno if new_lineno is not None else original_lineno
                    )

                    # Use a unified approach for both cases - update raw_lines with new context
                    context_size = getattr(frame_info, "context", 5) or 5
                    frame_info.raw_lines = _get_context_lines(
                        target_filename, target_lineno, context_size
                    )

        return super().format_record(frame_info)




class TracebackPatcher:
    """
    Convenience class providing a simple API for traceback patching.

    This provides backward compatibility with the original API while using
    the new PatchedTB implementation under the hood.
    """

    @classmethod
    def create_patched_formatter(
        cls,
        tb: TracebackType,
        replacements: List[Tuple[Optional[str], Optional[int]]],
        mode: str = "Plain",
        theme_name: str = "linux",
    ) -> PatchedTB:
        """
        Create a PatchedTB formatter with patches derived from a traceback.

        Parameters
        ----------
        tb : TracebackType
            The traceback to extract frame information from.
        replacements : list
            List of (filename, lineno) tuples, one per frame starting with
            the innermost frame. Use None to leave a field unchanged.
        mode : str
            Formatting mode ("Plain", "Context", "Verbose").
        theme_name : str
            Color theme name.

        Returns
        -------
        PatchedTB
            A formatter that will apply the specified patches.
        """
        # Extract frame information from the traceback
        frames = []
        cur = tb
        while cur is not None:
            frames.append((cur.tb_frame.f_code.co_filename, cur.tb_lineno))
            cur = cur.tb_next

        # Build patch mapping
        patches = {}
        for (orig_fname, orig_lineno), (new_fname, new_lineno) in zip(
            frames, replacements
        ):
            if new_fname is not None or new_lineno is not None:
                patches[(orig_fname, orig_lineno)] = (new_fname, new_lineno)

        return PatchedTB(patches, mode=mode, theme_name=theme_name)

    @classmethod
    def patch_traceback(
        cls,
        tb: TracebackType,
        replacements: List[Tuple[Optional[str], Optional[int]]],
    ) -> TracebackType:
        """
        Legacy API for backward compatibility.

        This method doesn't actually modify the traceback (which was problematic)
        but instead returns the original traceback unchanged. Use
        create_patched_formatter() to get a formatter that applies patches.

        Parameters
        ----------
        tb : TracebackType
            The traceback object.
        replacements : list
            List of patches (ignored in this implementation).

        Returns
        -------
        TracebackType
            The original traceback object, unchanged.
        """
        # Return the original traceback unchanged for backward compatibility
        return tb
