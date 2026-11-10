"""The guards themselves must fail correctly.

A guard that reports success without checking anything is worse than no guard: it
manufactures confidence. Codex found exactly that in the first version -- git
failing produced "checked 0 files" and exit 0. These tests pin the failure paths.
"""
import os
import subprocess
import sys
import unittest

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJ, "scripts"))

import check_no_real_data as data_guard  # noqa: E402
import check_no_runtime_deps as dep_guard  # noqa: E402


class FakeProc:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class TestDataGuardFailurePaths(unittest.TestCase):
    def setUp(self):
        self._orig = subprocess.run

    def tearDown(self):
        subprocess.run = self._orig

    def test_git_missing_is_a_failure(self):
        def boom(*a, **k):
            raise OSError("git not found")
        subprocess.run = boom
        self.assertEqual(data_guard.main([]), 1)

    def test_git_error_code_is_a_failure(self):
        subprocess.run = lambda *a, **k: FakeProc(128, "", "fatal: not a git repository")
        self.assertEqual(data_guard.main([]), 1)

    def test_empty_file_list_is_a_failure(self):
        subprocess.run = lambda *a, **k: FakeProc(0, "", "")
        self.assertEqual(data_guard.main([]), 1)

    def test_staged_mode_reads_the_staged_blob(self):
        """A dirty working tree must not decide what the committed check saw."""
        calls = []

        def fake(cmd, *a, **k):
            calls.append(cmd)
            if cmd[:2] == ("git", "diff"):
                return FakeProc(0, "README.md\n", "")
            if cmd[:2] == ("git", "show"):
                # the staged content is clean even though the file on disk is not
                return FakeProc(0, "nothing secret here\n", "")
            return FakeProc(0, "", "")

        subprocess.run = fake
        self.assertEqual(data_guard.main(["--staged"]), 0)
        self.assertTrue(any(c[:2] == ("git", "show") for c in calls),
                        "staged mode must read the blob via 'git show :path'")


class TestDependencyGuardPython39(unittest.TestCase):
    def test_stdlib_fallback_covers_what_the_package_imports(self):
        """Python 3.9 has no sys.stdlib_module_names; the fallback must not accuse
        the package of importing __future__ or unicodedata as third-party deps."""
        had = hasattr(sys, "stdlib_module_names")
        saved = getattr(sys, "stdlib_module_names", None)
        try:
            if had:
                del sys.stdlib_module_names
            roots = dep_guard.imported_roots()
            stdlib = dep_guard.main.__globals__  # ensure module loaded
            self.assertIn("__future__", roots)
            self.assertIn("unicodedata", roots)
            rc = dep_guard.main([])
            self.assertEqual(rc, 0, "python 3.9 fallback must not report false positives")
        finally:
            if had:
                sys.stdlib_module_names = saved

    def test_string_form_dependency_declaration_is_rejected(self):
        orig = dep_guard.declared_deps
        try:
            dep_guard.declared_deps = lambda: '["requests"]'
            self.assertEqual(dep_guard.main([]), 1)
        finally:
            dep_guard.declared_deps = orig

    def test_real_package_is_clean(self):
        self.assertEqual(dep_guard.main([]), 0)


if __name__ == "__main__":
    unittest.main()
