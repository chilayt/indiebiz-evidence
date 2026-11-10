#!/usr/bin/env python3
"""Refuse to commit or ship data this project must never publish.

The public repository is supposed to contain code, docs and synthetic fixtures
only. A .gitignore stops the obvious cases and nothing else: a rename, a forced
add, or a screenshot of a real export all slip past it. This runs in two places:

  pre-commit hook   git diff --cached --name-only  (what is about to enter history)
  CI                the whole tracked tree + built wheel/sdist

Exit code 1 means stop. The log never prints file contents -- only paths and the
reason, so a violation does not itself leak the thing it caught.
"""
from __future__ import annotations

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Directories and extensions that must never be tracked.
BLOCKED_DIRS = ("data/", "captures/", "exports/", "archive/", "archives/")
BLOCKED_EXT = (".db", ".db-wal", ".db-shm", ".sqlite", ".sqlite3", ".csv", ".jsonl",
               ".xlsx", ".xls", ".zip", ".7z", ".rar", ".pem", ".key", ".p12", ".pfx")

# Everything under tests/fixtures is synthetic by policy (see CONTRIBUTING.md):
# invented entities, year 2099, never real exports. Any new fixture directory must
# live there; that is the only place data-shaped files are allowed.
ALLOWED_PREFIX = "tests/fixtures/"

# Content markers: a real export pasted into an otherwise innocent file.
MARKERS = ("tmrr_", "Authorization: Bearer ", "-----BEGIN PRIVATE KEY-----",
           "AWS_SECRET_ACCESS_KEY", "ghp_", "github_pat_")

SKIP_PREFIX = (".git/", "node_modules/", "__pycache__/", "build/", "dist/", ".venv/")

# This file necessarily contains the marker strings it searches for. Skip exactly
# one path -- its own -- rather than weakening the check for everything else.
SELF = "scripts/check_no_real_data.py"


def tracked_files():
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True)
    return [p for p in out.stdout.splitlines() if p.strip()]


def staged_files():
    out = subprocess.run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
                         cwd=ROOT, capture_output=True, text=True)
    return [p for p in out.stdout.splitlines() if p.strip()]


def problems_for(path):
    rel = path.replace("\\", "/")
    if rel.startswith(ALLOWED_PREFIX):
        return []
    if any(rel.startswith(d) or ("/" + d) in ("/" + rel) for d in BLOCKED_DIRS):
        return ["lives in a data directory"]
    if rel.lower().endswith(BLOCKED_EXT):
        return ["has a data/credential extension"]
    if "credential" in rel.lower() or "token" in rel.lower() or ".env" in rel.lower():
        return ["looks like a credential file"]
    return []


def main(argv=None):
    argv = argv or sys.argv[1:]
    pre_commit = "--staged" in argv
    files = staged_files() if pre_commit else tracked_files()
    problems = []
    for f in files:
        for why in problems_for(f):
            problems.append((f, why))
    # content markers, only for text-ish files that exist
    for f in files:
        if f == SELF or f.startswith(ALLOWED_PREFIX):
            continue
        if not os.path.exists(os.path.join(ROOT, f)):
            continue
        if f.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".pdf")):
            continue
        try:
            with open(os.path.join(ROOT, f), encoding="utf-8", errors="ignore") as fh:
                body = fh.read()
        except OSError:
            continue
        for m in MARKERS:
            if m in body:
                problems.append((f, "contains a credential marker (%s)" % m.strip()))
    if problems:
        sys.stderr.write("REFUSED: this repository must not ship data or credentials.\n")
        for f, why in problems:
            sys.stderr.write("  %s -- %s\n" % (f, why))
        sys.stderr.write("\nIf this is a synthetic fixture, add it to ALLOWED in %s\n"
                         % os.path.basename(__file__))
        return 1
    print("data guard OK: %d %s checked, no blocked paths or markers"
          % (len(files), "staged file(s)" if pre_commit else "tracked file(s)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
