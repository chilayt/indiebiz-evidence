#!/usr/bin/env python3
"""CLI: run the stdio MCP server over the evidence store.

  python scripts/mcp_server.py --db data/my.db
  python scripts/mcp_server.py --db data/my.db --selftest
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

from indiebiz_evidence import mcp_server  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="data/evidence.db")
    ap.add_argument("--selftest", action="store_true",
                    help="call every tool once and print the results")
    a = ap.parse_args()
    if a.selftest:
        return mcp_server.selftest(a.db)
    mcp_server.serve(a.db)
    return 0


if __name__ == "__main__":
    sys.exit(main())
