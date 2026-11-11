"""The installed CLI (`indiebiz-evidence ...`) must work from any directory.

Codex point: the old install smoke only imported the package; it never proved
the first-success path works after `pip install` from outside the repository.
These tests exercise the same entry point the console script calls, with paths
relative to a temporary CWD -- not the repo root.
"""
import os
import sys
import tempfile
import unittest

PROJ = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(PROJ, "src"))

from indiebiz_evidence import cli  # noqa: E402


class TestInstalledCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ibe-cli-")
        self.addCleanup(self.tmp.cleanup)
        self._cwd = os.getcwd()
        os.chdir(self.tmp.name)
        self.addCleanup(os.chdir, self._cwd)

    def test_demo_builds_from_package_data(self):
        rc = cli.main(["demo", "--db", "demo.db"])
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.exists("demo.db"))

    def test_audit_reads_cwd_relative_db(self):
        cli.main(["demo", "--db", "demo.db"])
        rc = cli.main(["audit", "--db", "demo.db", "--source", "demo-prices"])
        self.assertEqual(rc, 0)

    def test_import_resolves_input_relative_to_cwd(self):
        os.makedirs("exports")
        with open(os.path.join("exports", "2099-01-01.csv"), "w",
                  encoding="utf-8", newline="") as f:
            f.write("id,price\nA,10\n")
        with open(os.path.join("exports", "2099-01-02.csv"), "w",
                  encoding="utf-8", newline="") as f:
            f.write("id,price\nA,40\n")
        rc = cli.main(["import", "--source", "cli-test", "--input", "exports",
                       "--db", "my.db"])
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.exists("my.db"))

    def test_import_missing_dir_fails_loudly(self):
        rc = cli.main(["import", "--source", "x", "--input", "no-such-dir",
                       "--db", "my.db"])
        self.assertEqual(rc, 3)

    def test_mcp_selftest_via_cli(self):
        cli.main(["demo", "--db", "demo.db"])
        rc = cli.main(["mcp", "--db", "demo.db", "--selftest"])
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()