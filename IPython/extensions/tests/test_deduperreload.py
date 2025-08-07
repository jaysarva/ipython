#!/usr/bin/env python
from __future__ import annotations
import ast
import asyncio
import platform
import pytest
import sys
import traceback
import unittest
from types import ModuleType

from IPython.extensions.tests.deduperreload_test_utils import (
    squish_text,
    ShellFixture,
)

from IPython.extensions.deduperreload.deduperreload import DeduperReloader
from IPython.extensions.deduperreload.change_detection import compare_ast

if platform.python_implementation() != "CPython":
    pytest.skip(
        "We do not support non-CPython versions.",
        allow_module_level=True,
    )


class DeduperTestReloader(DeduperReloader):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.exceptions_raised: list[Exception] = []

    def _patch_namespace(
        self, module: ModuleType | type, prefixes: list[str] | None = None
    ) -> bool:
        try:
            assert super()._patch_namespace(module, prefixes)
            return True
        except Exception as e:
            self.exceptions_raised.append(e)
            return False


def is_nonempty_file(fname: str) -> bool:
    return len(fname) > 0


class AutoreloadDetectionSuite(unittest.TestCase):
    """
    Unit tests for autoreload testing logic
    """

    def test_compare_ast(self):
        code1 = squish_text(
            """
            def factorial(n):
                def fn(sdfsdf):
                    print(sdfsdf)
                if n < 0:
                    return "Factorial is not defined for negative numbers."
                elif n == 0 or n == 1:
                    return 1
                else:
                    result = 1
                    for i in range(2, n + 1):
                        result *= i
                    return result
                y = 12
                print(y)
            print(1)
            x = 1212121
        """
        )
        code2 = squish_text(
            """
            def factorial(n):
                def fn(sdfsdf):
                    print(sdfsdf+"!!!")
                if n < 0:
                    return "Factorial is not defined for negative numbers."
                elif n == 0 or n == 1:
                    return 1
                else:
                    result = 1
                    for i in range(2, n + 1):
                        result *= i
                    return result
                y = 12
                print(y)
            print(1)
            x = 1212121
        """
        )
        ast_1 = ast.parse(code1)
        ast_2 = ast.parse(code2)

        assert not compare_ast(ast_1, ast_2)

    def test_compare_ast2(self):
        code1 = squish_text(
            """
            def factorial(n):
                def fn(sdfsdf):
                    print(sdfsdf)
                if n < 0:
                    return "Factorial is not defined for negative numbers."
                elif n == 0 or n == 1:
                    return 1
                else:
                    result = 1
                    for i in range(2, n + 1):
                        result *= i
                    return result
                y = 12
                print(y)
            print(1)
            x = 1212121
        """
        )
        code2 = squish_text(
            """
            def factorial(n):
                def fn(sdfsdf):
                    print(sdfsdf)
                if n < 0:
                    return "Factorial is not defined for negative numbers."
                elif n == 0 or n == 1:
                    return 1
                else:
                    result = 1
                    for i in range(2, n + 1):
                        result *= i
                    return result
                y = 12
                print(y)
            print(1)
            x = 1212121
        """
        )
        ast_1 = ast.parse(code1)
        ast_2 = ast.parse(code2)

        assert compare_ast(ast_1, ast_2)

    def test_autoreload_no_changes(self):
        code1 = squish_text(
            """
            def factorial(n):
                print(n)
            print(1)
            x = 1212121
        """
        )
        code2 = squish_text(
            """
            def factorial(n):
                print(n)
            print(1)
            x = 1212121
        """
        )
        deduperreloader = DeduperTestReloader()
        ast_1 = ast.parse(code1)
        ast_2 = ast.parse(code2)

        assert deduperreloader.detect_autoreload(ast_1, ast_2)
        assert deduperreloader._to_autoreload.defs_to_reload == []

    def test_autoreload_static_assign_change_outside_function(self):
        code1 = squish_text(
            """
            def factorial(n):
                print(n)
            print(1)
        """
        )
        code2 = squish_text(
            """
            def factorial(n):
                print(n)
            print(1)
            x = 1212121
        """
        )
        deduperreloader = DeduperTestReloader()
        ast_1 = ast.parse(code1)
        ast_2 = ast.parse(code2)

        assert deduperreloader.detect_autoreload(ast_1, ast_2)

    def test_autoreload_changes_inside_function(self):
        code1 = squish_text(
            """
            def factorial(n):
                print(n)
            print(1)
        """
        )
        code2 = squish_text(
            """
            def factorial(n):
                print(n + "edit!")
            print(1)
        """
        )
        deduperreloader = DeduperTestReloader()
        ast_1 = ast.parse(code1)
        ast_2 = ast.parse(code2)

        assert deduperreloader.detect_autoreload(ast_1, ast_2)
        assert len(deduperreloader._to_autoreload.defs_to_reload) == 1

    def test_autoreload_changes_inside_and_outside_function(self):
        code1 = squish_text(
            """
            def factorial(n):
                print(n)
            print(1)
        """
        )
        code2 = squish_text(
            """
            def factorial(n):
                print(n + "edit!")
            print(2)
        """
        )
        deduperreloader = DeduperTestReloader()
        ast_1 = ast.parse(code1)
        ast_2 = ast.parse(code2)

        assert not deduperreloader.detect_autoreload(ast_1, ast_2)

    def test_autoreload_changes_inner_function(self):
        code1 = squish_text(
            """
            def factorial(n):
                def foo():
                    x = 3   
                    return x
                return foo
        """
        )
        code2 = squish_text(
            """
            def factorial(n):
                def foo():
                    x = 4  
                    return x
                return foo
        """
        )
        deduperreloader = DeduperTestReloader()
        ast_1 = ast.parse(code1)
        ast_2 = ast.parse(code2)

        assert deduperreloader.detect_autoreload(ast_1, ast_2)
        assert len(deduperreloader._to_autoreload.defs_to_reload) == 1

    def test_autoreload_changes_multiple_function(self):
        code1 = squish_text(
            """
            def factorial(n):
                def foo():
                    x = 3   
                    return x
                return foo
            def bar():
                return 1
        """
        )
        code2 = squish_text(
            """
            def factorial(n):
                def foo():
                    x = 4  
                    return x
                return foo
            def bar():
                return 2
        """
        )
        deduperreloader = DeduperTestReloader()
        ast_1 = ast.parse(code1)
        ast_2 = ast.parse(code2)

        assert deduperreloader.detect_autoreload(ast_1, ast_2)
        assert len(deduperreloader._to_autoreload.defs_to_reload) == 2

    def test_autoreload_change_one_function_of_multiple(self):
        code1 = squish_text(
            """
            def factorial(n):
                def foo():
                    x = 3   
                    return x
                return foo
            def bar():
                return 1
        """
        )
        code2 = squish_text(
            """
            def factorial(n):
                def foo():
                    x = 4  
                    return x
                return foo
            def bar():
                return 1
        """
        )
        deduperreloader = DeduperTestReloader()
        ast_1 = ast.parse(code1)
        ast_2 = ast.parse(code2)

        assert deduperreloader.detect_autoreload(ast_1, ast_2)
        assert len(deduperreloader._to_autoreload.defs_to_reload) == 1

    def test_autoreload_handling_moves(self):
        code1 = squish_text(
            """
            def factorial(n):
                return 1
            x = 1
        """
        )
        code2 = squish_text(
            """
            x = 1
            def factorial(n):
                return 1
        """
        )
        deduperreloader = DeduperTestReloader()
        ast_1 = ast.parse(code1)
        ast_2 = ast.parse(code2)

        assert deduperreloader.detect_autoreload(ast_1, ast_2)
        assert len(deduperreloader._to_autoreload.defs_to_reload) == 0

    def test_autoreload_handling_function_moves_success(self):
        code1 = squish_text(
            """
            def factorial(n):
                return 1
            x = 1
            def foo():
                return 23
            x = 2
        """
        )
        code2 = squish_text(
            """
        x = 1
        x = 2
        def foo():
            return 23
        def factorial(n):
            return 1
        """
        )
        deduperreloader = DeduperTestReloader()
        ast_1 = ast.parse(code1)
        ast_2 = ast.parse(code2)

        assert deduperreloader.detect_autoreload(ast_1, ast_2)
        assert len(deduperreloader._to_autoreload.defs_to_reload) == 0

    def test_autoreload_handling_function_moves_only(self):
        code1 = squish_text(
            """
        def factorial(n):
            return 1
        x = 1
        x = 2
        """
        )
        code2 = squish_text(
            """
        x = 1
        x = 2
        def factorial(n):
            return 1
        """
        )
        deduperreloader = DeduperTestReloader()
        ast_1 = ast.parse(code1)
        ast_2 = ast.parse(code2)

        assert deduperreloader.detect_autoreload(ast_1, ast_2)

    def test_autoreload_handles_new_imports(self):
        code1 = squish_text(
            """
        def factorial(n):
            return 1
        x = 1
        """
        )
        code2 = squish_text(
            """
        import ast
        def factorial(n):
            return 1
        x = 1
        """
        )
        deduperreloader = DeduperTestReloader()
        ast_1 = ast.parse(code1)
        ast_2 = ast.parse(code2)

        assert deduperreloader.detect_autoreload(ast_1, ast_2)

    def test_autoreload_async_function(self):
        code1 = squish_text(
            """
        async def sleep():
            print(f'Time: {time.time() - start:.2f}')
            await asyncio.sleep(1)
        """
        )
        code2 = squish_text(
            """
        async def sleep():
            print(f'Time: {time.time() - start:.2f}')
            await asyncio.sleep(10)
        """
        )
        deduperreloader = DeduperTestReloader()
        ast_1 = ast.parse(code1)
        ast_2 = ast.parse(code2)

        assert deduperreloader.detect_autoreload(ast_1, ast_2)
        assert len(deduperreloader._to_autoreload.defs_to_reload) == 1

    def test_autoreload_add_function(self):
        code1 = squish_text(
            """
        async def sleep():
            print(f'Time: {time.time() - start:.2f}')
            await asyncio.sleep(1)
        """
        )
        code2 = squish_text(
            """
        async def sleep():
            print(f'Time: {time.time() - start:.2f}')
            await asyncio.sleep(1)
        def add(x,y):
            pass
        """
        )
        deduperreloader = DeduperTestReloader()
        ast_1 = ast.parse(code1)
        ast_2 = ast.parse(code2)

        assert deduperreloader.detect_autoreload(ast_1, ast_2)
        assert list(d[0][0] for d in deduperreloader._to_autoreload.defs_to_reload) == [
            "add"
        ]

    def test_autoreload_add_function_ellipsis(self):
        code1 = squish_text(
            """
        async def sleep():
            print(f'Time: {time.time() - start:.2f}')
            await asyncio.sleep(1)
        """
        )
        code2 = squish_text(
            """
        async def sleep():
            print(f'Time: {time.time() - start:.2f}')
            await asyncio.sleep(1)
        def add(x,y):
            ...
        """
        )
        deduperreloader = DeduperTestReloader()
        ast_1 = ast.parse(code1)
        ast_2 = ast.parse(code2)

        assert deduperreloader.detect_autoreload(ast_1, ast_2)
        assert list(d[0][0] for d in deduperreloader._to_autoreload.defs_to_reload) == [
            "add"
        ]


