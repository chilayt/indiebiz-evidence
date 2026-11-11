"""Build a synthetic demo database so every tool can be tried in minutes.

Purpose 1 (cold start): a user with no exports of their own can run the whole
engine, including every MCP tool, in under a minute.
Purpose 2 (CI): the end-to-end MCP tests run against this database on a clean
clone, so no test is ever silently skipped.

The fixtures ship INSIDE the package (demo_data/), so this works after
`pip install` from any directory -- not only from a repository checkout.

Contains ONLY invented entities in year 2099 -- impossible to confuse with a real
capture. No upstream data of any kind.
"""
from __future__ import annotations

import os

from . import generic, store

# package-relative: works from a checkout AND from site-packages
DEMO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "demo_data")
GENERIC_ROOT = os.path.join(DEMO_ROOT, "generic")


def build(db_path: str, demo_root: str = None, verbose: bool = False):
    demo_root = demo_root or DEMO_ROOT
    gen_root = os.path.join(demo_root, "generic")
    if not os.path.isdir(gen_root):
        raise FileNotFoundError("demo fixtures not found: %s" % gen_root)
    if os.path.exists(db_path):
        os.remove(db_path)
    for suffix in ("-wal", "-shm"):
        p = db_path + suffix
        if os.path.exists(p):
            os.remove(p)
    con = store.connect(db_path)
    store.init_db(con)
    counts = {}
    for name in sorted(os.listdir(gen_root)):
        p = os.path.join(gen_root, name)
        if os.path.isdir(p):
            generic.import_path(con, name, p, verbose=verbose)
            counts[name] = generic.detect_generic(con, name, verbose=False)
    con.commit()
    con.close()
    return counts