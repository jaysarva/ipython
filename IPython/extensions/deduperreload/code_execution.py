"""Execute updated code and patch existing objects in place (targeted reload)."""

from __future__ import annotations
import ast
import sys
from types import ModuleType
from typing import Any

from .change_detection import AutoreloadTree
from .deduperreload_patching import DeduperReloaderPatchingMixin, NOT_FOUND


def is_class_ns(ns: ModuleType | type) -> bool:
    return isinstance(ns, type)


class CodeExecutor(DeduperReloaderPatchingMixin):
    """Batch-compile/exec selected defs and patch them into existing namespaces."""

    def patch_namespace(
            self,
            ns: ModuleType | type,
            to_autoreload: AutoreloadTree,
    ) -> None:
        """Patch all reload-marked defs in a namespace; recurse into nested classes."""
        self._patch_all_reloadable_definitions(ns, to_autoreload)
        self._patch_deletes_and_new_classes(ns, to_autoreload)
        self._patch_nested_scopes(ns, to_autoreload)

    def _patch_all_reloadable_definitions(
            self,
            ns: ModuleType | type,
            to_autoreload: AutoreloadTree,
    ) -> None:
        if len(to_autoreload.defs_to_reload) == 0:
            return
        reloaded_locals = self._reload_scope_batch(ns, to_autoreload)
        for names, new_ast_def in to_autoreload.defs_to_reload:
            self._patch_single_reloadable_definition(
                ns,
                reloaded_locals,
                names,
                new_ast_def,
            )
        to_autoreload.defs_to_reload.clear()

    def _patch_single_reloadable_definition(
            self,
            ns: ModuleType | type,
            reloaded_locals: dict[str, Any],
            names: tuple[str, ...],
            new_ast_def: ast.AST,
    ) -> None:
        """Patch one def using type-based dispatch (function vs. other)."""
        if isinstance(new_ast_def, (ast.FunctionDef, ast.AsyncFunctionDef)):
            self._patch_function_definition(
                ns,
                reloaded_locals,
                names,
            )
        else:
            self._patch_other_definition(
                ns,
                reloaded_locals,
                names,
            )

    @staticmethod
    def _get_root_module(ns: ModuleType | type) -> ModuleType:
        """Return the top-level module for the provided namespace"""
        if isinstance(ns, ModuleType):
            return ns
        else:
            # For class types, get the module they belong to
            return sys.modules[ns.__module__]

    @staticmethod
    def _is_callable_object(obj: Any) -> bool:
        return callable(obj) or isinstance(obj, property)

    def _patch_function_definition(
            self,
            ns: ModuleType | type,
            reloaded_locals: dict[str, Any],
            names: tuple[str, ...],
    ) -> None:
        """Patch an existing function/method or add a new one to the target namespace."""
        if len(names) != 1:
            return  # Skip multi-name definitions for functions

        name = names[0]

        # Check if this is an existing function that needs patching
        if (old_function := ns.__dict__.get(name)) is None:
            self._add_new_function(
                ns,
                reloaded_locals,
                name,
            )
            return
        # Obtain new function/method from the compiled batch
        if is_class_ns(ns):
            new_function = getattr(reloaded_locals["__autoreload_class__"], name)
        else:
            new_function = reloaded_locals[name]

        # Ensure we have a proper function object when compiling at module level
        # If a non-function was bound (e.g. due to name shadowing), fallback to execution
        assert self._is_callable_object(new_function)

        # Patch the old function with the new one
        self._patch_function_object(old_function, new_function, is_method=is_class_ns(ns))

    def _patch_function_object(self, old_function: Any, new_function: Any, is_method: bool) -> None:
        """Patch function identity in-place (incl. properties/static/class methods)."""
        # Handle static/class method wrappers
        if isinstance(old_function, (staticmethod, classmethod)):
            old_function = old_function.__func__
        if isinstance(new_function, (staticmethod, classmethod)):
            new_function = new_function.__func__

        # Handle property objects
        if isinstance(old_function, property) and isinstance(new_function, property):
            self._patch_property_object(old_function, new_function, is_method)
        elif isinstance(old_function, property) or isinstance(new_function, property):
            raise ValueError("adding or removing property decorations not supported")
        else:
            # Patch regular function
            self.patch_function(old_function, new_function, is_method)

    def _patch_property_object(self, old_prop: Any, new_prop: Any, is_method: bool) -> None:
        """Patch the property's fget/fset/fdel by function-level patching when present."""
        for attr in ("fget", "fset", "fdel"):
            old_attr = getattr(old_prop, attr)
            new_attr = getattr(new_prop, attr)

            if old_attr is None or new_attr is None:
                self.try_patch_attr(old_prop, new_prop, attr)
            else:
                self.patch_function(old_attr, new_attr, is_method)

    def _add_new_function(
            self,
            ns: ModuleType | type,
            reloaded_locals: dict[str, Any],
            name: str,
    ) -> None:
        """Add a new callable from the compiled batch into the target namespace."""
        if is_class_ns(ns):
            new_function = getattr(reloaded_locals["__autoreload_class__"], name)
        else:
            new_function = reloaded_locals[name]
        assert self._is_callable_object(new_function)
        setattr(ns, name, new_function)

    def _patch_other_definition(
            self,
            ns: ModuleType | type,
            reloaded_locals: dict[str, Any],
            names: tuple[str, ...],
    ) -> None:
        """Patch imports/constexpr assignments via compiled bindings or globals."""
        for name in names:
            if is_class_ns(ns):
                new_item = getattr(reloaded_locals["__autoreload_class__"], name, NOT_FOUND)
            else:
                new_item = reloaded_locals.get(name, NOT_FOUND)
            assert new_item is not NOT_FOUND
            setattr(ns, name, new_item)

    def _reload_scope_batch(
            self,
            ns: ModuleType | type,
            to_autoreload: AutoreloadTree,
    ) -> dict[str, Any]:
        """Reload the scope's defs into an isolated env and return (env, is_class_scope)."""
        # Build AST module body
        assert len(to_autoreload.defs_to_reload) > 0
        module_body: list[ast.stmt] = []
        seen: set[int] = set()
        for _, stmt_or_mod in to_autoreload.defs_to_reload:
            node_id = id(stmt_or_mod)
            if node_id in seen:
                continue
            seen.add(node_id)
            if isinstance(stmt_or_mod, ast.Module):
                module_body.extend(stmt_or_mod.body)
            else:
                module_body.append(stmt_or_mod)
        assert len(module_body) > 0

        module_body.sort(key=lambda stmt: stmt.lineno)
        if is_class_ns(ns):
            # Wrap methods into a temporary class. This is only needed so that
            # any methods that call "super()" will have a __closure__ associated
            # with a __class__ freevar that we can later patch to the correct
            # __class__ object.
            module_body = [
                ast.ClassDef(
                    name="__autoreload_class__",
                    bases=[],
                    keywords=[],
                    decorator_list=[],
                    body=module_body,
                    lineno=1,
                    col_offset=0,
                )
            ]

        isolated_module = ast.Module(body=module_body, type_ignores=[])
        ast.fix_missing_locations(isolated_module)

        # Determine filename for proper tracebacks
        root_module = self._get_root_module(ns)
        filename = getattr(root_module, "__file__", None)
        if not filename:
            filename = "<autoreload>"
        if filename.endswith(".pyc"):
            filename = filename[:-1]

        compiled_code = compile(isolated_module, filename, "exec", dont_inherit=True)

        # Prepare isolated execution environment so globals and locals are the same
        # to ensure names like imports bind into the function globals mapping
        global_env = dict(root_module.__dict__)
        if is_class_ns(ns):
            local_env = dict(ns.__dict__)
        else:
            local_env = global_env
        exec(compiled_code, global_env, local_env)
        return local_env

    def _patch_deletes_and_new_classes(
            self,
            ns: ModuleType | type,
            to_autoreload: AutoreloadTree,
    ) -> None:
        """Delete removed defs, and add new nested classes."""

        # Delete removed definitions
        for name in to_autoreload.defs_to_delete:
            try:
                delattr(ns, name)
            except (AttributeError, TypeError, ValueError):
                # If deletion fails, let the stale definition remain
                pass
        to_autoreload.defs_to_delete.clear()

        for class_name, class_ast_node in to_autoreload.new_nested_classes.items():
            local_env: dict[str, Any] = {}
            global_env = dict(self._get_root_module(ns).__dict__)
            if is_class_ns(ns):
                local_env = dict(ns.__dict__)
            else:
                local_env = global_env
            exec(ast.unparse(class_ast_node), global_env, local_env)
            setattr(ns, class_name, local_env[class_name])
        to_autoreload.new_nested_classes.clear()

    def _patch_nested_scopes(
            self,
            ns: ModuleType | type,
            to_autoreload: AutoreloadTree,
    ) -> None:
        """Recurse into nested class scopes; return False on failure."""
        for class_name in list(to_autoreload.children.keys()):
            if (clazz := ns.__dict__.get(class_name)) is None:
                continue
            self.patch_namespace(clazz, to_autoreload=to_autoreload.get_child(class_name))
        to_autoreload.children.clear()