class AutoreloadPatchingSuite(unittest.TestCase):
    """
    Unit tests for autoreload patching logic
    """

    def setUp(self) -> None:
        self.deduperreloader = DeduperTestReloader()

    def test_patching(self):
        code1 = squish_text(
            """
            def foo():
                return 1
        """
        )
        code2 = squish_text(
            """
            def foo():
                return 2
        """
        )
        self.deduperreloader._to_autoreload.defs_to_reload = [
            (("foo",), ast.parse(code2))
        ]
        mod = ModuleType("mod")
        exec(code1, mod.__dict__)
        self.deduperreloader._patch_namespace(mod)
        assert mod.foo() == 2

    def test_patching_parameters(self):
        code1 = squish_text(
            """
            def foo(n,s):
                return n+s
        """
        )
        code2 = squish_text(
            """
            def foo(n):
                return n
        """
        )
        self.deduperreloader._to_autoreload.defs_to_reload = [
            (("foo",), ast.parse(code2))
        ]
        mod = ModuleType("mod")
        exec(code1, mod.__dict__)
        self.deduperreloader._patch_namespace(mod)
        assert mod.foo(2) == 2

    def test_add_function(self):
        code1 = squish_text(
            """
            def foo2(n):
                return n
        """
        )
        code2 = squish_text(
            """
            def foo(n):
                return 55
        """
        )
        self.deduperreloader._to_autoreload.defs_to_reload = [
            (("foo",), ast.parse(code2))
        ]
        mod = ModuleType("mod")
        exec(code1, mod.__dict__)
        self.deduperreloader._patch_namespace(mod)
        assert mod.foo(2) == 55
        assert mod.foo2(2) == 2

    def test_two_operations(self):
        code1 = squish_text(
            """
            def foo(n):
                return 1
        """
        )
        code2 = squish_text(
            """
            def foo(n):
                return 55
        """
        )
        code3 = squish_text(
            """
            def goo():
                return -1
            def foo(n):
                x = 2
                return x+n
            def bar():
                return 200
        """
        )
        self.deduperreloader._to_autoreload.defs_to_reload = [
            (("foo",), ast.parse(code2))
        ]
        mod = ModuleType("mod")
        exec(code1, mod.__dict__)
        assert mod.foo(2) == 1
        self.deduperreloader._patch_namespace(mod)
        assert mod.foo(2) == 55
        self.deduperreloader._to_autoreload.defs_to_reload = [
            (("foo",), ast.parse(code3))
        ]
        self.deduperreloader._patch_namespace(mod)
        assert mod.foo(2) == 4

    def test_using_outside_param(self):
        code1 = squish_text(
            """
            x=1
            def foo(n):
                return 1
        """
        )
        code2 = squish_text(
            """
            x=1
            def foo(n):
                return 55+x
        """
        )
        self.deduperreloader._to_autoreload.defs_to_reload = [
            (("foo",), ast.parse(code2))
        ]
        mod = ModuleType("mod")
        exec(code1, mod.__dict__)
        assert mod.foo(2) == 1
        self.deduperreloader._patch_namespace(mod)
        assert mod.foo(2) == 56

    def test_importing_func(self):
        code1 = squish_text(
            """
            from os import environ
            def foo(n):
                pass
        """
        )
        code2 = squish_text(
            """
            from os import environ
            def foo():
                environ._data
                return 1
        """
        )
        self.deduperreloader._to_autoreload.defs_to_reload = [
            (("foo",), ast.parse(code2))
        ]
        mod = ModuleType("mod")
        exec(code1, mod.__dict__)
        self.deduperreloader._patch_namespace(mod)
        assert mod.foo() == 1


