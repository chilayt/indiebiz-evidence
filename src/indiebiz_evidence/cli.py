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
                                    entity_column=a.entity_column)
    except FileNotFoundError:
        print("[import] FATAL: input path does not exist: %s" % os.path.abspath(a.input))
        con.close()
        return 3
    if stats["files"] == 0:
        print("[import] FATAL: no CSV/JSON/JSONL files found under %s" % a.input)
        con.close()
        return 3
    if stats.get("errors") or stats["facts"] == 0:
        print("[import] FATAL: errors=%d facts=%d -- nothing usable was imported; "
              "check warnings above (a typo'd entity/date column must fail loudly, not silently)"
              % (stats.get("errors", 0), stats["facts"]))
        con.close()
        return 3
    counts = generic.detect_generic(con, a.source)
    print("[import] anomalies for %s: %s" % (a.source, counts or "none"))
    print("[import] query via MCP: list_sources / get_source_entity / query_series "
          "(anomaly slug namespace '%s:<entity>')" % a.source)
    con.close()
    return 0


def _cmd_audit(a):
    return reporting.main(["--db", a.db] + (["--source", a.source] if a.source else []))


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
    p.set_defaults(fn=_cmd_import)

    p = sub.add_parser("audit", help="one-shot health report: is my collection still healthy?")
    p.add_argument("--db", default="data/evidence.db")
    p.add_argument("--source", default=None)
    p.set_defaults(fn=_cmd_audit)

    p = sub.add_parser("mcp", help="run the stdio MCP server (or --selftest)")
    p.add_argument("--db", default="data/evidence.db")
    p.add_argument("--selftest", action="store_true")
    p.set_defaults(fn=_cmd_mcp)

    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())