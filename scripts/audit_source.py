#!/usr/bin/env python3
"""CLI: one-shot health report for a bring-your-own-data source.

This is the command the quickstart tells you to run, and the one to run first
after every import: it answers "is my collection still healthy?" before you read
any trend. Thin human-readable wrapper over generic.field_coverage + the anomaly
table -- the same data the MCP tools return, printed for a terminal.

  python scripts/audit_source.py --db data/my.db --source competitors
  python scripts/audit_source.py --db data/my.db            # every source
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

from indiebiz_evidence import generic, store  # noqa: E402

STATUS_LABEL = {"ok": "ok", "partial_drop": "PARTIAL-DROP", "absent_on_latest": "ABSENT-NOW"}


def _resolve(p):
    return p if os.path.isabs(p) else os.path.normpath(os.path.join(PROJECT_ROOT, p))


def report(con, source):
    cov = generic.field_coverage(con, source)
    if cov is None:
        print("[%s] no facts -- import a source first (docs/ADAPTERS.md)" % source)
        return 1
    cad = cov.get("cadence") or {}
    print("== 数据源 %s ==" % source)
    med = cad.get("median_gap_days")
    if med is not None:
        rhythm = "参照间隔 %s 天" % med
    elif cov["dates"] <= 1:
        rhythm = "仅一次抓取，无法判断节奏"
    else:
        rhythm = "抓取次数太少，节奏未知（不臆测）"
    print("抓取日 %d 天 | 实体 %d 个 | 字段 %d 个 | %s"
          % (cov["dates"], cov["entities_latest"], len(cov["fields"]), rhythm))
    print()
    print("字段覆盖")
    print("  %-16s %8s %8s %10s  %s" % ("字段", "覆盖", "出现", "最新实体", "状态"))
    for f in cov["fields"]:
        label = STATUS_LABEL.get(f["status"], f["status"])
        print("  %-16s %7.1f%% %8s %10s  %s"
              % (f["field"], f["coverage_pct"],
                 "%d/%d" % (f["present_days"], f["total_days"]),
                 "%d/%d" % (f["entities_present_latest"], f["entities_live"]), label))
        if f["status"] != "ok":
            print("       -> %s" % f["verdict"])
        if f.get("exited_entities_note"):
            print("       -> %s" % f["exited_entities_note"])

    schema = cov.get("schema_events") or {}
    added = schema.get("fields_added_after_first_capture") or []
    missing = schema.get("fields_missing_on_latest") or []
    if added or missing:
        print()
        print("源结构变化（列可能被删除/改名/变空，需查原始文件确认）")
        for a in added:
            print("  + %-16s 首次出现 %s" % (a["field"], a["first_seen"]))
        for m in missing:
            print("  - %-16s 最后出现 %s" % (m["field"], m["last_seen"]))

    unknown = cad.get("cadence_unknown_for") or []
    if unknown:
        print()
        print("节奏未知（此前无抓取可参照，既不判为断档也不判为正常）")
        for d in unknown:
            print("  %s" % d)
    gaps = cad.get("gaps_over_threshold") or []
    if gaps:
        print()
        print("抓取断档")
        for gp in gaps:
            print("  %s 之前断了 %d 天" % (gp["date"], gp["gap_days"]))

    _ns = source + ":"
    cur = con.execute(
        "SELECT observed_date, slug, kind, severity, detail FROM anomalies "
        "WHERE substr(slug,1,?)=? ORDER BY observed_date, kind", (len(_ns), _ns))
    rows = cur.fetchall()
    print()
    print("异常（%d）" % len(rows))
    if not rows:
        print("  （无）")
    for d, slug, kind, sev, detail in rows:
        print("  %s  %-30s %-22s %s" % (d, slug, kind, sev or ""))
        if detail:
            print("      %s" % detail)
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="data/evidence.db")
    ap.add_argument("--source", help="generic source name; omit to audit every source")
    a = ap.parse_args()
    db = _resolve(a.db)
    if not os.path.exists(db):
        print("evidence db not found: %s" % db)
        return 1
    con = store.connect(db)
    if a.source:
        rc = report(con, a.source)
    else:
        srcs = [s["source"] for s in generic.list_sources(con)]
        if not srcs:
            print("no generic sources in this db -- import one first (docs/ADAPTERS.md)")
            rc = 1
        else:
            rc = 0
            for i, s in enumerate(srcs):
                if i:
                    print()
                rc = max(rc, report(con, s))
    con.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())
