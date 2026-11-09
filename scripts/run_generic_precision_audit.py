#!/usr/bin/env python3
"""Precision audit for the GENERIC detection rules (discipline 9).

The generic rules added in
v0.3.6-v0.4.0 had only unit tests, which prove "the case that should fire does
fire" but say nothing about how often they fire when they should not. This script
closes that gap with a fixed, labelled synthetic corpus: every scenario declares
which kinds MUST appear and which MUST NOT, and the runner scores each rule.

  python scripts/run_generic_precision_audit.py
  python scripts/run_generic_precision_audit.py --json

Exit code is 0 only when every rule meets its registered threshold AND no
forbidden kind fired. A scenario that cannot be scored reports "incomplete" and
fails -- missing labels never count as a pass.

Honest limitation: a synthetic corpus gives exact rates on cases we thought of.
It cannot substitute for sampling a real collection. Real-corpus sampling stays
an open item in the release checklist.
"""
import argparse
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

from indiebiz_evidence import generic, store  # noqa: E402


def _write_scenario(tmp, name, spec):
    d = os.path.join(tmp, name)
    os.makedirs(d, exist_ok=True)
    for date, body in spec["files"].items():
        with open(os.path.join(d, date + "-x.csv"), "w", encoding="utf-8", newline="\n") as f:
            f.write(body.strip() + "\n")
    if spec.get("config"):
        with open(os.path.join(d, "source.json"), "w", encoding="utf-8") as f:
            json.dump(spec["config"], f)
    return d


def _run_scenario(tmp, name, spec):
    src = _write_scenario(tmp, name, spec)
    db = os.path.join(tmp, name + ".db")
    con = store.connect(db)
    store.init_db(con)
    generic.import_path(con, name, src, verbose=False)
    generic.detect_generic(con, name, verbose=False)
    kinds = [r[0] for r in con.execute("SELECT kind FROM anomalies")]
    con.close()
    return kinds


def _base(kind):
    return kind.split(":", 1)[0]


# ---------------------------------------------------------------- scenarios
# Each scenario: files (date -> csv), optional config, expect/forbid kind bases.
SCENARIOS = [
    {
        "name": "steady",
        "why": "nothing changes: any anomaly here is a false positive",
        "files": {
            "2026-01-01": "id,price,views\na,10,100\nb,20,200",
            "2026-01-02": "id,price,views\na,10,100\nb,20,200",
            "2026-01-03": "id,price,views\na,10,100\nb,20,200",
        },
        "expect": [],
        "forbid": ["value_swing", "entity_disappeared", "field_disappeared",
                   "field_gone", "field_appeared", "gapped_transition",
                   "text_changed", "monotonic_regression", "identity_change"],
    },
    {
        "name": "rotating-list",
        "why": "a daily top-N list rotates members; churn is normal, not delisting",
        "files": {
            "2026-01-01": "id,rank\na,1\nb,2",
            "2026-01-02": "id,rank\nc,1\nd,2",
            "2026-01-03": "id,rank\ne,1\nf,2",
        },
        "config": {"entity_column": "id", "min_presence_days": 3},
        "expect": [],
        "forbid": ["entity_disappeared"],
    },
    {
        "name": "column-gone",
        "why": "a whole column stops arriving for every entity",
        "files": {
            "2026-01-01": "id,price,stock\na,10,in\nb,20,in",
            "2026-01-02": "id,price,stock\na,10,in\nb,20,in",
            "2026-01-03": "id,price\na,10\nb,20",
        },
        "expect": ["field_gone"],
        "forbid": ["entity_disappeared", "gapped_transition"],
    },
    {
        "name": "column-added",
        "why": "the export gained a column",
        "files": {
            "2026-01-01": "id,price\na,10\nb,20",
            "2026-01-02": "id,price\na,10\nb,20",
            "2026-01-03": "id,price,currency\na,10,USD\nb,20,USD",
        },
        "expect": ["field_appeared"],
        "forbid": ["field_gone", "entity_disappeared"],
    },
    {
        "name": "column-renamed",
        "why": "price renamed to cost with the values moving slightly",
        "files": {
            "2026-01-01": "id,price,views\na,10,100\nb,20,200",
            "2026-01-02": "id,price,views\na,10,100\nb,20,200",
            "2026-01-03": "id,cost,views\na,11,100\nb,21,200",
        },
        # a rename necessarily shows up as one column gone and another added:
        # all three kinds are expected, and the candidate is the interpretation
        "expect": ["field_renamed_candidate", "field_gone", "field_appeared"],
        "forbid": ["entity_disappeared", "value_swing"],
    },
    {
        "name": "intermittent-field",
        "why": "an entity-specific column must not look like a schema change",
        "files": {
            "2026-01-01": "id,price,listing_url\na,10,http://a\nb,20,",
            "2026-01-02": "id,price,listing_url\na,10,http://a\nb,20,",
            "2026-01-03": "id,price,listing_url\na,10,http://a\nb,20,",
        },
        "config": {"entity_column": "id", "null_markers": ["", "-"]},
        "expect": [],
        "forbid": ["field_gone", "field_renamed_candidate"],
    },
    {
        "name": "text-drift",
        "why": "a declared text field changed",
        "files": {
            "2026-01-01": "id,status,price\na,open,10",
            "2026-01-02": "id,status,price\na,closed,10",
        },
        "config": {"entity_column": "id", "track_text_fields": ["status"]},
        "expect": ["text_changed"],
        "forbid": ["value_swing"],
    },
    {
        "name": "text-undeclared",
        "why": "an undeclared text field must stay silent (noise control)",
        "files": {
            "2026-01-01": "id,status,price\na,open,10",
            "2026-01-02": "id,status,price\na,closed,10",
        },
        "config": {"entity_column": "id"},
        "expect": [],
        "forbid": ["text_changed"],
    },
    {
        "name": "numeric-swing",
        "why": "a 10x jump is a real numeric signal",
        "files": {
            "2026-01-01": "id,price\na,10\nb,20",
            "2026-01-02": "id,price\na,100\nb,20",
        },
        "expect": ["value_swing"],
        "forbid": ["entity_disappeared"],
    },
    {
        "name": "monotonic-regression",
        "why": "a declared cumulative field went down",
        "files": {
            "2026-01-01": "id,installs\na,100",
            "2026-01-02": "id,installs\na,90",
        },
        "config": {"entity_column": "id", "monotonic_fields": ["installs"]},
        "expect": ["monotonic_regression"],
        "forbid": [],
    },
    {
        "name": "identity-boundary",
        "why": "owner changed: identity_change fires and the price swing must be suppressed",
        "files": {
            "2026-01-01": "id,owner,price\na,ALPHA,10",
            "2026-01-02": "id,owner,price\na,ZULU,900",
        },
        "config": {"entity_column": "id", "identity_fields": ["owner"]},
        "expect": ["identity_change"],
        "forbid": ["value_swing"],
    },
    {
        "name": "capture-gap",
        "why": "a 30-day stall after a steady daily rhythm",
        "files": {
            "2026-01-01": "id,price\na,10",
            "2026-01-02": "id,price\na,10",
            "2026-01-03": "id,price\na,10",
            "2026-02-02": "id,price\na,10",
        },
        "expect": ["gapped_transition"],
        "forbid": ["entity_disappeared"],
    },
    {
        "name": "entity-disappeared",
        "why": "a listing that was present for several captures is gone",
        "files": {
            "2026-01-01": "id,price\na,10\nb,20",
            "2026-01-02": "id,price\na,10\nb,20",
            "2026-01-03": "id,price\na,10\nb,20",
            "2026-01-04": "id,price\na,10",
        },
        "config": {"entity_column": "id", "min_presence_days": 2},
        "expect": ["entity_disappeared"],
        "forbid": ["field_gone"],
    },
]