class AutoreloadHookSuite(ShellFixture):
    def test_deduperreloader_basic(self):
        self.shell.magic_autoreload("2")
        mod_name, mod_fn = self.new_module(
            """
            x = 9
            def foo(y):
                return y + 3
        """
        )
        self.shell.run_code("import %s" % mod_name)
        self.shell.run_code("pass")
        self.write_file(
            mod_fn,
            """
            x = 9
            def foo(y):
                return y + 5
            """,
        )
        self.shell.run_code("pass")
        self.assertIn(mod_name, self.shell.user_ns)
        mod = sys.modules[mod_name]
        assert mod.foo(0) == 5

    def test_deduperreloader_basic2(self):
        self.shell.magic_autoreload("2")
        mod_name, mod_fn = self.new_module(
            """
            x = 9
            def foo(y):
                return y + 3
        """
        )
        self.shell.run_code("import %s" % mod_name)
        self.shell.run_code("pass")
        self.write_file(
            mod_fn,
            """
            x = 9
            def foo(y):
                return y + 5
            """,
        )
        self.shell.run_code("pass")
        self.assertIn(mod_name, self.shell.user_ns)
        mod = sys.modules[mod_name]
        assert mod.foo(0) == 5

    def test_deduperreloader_basic3(self):
        mod_name, mod_fn = self.new_module(
            """
            x = 9
            def foo(y):
                return y + 3
        """
        )
        self.shell.run_code("import %s" % mod_name)
        self.shell.magic_autoreload("2")
        self.shell.run_code("pass")
        self.write_file(
            mod_fn,
            """
            x = 9
            def foo(y):
                return y + 5
            """,
        )
        self.shell.run_code("pass")
        self.assertIn(mod_name, self.shell.user_ns)
        mod = sys.modules[mod_name]
        assert mod.foo(0) == 5

    def test_deduperreloader_basic4(self):
        mod_name, mod_fn = self.new_module(
            """
            x = 9
            def foo(y):
                return y + 3
        """
        )
        self.shell.run_code("import %s" % mod_name)
        self.shell.magic_autoreload("2")
        self.shell.run_code("pass")
        self.write_file(
            mod_fn,
            """
            x = 9
            def foo(y):
                return y + 5
            """,
        )
        self.shell.run_code("pass")
        self.assertIn(mod_name, self.shell.user_ns)
        mod = sys.modules[mod_name]
        assert mod.foo(0) == 5

    def test_deduperreloader_basic5(self):
        mod_name, mod_fn = self.new_module(
            """
            x = 9
            def foo(y):
                return y + 3
        """
        )
        self.shell.run_code("import %s" % mod_name)
        self.shell.run_code("pass")
        self.shell.magic_autoreload("2")
        self.shell.run_code("pass")
        self.write_file(
            mod_fn,
            """
            x = 9
            def foo(y):
                return y + 5
            """,
        )
        self.shell.run_code("pass")
        self.assertIn(mod_name, self.shell.user_ns)
        mod = sys.modules[mod_name]
        assert mod.foo(0) == 5

    def test_deduperreloader_basic6(self):
        mod_name, mod_fn = self.new_module(
            """
            x = 9
            def foo(y):
                return y + 3
        """
        )
        self.shell.run_code("import %s" % mod_name)
        self.shell.run_code("pass")
        self.shell.magic_autoreload("2")
        self.shell.run_code("pass")
        self.write_file(
            mod_fn,
            """
            x = 9
            def foo(y):
                return y + 5
            """,
        )
        self.shell.run_code("pass")
        self.assertIn(mod_name, self.shell.user_ns)
        mod = sys.modules[mod_name]
        assert mod.foo(0) == 5

    def test_super(self):
        self.shell.magic_autoreload("2")
        mod_name, mod_fn = self.new_module(
            """
            class Foo:
                def foo(self):
                    return 1
            class Bar(Foo):
                def bar(self):
                    return super().foo() + 1
        """
        )
        self.shell.run_code(f"from {mod_name} import Bar; bar = Bar()")
        self.shell.run_code("pass")
        self.write_file(
            mod_fn,
            """
            class Foo:
                def foo(self):
                    return 1
            class Bar(Foo):
                def bar(self):
                    return super().foo() + 2
            """,
        )
        self.shell.run_code("result = bar.bar()")
        # NOTE : only works on CPython, requires read-only patching.
        if platform.python_implementation() == "CPython":
            assert self.shell.user_ns["result"] == 3

    def test_deduperreloader_need_to_default_back(self):
        self.shell.magic_autoreload("2")
        mod_name, mod_fn = self.new_module(
            """
            x = 9
            def foo(y):
                return y + 3
        """
        )
        self.shell.run_code("import %s" % mod_name)
        self.shell.run_code("pass")
        self.write_file(
            mod_fn,
            """
            x = 200
            def foo(y):
                return y + 5
            """,
        )
        self.shell.run_code("pass")
        self.assertIn(mod_name, self.shell.user_ns)
        mod = sys.modules[mod_name]
        assert mod.foo(0) == 5

    def test_deduperreloader_failure(self):
        self.shell.magic_autoreload("2")
        mod_name, mod_fn = self.new_module(
            """
            x = 9
            def foo(y):
                return y + 3
        """
        )
        self.shell.run_code("import %s" % mod_name)
        self.shell.run_code("pass")
        self.write_file(
            mod_fn,
            """
            broken broken broken
            """,
        )
        self.shell.run_code("pass")
        self.assertIn(mod_name, self.shell.user_ns)
        mod = sys.modules[mod_name]
        assert mod.foo(0) == 3

    def test_deduperreloader_imported_mod(self):
        self.shell.magic_autoreload("2")
        mod_name, mod_fn = self.new_module(
            """
            from os import environ
            def foo(n):
                pass
        """
        )
        self.shell.run_code("import %s" % mod_name)
        self.shell.run_code("pass")
        self.write_file(
            mod_fn,
            """
            from os import environ
            def foo():
                environ._data
                return 1
        """,
        )
        self.shell.run_code("pass")
        self.assertIn(mod_name, self.shell.user_ns)
        mod = sys.modules[mod_name]
        assert mod.foo() == 1


