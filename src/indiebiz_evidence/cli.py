"""Installed command-line entry point: `indiebiz-evidence <command>`.

After `pip install .` these work from any directory, with no repository
checkout and no PYTHONPATH tricks:

  indiebiz-evidence demo   --db demo.db          # synthetic data, try everything
  indiebiz-evidence import --source s --input exports/ --db my.db
  indiebiz-evidence audit  --db my.db --source s
  indiebiz-evidence mcp    --db my.db            # stdio MCP server

All paths are relative to the current working directory.
"""
from __future__ import annotations

import argparse
import os
import sys

from . import __version__, demo, generic, reporting, store


def _cmd_demo(a):
    reporting.utf8_stdio()
    counts = demo.build(a.db, verbose=a.verbose)
    print("demo db built: %s" % os.path.abspath(a.db))
    for source, kinds in sorted(counts.items()):
        detail = ", ".join("%s=%d" % (k, v) for k, v in sorted(kinds.items())) or "no anomalies"
        print("  %-14s %s" % (source, detail))
    print('try: indiebiz-evidence audit --db "%s" --source demo-prices' % a.db)
    return 0


def _cmd_import(a):
    reporting.utf8_stdio()
    db = os.path.abspath(a.db)
    con = store.connect(db)
    store.init_db(con)
    try:
        stats = generic.import_path(con, a.source, os.path.abspath(a.input),
                                    entity_column=a.entity_column,
                                    allow_empty_replace=a.allow_empty_replace)
    except FileNotFoundError:
        print("[import] FATAL: input path does not exist: %s" % os.path.abspath(a.input))
        con.close()
        return 3
    if stats["files"] == 0:
        print("[import] FATAL: no CSV/JSON/JSONL files found under %s" % a.input)
        con.close()
        return 3
    if stats.get("errors"):
        print("[import] FATAL: errors=%d -- nothing usable was imported; check warnings "
              "above (a typo'd entity/date column must fail loudly, not silently)"
              % stats["errors"])
        con.close()
        return 3
    # facts==0 is NOT itself a failure: it can be a valid empty capture or a refused
    # empty replace. Always run detection so anomalies stay consistent with the facts
    # (Codex: 'report failure but already committed the deletion' is unacceptable).
    counts = generic.detect_generic(con, a.source)
    if stats["facts"] == 0:
        print("[import] 0 usable facts imported (empty capture, or an empty replace was refused)")
    if stats.get("refused_empty_replace"):
        print("[import] %d empty replace(s) REFUSED -- existing facts kept; "
              "pass --allow-empty-replace to override" % stats["refused_empty_replace"])
    print("[import] anomalies for %s: %s" % (a.source, counts or "none"))
    print("[import] query via MCP: list_sources / get_source_entity / query_series "
          "(anomaly slug namespace '%s:<entity>')" % a.source)
    con.close()
    return 0


def _cmd_audit(a):
    return reporting.main(["--db", a.db] + (["--source", a.source] if a.source else []))


def _cmd_crosscheck(a):
    reporting.utf8_stdio()
    db = os.path.abspath(a.db)
    if not os.path.exists(db):
        print("evidence db not found: %s" % db)
        return 1
    con = store.connect(db)
    res = generic.cross_check(con, a.entity, field=a.field, date=a.date)
    con.close()
    if res is None:
        print("entity is empty after normalization")
        return 1
    if not res["sources_compared"]:
        print("no source reports an entity matching %r" % a.entity)
        return 1
    print("== 跨源核对 %s ==" % a.entity)
    print("对比来源：%s" % ", ".join(res["sources_compared"]))
    print()
    label = {"agrees": "一致", "differs": "打架", "single_source": "孤证",
             "numbers_match": "数值同·口径未确认"}
    for fld, e in res["fields"].items():
        print("  %-16s [%s] %d 个来源报告" % (fld, label.get(e["verdict"], e["verdict"]), e["reported_by"]))
        for v in e["values"]:
            for o in v["observations"]:
                shown = o["text"] if o["text"] is not None else o["num"]
                print("      = %-14s 来自 %s @ %s" % (shown, o["source"], o["date"]))
                print("          出处 %s" % o["raw_ref"])
        if e.get("not_reporting"):
            print("      未报告：%s（缺席≠0）" % ", ".join(e["not_reporting"]))
        if e.get("note"):
            print("      -> %s" % e["note"])
    print()
    for cv in res["caveats"]:
        print("  注意：%s" % cv)
    return 0


def _cmd_mcp(a):
    from . import mcp_server
    if a.selftest:
        return mcp_server.selftest(a.db)
    mcp_server.serve(a.db)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="indiebiz-evidence",
                                 description="auditable evidence layer for your own periodic captures")
    ap.add_argument("--version", action="version", version="indiebiz-evidence " + __version__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("demo", help="build a synthetic demo database (no data of your own needed)")
    p.add_argument("--db", default="demo.db")
    p.add_argument("--verbose", action="store_true")
    p.set_defaults(fn=_cmd_demo)

    p = sub.add_parser("import", help="import dated CSV/JSON exports as a source")
    p.add_argument("--source", required=True)
    p.add_argument("--input", required=True, help="directory or file of dated exports (relative to CWD)")
    p.add_argument("--entity-column", default=None)
    p.add_argument("--db", default="data/evidence.db")
    p.add_argument("--allow-empty-replace", action="store_true",
                   help="permit a zero-fact export to delete a date's existing facts "
                        "(default: refuse, because an empty file is usually a broken scraper)")
    p.set_defaults(fn=_cmd_import)

    p = sub.add_parser("audit", help="one-shot health report: is my collection still healthy?")
    p.add_argument("--db", default="data/evidence.db")
    p.add_argument("--source", default=None)
    p.set_defaults(fn=_cmd_audit)

    p = sub.add_parser("crosscheck", help="verify one claim across every source that reports it")
    p.add_argument("--db", default="data/evidence.db")
    p.add_argument("--entity", required=True)
    p.add_argument("--field", default=None)
    p.add_argument("--date", default=None)
    p.set_defaults(fn=_cmd_crosscheck)

    p = sub.add_parser("mcp", help="run the stdio MCP server (or --selftest)")
    p.add_argument("--db", default="data/evidence.db")
    p.add_argument("--selftest", action="store_true")
    p.set_defaults(fn=_cmd_mcp)

    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())