"""Deduperreload Extension for IPython.

This module provides smart code reloading that can selectively update functions
and classes without reloading entire modules, preserving state and improving
development workflow.

The core idea is to compare AST nodes between old and new versions of code,
identify what has changed, and patch only the changed components in-place.
"""

from __future__ import annotations
import ast
import contextlib
import os
import platform
import sys
from types import ModuleType
from typing import TYPE_CHECKING

from IPython.extensions.deduperreload.deduperreload_patching import (
    DeduperReloaderPatchingMixin,
)
from IPython.extensions.deduperreload.dependency_graph import (
    DependencyGraphManager,
    DependencyNode,
)
from IPython.extensions.deduperreload.change_detection import (
    ChangeDetector,
    AutoreloadTree,
)
from IPython.extensions.deduperreload.code_execution import (
    CodeExecutor,
)

if TYPE_CHECKING:
    pass


def get_module_file_name(module: ModuleType | str) -> str | None:
    """Get the file path for a module.

    Args:
        module: Either a module object or module name as string

    Returns:
        Module file path, or empty string if not accessible
    """
    if isinstance(module, str):
        mod = sys.modules.get(module)
    else:
        mod = module

    if mod is None:
        return ""

    return getattr(mod, "__file__", "") or ""


class DeduperReloader(DeduperReloaderPatchingMixin):
    """Smart code reloader that patches only changed functions and classes.

    This reloader performs intelligent analysis of code changes by comparing
    AST between old and new versions of modules. Instead of reloading
    the entire module as traditional autoreload does, it identifies exactly what has changed
    and patches only those specific functions, methods, or classes in-place.

    Key features:
    - Preserves object identity and state when possible
    - Handles nested classes and functions correctly
    - Tracks decorator dependencies for proper reload ordering
    - Maintains line number accuracy in tracebacks
    - Falls back to full reload when changes are too complex

    The reloader works by:
    1. Parsing both old and new module source into AST
    2. Comparing AST nodes to identify changes
    3. Building a tree of what needs to be reloaded
    4. Patching changed code objects in-place using ctypes
    5. Updating line numbers to maintain traceback accuracy
    """

    def __init__(self) -> None:
        # Cache of module source code for comparison
        self.source_by_modname: dict[str, str] = {}

        # Whether the reloader is enabled (only works on CPython)
        self._enabled = True

        # Initialize the component modules
        self.dependency_manager = DependencyGraphManager()
        self.change_detector = ChangeDetector()
        self.code_executor = CodeExecutor(self)

        # Enable line number patching by default
        self.code_executor.enable_line_number_patching = True

    @property
    def enabled(self) -> bool:
        return self._enabled and platform.python_implementation() == "CPython"

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value

    @property
    def enable_line_number_patching(self) -> bool:
        """Get the line number patching setting."""
        return self.code_executor.enable_line_number_patching

    @enable_line_number_patching.setter
    def enable_line_number_patching(self, value: bool) -> None:
        """Set the line number patching setting."""
        self.code_executor.enable_line_number_patching = value

    # Backward compatibility properties for tests
    @property
    def _to_autoreload(self) -> AutoreloadTree:
        """Backward compatibility property for accessing the autoreload tree."""
        return self.change_detector.get_autoreload_tree()

    @_to_autoreload.setter
    def _to_autoreload(self, value: AutoreloadTree) -> None:
        """Backward compatibility setter for the autoreload tree."""
        # For tests that set this directly, we need to update the change detector
        self.change_detector._to_autoreload = value

    @property
    def dependency_graph(self) -> dict[tuple[str, ...], list[DependencyNode]]:
        """Backward compatibility property for accessing the dependency graph."""
        return self.dependency_manager.dependency_graph

    @dependency_graph.setter
    def dependency_graph(
        self, value: dict[tuple[str, ...], list[DependencyNode]]
    ) -> None:
        """Backward compatibility setter for the dependency graph."""
        self.dependency_manager.dependency_graph = value

    def update_sources(self) -> None:
        """Update the source code cache for all loaded modules.

        This method scans sys.modules for any new modules that haven't been
        cached yet and reads their source code. It skips:
        - Modules without accessible files
        - Third-party packages (site-packages, dist-packages)
        - Files that can't be read
        """
        if not self.enabled:
            return

        # Find new modules that aren't in our cache
        new_module_names = sys.modules.keys() - self.source_by_modname.keys()

        for module_name in new_module_names:
            module = sys.modules[module_name]
            source_code = self._read_module_source(module)
            self.source_by_modname[module_name] = source_code

    def _read_module_source(self, module: ModuleType) -> str:
        """Read source code for a single module.

        Args:
            module: Module to read source for

        Returns:
            Source code string, or empty string if not readable
        """
        file_path = get_module_file_name(module)

        # Skip if no file or is a third-party package
        if (
            file_path is None
            or "site-packages" in file_path
            or "dist-packages" in file_path
            or not os.access(file_path, os.R_OK)
        ):
            return ""

        # Try to read the file
        try:
            with open(file_path, "r") as f:
                return f.read()
        except Exception:
            return ""

    def detect_autoreload(
        self,
        old_node: ast.Module | ast.ClassDef,
        new_node: ast.Module | ast.ClassDef,
        prefixes: list[str] | None = None,
    ) -> bool:
        """Analyze if targeted autoreload is possible for the given changes.

        This method compares old and new AST nodes to determine if the changes
        are simple enough to handle with targeted reloading. It builds up the
        autoreload tree with what needs to be reloaded.

        Args:
            old_node: AST node from the previous version
            new_node: AST node from the current version
            prefixes: Namespace prefixes for nested scopes

        Returns:
            True if targeted autoreload is possible, False if full reload needed
        """
        if not self.enabled:
            return False

        return self.change_detector.detect_autoreload(old_node, new_node, prefixes)

    def _check_dependents(self) -> bool:
        """Check for decorator dependencies and add them to the reload tree.

        When a decorator function is modified, we also need to reload any
        functions that use that decorator, since the decorator application
        happens at function definition time.

        Returns:
            True (always succeeds)
        """
        dependent_nodes = self._check_dependents_inner()
        for node in dependent_nodes:
            self.code_executor.add_node_to_autoreload_tree(
                node, self.change_detector.get_autoreload_tree()
            )
        return True

    def _check_dependents_inner(
        self, prefixes: list[str] | None = None
    ) -> list[DependencyNode]:
        """Recursively check for dependent functions that need reloading.

        Args:
            prefixes: Current namespace prefixes

        Returns:
            List of dependency nodes that need to be reloaded
        """
        prefixes = prefixes or []
        autoreload_tree = self.change_detector.get_autoreload_tree()
        current_scope = autoreload_tree.traverse_prefixes(prefixes)
        dependent_nodes = []

        # Check dependencies for functions being reloaded
        for (func_name, *_), _ in current_scope.defs_to_reload:
            qualified_name = tuple(prefixes + [func_name])
            dependent_nodes.extend(
                self.dependency_manager.get_dependents(qualified_name)
            )

        # Recursively check new nested classes
        for class_name in current_scope.new_nested_classes:
            nested_dependents = self._check_dependents_inner(prefixes + [class_name])
            dependent_nodes.extend(nested_dependents)

        return dependent_nodes

    def _patch_namespace(
        self, ns: ModuleType | type, prefixes: list[str] | None = None
    ) -> bool:
        """
        Wrapper for patching all elements in a namespace as specified by the to_autoreload member variable.
        Returns `true` if patching was successful, and `false` if unsuccessful.
        """
        return self.code_executor.patch_namespace(ns, prefixes)

    def maybe_reload_module(self, module: ModuleType) -> bool:
        """Attempt to reload a module using targeted patching.

        This is the main entry point for the dedupe reloader. It:
        1. Reads the current module source
        2. Compares with cached source to detect changes
        3. Attempts targeted reloading if changes are suitable
        4. Falls back to indicating full reload is needed if not

        Args:
            module: The module to potentially reload

        Returns:
            True if targeted reload succeeded, False if full reload needed
        """
        if not self.enabled:
            return False

        # Get module information
        module_name = getattr(module, "__name__", None)
        if not module_name:
            return False

        file_path = get_module_file_name(module)
        if file_path is None:
            return False

        # Read current source code
        try:
            with open(file_path, "r") as f:
                new_source_code = f.read()
        except Exception:
            return False

        # Try targeted reloading if we have old source to compare
        reload_succeeded = False
        old_source_code = self.source_by_modname.get(module_name)
        if old_source_code:
            reload_succeeded = self._attempt_targeted_reload(
                old_source_code, new_source_code, module
            )

        # Update source cache and reset state
        self.source_by_modname[module_name] = new_source_code
        self.change_detector.reset()
        self.dependency_manager.clear()

        return reload_succeeded

    def _attempt_targeted_reload(
        self, old_source: str, new_source: str, module: ModuleType
    ) -> bool:
        """Attempt targeted reload by comparing old and new source.

        Args:
            old_source: Previous source code
            new_source: Current source code
            module: Module object to patch

        Returns:
            True if targeted reload succeeded, False otherwise
        """
        try:
            # Parse both versions into AST
            old_module_ast = ast.parse(old_source)
            new_module_ast = ast.parse(new_source)
        except Exception:
            return False

        # Attempt the reload process
        try:
            with contextlib.suppress():
                # Build dependency graph for decorator handling
                self.dependency_manager.build_dependency_graph(new_module_ast)

                # Check if we can handle the changes
                if (
                    self.detect_autoreload(old_module_ast, new_module_ast)
                    and self._check_dependents()
                    and self._patch_namespace(module)
                ):
                    return True
        except Exception:
            pass

        return False