class AutoreloadClassMethodsDetectionSuite(unittest.TestCase):
    """
    Unit tests for autoreload testing logic
    """

    def test_autoreload_method(self):
        code1 = squish_text(
            """
            class C(n):
                def foo():
                    pass
        """
        )
        code2 = squish_text(
            """
            class C(n):
                def foo():
                    x = 1
                    return x
        """
        )
        deduperreloader = DeduperTestReloader()
        ast_1 = ast.parse(code1)
        ast_2 = ast.parse(code2)

        assert deduperreloader.detect_autoreload(ast_1, ast_2)
        assert deduperreloader._to_autoreload.defs_to_reload == []
        assert "C" in deduperreloader._to_autoreload.children
        assert ["foo"] == list(
            d[0][0] for d in deduperreloader._to_autoreload.children["C"].defs_to_reload
        )
        assert deduperreloader._to_autoreload.children["C"].children == {}

    def test_autoreload_no_changes(self):
        code1 = squish_text(
            """
            class D(n):
                def foo():
                    pass
            def foo():
                pass
        """
        )
        code2 = squish_text(
            """
            class D(n):
                def foo():
                    pass
            def foo():
                pass
        """
        )
        deduperreloader = DeduperTestReloader()
        ast_1 = ast.parse(code1)
        ast_2 = ast.parse(code2)

        assert deduperreloader.detect_autoreload(ast_1, ast_2)
        assert deduperreloader._to_autoreload.defs_to_reload == []
        assert deduperreloader._to_autoreload.children == {}

    def test_autoreload_add_function(self):
        code1 = squish_text(
            """
            class C:
                def foo():
                    pass
            def foo():
                pass
        """
        )
        code2 = squish_text(
            """
            class C:
                def foo():
                    x = 1
                    return x
                def bar():
                    return -1
            def foo():
                pass
        """
        )
        deduperreloader = DeduperTestReloader()
        ast_1 = ast.parse(code1)
        ast_2 = ast.parse(code2)

        assert deduperreloader.detect_autoreload(ast_1, ast_2)
        assert deduperreloader._to_autoreload.defs_to_reload == []
        assert "C" in deduperreloader._to_autoreload.children
        assert ["foo", "bar"] == list(
            d[0][0] for d in deduperreloader._to_autoreload.children["C"].defs_to_reload
        )
        assert len(deduperreloader._to_autoreload.children["C"].children) == 0

    def test_autoreload_remove_method(self):
        code1 = squish_text(
            """
            class C:
                def foo():
                    pass
            def foo():
                pass
        """
        )
        code2 = squish_text(
            """
            class C:
                pass
            def foo():
                pass
        """
        )
        deduperreloader = DeduperTestReloader()
        ast_1 = ast.parse(code1)
        ast_2 = ast.parse(code2)

        assert deduperreloader.detect_autoreload(ast_1, ast_2)

    def test_autoreload_remove_class(self):
        code1 = squish_text(
            """
            class C:
                def foo():
                    pass
            def foo():
                pass
        """
        )
        code2 = squish_text(
            """
            def foo():
                pass
        """
        )
        deduperreloader = DeduperTestReloader()
        ast_1 = ast.parse(code1)
        ast_2 = ast.parse(code2)

        assert deduperreloader.detect_autoreload(ast_1, ast_2)

    def test_autoreload_add_class_in_class(self):
        code1 = squish_text(
            """
            class C:
                pass
            def foo():
                pass
        """
        )
        code2 = squish_text(
            """
            class C:
                class D:
                    pass
            def foo():
                pass
        """
        )
        deduperreloader = DeduperTestReloader()
        ast_1 = ast.parse(code1)
        ast_2 = ast.parse(code2)

        assert deduperreloader.detect_autoreload(ast_1, ast_2)

    def test_autoreload_add_method_in_class_in_class(self):
        code1 = squish_text(
            """
            class C:
                class D:
                    x = 1
            def foo():
                pass
        """
        )
        code2 = squish_text(
            """
            class C:
                class D:
                    x = 1
                    def foo():
                        return 1
            def foo():
                pass
        """
        )
        deduperreloader = DeduperTestReloader()
        ast_1 = ast.parse(code1)
        ast_2 = ast.parse(code2)

        assert deduperreloader.detect_autoreload(ast_1, ast_2)
        assert deduperreloader._to_autoreload.defs_to_reload == []
        assert list(deduperreloader._to_autoreload.children.keys()) == ["C"]
        assert deduperreloader._to_autoreload.children["C"].defs_to_reload == []
        assert list(deduperreloader._to_autoreload.children["C"].children.keys()) == [
            "D"
        ]
        assert list(
            d[0][0]
            for d in deduperreloader._to_autoreload.children["C"]
            .children["D"]
            .defs_to_reload
        ) == ["foo"]
        assert deduperreloader._to_autoreload.children["C"].children["D"].children == {}

    def test_autoreload_add_var_and_method_in_class_in_class(self):
        code1 = squish_text(
            """
            class C:
                class D:
                    pass
            def foo():
                pass
        """
        )
        code2 = squish_text(
            """
            class C:
                class D:
                    x = 1
                    def foo():
                        return 1
            def foo():
                pass
        """
        )
        deduperreloader = DeduperTestReloader()
        ast_1 = ast.parse(code1)
        ast_2 = ast.parse(code2)

        assert deduperreloader.detect_autoreload(ast_1, ast_2)

    def test_autoreload_add_method_in_class_in_class_pass(self):
        code1 = squish_text(
            """
            class C:
                class D:
                    pass
            def foo():
                pass
        """
        )
        code2 = squish_text(
            """
            class C:
                class D:
                    def foo():
                        return 1
            def foo():
                pass
        """
        )
        deduperreloader = DeduperTestReloader()
        ast_1 = ast.parse(code1)
        ast_2 = ast.parse(code2)

        assert deduperreloader.detect_autoreload(ast_1, ast_2)
        assert deduperreloader._to_autoreload.defs_to_reload == []
        assert list(deduperreloader._to_autoreload.children.keys()) == ["C"]
        assert deduperreloader._to_autoreload.children["C"].defs_to_reload == []
        assert list(deduperreloader._to_autoreload.children["C"].children.keys()) == [
            "D"
        ]
        assert list(
            d[0][0]
            for d in deduperreloader._to_autoreload.children["C"]
            .children["D"]
            .defs_to_reload
        ) == ["foo"]
        assert deduperreloader._to_autoreload.children["C"].children["D"].children == {}

    def test_autoreload_add_method_in_class_in_class_more(self):
        code1 = squish_text(
            """
            class C:
                class D:
                    pass
            def foo():
                pass
        """
        )
        code2 = squish_text(
            """
            class C:
                def bar():
                    return -1
                class D:
                    def foo():
                        return 1
            def foo():
                pass
        """
        )
        deduperreloader = DeduperTestReloader()
        ast_1 = ast.parse(code1)
        ast_2 = ast.parse(code2)

        assert deduperreloader.detect_autoreload(ast_1, ast_2)
        assert deduperreloader._to_autoreload.defs_to_reload == []
        assert list(deduperreloader._to_autoreload.children.keys()) == ["C"]
        assert list(
            d[0][0] for d in deduperreloader._to_autoreload.children["C"].defs_to_reload
        ) == ["bar"]
        assert list(deduperreloader._to_autoreload.children["C"].children.keys()) == [
            "D"
        ]
        assert list(
            d[0][0]
            for d in deduperreloader._to_autoreload.children["C"]
            .children["D"]
            .defs_to_reload
        ) == ["foo"]
        assert deduperreloader._to_autoreload.children["C"].children["D"].children == {}

    def test_autoreload_add_method_in_class_in_class_with_members(self):
        code1 = squish_text(
            """
            class C:
                class D:
                    pass
            def foo():
                pass
        """
        )
        code2 = squish_text(
            """
            class C:
                def bar():
                    return -1
                class D:
                    s = 2
                    def foo():
                        return 1
            def foo():
                pass
        """
        )
        deduperreloader = DeduperTestReloader()
        ast_1 = ast.parse(code1)
        ast_2 = ast.parse(code2)

        assert deduperreloader.detect_autoreload(ast_1, ast_2)


