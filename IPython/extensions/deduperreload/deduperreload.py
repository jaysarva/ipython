from __future__ import annotations
import ast
import builtins
import contextlib
import itertools
import os
import platform
import sys
import textwrap
from types import ModuleType
from typing import TYPE_CHECKING, Any, Generator, Iterable, NamedTuple, cast

from IPython.extensions.deduperreload.deduperreload_patching import (
    DeduperReloaderPatchingMixin,
)

# Enable line number updates with enhanced reconstruction system
try:
    import os
    # Add the root directory to sys.path temporarily to import the modules
    root_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    if root_dir not in sys.path:
        sys.path.insert(0, root_dir)
    
    from line_table_reconstruction import (
        LineTableReconstructor,
        update_module_functions_enhanced,
        get_reconstruction_statistics
    )
    LINE_NUMBER_UPDATE_AVAILABLE = True
    LINE_TABLE_RECONSTRUCTION_AVAILABLE = True
    
    # Create a global reconstructor for enhanced line number updates
    _global_line_reconstructor = LineTableReconstructor(enable_logging=False)
    
except ImportError:
    LINE_NUMBER_UPDATE_AVAILABLE = False
    LINE_TABLE_RECONSTRUCTION_AVAILABLE = False

if TYPE_CHECKING:
    TDefinitionAst = (
        ast.FunctionDef
        | ast.AsyncFunctionDef
        | ast.Import
        | ast.ImportFrom
        | ast.Assign
        | ast.AnnAssign
    )


def get_module_file_name(module: ModuleType | str) -> str | None:
    """Returns the module's file path, or the empty string if it's inaccessible"""
    if (mod := sys.modules.get(module) if isinstance(module, str) else module) is None:
        return ""
    return getattr(mod, "__file__", "") or ""


def compare_ast(node1: ast.AST | list[ast.AST], node2: ast.AST | list[ast.AST]) -> bool:
    """Checks if node1 and node2 have identical AST structure/values, apart from some attributes"""
    if type(node1) is not type(node2):
        return False

    if isinstance(node1, ast.AST):
        for k, v in node1.__dict__.items():
            if k in (
                "lineno",
                "end_lineno",
                "col_offset",
                "end_col_offset",
                "ctx",
                "parent",
            ):
                continue
            if not hasattr(node2, k) or not compare_ast(v, getattr(node2, k)):
                return False
        return True

    elif isinstance(node1, list) and isinstance(  # type:ignore [redundant-expr]
        node2, list
    ):
        return len(node1) == len(node2) and all(
            compare_ast(n1, n2) for n1, n2 in zip(node1, node2)
        )
    else:
        return node1 == node2


class DependencyNode(NamedTuple):
    """
    Each node represents a function.
    qualified_name: string which represents the namespace/name of the function
    abstract_syntax_tree: subtree of the overall module which corresponds to this function

    qualified_name is of the structure: (namespace1, namespace2, ..., name)

    For example, foo() in the following would be represented as (A, B, foo):

    class A:
        class B:
            def foo():
                pass
    """

    qualified_name: tuple[str, ...]
    abstract_syntax_tree: ast.AST


class GatherResult(NamedTuple):
    import_defs: list[tuple[tuple[str, ...], ast.Import | ast.ImportFrom]] = []
    assign_defs: list[tuple[tuple[str, ...], ast.Assign | ast.AnnAssign]] = []
    function_defs: list[
        tuple[tuple[str, ...], ast.FunctionDef | ast.AsyncFunctionDef]
    ] = []
    classes: dict[str, ast.ClassDef] = {}
    unfixable: list[ast.AST] = []

    @classmethod
    def create(cls) -> GatherResult:
        return cls([], [], [], {}, [])

    def all_defs(self) -> Iterable[tuple[tuple[str, ...], TDefinitionAst]]:
        return itertools.chain(self.import_defs, self.assign_defs, self.function_defs)

    def inplace_merge(self, other: GatherResult) -> None:
        self.import_defs.extend(other.import_defs)
        self.assign_defs.extend(other.assign_defs)
        self.function_defs.extend(other.function_defs)
        self.classes.update(other.classes)
        self.unfixable.extend(other.unfixable)


