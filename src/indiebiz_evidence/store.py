"""SQLite storage layer for the generic engine.

The source exports are the source of truth; this database is a derived,
rebuildable view. Deleting it and re-running the import must reproduce it.
"""
from __future__ import annotations

import os
import sqlite3

_SCHEMA = os.path.join(os.path.dirname(__file__), "schema.sql")


def connect(db_path: str) -> sqlite3.Connection:
    d = os.path.dirname(os.path.abspath(db_path))
    if d:
        os.makedirs(d, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    return con


def init_db(con: sqlite3.Connection) -> None:
    with open(_SCHEMA, encoding="utf-8") as f:
        con.executescript(f.read())
    con.commit()


def log_file(con, path: str, observed_date: str, slug, status: str, message: str = "") -> None:
    con.execute(
        "INSERT OR REPLACE INTO ingest_files(path, observed_date, slug, status, message) "
        "VALUES (?,?,?,?,?)",
        (path, observed_date, slug, status, message[:500]),
    )


def put_anomaly(con, observed_date: str, slug: str, kind: str, severity: str, detail: str) -> None:
    # The anomaly namespace is '<source>:<entity>'. More than one colon makes the
    # two halves ambiguous ('s' + 't:x' vs 's:t' + 'x' both render 's:t:x'), which
    # silently mixes two sources' anomalies. Refuse it at the lowest write path so
    # no caller can introduce it.
    if slug is not None and str(slug).count(":") > 1:
        raise ValueError("anomaly slug %r has more than one ':' -- the namespace is "
                         "'<source>:<entity>' and neither half may contain a colon"
                         % (slug,))
    con.execute(
        "INSERT OR REPLACE INTO anomalies(observed_date, slug, kind, severity, detail) "
        "VALUES (?,?,?,?,?)",
        (observed_date, slug, kind, severity, detail[:800]),
    )


def latest_source_date(con, source: str):
    row = con.execute("SELECT MAX(observed_date) FROM generic_facts WHERE source=?",
                      (source,)).fetchone()
    return row[0] if row and row[0] else None
