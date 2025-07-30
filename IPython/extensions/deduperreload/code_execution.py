"""Code Execution Module for Deduperreload Extension.

This module handles the execution and patching logic for the deduperreload system.
It is responsible for executing new code and patching old code objects in-place,
maintaining object identity and state when possible.

Key Features:
- Execution of new function code in the correct environment
- In-place patching of function objects using ctypes
- Handling of different function types (regular, static, class methods, properties)
- Management of namespace updates and cleanups
- Integration with line number patching for traceback accuracy

Classes:
- CodeExecutor: Main class for code execution and patching operations
"""

from __future__ import annotations
import ast
import sys
import textwrap
from types import ModuleType
from typing import Any

from IPython.extensions.deduperreload.change_detection import AutoreloadTree
from IPython.extensions.deduperreload.dependency_graph import DependencyNode
from IPython.extensions.deduperreload.line_number_patcher import LineNumberPatcher
from IPython.extensions.deduperreload.deduperreload import DeduperReloader


class CodeExecutor:
    """Handles code execution and patching operations for deduperreload.

    This class manages the execution of new code and the patching of existing
    objects in-place. It preserves object identity while updating the underlying
    implementation.
    """

    def __init__(self, dedupereloader: DeduperReloader) -> None:
        """Initialize the code executor.

        Args:
            dedupereloader: DeduperReloader instance
        """
        self.dedupereloader = dedupereloader

        # Line number patcher for maintaining traceback accuracy
        self.line_patcher = LineNumberPatcher()

        # Feature flag for line number patching
        self.enable_line_number_patching = True

    def patch_namespace(
        self, ns: ModuleType | type, prefixes: list[str] | None = None
    ) -> bool:
        """
        Wrapper for patching all elements in a namespace as specified by the to_autoreload member variable.
        Returns `true` if patching was successful, and `false` if unsuccessful.
        """
        try:
            # Get the autoreload tree from the parent DeduperReloader instance
            # We need to access it through the dedupereloader which is the DeduperReloader
            to_autoreload = self.dedupereloader.change_detector.get_autoreload_tree()
            return self._patch_namespace_inner(
                ns, prefixes=prefixes, to_autoreload=to_autoreload
            )
        except Exception:
            return False

    def _patch_namespace_inner(
        self,
        ns: ModuleType | type,
        prefixes: list[str] | None = None,
        to_autoreload: AutoreloadTree | None = None,
    ) -> bool:
        """Patch all definitions marked for reloading in a specific namespace.

        This method handles the actual patching of functions, methods, classes,
        and other definitions that have been identified as needing updates.

        The patching process:
        1. Execute new code in the old object's global environment
        2. Extract the new function/class from the execution result
        3. Patch the old object's attributes with the new one's attributes
        4. Handle special cases like properties, static methods, etc.

        Args:
            ns: The namespace (module or class) to patch
            prefixes: List of nested scope names leading to this namespace
            to_autoreload: AutoreloadTree containing what needs to be reloaded

        Returns:
            True if patching succeeded, False otherwise
        """
        if to_autoreload is None:
            raise ValueError("to_autoreload tree must be provided")

        prefixes = prefixes or []
        current_scope = to_autoreload.traverse_prefixes(prefixes)
        target_namespace = self._resolve_target_namespace(ns, prefixes)
        root_module = self._get_root_module(ns)

        # Patch all definitions that need reloading
        for names, new_ast_def in current_scope.defs_to_reload:
            if isinstance(new_ast_def, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Handle function/method patching
                if not self._patch_function_definition(
                    names, new_ast_def, target_namespace, ns, prefixes
                ):
                    return False
            else:
                # Handle other definitions (imports, assignments, etc.)
                if not self._patch_other_definition(
                    names, new_ast_def, target_namespace, ns, prefixes
                ):
                    return False

        # Clean up completed reload operations
        self._cleanup_current_scope(current_scope, target_namespace, ns)

        # Recursively patch nested scopes (classes)
        if not self._patch_nested_scopes(current_scope, ns, prefixes, to_autoreload):
            return False

        # Update line numbers after patching (only at root module level)
        self._update_line_numbers_if_needed(prefixes, root_module)

        return True

    def _resolve_target_namespace(
        self, ns: ModuleType | type, prefixes: list[str]
    ) -> Any:
        """Resolve the target namespace by following the prefix chain."""
        target = ns
        for prefix in prefixes:
            target = target.__dict__[prefix]
        return target

    def _get_root_module(self, ns: ModuleType | type) -> ModuleType | type | None:
        """Get the root module for line number patching purposes."""
        if isinstance(ns, ModuleType):
            return ns
        else:
            # For class types, get the module they belong to
            module_name = getattr(ns, "__module__", "")
            return sys.modules.get(module_name) if module_name else ns

    def _patch_function_definition(
        self,
        names: tuple[str, ...],
        new_ast_def: ast.FunctionDef | ast.AsyncFunctionDef,
        target_namespace: Any,
        ns: ModuleType | type,
        prefixes: list[str],
    ) -> bool:
        """Patch a function or method definition."""
        if len(names) != 1:
            return True  # Skip multi-name definitions for functions

        name = names[0]

        # Check if this is an existing function that needs patching
        if name in target_namespace.__dict__:
            old_function = target_namespace.__dict__[name]

            # Execute new function code to get the new function object
            new_function = self._execute_function_code(
                new_ast_def, ns, prefixes, old_function
            )
            if new_function is None:
                return False

            # Patch the old function with the new one
            return self._patch_function_object(
                old_function, new_function, len(prefixes) > 0
            )
        else:
            # This is a new function being added - execute and add it
            return self._add_new_function(
                names, new_ast_def, target_namespace, ns, prefixes
            )

    def _execute_function_code(
        self,
        new_ast_def: ast.FunctionDef | ast.AsyncFunctionDef,
        ns: ModuleType | type,
        prefixes: list[str],
        old_function: Any,
    ) -> Any:
        """Execute the new function code and return the resulting function object."""
        try:
            # Generate source code from AST
            func_code = textwrap.dedent(ast.unparse(new_ast_def))

            # Wrap in class if this is a method
            is_method = len(prefixes) > 0
            if is_method:
                func_code = "class __autoreload_class__:\n" + textwrap.indent(
                    func_code, "    "
                )

            # Set up execution environment
            global_env = (
                dict(ns.__dict__) if not isinstance(ns.__dict__, dict) else ns.__dict__
            )
            local_env: dict[str, Any] = {}

            # Get filename for proper traceback
            filename = getattr(old_function, "__code__", None)
            filename = filename.co_filename if filename else "<string>"

            # Compile and execute
            compiled_code = compile(func_code, filename, "exec", dont_inherit=True)
            exec(compiled_code, global_env, local_env)

            # Extract the new function
            if is_method:
                return getattr(local_env["__autoreload_class__"], new_ast_def.name)
            else:
                return local_env[new_ast_def.name]

        except Exception:
            return None

    def _patch_function_object(
        self, old_function: Any, new_function: Any, is_method: bool
    ) -> bool:
        """Patch an old function object with a new one."""
        try:
            # Handle static/class method wrappers
            if isinstance(old_function, (staticmethod, classmethod)):
                old_function = old_function.__func__
            if isinstance(new_function, (staticmethod, classmethod)):
                new_function = new_function.__func__

            # Handle property objects
            if isinstance(old_function, property) and isinstance(
                new_function, property
            ):
                return self._patch_property_object(
                    old_function, new_function, is_method
                )
            elif isinstance(old_function, property) or isinstance(
                new_function, property
            ):
                raise ValueError(
                    "adding or removing property decorations not supported"
                )
            else:
                # Patch regular function
                self.dedupereloader.patch_function(
                    old_function, new_function, is_method
                )
                return True

        except Exception:
            return False

    def _patch_property_object(
        self, old_prop: Any, new_prop: Any, is_method: bool
    ) -> bool:
        """Patch a property object's getter, setter, and deleter."""
        try:
            for attr in ("fget", "fset", "fdel"):
                old_attr = getattr(old_prop, attr)
                new_attr = getattr(new_prop, attr)

                if old_attr is None or new_attr is None:
                    # One is None, just copy the attribute
                    self.dedupereloader.try_patch_attr(old_prop, new_prop, attr)
                else:
                    # Both exist, patch the function
                    self.dedupereloader.patch_function(old_attr, new_attr, is_method)
            return True
        except Exception:
            return False

    def _add_new_function(
        self,
        names: tuple[str, ...],
        new_ast_def: ast.FunctionDef | ast.AsyncFunctionDef,
        target_namespace: Any,
        ns: ModuleType | type,
        prefixes: list[str],
    ) -> bool:
        """Add a new function to the target namespace."""
        try:
            # Execute the function definition
            local_env: dict[str, Any] = {}

            # Generate source code from AST
            func_code = textwrap.dedent(ast.unparse(new_ast_def))

            # Wrap in class if this is a method
            is_method = len(prefixes) > 0
            if is_method:
                func_code = "class __autoreload_class__:\n" + textwrap.indent(
                    func_code, "    "
                )

            # Set up execution environment
            global_env = (
                dict(ns.__dict__) if not isinstance(ns.__dict__, dict) else ns.__dict__
            )
            global_env.update(target_namespace.__dict__)

            # Compile and execute
            compiled_code = compile(
                func_code, "<autoreload>", "exec", dont_inherit=True
            )
            exec(compiled_code, global_env, local_env)

            # Extract and set the new function
            if is_method:
                new_function = getattr(
                    local_env["__autoreload_class__"], new_ast_def.name
                )
            else:
                new_function = local_env[new_ast_def.name]

            setattr(target_namespace, names[0], new_function)
            return True

        except Exception:
            return False

    def _patch_other_definition(
        self,
        names: tuple[str, ...],
        new_ast_def: ast.AST,
        target_namespace: Any,
        ns: ModuleType | type,
        prefixes: list[str],
    ) -> bool:
        """Patch non-function definitions (imports, assignments, etc.)."""
        try:
            # Execute the new definition
            local_env: dict[str, Any] = {}
            global_env = ns.__dict__ | target_namespace.__dict__
            exec(ast.unparse(new_ast_def), global_env, local_env)

            # Set the new values in the target namespace
            for name in names:
                setattr(target_namespace, name, local_env[name])

            return True
        except Exception:
            return False

    def _cleanup_current_scope(
        self,
        current_scope: AutoreloadTree,
        target_namespace: Any,
        ns: ModuleType | type,
    ) -> None:
        """Clean up the current scope after patching."""
        # Clear the reload list
        current_scope.defs_to_reload.clear()

        # Delete removed definitions
        for name in current_scope.defs_to_delete:
            try:
                delattr(target_namespace, name)
            except (AttributeError, TypeError, ValueError):
                # If deletion fails, let the stale definition remain
                pass
        current_scope.defs_to_delete.clear()

        # Add new nested classes
        for class_name, class_ast_node in current_scope.new_nested_classes.items():
            try:
                local_env: dict[str, Any] = {}
                global_env = dict(vars(ns))
                global_env.update(vars(target_namespace))
                exec(ast.unparse(class_ast_node), global_env, local_env)
                setattr(target_namespace, class_name, local_env[class_name])
            except Exception as e:
                # If adding new class fails, try alternative approach
                import warnings

                warnings.warn(f"Failed to add nested class {class_name}: {e}")
                # Try a simpler approach: just exec in the target namespace
                try:
                    exec(ast.unparse(class_ast_node), target_namespace.__dict__)
                except Exception:
                    # If that also fails, continue with other operations
                    pass
        current_scope.new_nested_classes.clear()

    def _patch_nested_scopes(
        self,
        current_scope: AutoreloadTree,
        ns: ModuleType | type,
        prefixes: list[str],
        to_autoreload: AutoreloadTree,
    ) -> bool:
        """Recursively patch nested scopes (classes)."""
        for class_name in list(current_scope.children.keys()):
            if not self._patch_namespace_inner(
                ns, prefixes + [class_name], to_autoreload
            ):
                return False
        current_scope.children.clear()
        return True

    def _update_line_numbers_if_needed(
        self, prefixes: list[str], root_module: ModuleType | type | None
    ) -> None:
        """Update line numbers if we're at the root level and feature is enabled."""
        if (
            not prefixes
            and self.enable_line_number_patching
            and isinstance(root_module, ModuleType)
        ):
            try:
                # Note: force_update=True ensures all line numbers are updated
                # even when no explicit shifts are detected. This is necessary
                # because ANY change to a module can affect line numbers.
                self.line_patcher.update_all_code_object_line_numbers(
                    root_module, [], force_update=True
                )
            except Exception as e:
                # Line number patching is optional - don't break main functionality
                import warnings

                warnings.warn(f"Line number patching failed: {e}")

    def add_node_to_autoreload_tree(
        self, node: DependencyNode, to_autoreload: AutoreloadTree
    ) -> None:
        """Add a dependency node to the autoreload tree.

        Args:
            node: Dependency node representing a function that needs reloading
            to_autoreload: AutoreloadTree to add the node to
        """
        if not node.qualified_name:
            return

        # Navigate to the appropriate scope in the tree
        scope_prefixes = list(node.qualified_name[:-1])
        current_scope = to_autoreload.traverse_prefixes(scope_prefixes)

        # Add the function to be reloaded
        if node.abstract_syntax_tree is not None:
            function_name = node.qualified_name[-1]
            current_scope.defs_to_reload.append(
                ((function_name,), node.abstract_syntax_tree)
            )
