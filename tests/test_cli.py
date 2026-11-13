"""The installed CLI (`indiebiz-evidence ...`) must work from any directory.

Codex point: the old install smoke only imported the package; it never proved
the first-success path works after `pip install` from outside the repository.
These tests exercise the same entry point the console script calls, with paths
relative to a temporary CWD -- not the repo root.
"""
import json
import os
import subprocess
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

    def test_empty_reimport_refused_by_default_allowed_with_flag(self):
        from indiebiz_evidence import store
        os.makedirs("exports")
        with open(os.path.join("exports", "2099-01-01.csv"), "w",
                  encoding="utf-8", newline="") as f:
            f.write("id,price\nA,10\nB,20\n")
        cli.main(["import", "--source", "s", "--input", "exports", "--db", "my.db"])
        # overwrite the same date with an empty export
        with open(os.path.join("exports", "2099-01-01.csv"), "w",
                  encoding="utf-8", newline="") as f:
            f.write("id,price\n")
        # default: refused, NOT a crash/exit-3-after-commit; old facts kept
        rc = cli.main(["import", "--source", "s", "--input", "exports", "--db", "my.db"])
        self.assertEqual(rc, 0)
        con = store.connect("my.db")
        n = con.execute("SELECT COUNT(*) FROM generic_facts WHERE source='s'").fetchone()[0]
        con.close()
        self.assertEqual(n, 2, "default must keep the existing facts")
        # explicit flag: the destructive clear is allowed
        rc = cli.main(["import", "--source", "s", "--input", "exports", "--db", "my.db",
                       "--allow-empty-replace"])
        self.assertEqual(rc, 0)
        con = store.connect("my.db")
        n = con.execute("SELECT COUNT(*) FROM generic_facts WHERE source='s'").fetchone()[0]
        con.close()
        self.assertEqual(n, 0, "--allow-empty-replace clears the facts")

    def test_mcp_selftest_via_cli(self):
        cli.main(["demo", "--db", "demo.db"])
        rc = cli.main(["mcp", "--db", "demo.db", "--selftest"])
        self.assertEqual(rc, 0)


class TestMcpEmptyDbStartup(unittest.TestCase):
    """P0-1: an MCP host installing from the registry has no data yet. The server
    must START (not exit 2) and tell the user how to import, not die silently."""

    def test_mcp_starts_with_no_db_and_guides(self):
        work = tempfile.mkdtemp(prefix="ibe-mcp-empty-")
        env = dict(os.environ, PYTHONIOENCODING="utf-8",
                   PYTHONPATH=os.path.join(PROJ, "src"))
        init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                           "clientInfo": {"name": "t", "version": "0"}}}
        ls = {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
              "params": {"name": "list_sources", "arguments": {}}}
        stdin = json.dumps(init) + "\n" + json.dumps(ls) + "\n"
        p = subprocess.run([sys.executable, "-m", "indiebiz_evidence.cli", "mcp"],
                           input=stdin, capture_output=True, text=True,
                           cwd=work, env=env, timeout=60)
        self.assertEqual(p.returncode, 0, "mcp must not exit 2 on a missing db")
        resp = [json.loads(l) for l in p.stdout.splitlines() if l.strip()]
        ls_resp = [d for d in resp if d.get("id") == 2]
        self.assertTrue(ls_resp)
        payload = json.loads(ls_resp[0]["result"]["content"][0]["text"])
        self.assertEqual(payload["sources"], [])
        self.assertIn("next_step", payload)
        self.assertIn("import", payload["next_step"])


if __name__ == "__main__":
    unittest.main()