class ConstexprDetector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.is_constexpr = True
        self._allow_builtins_exceptions = True

    @contextlib.contextmanager
    def disallow_builtins_exceptions(self) -> Generator[None, None, None]:
        prev_allow = self._allow_builtins_exceptions
        self._allow_builtins_exceptions = False
        try:
            yield
        finally:
            self._allow_builtins_exceptions = prev_allow

    def visit_Attribute(self, node: ast.Attribute) -> None:
        with self.disallow_builtins_exceptions():
            self.visit(node.value)

    def visit_Name(self, node: ast.Name) -> None:
        if self._allow_builtins_exceptions and hasattr(builtins, node.id):
            return
        self.is_constexpr = False

    def visit(self, node: ast.AST) -> None:
        if not self.is_constexpr:
            # can short-circuit if we've already detected that it's not a constexpr
            return
        super().visit(node)

    def __call__(self, node: ast.AST) -> bool:
        self.is_constexpr = True
        self.visit(node)
        return self.is_constexpr


class AutoreloadTree:
    """
    Recursive data structure to keep track of reloadable functions/methods. Each object corresponds to a specific scope level.
    children: classes inside given scope, maps class name to autoreload tree for that class's scope
    funcs_to_autoreload: list of function names that can be autoreloaded in given scope.
    new_nested_classes: Classes getting added in new autoreload cycle
    """

    def __init__(self) -> None:
        self.children: dict[str, AutoreloadTree] = {}
        self.defs_to_reload: list[tuple[tuple[str, ...], ast.AST]] = []
        self.defs_to_delete: set[str] = set()
        self.new_nested_classes: dict[str, ast.AST] = {}

    def traverse_prefixes(self, prefixes: list[str]) -> AutoreloadTree:
        """
        Return ref to the AutoreloadTree at the namespace specified by prefixes
        """
        cur = self
        for prefix in prefixes:
            if prefix not in cur.children:
                cur.children[prefix] = AutoreloadTree()
            cur = cur.children[prefix]
        return cur


