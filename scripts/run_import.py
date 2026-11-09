#!/usr/bin/env python3
"""CLI: import a generic (bring-your-own-data) snapshot source.

Point --input at a directory of dated CSV/JSON exports (date from filename
YYYY-MM-DD/YYYYMMDD, or an observed_date/date column), optionally with a
source.json declaring field roles. Import is idempotent; detection for that
source re-runs automatically afterwards.

Examples:
  python scripts/run_import.py --source my-prices  --input exports/prices
  python scripts/run_import.py --source gh-stars   --input exports/stars --entity-column repo
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

from indiebiz_evidence import generic, store  # noqa: E402


def _resolve(p: str) -> str:
    return p if os.path.isabs(p) else os.path.normpath(os.path.join(PROJECT_ROOT, p))


def _utf8_stdio():
    """A GBK console must not crash a tool that prints Chinese."""
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def main():
    _utf8_stdio()
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", required=True, help="source name (namespace for entities/anomalies)")
    ap.add_argument("--input", required=True, help="directory (or single file) of dated CSV/JSON snapshots")
    ap.add_argument("--entity-column", default=None, help="override entity column auto-detection")
    ap.add_argument("--config", default=os.path.join(PROJECT_ROOT, "config.local.json"),
                    help="project config for db path (not the source.json; that lives in --input)")
    ap.add_argument("--db", default=None)
    args = ap.parse_args()

    db = args.db
    if not db and os.path.exists(args.config):
        try:
            with open(args.config, encoding="utf-8") as f:
                db = json.load(f).get("db")
        except Exception:
            db = None
    db = _resolve(db or os.path.join("data", "evidence.db"))

    con = store.connect(db)
    store.init_db(con)
    stats = generic.import_path(con, args.source, _resolve(args.input),
                                entity_column=args.entity_column)
    if stats["files"] == 0:
        print("[import] FATAL: no CSV/JSON/JSONL files found under %s" % args.input)
        con.close()
        sys.exit(3)
    if stats.get("errors") or stats["facts"] == 0:
        print("[import] FATAL: errors=%d facts=%d -- nothing usable was imported; "
              "check warnings above (a typo'd entity/date column must fail loudly, not silently)"
              % (stats.get("errors", 0), stats["facts"]))
        con.close()
        sys.exit(3)
    counts = generic.detect_generic(con, args.source)
    print("[import] anomalies for %s: %s" % (args.source, counts or "none"))
    print("[import] query via MCP: list_sources / get_source_entity / query_series "
          "(anomaly slug namespace '%s:<entity>')" % args.source)
    con.close()


if __name__ == "__main__":
    main()
