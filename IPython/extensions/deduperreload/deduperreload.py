"""Targeted function/class reloading for IPython with identity preservation."""

from __future__ import annotations
import ast
import os
import platform
import sys
from types import ModuleType

from .deduperreload_patching import DeduperReloaderPatchingMixin
from .dependency_graph import DependencyGraphManager, QualifiedFunctionDef
from .change_detection import ChangeDetector, AutoreloadTree
from .code_execution import CodeExecutor


def get_module_file_name(module: ModuleType | str) -> str | None:
    """Returns the module's file path, or None if it's inaccessible."""
    if (mod := sys.modules.get(module) if isinstance(module, str) else module) is None:
        return None
    return getattr(mod, "__file__", None) or None


class DeduperReloader(DeduperReloaderPatchingMixin):
    """Patch only changed defs; preserve object identity and state.

    This version of autoreload detects when we can leverage targeted recompilation
    of a subset of a module and patching existing function/method objects to reflect
    these changes.

    Detects what functions/methods can be reloaded by recursively comparing the
    old/new AST of module-level classes, module-level classes' methods, recursing
    through nested classes' methods. If other changes are made, original autoreload
    algorithm is called directly.
    """

    def __init__(self) -> None:
        self.source_by_modname: dict[str, str] = {}
        self.dependency_manager = DependencyGraphManager()
        self.change_detector = ChangeDetector()
        self.code_executor = CodeExecutor()
        self._enabled = True

    @property
    def enabled(self) -> bool:
        return self._enabled and platform.python_implementation() == "CPython"

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value

    def update_sources(self) -> None:
        """Update dictionary source_by_modname with current modules' source codes."""
        for new_modname in sys.modules.keys() - self.source_by_modname.keys():
            new_module = sys.modules[new_modname]
            if (
                (fname := get_module_file_name(new_module)) is None
                or "site-packages" in fname
                or "dist-packages" in fname
                or not os.access(fname, os.R_OK)
            ):
                self.source_by_modname[new_modname] = ""
                continue
            with open(fname, "r") as f:
                try:
                    self.source_by_modname[new_modname] = f.read()
                except Exception:
                    self.source_by_modname[new_modname] = ""

    def detect_autoreload(
            self,
            old_node: ast.Module | ast.ClassDef,
            new_node: ast.Module | ast.ClassDef,
    ) -> bool:
        """Return True if safe to apply targeted reload; populate internal tree."""
        return self.change_detector.detect_autoreload(
            old_node, new_node, self.change_detector.autoreload_tree)

    def add_dependent_defs(self) -> None:
        """Add functions dependent on changed decorators into the reload tree."""
        autoreload_tree = self.change_detector.autoreload_tree
        for node in self._get_dependent_defs(autoreload_tree):
            autoreload_tree.add_qualified_def(node)

    def _get_dependent_defs(self, autoreload_tree: AutoreloadTree) -> list[QualifiedFunctionDef]:
        """Return dependency nodes to reload at this scope; recurse into new nested classes."""
        dependent_defs = []

        # Check dependencies for functions being reloaded
        for (func_name, *_), _ in autoreload_tree.defs_to_reload:
            qualified_name = tuple(autoreload_tree.path + (func_name, ))
            dependent_defs.extend(self.dependency_manager.get_dependents(qualified_name))

        # Recursively check new nested classes
        for class_name in autoreload_tree.new_nested_classes:
            dependent_defs.extend(self._get_dependent_defs(autoreload_tree.get_child(class_name)))

        return dependent_defs

    def attempt_targeted_reload(self, module: ModuleType, old_source: str,
                                new_source: str) -> bool:
        """Try targeted reload for a module; return True if applied, else False."""
        # Try targeted reloading if we have old source to compare
        try:
            old_module_ast = ast.parse(old_source)
            new_module_ast = ast.parse(new_source)
            # Build dependency graph for decorator handling
            self.dependency_manager.build_dependency_graph(new_module_ast)

            # Check if we can handle the changes and apply patches
            if not self.detect_autoreload(old_module_ast, new_module_ast):
                return False
            self.add_dependent_defs()
            self.code_executor.patch_namespace(module, self.change_detector.autoreload_tree)
            return True
        except Exception:
            return False
        finally:
            self.change_detector.reset()
            self.dependency_manager.clear()

    def maybe_reload_module(self, module: ModuleType) -> bool:
        """Uses Deduperreload to try to update a module.

        Returns `true` on success and `false` on failure.
        """
        if not self.enabled:
            return False
        if not (modname := getattr(module, "__name__", None)):
            return False
        if (fname := get_module_file_name(module)) is None:
            return False
        with open(fname, "r") as f:
            new_source_code = f.read()

        patched_flag = False
        if old_source_code := self.source_by_modname.get(modname):
            patched_flag = self.attempt_targeted_reload(module, old_source_code, new_source_code)

        self.source_by_modname[modname] = new_source_code
        return patched_flag
