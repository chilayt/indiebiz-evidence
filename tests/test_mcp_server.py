"""End-to-end MCP protocol tests against a real subprocess.

The server is exercised over stdio exactly as a host would: handshake, tool
discovery, tool calls, notifications, unknown methods. The database is the
synthetic demo, so a clean clone runs every test and skips none.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJ, "src"))

from indiebiz_evidence import demo  # noqa: E402

INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                   "clientInfo": {"name": "test", "version": "0"}}}
INITIALIZED = {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}


def req(mid, method, params=None):
    m = {"jsonrpc": "2.0", "id": mid, "method": method}
    if params is not None:
        m["params"] = params
    return m


def run_session(db_path, msgs, timeout=180):
    script = os.path.join(PROJ, "scripts", "mcp_server.py")
    p = subprocess.run([sys.executable, script, "--db", db_path],
                       input="\n".join(json.dumps(m) for m in msgs) + "\n",
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout, cwd=PROJ)
    out = [json.loads(l) for l in (p.stdout or "").splitlines() if l.strip()]
    by_id = {}
    for r in out:
        if isinstance(r, dict) and "id" in r:
            by_id[r["id"]] = r
    return by_id, p.returncode, (p.stderr or "")


class TestMcpProtocol(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="ibe-core-")
        cls.db = os.path.join(cls.tmp, "demo.db")
        demo.build(cls.db)
        msgs = [
            INIT, INITIALIZED,
            req(2, "tools/list"),
            req(3, "tools/call", {"name": "list_sources", "arguments": {}}),
            req(4, "tools/call", {"name": "audit_field_coverage",
                                  "arguments": {"source": "demo-prices"}}),
            req(5, "tools/call", {"name": "diff_snapshots",
                                  "arguments": {"source": "demo-prices"}}),
            req(6, "tools/call", {"name": "no_such_tool", "arguments": {}}),
            req(7, "ping"),
            {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {}},
            req(8, "bogus/method"),
        ]
        cls.responses, cls.rc, cls.err = run_session(cls.db, msgs)

    def test_server_exits_clean(self):
        self.assertEqual(self.rc, 0, self.err[-600:])

    def test_initialize(self):
        init = self.responses[1]["result"]
        self.assertEqual(init["protocolVersion"], "2025-06-18")
        self.assertEqual(init["serverInfo"]["name"], "indiebiz-evidence")
        self.assertIn("tools", init["capabilities"])
        self.assertTrue(init["instructions"])

    def test_tool_inventory_is_generic_only(self):
        tools = {t["name"] for t in self.responses[2]["result"]["tools"]}
        self.assertEqual(tools, {
            "list_sources", "audit_field_coverage", "search_records",
            "get_source_entity", "query_series", "get_source_evidence_chain",
            "diff_snapshots", "list_entities", "find_duplicate_entities",
            "resolve_entities", "list_source_anomalies"})
        for name in ("search_entities", "get_entity", "get_daily_brief", "list_dates"):
            self.assertNotIn(name, tools, "vertical-only tools must not ship here")

    def test_list_sources(self):
        r = self.responses[3]["result"]
        self.assertFalse(r.get("isError"))
        payload = json.loads(r["content"][0]["text"])
        names = {s["source"] for s in payload["sources"]}
        self.assertIn("demo-prices", names)
        self.assertIn("demo-ranks", names)

    def test_audit_field_coverage(self):
        payload = json.loads(self.responses[4]["result"]["content"][0]["text"])
        self.assertEqual(payload["source"], "demo-prices")
        fields = {f["field"]: f for f in payload["fields"]}
        self.assertIn("price", fields)
        self.assertIn(fields["price"]["status"], ("ok", "partial_drop", "absent_on_latest"))

    def test_diff_has_span_and_boundaries(self):
        payload = json.loads(self.responses[5]["result"]["content"][0]["text"])
        self.assertEqual(payload["from"], "2099-01-01")
        self.assertEqual(payload["to"], "2099-01-02")
        self.assertIn("span_days", payload)
        self.assertIn("identity_boundaries", payload)

    def test_unknown_tool_is_error(self):
        self.assertTrue(self.responses[6]["result"].get("isError"))

    def test_ping(self):
        self.assertEqual(self.responses[7]["result"], {})

    def test_notifications_are_never_answered(self):
        self.assertNotIn("notifications/cancelled", json.dumps(self.responses))

    def test_unknown_method_is_jsonrpc_error(self):
        self.assertIn("error", self.responses[8])
        self.assertEqual(self.responses[8]["error"]["code"], -32601)


if __name__ == "__main__":
    unittest.main()
