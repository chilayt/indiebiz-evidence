"""Zero-dependency MCP server over the generic evidence store.

Exposes the bring-your-own-data tools (audit, search, diff, resolution) to any
MCP host. Hand-rolled JSON-RPC 2.0 over stdio using only the standard library, so
the engine has no runtime dependencies to install or audit.

  python scripts/mcp_server.py --db data/my.db            # serve over stdio
  python scripts/mcp_server.py --db data/my.db --selftest # human smoke test
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from . import __version__, generic as G, store

PROTOCOL_VERSIONS = ("2024-11-05", "2025-03-26", "2025-06-18")
DEFAULT_PROTOCOL = "2025-06-18"

_S = {"type": "string"}
_N = {"type": "number"}
_I = {"type": "integer"}
_B = {"type": "boolean"}


def _instructions():
    return (
        "Evidence layer for your own periodic captures. Disciplines that are not "
        "negotiable: (1) an absent field is NOT zero -- it is absent; (2) run "
        "audit_field_coverage before reading any trend, because a field that stopped "
        "arriving is a capture problem until proven otherwise; (3) never diff across "
        "an identity boundary; (4) a change seen across a capture gap spans the whole "
        "gap, not one interval; (5) duplicate/resolution output is CANDIDATES, not "
        "verdicts -- never merge without checking the field values."
    )


TOOL_SCHEMAS = [
    {
        "name": "list_sources",
        "title": "List imported sources",
        "description": "Registered sources with their date range, entity and field "
                       "counts. Start here.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "audit_field_coverage",
        "title": "Is my collection still healthy?",
        "description": "Per-field presence audit: coverage %, present/absent days, "
                       "first/last seen, blank rows, a machine-readable status "
                       "(ok / partial_drop / absent_on_latest / no_facts_in_latest_capture) and a "
                       "schema_events summary. Run this BEFORE interpreting any trend.",
        "inputSchema": {
            "type": "object",
            "properties": {"source": dict(_S, description="source name; omit to audit every source")},
            "additionalProperties": False,
        },
    },
    {
        "name": "search_records",
        "title": "Filter your own records",
        "description": "Filter and sort one source at a capture date, with pagination. "
                       "Absent fields never satisfy a comparison (missing != zero).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "source": dict(_S),
                "date": dict(_S, description="YYYY-MM-DD; default latest"),
                "q": dict(_S, description="substring filter on entity id"),
                "filters": {"type": "array", "items": {"type": "object"},
                            "description": "[{field, op, value}], AND-combined"},
                "sort": dict(_S),
                "desc": dict(_B),
                "limit": dict(_I),
                "offset": dict(_I),
            },
            "required": ["source"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_source_entity",
        "title": "One entity, one date",
        "description": "All stored fields for one entity at a capture date, each as "
                       "{num, text}. Absent fields are simply not present.",
        "inputSchema": {
            "type": "object",
            "properties": {"source": dict(_S), "entity": dict(_S), "date": dict(_S)},
            "required": ["source", "entity"],
            "additionalProperties": False,
        },
    },
    {
        "name": "query_series",
        "title": "One field over time",
        "description": "Full time series of one field for one entity. Gaps mean the "
                       "field was absent those days (recorded absence, never zero).",
        "inputSchema": {
            "type": "object",
            "properties": {"source": dict(_S), "entity": dict(_S), "field": dict(_S),
                           "since": dict(_S)},
            "required": ["source", "entity", "field"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_source_evidence_chain",
        "title": "Audited chain for one entity",
        "description": "All fields across every capture date, with raw_ref per date and "
                       "an explicit field_disappearances list.",
        "inputSchema": {
            "type": "object",
            "properties": {"source": dict(_S), "entity": dict(_S), "since": dict(_S)},
            "required": ["source", "entity"],
            "additionalProperties": False,
        },
    },
    {
        "name": "diff_snapshots",
        "title": "What changed between two captures",
        "description": "New entities, entities that disappeared, and per-field changes "
                       "(numeric delta, text before/after, field appeared/disappeared). "
                       "Domain-neutral. Respects identity boundaries and reports the "
                       "span, so a 30-day gap is never read as one day.",
        "inputSchema": {
            "type": "object",
            "properties": {"source": dict(_S), "from": dict(_S), "to": dict(_S),
                           "limit": dict(_I)},
            "required": ["source"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_entities",
        "title": "Inventory a source",
        "description": "Paginated entity inventory: first/last seen, CAPTURE-DAYS present "
                       "(not calendar days), fact count.",
        "inputSchema": {
            "type": "object",
            "properties": {"source": dict(_S), "limit": dict(_I), "offset": dict(_I)},
            "required": ["source"],
            "additionalProperties": False,
        },
    },
    {
        "name": "find_duplicate_entities",
        "title": "Merge candidates inside one source",
        "description": "Entity ids that fold to the same comparison key (case/separator "
                       "differences). Reports CANDIDATES with per-pair evidence; never merges.",
        "inputSchema": {
            "type": "object",
            "properties": {"source": dict(_S), "limit": dict(_I)},
            "required": ["source"],
            "additionalProperties": False,
        },
    },
    {
        "name": "resolve_entities",
        "title": "Find one entity across all sources",
        "description": "Look an entity up across every source by normalized id, so the "
                       "same thing captured under different spellings can be found. "
                       "Name-based only: a lead, not a join.",
        "inputSchema": {
            "type": "object",
            "properties": {"q": dict(_S), "limit": dict(_I)},
            "required": ["q"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_source_anomalies",
        "title": "Detected anomalies",
        "description": "Anomalies for a source: credential/timestamp staleness, value "
                       "swings, monotonic regressions, field or entity disappearance, "
                       "text drift, schema changes and capture gaps. Check these BEFORE "
                       "reading any move as a business signal.",
        "inputSchema": {
            "type": "object",
            "properties": {"source": dict(_S), "kind": dict(_S), "severity": dict(_S),
                           "slug": dict(_S), "limit": dict(_I)},
            "additionalProperties": False,
        },
    },
]


def _rows(con, sql, args=()):
    cur = con.execute(sql, args)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def tool_list_sources(con, args):
    return {"sources": G.list_sources(con),
            "note": "anomaly slugs for these sources are '<source>:<entity>'; the "
                    "source-level pseudo entity is '<source>:__schema__'"}


def tool_audit_field_coverage(con, args):
    src = args.get("source")
    if src:
        cov = G.field_coverage(con, src)
        if cov is None:
            return {"error": "no facts for this source", "queried": {"source": src},
                    "known_sources": [s["source"] for s in G.list_sources(con)]}
        return cov
    out = []
    for s in G.list_sources(con):
        cov = G.field_coverage(con, s["source"])
        if cov:
            out.append(cov)
    if not out:
        return {"error": "no sources with facts",
                "hint": "import a CSV/JSON export first; see docs/ADAPTERS.md"}
    return {"sources": out}


def tool_search_records(con, args):
    src = args.get("source")
    if not src:
        return {"error": "source is required",
                "known_sources": [s["source"] for s in G.list_sources(con)]}
    res = G.search_records(con, src, date=args.get("date"), q=args.get("q"),
                           filters=args.get("filters"), sort=args.get("sort"),
                           desc=args.get("desc", True),
                           limit=args.get("limit", 20), offset=args.get("offset", 0))
    if res is None:
        return {"error": "no facts for this source", "queried": {"source": src},
                "known_sources": [s["source"] for s in G.list_sources(con)]}
    if res.get("total_matched") == 0 and "error" not in res:
        res["hint"] = ("zero rows: an absent field never satisfies a comparison "
                       "(missing != zero) -- run audit_field_coverage to see whether "
                       "the field is being captured at all")
    return res


def tool_get_source_entity(con, args):
    src, ent = args.get("source"), args.get("entity")
    if not src or not ent:
        return {"error": "source and entity are required"}
    snap = G.entity_snapshot(con, src, ent, args.get("date"))
    if snap is None:
        return {"error": "entity not found in source",
                "queried": {"source": src, "entity": ent},
                "close_matches": G.suggest_entities(con, src, ent.split()[0] if " " in ent else ent[:4])}
    return snap


def tool_query_series(con, args):
    src, ent, fld = args.get("source"), args.get("entity"), args.get("field")
    if not src or not ent or not fld:
        return {"error": "source, entity and field are required"}
    rows = G.query_series(con, src, ent, fld, args.get("since"))
    if not rows:
        cur = con.execute("SELECT DISTINCT field FROM generic_facts WHERE source=? AND entity=? LIMIT 30",
                          (src, ent))
        return {"error": "no facts for this series",
                "queried": {"source": src, "entity": ent, "field": fld},
                "known_fields": [r[0] for r in cur.fetchall()]}
    anoms = _rows(con, "SELECT observed_date, kind, severity, detail FROM anomalies "
                      "WHERE slug=? AND kind LIKE ? ORDER BY observed_date",
                  (src + ":" + ent, "%:" + fld))
    bounds = [r["observed_date"] for r in _rows(con,
              "SELECT DISTINCT observed_date FROM anomalies WHERE slug=? AND kind LIKE "
              "'identity_change:%' ORDER BY observed_date", (src + ":" + ent,))]
    out = {"source": src, "entity": ent, "field": fld, "points": len(rows),
           "series": rows, "field_anomalies": anoms}
    if bounds:
        out["identity_boundaries"] = bounds
        out["warning"] = ("do NOT diff series values across identity boundary dates: "
                          + ", ".join(bounds))
    return out


def tool_get_source_evidence_chain(con, args):
    src, ent = args.get("source"), args.get("entity")
    if not src or not ent:
        return {"error": "source and entity are required"}
    chain = G.entity_chain(con, src, ent, args.get("since"))
    if chain is None:
        return {"error": "entity not found in source",
                "queried": {"source": src, "entity": ent},
                "close_matches": G.suggest_entities(con, src, ent.split()[0] if " " in ent else ent[:4])}
    anoms = _rows(con, "SELECT observed_date, kind, severity, detail FROM anomalies "
                      "WHERE slug=? ORDER BY observed_date", (src + ":" + ent,))
    chain["anomalies"] = anoms
    bounds = sorted({a["observed_date"] for a in anoms if a["kind"].startswith("identity_change:")})
    if bounds:
        chain["identity_boundaries"] = bounds
        chain["warning"] = ("do NOT diff values across identity boundary dates: "
                            + ", ".join(bounds))
    return chain


def tool_diff_snapshots(con, args):
    src = args.get("source")
    if not src:
        return {"error": "source is required",
                "known_sources": [s["source"] for s in G.list_sources(con)]}
    res = G.diff_snapshots(con, src, from_date=args.get("from"), to_date=args.get("to"),
                           limit=min(max(int(args.get("limit") or 200), 1), 1000))
    if res is None:
        return {"error": "no facts for this source", "queried": {"source": src},
                "known_sources": [s["source"] for s in G.list_sources(con)]}
    res["anomalies_in_range"] = _rows(
        con, "SELECT observed_date, slug, kind, severity, detail FROM anomalies "
             "WHERE substr(slug,1,?)=? AND observed_date BETWEEN ? AND ? "
             "ORDER BY observed_date, kind",
        (len(src + ":"), src + ":", res.get("from") or "", res.get("to") or ""))
    return res


def tool_list_entities(con, args):
    src = args.get("source")
    if not src:
        return {"error": "source is required",
                "known_sources": [s["source"] for s in G.list_sources(con)]}
    res = G.list_entities(con, src, args.get("limit", 100), args.get("offset", 0))
    if res is None:
        return {"error": "no facts for this source", "queried": {"source": src},
                "known_sources": [s["source"] for s in G.list_sources(con)]}
    return res


def tool_find_duplicate_entities(con, args):
    src = args.get("source")
    if not src:
        return {"error": "source is required",
                "known_sources": [s["source"] for s in G.list_sources(con)]}
    res = G.find_duplicate_entities(con, src, args.get("limit", 50))
    if res is None:
        return {"error": "no facts for this source", "queried": {"source": src},
                "known_sources": [s["source"] for s in G.list_sources(con)]}
    return res


def tool_resolve_entities(con, args):
    q = args.get("q")
    if not q:
        return {"error": "q is required"}
    res = G.resolve_entities(con, q, args.get("limit", 20))
    if res is None:
        return {"error": "no generic sources with facts",
                "hint": "import a CSV/JSON export first; see docs/ADAPTERS.md"}
    if res["matches"] == 0:
        res["hint"] = ("no name match across sources; try a shorter fragment, or run "
                       "list_sources to see what is loaded")
    return res


def tool_list_source_anomalies(con, args):
    conds, params = [], []
    if args.get("kind"):
        conds.append("(kind=? OR kind LIKE ?)")
        params.extend([args["kind"], args["kind"] + ":%"])
    if args.get("severity"):
        conds.append("severity=?")
        params.append(args["severity"])
    if args.get("slug"):
        conds.append("slug=?")
        params.append(args["slug"])
    if args.get("source"):
        conds.append("substr(slug,1,?)=?")
        params.extend([len(args["source"] + ":"), args["source"] + ":"])
    where = (" WHERE " + " AND ".join(conds)) if conds else ""
    limit = min(max(int(args.get("limit") or 100), 1), 1000)
    total = _rows(con, "SELECT COUNT(*) AS n FROM anomalies" + where, tuple(params))[0]["n"]
    rows = _rows(con, "SELECT observed_date, slug, kind, severity, detail FROM anomalies"
                      + where + " ORDER BY observed_date DESC, kind LIMIT ?",
                  tuple(params) + (limit,))
    # count must be the TOTAL that matched, not the page size: this tool exists so
    # an agent checks anomalies before reading a trend, and a truncated list that
    # calls itself "count" makes it believe there is nothing else to see.
    return {"count": total, "returned": len(rows), "limit": limit,
            "has_more": total > len(rows), "truncated": total > len(rows),
            "anomalies": rows}


TOOL_FUNCS = {
    "list_sources": tool_list_sources,
    "audit_field_coverage": tool_audit_field_coverage,
    "search_records": tool_search_records,
    "get_source_entity": tool_get_source_entity,
    "query_series": tool_query_series,
    "get_source_evidence_chain": tool_get_source_evidence_chain,
    "diff_snapshots": tool_diff_snapshots,
    "list_entities": tool_list_entities,
    "find_duplicate_entities": tool_find_duplicate_entities,
    "resolve_entities": tool_resolve_entities,
    "list_source_anomalies": tool_list_source_anomalies,
}


# ---------------------------------------------------------------- protocol

def _reconfigure_stdio():
    for s in (sys.stdin, sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _send(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n")
    sys.stdout.flush()


def _finite(value):
    """Replace non-finite floats so the payload is always valid JSON.

    Parsing refuses inf/NaN now, but a database written by an older version can
    still hold them, and one Infinity would make the client fail to parse the
    entire response.
    """
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return None
        return value
    if isinstance(value, dict):
        return {k: _finite(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finite(v) for v in value]
    return value


def _call_tool(con, params):
    name = params.get("name")
    args = params.get("arguments") or {}
    fn = TOOL_FUNCS.get(name)
    if fn is None:
        return {"content": [{"type": "text", "text": "Unknown tool: %s" % name}], "isError": True}
    try:
        payload = fn(con, args)
        text = payload if isinstance(payload, str) else json.dumps(
            _finite(payload), ensure_ascii=False, indent=1, default=str)
        # A payload that carries "error" is a failed call, not a success with a
        # message: hosts branch on isError, and returning false there let an agent
        # treat "source is required" as data.
        is_err = isinstance(payload, dict) and "error" in payload
        return {"content": [{"type": "text", "text": text}], "isError": bool(is_err)}
    except Exception as e:
        return {"content": [{"type": "text", "text": "Tool error: %s: %s" % (type(e).__name__, e)}],
                "isError": True}


def _handle(con, msg):
    if not isinstance(msg, dict):
        return None
    method = msg.get("method")
    if "id" not in msg:
        return None  # notification: never answer
    mid = msg.get("id")
    params = msg.get("params") or {}
    try:
        if method == "initialize":
            proto = params.get("protocolVersion")
            result = {
                "protocolVersion": proto if proto in PROTOCOL_VERSIONS else DEFAULT_PROTOCOL,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "indiebiz-evidence", "version": __version__,
                               "title": "Auditable evidence layer for your own captures"},
                "instructions": _instructions(),
            }
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": TOOL_SCHEMAS}
        elif method == "tools/call":
            result = _call_tool(con, params)
        elif method == "resources/list":
            result = {"resources": []}
        elif method == "prompts/list":
            result = {"prompts": []}
        else:
            return {"jsonrpc": "2.0", "id": mid,
                    "error": {"code": -32601, "message": "Method not found: %s" % method}}
        return {"jsonrpc": "2.0", "id": mid, "result": result}
    except Exception as e:
        return {"jsonrpc": "2.0", "id": mid,
                "error": {"code": -32603,
                          "message": "Internal error: %s: %s" % (type(e).__name__, e)}}


def serve(db_path: str):
    if not os.path.exists(db_path):
        sys.stderr.write("evidence db not found: %s (import a source first)\n" % db_path)
        sys.exit(2)
    _reconfigure_stdio()
    con = store.connect(db_path)
    store.init_db(con)
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            _send({"jsonrpc": "2.0", "id": None,
                   "error": {"code": -32700, "message": "Parse error"}})
            continue
        if isinstance(msg, list):
            resps = [r for r in (_handle(con, m) for m in msg) if r is not None]
            if resps:
                _send(resps)
        else:
            r = _handle(con, msg)
            if r is not None:
                _send(r)
    con.close()


def selftest(db_path: str):
    """Human-runnable smoke: call every tool once and print what came back."""
    # serve() reconfigures stdio but selftest did not: on a GBK console an entity
    # with a non-GBK character raised UnicodeEncodeError (Codex 2026-11-11). CI's
    # global PYTHONIOENCODING=utf-8 masked it.
    _reconfigure_stdio()
    if not os.path.exists(db_path):
        print("evidence db not found: %s" % db_path)
        return 1
    con = store.connect(db_path)
    sources = [s["source"] for s in G.list_sources(con)]
    if not sources:
        print("no sources in this db -- import one first (docs/ADAPTERS.md)")
        con.close()
        return 1
    src = sources[0]
    ent = None
    le = G.list_entities(con, src, limit=1)
    if le and le.get("entities"):
        ent = le["entities"][0]["entity"]
    fld = None
    if ent:
        cur = con.execute("SELECT field FROM generic_facts WHERE source=? AND entity=? LIMIT 1",
                          (src, ent))
        r = cur.fetchone()
        fld = r[0] if r else None
    samples = [
        ("list_sources", {}),
        ("audit_field_coverage", {"source": src}),
        ("search_records", {"source": src, "limit": 3}),
        ("list_entities", {"source": src, "limit": 3}),
        ("find_duplicate_entities", {"source": src}),
        ("diff_snapshots", {"source": src}),
        ("list_source_anomalies", {"source": src, "limit": 5}),
    ]
    if ent:
        samples += [("get_source_entity", {"source": src, "entity": ent}),
                    ("get_source_evidence_chain", {"source": src, "entity": ent})]
    if ent and fld:
        samples.append(("query_series", {"source": src, "entity": ent, "field": fld}))
    samples.append(("resolve_entities", {"q": ent or src}))
    ok = True
    n_ok = n_errpath = n_err = 0
    for name, args in samples:
        res = _call_tool(con, {"name": name, "arguments": args})
        text = res["content"][0]["text"]
        is_err_path = (not res.get("isError")) and text.lstrip().startswith("{") and '"error"' in text[:200]
        if res.get("isError"):
            status, n_err = "ERR", n_err + 1
            ok = False
        elif is_err_path:
            status, n_errpath = "ok(error-path)", n_errpath + 1
        else:
            status, n_ok = "ok", n_ok + 1
        print("%-13s %-28s -> %d chars | %s"
              % (status, name, len(text), text[:140].replace("\n", " ")))
    res = _call_tool(con, {"name": "no_such_tool", "arguments": {}})
    print("%-13s %-28s -> isError=%s" % ("ok" if res.get("isError") else "ERR",
                                         "unknown-tool handling", res.get("isError")))
    rows = _rows(con, "SELECT observed_date, slug, kind, severity, detail FROM anomalies "
                      "ORDER BY CASE severity WHEN 'high' THEN 0 WHEN 'contradiction' THEN 1 "
                      "WHEN 'warn' THEN 2 ELSE 3 END, observed_date DESC, slug LIMIT 60")
    print("")
    print("anomalies stored in this database (%d shown):" % len(rows))
    if not rows:
        print("  (none)")
    for r in rows:
        print("  %s  %-28s %-24s %s" % (r["observed_date"], r["slug"], r["kind"], r["severity"]))
        if r["detail"]:
            print("      %s" % r["detail"])
    print("")
    print("summary: ok=%d error-path=%d err=%d" % (n_ok, n_errpath, n_err))
    con.close()
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="stdio MCP server over the evidence store")
    ap.add_argument("--db", default="data/evidence.db")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest(a.db)
    serve(a.db)
    return 0


if __name__ == "__main__":
    sys.exit(main())
