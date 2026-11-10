#!/usr/bin/env python3
"""Run every gate that must pass before a commit is pushed.

The individual scripts each exit non-zero, but running them one after another by
hand let a failing doc check be committed and pushed anyway (it happened twice in
one session). One entry point that stops at the first failure removes that gap.
"""
from __future__ import annotations

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable

CHECKS = [
    ("data guard (no real data or credentials)", ["scripts/check_no_real_data.py"]),
    ("dependency contract (zero runtime deps)", ["scripts/check_no_runtime_deps.py"]),
    ("tests (skips are failures)", ["scripts/run_tests.py"]),
    ("precision matrix (labelled scenarios)", ["scripts/run_generic_precision_audit.py"]),
    ("docs are true", ["scripts/check_docs_are_true.py"]),
]


def main(argv=None):
    failed = []
    for label, cmd in CHECKS:
        print("== %s ==" % label)
        p = subprocess.run([PY] + cmd, cwd=ROOT)
        if p.returncode != 0:
            failed.append(label)
            print("   FAILED: %s" % label)
            break  # stop at the first failure; later checks are not meaningful
    print()
    if failed:
        sys.stderr.write("RELEASE GATE FAILED: %s\n" % ", ".join(failed))
        return 1
    print("RELEASE GATE OK: %d checks passed" % len(CHECKS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
