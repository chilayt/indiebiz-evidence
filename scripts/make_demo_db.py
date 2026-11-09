#!/usr/bin/env python3
"""CLI: build the synthetic demo DB (cold start / CI).

Contains only invented entities in year 2099. No upstream data.
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

from indiebiz_evidence import demo  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=os.path.join(PROJECT_ROOT, "data", "demo.db"))
    args = ap.parse_args()
    counts = demo.build(args.db)
    print("demo db built: %s" % os.path.abspath(args.db))
    for source, kinds in sorted(counts.items()):
        detail = ", ".join("%s=%d" % (k, v) for k, v in sorted(kinds.items())) or "no anomalies"
        print("  %-14s %s" % (source, detail))
    print('try: python scripts/mcp_server.py --db "%s" --selftest' % args.db)


if __name__ == "__main__":
    main()