class AutoreloadReliabilitySuite(ShellFixture):
    def test_autoreload_class_basic(self):
        self.shell.magic_autoreload("2")
        mod_name, mod_fn = self.new_module(
            """
            x = 9
            class C:
                def foo():
                    return 1
        """
        )
        self.shell.run_code("import %s" % mod_name)
        self.shell.run_code("pass")
        self.write_file(
            mod_fn,
            """
            x = 9
            class C:
                def foo():
                    return 1
            """,
        )
        self.shell.run_code("pass")
        self.assertIn(mod_name, self.shell.user_ns)
        mod = sys.modules[mod_name]
        assert mod.C.foo() == 1

    def test_remove_overridden_method(self):
        self.shell.magic_autoreload("2")
        mod_name, mod_fn = self.new_module(
            """
            class A:
                def foo(self):
                    return 1
            class B(A):
                def foo(self):
                    return 42
        """
        )
        self.shell.run_code(f"from {mod_name} import B; b = B()")
        self.shell.run_code("assert b.foo() == 42")
        self.write_file(
            mod_fn,
            """
            class A:
                def foo(self):
                    return 1
            class B(A):
                pass
            """,
        )
        self.shell.run_code("assert b.foo() == 1")

    def test_autoreload_class_use_outside_func(self):
        self.shell.magic_autoreload("2")
        mod_name, mod_fn = self.new_module(
            """
            x = 9
            class C:
                def foo():
                    return 1
        """
        )
        self.shell.run_code("import %s" % mod_name)
        self.shell.run_code("pass")
        self.write_file(
            mod_fn,
            """
            x = 9
            class C:
                def foo():
                    return 1+x
            """,
        )
        self.shell.run_code("pass")
        self.assertIn(mod_name, self.shell.user_ns)
        mod = sys.modules[mod_name]
        assert mod.C.foo() == 10

    def test_autoreload_class_use_class_member(self):
        self.shell.magic_autoreload("2")
        mod_name, mod_fn = self.new_module(
            """
            x = 9
            class C:
                def foo():
                    return 1
        """
        )
        self.shell.run_code("import %s" % mod_name)
        self.shell.run_code("pass")
        self.write_file(
            mod_fn,
            """
            class C:
                x = 9
                def foo():
                    return 1+C.x
            """,
        )
        self.shell.run_code("pass")
        self.assertIn(mod_name, self.shell.user_ns)
        mod = sys.modules[mod_name]
        assert mod.C.foo() == 10

    def test_autoreload_class_pass(self):
        self.shell.magic_autoreload("2")
        mod_name, mod_fn = self.new_module(
            """
            x = 9
            class C:
                pass
        """
        )
        self.shell.run_code("import %s" % mod_name)
        self.shell.run_code("pass")
        self.write_file(
            mod_fn,
            """
            class C:
                x = 9
                def foo():
                    return 1+C.x
            """,
        )
        self.shell.run_code("pass")
        self.assertIn(mod_name, self.shell.user_ns)
        mod = sys.modules[mod_name]
        assert mod.C.foo() == 10

    def test_autoreload_class_ellipsis(self):
        self.shell.magic_autoreload("2")
        mod_name, mod_fn = self.new_module(
            """
            x = 9
            class C:
                ...
        """
        )
        self.shell.run_code("import %s" % mod_name)
        self.shell.run_code("pass")
        self.write_file(
            mod_fn,
            """
            class C:
                x = 9
                def foo():
                    return 1+C.x
            """,
        )
        self.shell.run_code("pass")
        self.assertIn(mod_name, self.shell.user_ns)
        mod = sys.modules[mod_name]
        assert mod.C.foo() == 10

    def test_autoreload_class_default_autoreload(self):
        self.shell.magic_autoreload("2")
        mod_name, mod_fn = self.new_module(
            """
            class C:
                x = 9
                def foo():
                    return 1+C.x
        """
        )
        self.shell.run_code("import %s" % mod_name)
        self.shell.run_code("pass")
        self.write_file(
            mod_fn,
            """
            class C:
                x = 20
                def foo():
                    return 1+C.x
            """,
        )
        self.shell.run_code("pass")
        self.assertIn(mod_name, self.shell.user_ns)
        mod = sys.modules[mod_name]
        assert mod.C.foo() == 21

    def test_autoreload_class_nested(self):
        self.shell.magic_autoreload("2")
        mod_name, mod_fn = self.new_module(
            """
            class C:
                x = 9
                class D:
                    def foo():
                        pass
        """
        )
        self.shell.run_code("import %s" % mod_name)
        self.shell.run_code("pass")
        self.write_file(
            mod_fn,
            """
            class C:
                x = 9
                class D:
                    def foo():
                        return 10
            """,
        )
        self.shell.run_code("pass")
        self.assertIn(mod_name, self.shell.user_ns)
        mod = sys.modules[mod_name]
        assert mod.C.D.foo() == 10

    def test_autoreload_class_nested2(self):
        self.shell.magic_autoreload("2")
        mod_name, mod_fn = self.new_module(
            """
            class C:
                x = 9
                def c():
                    return 1
                class D:
                    def foo():
                        pass
        """
        )
        self.shell.run_code("import %s" % mod_name)
        self.shell.run_code("pass")
        self.write_file(
            mod_fn,
            """
            class C:
                x = 9
                def c():
                    return 1
                class D:
                    def foo():
                        return 10
            """,
        )
        self.shell.run_code("pass")
        self.assertIn(mod_name, self.shell.user_ns)
        mod = sys.modules[mod_name]
        assert mod.C.D.foo() == 10
        assert mod.C.c() == 1

    def test_autoreload_class_nested3(self):
        self.shell.magic_autoreload("2")
        mod_name, mod_fn = self.new_module(
            """
            class C:
                x = 9
                def c():
                    return 1
                class D:
                    def foo():
                        pass
        """
        )
        self.shell.run_code("import %s" % mod_name)
        self.shell.run_code("pass")
        self.write_file(
            mod_fn,
            """
            class C:
                x = 9
                def c():
                    return 13
                class D:
                    def foo():
                        return 10
            """,
        )
        self.shell.run_code("pass")
        self.assertIn(mod_name, self.shell.user_ns)
        mod = sys.modules[mod_name]
        assert mod.C.D.foo() == 10
        assert mod.C.c() == 13

    def test_autoreload_new_class_added(self):
        self.shell.magic_autoreload("2")
        mod_name, mod_fn = self.new_module(
            """
            class C:
                x = 9
                def c():
                    return 1
        """
        )
        self.shell.run_code("import %s" % mod_name)
        self.shell.run_code("pass")
        self.write_file(
            mod_fn,
            """
            class C:
                x = 9
                def c():
                    return 13
            class D:
                def c():
                    return 1
            """,
        )
        self.shell.run_code("pass")
        self.assertIn(mod_name, self.shell.user_ns)
        mod = sys.modules[mod_name]
        assert mod.C.c() == 13
        assert mod.D.c() == 1

    def test_autoreload_class_nested_default(self):
        self.shell.magic_autoreload("2")
        mod_name, mod_fn = self.new_module(
            """
            class C:
                pass
        """
        )
        self.shell.run_code("import %s" % mod_name)
        self.shell.run_code("pass")
        self.write_file(
            mod_fn,
            """
            class C:
                x = 9
                def c():
                    return 13
                class D:
                    def foo():
                        return 10
            """,
        )
        self.shell.run_code("pass")
        self.assertIn(mod_name, self.shell.user_ns)
        mod = sys.modules[mod_name]
        assert mod.C.D.foo() == 10
        assert mod.C.c() == 13

    def test_autoreload_class_nested_using_members(self):
        self.shell.magic_autoreload("2")
        mod_name, mod_fn = self.new_module(
            """
            class C:
                x = 9
                def c():
                    return 13
                class D:
                    def foo():
                        return 10
            """
        )
        self.shell.run_code("import %s" % mod_name)
        self.shell.run_code("pass")
        self.write_file(
            mod_fn,
            """
            class C:
                x = 9
                def c():
                    return 13
                class D:
                    def foo():
                        return 10 + C.x
            """,
        )
        self.shell.run_code("pass")
        self.assertIn(mod_name, self.shell.user_ns)
        mod = sys.modules[mod_name]
        assert mod.C.D.foo() == 19
        assert mod.C.c() == 13

    def test_autoreload_class_nested_using_members_ellipsis(self):
        self.shell.magic_autoreload("2")
        mod_name, mod_fn = self.new_module(
            """
            class C:
                x = 9
                def c():
                    return 13
                class D:
                    def foo():
                        ...
            """
        )
        self.shell.run_code("import %s" % mod_name)
        self.shell.run_code("pass")
        self.write_file(
            mod_fn,
            """
            class C:
                x = 9
                def c():
                    return 13
                class D:
                    def foo():
                        return 10 + C.x
            """,
        )
        self.shell.run_code("pass")
        self.assertIn(mod_name, self.shell.user_ns)
        mod = sys.modules[mod_name]
        assert mod.C.D.foo() == 19
        assert mod.C.c() == 13

    def test_method_decorators_no_changes(self):
        self.shell.magic_autoreload("2")
        mod_name, mod_file = self.new_module(
            """
            class Foo:
                @classmethod
                def bar(cls):
                    return 0
                    
                @classmethod
                def foo(cls):
                    return 42 + cls.bar()
            
            foo = Foo.foo
            """
        )
        self.shell.run_code("import %s" % mod_name)
        self.shell.run_code("pass")
        self.assertIn(mod_name, self.shell.user_ns)
        mod = sys.modules[mod_name]
        assert mod.foo() == 42

        self.shell.run_code(f"assert {mod_name}.foo() == 42")
        self.write_file(
            mod_file,
            """
            class Foo:
                @classmethod
                def bar(cls):
                    return 0
            
                @classmethod
                def foo(cls):
                    return 42 + cls.bar()
            
            foo = Foo.foo
            """,
        )
        self.shell.run_code(f"assert {mod_name}.foo() == 42")

    def test_method_decorators_no_changes1(self):
        self.shell.magic_autoreload("2")
        mod_name, mod_file = self.new_module(
            """
            class Foo:
                @classmethod
                def bar(cls):
                    return 0
                    
                @classmethod
                def foo(cls):
                    return 42 + cls.bar()
            
            foo = Foo.foo
            """
        )

        self.shell.run_code(f"from {mod_name} import foo")
        self.shell.run_code("assert foo() == 42")
        self.write_file(
            mod_file,
            """
            class Foo:
                @classmethod
                def bar(cls):
                    return 0
            
                @classmethod
                def foo(cls):
                    return 42 + cls.bar()
            
            foo = Foo.foo
            """,
        )
        self.shell.run_code("assert foo() == 42")

    def test_method_classmethod_one_change(self):
        self.shell.magic_autoreload("2")
        mod_name, mod_file = self.new_module(
            """
            class Foo:
                @classmethod
                def bar(cls):
                    return 0
                    
                @classmethod
                def func(cls):
                    return 42 + cls.bar()
            
            func = Foo.func
            """
        )
        self.shell.run_code("import %s" % mod_name)
        self.shell.run_code(f"assert {mod_name}.func() == 42")
        self.write_file(
            mod_file,
            """
            class Foo:
                @classmethod
                def bar(cls):
                    return 1
            
                @classmethod
                def func(cls):
                    return 42 + cls.bar()
            
            func = Foo.func
            """,
        )
        mod = sys.modules[mod_name]
        self.shell.run_code(f"assert {mod_name}.func() == 43")

    def test_method_staticmethod_one_change(self):
        self.shell.magic_autoreload("2")
        mod_name, mod_file = self.new_module(
            """
            class Foo:
                @staticmethod
                def bar():
                    return 0
                    
                @staticmethod
                def func():
                    return 42 + Foo.bar()
            
            func = Foo.func
            """
        )
        self.shell.run_code(f"from {mod_name} import func")
        self.shell.run_code("assert func() == 42")
        self.write_file(
            mod_file,
            """
            class Foo:
                @staticmethod
                def bar():
                    return 1
            
                @staticmethod
                def func():
                    return 42 + Foo.bar()
            
            func = Foo.func
            """,
        )
        self.shell.run_code("assert func() == 43")

    def test_autoreload_class_default_args(self):
        self.shell.magic_autoreload("2")
        mod_name, mod_fn = self.new_module(
            """
            x = 42
            class Foo:
                def foo(self, y): return y
        """
        )
        self.shell.run_code("import %s" % mod_name)
        self.shell.run_code("pass")
        self.write_file(
            mod_fn,
            """
            x = 42
            class Foo:
                def foo(self, y=x): return y
            """,
        )
        self.shell.run_code("pass")
        self.assertIn(mod_name, self.shell.user_ns)
        mod = sys.modules[mod_name]
        obj = mod.Foo()
        assert obj.foo(2) == 2
        assert obj.foo() == 42

    def test_autoreload_class_change_default_args(self):
        self.shell.magic_autoreload("2")
        mod_name, mod_fn = self.new_module(
            """
            x = 42
            class Foo:
                def foo(y): return y
        """
        )
        self.shell.run_code("import %s" % mod_name)
        self.shell.run_code("pass")
        self.write_file(
            mod_fn,
            """
            x = 44
            class Foo:
                def foo(y=x): return y
            """,
        )
        self.shell.run_code("pass")
        self.assertIn(mod_name, self.shell.user_ns)
        mod = sys.modules[mod_name]
        assert mod.Foo.foo() == 44

    def test_autoreload_class_new_class(self):
        self.shell.magic_autoreload("2")
        mod_name, mod_fn = self.new_module(
            """
            x = 42
            class Foo:
                def foo(y=x): return y
        """
        )
        self.shell.run_code("import %s" % mod_name)
        self.shell.run_code("pass")
        prev_foo = self.shell.user_ns[mod_name].Foo.foo
        self.write_file(
            mod_fn,
            """
            x = 42
            class Foo:
                def foo(y=x): return y
            class C:
                def foo(): return 200
            """,
        )
        self.shell.run_code("pass")
        self.assertIn(mod_name, self.shell.user_ns)
        self.assertIs(prev_foo, self.shell.user_ns[mod_name].Foo.foo)
        mod = sys.modules[mod_name]
        assert mod.Foo.foo() == 42
        assert mod.C.foo() == 200

    def test_autoreload_overloaded_vars(self):
        self.shell.magic_autoreload("2")
        mod_name, mod_fn = self.new_module(
            """
            x = 42
            class Foo:
                pass
        """
        )
        self.shell.run_code("import %s" % mod_name)
        self.shell.run_code("pass")
        mod = sys.modules[mod_name]
        self.write_file(
            mod_fn,
            """
            x = 44
            class Foo:
                def foo(): 
                    x = 2
                    return x
            """,
        )
        self.shell.run_code("pass")
        self.assertIn(mod_name, self.shell.user_ns)
        assert mod.Foo.foo() == 2

    def test_autoreload_overloaded_vars2(self):
        self.shell.magic_autoreload("2")
        mod_name, mod_fn = self.new_module(
            """
            x = 42
            def foo():
                return x
        """
        )
        self.shell.run_code("import %s" % mod_name)
        self.shell.run_code("pass")
        mod = sys.modules[mod_name]
        self.write_file(
            mod_fn,
            """
            x = 44
            def foo(): 
                x = 2
                return x
            """,
        )
        self.shell.run_code("pass")
        self.assertIn(mod_name, self.shell.user_ns)
        assert mod.foo() == 2


