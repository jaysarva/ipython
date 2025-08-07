#!/usr/bin/env python
from __future__ import annotations
import os
import platform
import random
import shutil
import sys
import tempfile
import textwrap
import time
import unittest
from IPython.extensions.autoreload import AutoreloadMagics


def squish_text(text: str) -> str:
    """
    Turns text like this:

    '''        def foo():
    return "bar"
            def baz():
                return "bat"
    def bam():
                return "bat"
    '''

    into this:

    '''def foo():
        return "bar"
    def baz():
        return "bat"
    def bam():
        return "bat"
    '''

    The former is common when we are trying to use string templates
    whose parameters are multiline and unaware of the existing indentation.

    :param text: a string with messed up indentation
    :return: `text` but with indentation fixed
    """
    prev_indentation = 0
    transformed_text_lines = []
    for line in text.strip("\n").splitlines():
        line_without_indentation = line.lstrip()
        indentation = len(line) - len(line_without_indentation)
        if indentation == 0:
            indentation = prev_indentation
        else:
            prev_indentation = indentation
        transformed_text_lines.append(
            textwrap.indent(line_without_indentation, " " * indentation)
        )
    return textwrap.dedent("\n".join(transformed_text_lines))


class FakeShell:
    def __init__(self):
        self.ns = {}
        self.user_ns = self.ns
        self.user_ns_hidden = {}
        self.auto_magics = AutoreloadMagics(shell=self)

    @staticmethod
    def pre_run_cell(obj):
        try_with_arg = False
        try:
            obj.pre_run_cell()
        except TypeError:
            try_with_arg = True
        if try_with_arg:
            obj.pre_run_cell(None)

    @staticmethod
    def post_run_cell(obj):
        try_with_arg = False
        try:
            obj.post_run_cell()
        except TypeError:
            try_with_arg = True
        if try_with_arg:
            obj.post_run_cell(None)

    def run_code(self, code):
        self.pre_run_cell(self.auto_magics)
        exec(code, self.user_ns)
        self.auto_magics.post_execute_hook()

    def push(self, items):
        self.ns.update(items)

    def magic_autoreload(self, parameter):
        self.auto_magics.autoreload(parameter)


class ShellFixture(unittest.TestCase):
    """Fixture for creating test module files"""

    test_dir = None
    old_sys_path = None
    filename_chars = "abcdefghijklmopqrstuvwxyz0123456789"

    def setUp(self):
        self.created_temp_modules = set()
        self.test_dir = tempfile.mkdtemp()
        self.old_sys_path = list(sys.path)
        sys.path.insert(0, self.test_dir)
        self.shell = FakeShell()

    def tearDown(self):
        for mod_name in self.created_temp_modules:
            sys.modules.pop(mod_name, None)
        shutil.rmtree(self.test_dir)
        sys.path = self.old_sys_path

        self.test_dir = None
        self.old_sys_path = None
        self.shell = None

    def get_module(self):
        module_name = "tmpmod_" + "".join(random.sample(self.filename_chars, 20))
        if module_name in sys.modules:
            del sys.modules[module_name]
        file_name = os.path.join(self.test_dir, module_name + ".py")
        return module_name, file_name

    def write_file(self, filename, content):
        """
        Write a file, and force a timestamp difference of at least one second

        Notes
        -----
        Python's .pyc files record the timestamp of their compilation
        with a time resolution of one second.

        Therefore, we need to force a timestamp difference between .py
        and .pyc, without having the .py file be timestamped in the
        future, and without changing the timestamp of the .pyc file
        (because that is stored in the file). The only reliable way
        to achieve this seems to be to sleep.

        Doesn't seem necessary on Darwin so we make this the exception.
        """
        if platform.system().lower() != "darwin":
            time.sleep(1.05)
        with open(filename, "w", encoding="utf-8") as f:
            f.write(squish_text(content))

    def new_module(self, code):
        mod_name, mod_fn = self.get_module()
        with open(mod_fn, "w", encoding="utf-8") as f:
            f.write(squish_text(code))
        self.created_temp_modules.add(mod_name)
        return mod_name, mod_fn
