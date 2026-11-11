"""Human-readable health report for a source -- the same data the MCP tools
return, printed for a terminal. Lives in the package so it works after
`pip install`, not only from a checkout.

Paths are resolved relative to the CURRENT WORKING DIRECTORY, like any normal
CLI. (The old scripts resolved them against the repository root, which broke
the moment you ran them from anywhere else.)
"""
from __future__ import annotations

import argparse
import os
import sys

from . import generic, store

STATUS_LABEL = {"ok": "ok", "partial_drop": "PARTIAL-DROP", "absent_on_latest": "ABSENT-NOW"}


def utf8_stdio():
    """A GBK console must not crash a tool that prints Chinese."""
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


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
    # An empty latest capture must be stated, not hidden behind "no anomalies"
    # (Codex 2026-11-11): "无异常" is not the same as "采集健康".
    if cov.get("latest_capture_empty"):
        print()
        print("⚠ 最新抓取 %s 没有导入任何可用事实（空批次）。" % cov.get("latest"))
        print("  下方覆盖率以 %s 为参照计算；空批次可能是抓取器故障，先查原始文件再下结论。"
              % cov.get("coverage_anchor_date"))
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


def main(argv=None):
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="indiebiz-evidence audit",
                                 description="one-shot health report for a source")
    ap.add_argument("--db", default="data/evidence.db")
    ap.add_argument("--source", help="generic source name; omit to audit every source")
    a = ap.parse_args(argv)
    db = os.path.abspath(a.db)
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