class DecoratorPatchingSuite(ShellFixture):
    """
    Unit tests for autoreload patching logic
    """

    def test_modify_property(self):
        self.shell.magic_autoreload("2")
        mod_name, mod_file = self.new_module(
            """
            class Foo:
                @property
                def foo(self):
                    return 42
            """
        )
        self.shell.run_code(f"from {mod_name} import Foo")
        self.shell.run_code("foo = Foo()")
        self.shell.run_code("assert foo.foo == 42")
        self.write_file(
            mod_file,
            """
            class Foo:
                @property
                def foo(self):
                    return 43
            """,
        )
        self.shell.run_code("pass")
        self.shell.run_code("assert foo.foo == 43")

    def test_method_decorator(self):
        self.shell.magic_autoreload("2")
        mod_name, mod_file = self.new_module(
            """
            def incremented(f):
                return lambda *args: f(*args) + 1

            class Foo:
                @classmethod
                @incremented
                def foo(cls):
                    return 42
            
            foo = Foo.foo
            """
        )
        self.shell.run_code(f"from {mod_name} import foo")
        self.shell.run_code("assert foo() == 43")
        self.write_file(
            mod_file,
            """
            def incremented(f):
                return lambda *args: f(*args) + 1

            class Foo:
                @classmethod
                def foo(cls):
                    return 42
            
            foo = Foo.foo
            """,
        )
        self.shell.run_code("assert foo() == 42")

    def test_method_modified_decorator(self):
        self.shell.magic_autoreload("2")
        mod_name, mod_file = self.new_module(
            """
            def incremented(f):
                return lambda *args: f(*args) + 1

            class Foo:
                @classmethod
                @incremented
                def foo(cls):
                    return 42
            
            foo = Foo.foo
            """
        )
        self.shell.run_code(f"from {mod_name} import foo")
        self.shell.run_code("assert foo() == 43")
        self.write_file(
            mod_file,
            """
            def incremented(f):
                return lambda *args: f(*args) + 0

            class Foo:
                @classmethod
                @incremented
                def foo(cls):
                    return 42
            
            foo = Foo.foo
            """,
        )
        self.shell.run_code("assert foo() == 42")

    def test_function_decorators(self):
        self.shell.magic_autoreload("2")
        mod_name, mod_file = self.new_module(
            """
            def incremented(f):
                return lambda *args: f(*args) + 1
            
            @incremented
            def foo():
                return 42
            """
        )
        self.shell.run_code("import %s" % mod_name)
        self.shell.run_code("pass")
        mod = sys.modules[mod_name]
        assert mod.foo() == 43
        self.write_file(
            mod_file,
            """
            def incremented(f):
                return lambda *args: f(*args) + 1

            def foo():
                return 42
            """,
        )
        self.shell.run_code("pass")
        assert mod.foo() == 42
        self.write_file(
            mod_file,
            """
            def incremented(v):
                def deco(f):
                    return lambda *args: f(*args) + v
                return deco

            @incremented(2)
            def foo():
                return 43
            """,
        )
        self.shell.run_code("pass")
        assert mod.foo() == 45

    def test_method_decorators_again(self):
        self.shell.magic_autoreload("2")
        mod_name, mod_file = self.new_module(
            """
            class Foo:
                @classmethod
                def bar(cls):
                    return 0
                    
                @classmethod
                def foo(cls):
                    return 42 + cls.bar()
            
            foo = Foo.foo
            """
        )
        self.shell.run_code("import %s" % mod_name)
        self.shell.run_code("pass")
        mod = sys.modules[mod_name]
        assert mod.foo() == 42
        self.write_file(
            mod_file,
            """
            class Foo:
                @classmethod
                def bar(cls):
                    return 1
            
                @classmethod
                def foo(cls):
                    return 42 + cls.bar()
            
            foo = Foo.foo
            """,
        )
        self.shell.run_code("pass")
        assert mod.Foo.foo() == 43
        assert mod.foo() == 43

    # This test verifies that the correct globals are used when patching a function
    # decorated by a function from another module. For this example, we should always
    # use <mod_name>.__dict__ as the global environment when patching foo, which comes
    # from <mod_name>, and never <other_mod_name>.__dict__, which is what we would get
    # if we use foo.__globals__ after it has been decorated.
    def test_function_decorator_from_other_module(self):
        self.shell.magic_autoreload("2")
        other_mod_name, _ = self.new_module(
            """
            import functools

            def incremented(f):
                @functools.wraps(f)
                def wrapper(*args, **kwargs):
                    return f(*args, **kwargs) + 1
                return wrapper
            """
        )
        mod_name, mod_file = self.new_module(
            f"""
            from {other_mod_name} import incremented as deco
            @deco
            def foo():
                return 42
            """
        )
        self.shell.run_code(f"from {mod_name} import foo")
        self.shell.run_code("assert foo() == 43")
        self.write_file(
            mod_file,
            f"""
            from {other_mod_name} import incremented as deco
            @deco
            def foo():
                return 43
            """,
        )
        self.shell.run_code("assert foo() == 44")


class TestAutoreloadEnum(ShellFixture):
    def test_reload_enums(self):
        self.shell.magic_autoreload("2")
        mod_name, mod_fn = self.new_module(
            """
            from enum import Enum
            class MyEnum(Enum):
                A = 'A'
                B = 'B'
            """,
        )
        self.shell.run_code("import %s" % mod_name)
        self.shell.run_code("pass")
        mod = sys.modules[mod_name]
        self.write_file(
            mod_fn,
            """
            from enum import Enum
            class MyEnum(Enum):
                A = 'A'
                B = 'B'
                C = 'C'
            """,
        )
        self.shell.run_code("pass")
        assert mod.MyEnum.C.value == "C"


if __name__ == "__main__":
    unittest.main()