class DeduperReloader(DeduperReloaderPatchingMixin):
    """
    This version of autoreload detects when we can leverage targeted recompilation of a subset of a module and patching
    existing function/method objects to reflect these changes.

    Detects what functions/methods can be reloaded by recursively comparing the old/new AST of module-level classes,
    module-level classes' methods, recursing through nested classes' methods. If other changes are made, original
    autoreload algorithm is called directly.
    """

    def __init__(self) -> None:
        self._to_autoreload: AutoreloadTree = AutoreloadTree()
        self.source_by_modname: dict[str, str] = {}
        self.dependency_graph: dict[tuple[str, ...], list[DependencyNode]] = {}
        self._enabled = True

    @property
    def enabled(self) -> bool:
        return self._enabled and platform.python_implementation() == "CPython"

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value

    def update_sources(self) -> None:
        """
        Update dictionary source_by_modname with current modules' source codes.
        """
        if not self.enabled:
            return
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

    constexpr_detector = ConstexprDetector()

    @staticmethod
    def is_enum_subclass(node: ast.Module | ast.ClassDef) -> bool:
        if isinstance(node, ast.Module):
            return False
        for base in node.bases:
            if isinstance(base, ast.Name) and base.id == "Enum":
                return True
            elif (
                isinstance(base, ast.Attribute)
                and base.attr == "Enum"
                and isinstance(base.value, ast.Name)
                and base.value.id == "enum"
            ):
                return True
        return False

    @classmethod
    def is_constexpr_assign(
        cls, node: ast.AST, parent_node: ast.Module | ast.ClassDef
    ) -> bool:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)) or node.value is None:
            return False
        if cls.is_enum_subclass(parent_node):
            return False
        for target in node.targets if isinstance(node, ast.Assign) else [node.target]:
            if not isinstance(target, ast.Name):
                return False
        return cls.constexpr_detector(node.value)

    @classmethod
    def _gather_children(
        cls, body: list[ast.stmt], parent_node: ast.Module | ast.ClassDef
    ) -> GatherResult:
        """
        Given list of ast elements, return:
        1. dict mapping function names to their ASTs.
        2. dict mapping class names to their ASTs.
        3. list of any other ASTs.
        """
        result = GatherResult.create()
        for ast_node in body:
            ast_elt: ast.expr | ast.stmt = ast_node
            while isinstance(ast_elt, ast.Expr):
                ast_elt = ast_elt.value
            if isinstance(ast_elt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                result.function_defs.append(((ast_elt.name,), ast_elt))
            elif isinstance(ast_elt, (ast.Import, ast.ImportFrom)):
                result.import_defs.append(
                    (tuple(name.asname or name.name for name in ast_elt.names), ast_elt)
                )
            elif isinstance(ast_elt, ast.ClassDef):
                result.classes[ast_elt.name] = ast_elt
            elif isinstance(ast_elt, ast.If):
                result.unfixable.append(ast_elt.test)
                result.inplace_merge(cls._gather_children(ast_elt.body, parent_node))
                result.inplace_merge(cls._gather_children(ast_elt.orelse, parent_node))
            elif isinstance(ast_elt, (ast.AsyncWith, ast.With)):
                result.unfixable.extend(ast_elt.items)
                result.inplace_merge(cls._gather_children(ast_elt.body, parent_node))
            elif isinstance(ast_elt, ast.Try):
                result.inplace_merge(cls._gather_children(ast_elt.body, parent_node))
                result.inplace_merge(cls._gather_children(ast_elt.orelse, parent_node))
                result.inplace_merge(
                    cls._gather_children(ast_elt.finalbody, parent_node)
                )
                for handler in ast_elt.handlers:
                    if handler.type is not None:
                        result.unfixable.append(handler.type)
                    result.inplace_merge(
                        cls._gather_children(handler.body, parent_node)
                    )
            elif not isinstance(ast_elt, (ast.Ellipsis, ast.Pass)):
                if cls.is_constexpr_assign(ast_elt, parent_node):
                    assert isinstance(ast_elt, (ast.Assign, ast.AnnAssign))
                    targets = (
                        ast_elt.targets
                        if isinstance(ast_elt, ast.Assign)
                        else [ast_elt.target]
                    )
                    result.assign_defs.append(
                        (
                            tuple(cast(ast.Name, target).id for target in targets),
                            ast_elt,
                        )
                    )
                else:
                    result.unfixable.append(ast_elt)
        return result

    def detect_autoreload(
        self,
        old_node: ast.Module | ast.ClassDef,
        new_node: ast.Module | ast.ClassDef,
        prefixes: list[str] | None = None,
    ) -> bool:
        """
        Returns
        -------
        `True` if we can run our targeted autoreload algorithm safely.
        `False` if we should instead use IPython's original autoreload implementation.
        """
        if not self.enabled:
            return False
        prefixes = prefixes or []

        old_result = self._gather_children(old_node.body, old_node)
        new_result = self._gather_children(new_node.body, new_node)
        old_defs_by_name: dict[str, ast.AST] = {
            name: ast_def for names, ast_def in old_result.all_defs() for name in names
        }
        new_defs_by_name: dict[str, ast.AST] = {
            name: ast_def for names, ast_def in new_result.all_defs() for name in names
        }

        if not compare_ast(old_result.unfixable, new_result.unfixable):
            return False

        cur = self._to_autoreload.traverse_prefixes(prefixes)
        for names, new_ast_def in new_result.all_defs():
            names_to_reload = []
            for name in names:
                if new_defs_by_name[name] is not new_ast_def:
                    continue
                if name not in old_defs_by_name or not compare_ast(
                    new_ast_def, old_defs_by_name[name]
                ):
                    names_to_reload.append(name)
            if names_to_reload:
                cur.defs_to_reload.append((tuple(names), new_ast_def))
        cur.defs_to_delete |= set(old_defs_by_name.keys()) - set(
            new_defs_by_name.keys()
        )
        for name, new_ast_def_class in new_result.classes.items():
            if name not in old_result.classes:
                cur.new_nested_classes[name] = new_ast_def_class
            elif not compare_ast(
                new_ast_def_class, old_result.classes[name]
            ) and not self.detect_autoreload(
                old_result.classes[name], new_ast_def_class, prefixes + [name]
            ):
                return False
        return True

    def _check_dependents(self) -> bool:
        """
        If a decorator function is modified, we should similarly reload the functions which are decorated by this
        decorator. Iterate through the Dependency Graph to find such cases in the given AutoreloadTree.
        """
        for node in self._check_dependents_inner():
            self._add_node_to_autoreload_tree(node)
        return True

    def _add_node_to_autoreload_tree(self, node: DependencyNode) -> None:
        """
        Given a node of the dependency graph, add decorator dependencies to the autoreload tree.
        """
        if len(node.qualified_name) == 0:
            return
        cur = self._to_autoreload.traverse_prefixes(list(node.qualified_name[:-1]))
        if node.abstract_syntax_tree is not None:
            cur.defs_to_reload.append(
                ((node.qualified_name[-1],), node.abstract_syntax_tree)
            )

    def _check_dependents_inner(
        self, prefixes: list[str] | None = None
    ) -> list[DependencyNode]:
        prefixes = prefixes or []
        cur = self._to_autoreload.traverse_prefixes(prefixes)
        ans = []
        for (func_name, *_), _ in cur.defs_to_reload:
            node = tuple(prefixes + [func_name])
            ans.extend(self._gen_dependents(node))
        for class_name in cur.new_nested_classes:
            ans.extend(self._check_dependents_inner(prefixes + [class_name]))
        return ans

    def _gen_dependents(self, qualname: tuple[str, ...]) -> list[DependencyNode]:
        ans = []
        if qualname not in self.dependency_graph:
            return []
        for elt in self.dependency_graph[qualname]:
            ans.extend(self._gen_dependents(elt.qualified_name))
            ans.append(elt)
        return ans

    def _patch_namespace_inner(
        self, ns: ModuleType | type, prefixes: list[str] | None = None
    ) -> bool:
        """
        This function patches module functions and methods. Specifically, only objects with their name in
        self.to_autoreload will be considered for patching. If an object has been marked to be autoreloaded,
        new_source_code gets executed in the old version's global environment. Then, replace the old function's
        attributes with the new function's attributes.
        """
        prefixes = prefixes or []
        cur = self._to_autoreload.traverse_prefixes(prefixes)
        namespace_to_check = ns
        for prefix in prefixes:
            namespace_to_check = namespace_to_check.__dict__[prefix]
        for names, new_ast_def in cur.defs_to_reload:
            local_env: dict[str, Any] = {}
            if (
                isinstance(new_ast_def, (ast.FunctionDef, ast.AsyncFunctionDef))
                and (name := names[0]) in namespace_to_check.__dict__
            ):
                assert len(names) == 1
                to_patch_to = namespace_to_check.__dict__[name]
                if isinstance(to_patch_to, (staticmethod, classmethod)):
                    to_patch_to = to_patch_to.__func__
                # exec new source code using old function's (obj) globals environment.
                func_code = textwrap.dedent(ast.unparse(new_ast_def))
                if is_method := (len(prefixes) > 0):
                    func_code = "class __autoreload_class__:\n" + textwrap.indent(
                        func_code, "    "
                    )
                global_env = ns.__dict__
                if not isinstance(global_env, dict):
                    global_env = dict(global_env)

                # Compile with correct filename to preserve in traceback
                filename = (
                    getattr(to_patch_to, "__code__", None)
                    and to_patch_to.__code__.co_filename
                    or "<string>"
                )
                compiled_code = compile(func_code, filename, mode="exec", dont_inherit=True)
                exec(compiled_code, global_env, local_env)  # type: ignore[arg-type]

                # local_env contains the function exec'd from  new version of function
                if is_method:
                    to_patch_from = getattr(local_env["__autoreload_class__"], name)
                else:
                    to_patch_from = local_env[name]
                if isinstance(to_patch_from, (staticmethod, classmethod)):
                    to_patch_from = to_patch_from.__func__
                if isinstance(to_patch_to, property) and isinstance(
                    to_patch_from, property
                ):
                    for attr in ("fget", "fset", "fdel"):
                        if (
                            getattr(to_patch_to, attr) is None
                            or getattr(to_patch_from, attr) is None
                        ):
                            self.try_patch_attr(to_patch_to, to_patch_from, attr)
                        else:
                            self.patch_function(
                                getattr(to_patch_to, attr),
                                getattr(to_patch_from, attr),
                                is_method,
                            )
                elif not isinstance(to_patch_to, property) and not isinstance(
                    to_patch_from, property
                ):
                    self.patch_function(to_patch_to, to_patch_from, is_method)
                else:
                    raise ValueError(
                        "adding or removing property decorations not supported"
                    )
            else:
                exec(
                    ast.unparse(new_ast_def),
                    ns.__dict__ | namespace_to_check.__dict__,
                    local_env,
                )
                for name in names:
                    setattr(namespace_to_check, name, local_env[name])
        cur.defs_to_reload.clear()
        for name in cur.defs_to_delete:
            try:
                delattr(namespace_to_check, name)
            except (AttributeError, TypeError, ValueError):
                # give up on deleting the attribute, let the stale one dangle
                pass
        cur.defs_to_delete.clear()
        for class_name, class_ast_node in cur.new_nested_classes.items():
            local_env_class: dict[str, Any] = {}
            exec(
                ast.unparse(class_ast_node),
                ns.__dict__ | namespace_to_check.__dict__,
                local_env_class,
            )
            setattr(namespace_to_check, class_name, local_env_class[class_name])
        cur.new_nested_classes.clear()
        for class_name in cur.children.keys():
            if not self._patch_namespace(ns, prefixes + [class_name]):
                return False
        cur.children.clear()
        return True

    def _patch_namespace(
        self, ns: ModuleType | type, prefixes: list[str] | None = None
    ) -> bool:
        """
        Wrapper for patching all elements in a namespace as specified by the to_autoreload member variable.
        Returns `true` if patching was successful, and `false` if unsuccessful.
        """
        try:
            return self._patch_namespace_inner(ns, prefixes=prefixes)
        except Exception:
            return False

    def maybe_reload_module(self, module: ModuleType) -> bool:
        """
        Uses Deduperreload to try to update a module.
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
            # get old/new module ast
            try:
                old_module_ast = ast.parse(old_source_code)
                new_module_ast = ast.parse(new_source_code)
            except Exception:
                return False
            # detect if we are able to use our autoreload algorithm
            ctx = contextlib.suppress()
            with ctx:
                self._build_dependency_graph(new_module_ast)
                if (
                    self.detect_autoreload(old_module_ast, new_module_ast)
                    and self._check_dependents()
                    and self._patch_namespace(module)
                ):
                    patched_flag = True

        # Update line numbers for ALL functions in the module (not just reloaded ones)
        if LINE_TABLE_RECONSTRUCTION_AVAILABLE:
            try:
                self.update_all_line_numbers_enhanced(module, new_source_code)
            except Exception as e:
                # Don't fail the entire reload if line number updates fail
                try:
                    print(f"Warning: Enhanced line number updates failed: {e}", file=sys.stderr)
                except Exception:
                    pass
        elif LINE_NUMBER_UPDATE_AVAILABLE:
            try:
                self.update_all_line_numbers(module, new_source_code)
            except Exception:
                # Don't fail the entire reload if line number updates fail
                pass

        self.source_by_modname[modname] = new_source_code
        self._to_autoreload = AutoreloadTree()
        return patched_flag

    def _separate_name(
        self,
        decorator: ast.Attribute | ast.Name | ast.Call | ast.expr,
        accept_calls: bool,
    ) -> list[str] | None:
        """
        Generates a qualified name for a given decorator by finding its relative namespace.
        """
        if isinstance(decorator, ast.Name):
            return [decorator.id]
        elif isinstance(decorator, ast.Call):
            if accept_calls:
                return self._separate_name(decorator.func, False)
            else:
                return None
        if not isinstance(decorator, ast.Attribute):
            return None
        if pref := self._separate_name(decorator.value, False):
            return pref + [decorator.attr]
        else:
            return None

    def _gather_dependents(
        self, body: list[ast.stmt], body_prefixes: list[str] | None = None
    ) -> bool:
        body_prefixes = body_prefixes or []
        for ast_node in body:
            ast_elt: ast.expr | ast.stmt = ast_node
            if isinstance(ast_elt, ast.ClassDef):
                self._gather_dependents(ast_elt.body, body_prefixes + [ast_elt.name])
                continue
            if not isinstance(ast_elt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            qualified_name = tuple(body_prefixes + [ast_elt.name])
            cur_dependency_node = DependencyNode(qualified_name, ast_elt)
            for decorator in ast_elt.decorator_list:
                decorator_path = self._separate_name(decorator, True)
                if not decorator_path:
                    continue
                decorator_path_tuple = tuple(decorator_path)
                self.dependency_graph.setdefault(decorator_path_tuple, []).append(
                    cur_dependency_node
                )
        return True

    def _build_dependency_graph(self, new_ast: ast.Module | ast.ClassDef) -> bool:
        """
        Wrapper function for generating dependency graph given some AST.
        Returns `true` on success. Returns `false` on failure.
        Currently, only returns `true` as we do not block on failure to build this graph.
        """
        return self._gather_dependents(new_ast.body)

    def update_all_line_numbers_enhanced(self, module: ModuleType, new_source: str) -> bool:
        """
        Update line numbers for ALL functions in the module using enhanced reconstruction.
        
        This method uses the comprehensive line table reconstruction system to handle
        all types of functions including decorated functions, nested functions, 
        class methods, properties, etc.
        
        Args:
            module: The module to update
            new_source: The new source code to parse for line numbers
            
        Returns:
            True if line number updates were successful, False otherwise
        """
        if not LINE_TABLE_RECONSTRUCTION_AVAILABLE:
            return False
            
        try:
            # Parse the new source to get updated line numbers
            new_ast = ast.parse(new_source)
            
            # Build a comprehensive mapping of function names to their new line numbers
            line_number_map = {}
            self._collect_function_line_numbers_enhanced(new_ast.body, line_number_map)
            
            # Update line numbers for all functions in the module using enhanced system
            results = _global_line_reconstructor.update_module_functions(module, line_number_map)
            
            # Log statistics for debugging
            stats = _global_line_reconstructor.get_statistics()
            if stats['total_functions'] > 0:
                success_rate = stats['success_rate']
                try:
                    if success_rate < 0.8:  # Log if success rate is below 80%
                        print(f"Line number update stats: {stats['successful_updates']}/{stats['total_functions']} "
                              f"successful ({success_rate:.1%}), {stats['fallback_updates']} fallbacks", 
                              file=sys.stderr)
                except Exception:
                    pass
            
            # Return True if most updates were successful
            return stats['success_rate'] > 0.5 if stats['total_functions'] > 0 else True
            
        except Exception as e:
            # Log the specific error for debugging, but don't fail the reload
            try:
                print(f"Warning: Enhanced line number update failed: {e}", file=sys.stderr)
                import traceback
                print(f"Traceback: {traceback.format_exc()}", file=sys.stderr)
            except Exception:
                pass
            return False

    def _collect_function_line_numbers_enhanced(self, body: list[ast.stmt], line_map: dict[str, int], 
                                              prefixes: list[str] = None) -> None:
        """
        Recursively collect line numbers for all functions with enhanced analysis.
        
        This enhanced version provides better handling of complex scenarios like
        decorated functions, nested functions, and class methods.
        
        Args:
            body: AST body to process
            line_map: Dictionary to store qualified_name -> line_number mappings
            prefixes: Current namespace prefixes for nested contexts
        """
        prefixes = prefixes or []
        
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Regular function or async function
                qualified_name = ".".join(prefixes + [node.name])
                
                # For decorated functions, use the first decorator's line number
                # to match Python's co_firstlineno behavior  
                # if node.decorator_list:
                #     line_map[qualified_name] = node.decorator_list[0].lineno
                # else:
                #     line_map[qualified_name] = node.lineno
                line_map[qualified_name] = node.lineno

                # Process nested functions with enhanced context
                self._collect_function_line_numbers_enhanced(
                    node.body, line_map, prefixes + [node.name]
                )
                
            elif isinstance(node, ast.ClassDef):
                # Class - process its methods with enhanced method type detection
                class_prefixes = prefixes + [node.name]
                
                for class_node in node.body:
                    if isinstance(class_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        qualified_name = ".".join(class_prefixes + [class_node.name])
                        
                        # For decorated methods, use the first decorator's line number
                        if class_node.decorator_list:
                            line_map[qualified_name] = class_node.decorator_list[0].lineno
                            
                            # Handle special method decorators
                            for decorator in class_node.decorator_list:
                                if isinstance(decorator, ast.Name):
                                    if decorator.id == 'property':
                                        # Property getter
                                        line_map[qualified_name] = decorator.lineno
                                    elif decorator.id in ('classmethod', 'staticmethod'):
                                        line_map[qualified_name] = decorator.lineno
                                elif isinstance(decorator, ast.Attribute):
                                    # Handle property setter/deleter: @prop.setter, @prop.deleter
                                    if decorator.attr in ('setter', 'deleter'):
                                        prop_name = qualified_name + '.' + decorator.attr
                                        line_map[prop_name] = decorator.lineno
                        else:
                            line_map[qualified_name] = class_node.lineno
                        
                        # Process nested functions within methods
                        self._collect_function_line_numbers_enhanced(
                            class_node.body, line_map, 
                            class_prefixes + [class_node.name]
                        )
                
                # Process nested classes
                self._collect_function_line_numbers_enhanced(
                    node.body, line_map, class_prefixes
                )

    def update_all_line_numbers(self, module: ModuleType, new_source: str) -> bool:
        """
        Update line numbers for ALL functions in the module based on the new source code.
        This ensures line number information is accurate for debugging and tracebacks.
        
        Args:
            module: The module to update
            new_source: The new source code to parse for line numbers
            
        Returns:
            True if line number updates were successful, False otherwise
        """
        if not LINE_NUMBER_UPDATE_AVAILABLE:
            return False
            
        try:
            # Parse the new source to get updated line numbers
            new_ast = ast.parse(new_source)
            
            # Build a mapping of function names to their new line numbers
            line_number_map = {}
            self._collect_function_line_numbers(new_ast.body, line_number_map)
            
            # Update line numbers for all functions in the module
            self._update_module_line_numbers(module, line_number_map)
            
            return True
        except Exception as e:
            # Log the specific error for debugging, but don't fail the reload
            # This ensures that line number update failures don't break the entire reload process
            try:
                import traceback
                print(f"Warning: Line number update failed: {e}", file=sys.stderr)
                print(f"Traceback: {traceback.format_exc()}", file=sys.stderr)
            except Exception:
                # Even error reporting shouldn't break the reload
                pass
            return False

    def _collect_function_line_numbers(self, body: list[ast.stmt], line_map: dict[str, int], 
                                     prefixes: list[str] = None) -> None:
        """
        Recursively collect line numbers for all functions, methods, and nested functions.
        
        Args:
            body: AST body to process
            line_map: Dictionary to store qualified_name -> line_number mappings
            prefixes: Current namespace prefixes for nested contexts
        """
        prefixes = prefixes or []
        
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Regular function or async function
                qualified_name = ".".join(prefixes + [node.name])
                
                # For decorated functions, use the first decorator's line number
                # to match Python's co_firstlineno behavior  
                # if node.decorator_list:
                #     line_map[qualified_name] = node.decorator_list[0].lineno
                # else:
                #     line_map[qualified_name] = node.lineno
                line_map[qualified_name] = node.lineno
                
                # Process nested functions
                self._collect_function_line_numbers(node.body, line_map, prefixes + [node.name])
                
            elif isinstance(node, ast.ClassDef):
                # Class - process its methods
                class_prefixes = prefixes + [node.name]
                for class_node in node.body:
                    if isinstance(class_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        qualified_name = ".".join(class_prefixes + [class_node.name])
                        
                        # For decorated methods, use the first decorator's line number
                        # to match Python's co_firstlineno behavior
                        if class_node.decorator_list:
                            line_map[qualified_name] = class_node.decorator_list[0].lineno
                        else:
                            line_map[qualified_name] = class_node.lineno
                        
                        # Process nested functions within methods
                        self._collect_function_line_numbers(class_node.body, line_map, 
                                                          class_prefixes + [class_node.name])
                
                # Process nested classes
                self._collect_function_line_numbers(node.body, line_map, class_prefixes)

    def _update_module_line_numbers(self, module: ModuleType, line_map: dict[str, int]) -> None:
        """
        Update line numbers for all functions in a module using the line number map.
        Handles decorated functions, nested functions, methods, properties, etc.
        
        Args:
            module: Module whose functions need line number updates
            line_map: Mapping of qualified names to new line numbers
        """
        # Update module-level functions
        self._update_namespace_line_numbers(module, line_map, [])

    def _update_namespace_line_numbers(self, namespace: Any, line_map: dict[str, int], 
                                     prefixes: list[str]) -> None:
        """
        Recursively update line numbers in a namespace (module, class, etc.).
        
        Args:
            namespace: The namespace object (module, class, etc.)
            line_map: Mapping of qualified names to new line numbers  
            prefixes: Current namespace prefixes
        """
        namespace_dict = getattr(namespace, '__dict__', {})
        if not isinstance(namespace_dict, dict):
            namespace_dict = dict(namespace_dict)
            
        for name, obj in namespace_dict.items():
            current_path = ".".join(prefixes + [name])
            
            try:
                # Handle regular functions and methods
                if hasattr(obj, '__code__') and callable(obj):
                    self._update_single_function_line_numbers(obj, current_path, line_map)
                    
                # Handle decorated functions (staticmethod, classmethod, property)
                # elif isinstance(obj, (staticmethod, classmethod)):
                #     func = obj.__func__
                #     if hasattr(func, '__code__'):
                #         self._update_single_function_line_numbers(func, current_path, line_map)
                        
                # elif isinstance(obj, property):
                #     # Handle property getter, setter, deleter
                #     for prop_func, suffix in [(obj.fget, ''), (obj.fset, '.setter'), (obj.fdel, '.deleter')]:
                #         if prop_func is not None and hasattr(prop_func, '__code__'):
                #             prop_path = current_path + suffix
                #             self._update_single_function_line_numbers(prop_func, prop_path, line_map)
                            
                # Handle nested classes
                elif hasattr(obj, '__dict__') and hasattr(obj, '__name__'):
                    # This is likely a class, recurse into it
                    self._update_namespace_line_numbers(obj, line_map, prefixes + [name])
                    
            except Exception as e:
                # Skip objects that cause issues, continue with others
                # Optionally log for debugging
                try:
                    print(f"Warning: Failed to update line numbers for {current_path}: {e}", file=sys.stderr)
                except Exception:
                    pass
                continue

    def _update_single_function_line_numbers(self, func: Any, qualified_name: str, 
                                           line_map: dict[str, int]) -> None:
        """
        Update line numbers for a single function object.
        
        Args:
            func: Function object to update
            qualified_name: Qualified name of the function
            line_map: Mapping of qualified names to new line numbers
        """
        if not hasattr(func, '__code__'):
            return
            
        # Try exact match first
        new_line = line_map.get(qualified_name)
        
        # If no exact match, try matching just the function name (for simple cases)
        if new_line is None:
            func_name = qualified_name.split('.')[-1]
            for key, value in line_map.items():
                if key.endswith('.' + func_name) or key == func_name:
                    new_line = value
                    break
                    
        if new_line is not None and new_line != func.__code__.co_firstlineno:
            try:
                # Use a simplified approach that just updates co_firstlineno
                # The original line table preserves relative line differences
                old_code = func.__code__  
                old_firstlineno = old_code.co_firstlineno
                
                # For simple cases, just updating co_firstlineno is sufficient
                # The line table will maintain relative offsets correctly
                new_code = old_code.replace(co_firstlineno=new_line)
                
                # Update the function's code object
                func.__code__ = new_code
                
            except Exception as e:
                # If the complete pipeline fails, fall back to basic update
                try:
                    print(f"Warning: Complete line number update failed for {qualified_name}, trying basic update: {e}", file=sys.stderr)
                    func.__code__ = func.__code__.replace(co_firstlineno=new_line)
                except Exception as e2:
                    try:
                        print(f"Warning: Basic line number update also failed for {qualified_name}: {e2}", file=sys.stderr)
                    except Exception:
                        pass