def audit():
    tmp = tempfile.mkdtemp(prefix="ibe-gpa-")
    rows = []
    incomplete = []
    try:
        for spec in SCENARIOS:
            try:
                kinds = _run_scenario(tmp, spec["name"], spec)
            except Exception as e:
                incomplete.append({"scenario": spec["name"], "error": str(e)[:200]})
                continue
            fired = {_base(k) for k in kinds}
            if not spec["expect"] and not spec["forbid"]:
                incomplete.append({"scenario": spec["name"],
                                   "error": "no labels: a scenario that asserts nothing "
                                            "cannot pass"})
                continue
            # Any kind that fired but was not registered for this scenario is a
            # finding: it means the matrix has a blind spot, and a blind spot is
            # how a gate goes green while the code is wrong.
            declared = set(spec["expect"]) | set(spec["forbid"])
            unexpected = sorted(fired - declared)
            if unexpected:
                for kind in unexpected:
                    rows.append({"scenario": spec["name"], "rule": kind,
                                 "verdict": "FP",
                                 "why": "fired but not declared in this scenario"})
            for want in spec["expect"]:
                rows.append({"scenario": spec["name"], "rule": want,
                             "verdict": "TP" if want in fired else "FN",
                             "why": spec.get("why", "")})
            for never in spec["forbid"]:
                rows.append({"scenario": spec["name"], "rule": never,
                             "verdict": "FP" if never in fired else "TN",
                             "why": spec.get("why", "")})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    rules = sorted({r["rule"] for r in rows})
    summary = []
    failed = False
    for rule in rules:
        rs = [r for r in rows if r["rule"] == rule]
        tp = sum(1 for r in rs if r["verdict"] == "TP")
        fp = sum(1 for r in rs if r["verdict"] == "FP")
        fn = sum(1 for r in rs if r["verdict"] == "FN")
        tn = sum(1 for r in rs if r["verdict"] == "TN")
        prec = (tp / (tp + fp)) if (tp + fp) else None
        rec = (tp / (tp + fn)) if (tp + fn) else None
        fpr = (fp / (fp + tn)) if (fp + tn) else None
        # registered thresholds: a rule that must fire and does not is fatal;
        # a rule that fires when forbidden is fatal; otherwise report the rate.
        if fn:
            failed = True
        if fp:
            failed = True
        summary.append({"rule": rule, "TP": tp, "FP": fp, "FN": fn, "TN": tn,
                        "precision": prec, "recall": rec, "false_positive_rate": fpr})
    if incomplete:
        failed = True
    return {"scenarios": len(SCENARIOS), "incomplete": incomplete,
            "summary": summary, "failed": failed}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    res = audit()
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
    else:
        print("generic precision audit  (%d scenarios)" % res["scenarios"])
        print("%-28s %4s %4s %4s %4s %10s %8s %10s"
              % ("rule", "TP", "FP", "FN", "TN", "precision", "recall", "FP-rate"))
        for s in res["summary"]:
            fmt = lambda v: "-" if v is None else ("%.2f" % v)
            print("%-28s %4d %4d %4d %4d %10s %8s %10s"
                  % (s["rule"], s["TP"], s["FP"], s["FN"], s["TN"],
                     fmt(s["precision"]), fmt(s["recall"]), fmt(s["false_positive_rate"])))
        for inc in res["incomplete"]:
            print("INCOMPLETE %s: %s" % (inc["scenario"], inc["error"]))
    if res["failed"]:
        print("GENERIC PRECISION AUDIT FAILED")
        return 1
    print("GENERIC PRECISION AUDIT OK: %d scenarios, no false positive, no missed case"
          % res["scenarios"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
