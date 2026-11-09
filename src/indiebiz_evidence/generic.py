"""Generic bring-your-own-source adapter (v0.3.1).

Any pipeline that produces PERIODIC SNAPSHOTS (CSV/JSON exports, API dumps,
scraped tables, spreadsheets) can join the same evidence store, the same
anomaly discipline, one store shape and one MCP server.

The ingest layer enforces the ingest-time subset of the nine disciplines
(docs/PATTERNS.md); cross-period disciplines fire in detect_generic:
- missing != zero: absent keys, null, empty strings AND configurable null
  markers ("N/A", "-", ...) are ABSENT facts -- never stored (P0-B);
- raw is kept: every fact stores text=original string alongside the parsed
  num, so unit semantics ("12%", "$99") survive parsing (P0-A);
- three times stay separate: observed_date is validated as a real calendar
  YYYY-MM-DD; unparseable dates reject the record with a WARN (P0-D);
- identity resolution is loud: the chosen entity/date columns and the date
  source are printed, persisted into sources.config, and ambiguous
  auto-detection emits a WARN listing every candidate (P0-C);
- every fact keeps raw_ref -> the exact file it came from.

Conventions
-----------
Input directory::

    <input>/2026-11-07.csv      date from filename (YYYY-MM-DD or YYYYMMDD)
    <input>/20261107.json       ...or rows carry an observed_date/date column
    <input>/source.json         OPTIONAL field-role config (see ADAPTERS.md)

Records are flat objects, one entity per record. Entity column resolution:
CLI/param override > config "entity_column" > first present of
_ENTITY_CANDIDATES > first column (with WARN when several candidates exist).

source.json roles (all optional)::

    {
      "entity_column": "product",
      "date_column": null,
      "monotonic_fields": ["cumulative_units"],
      "identity_fields": ["owner"],
      "timestamp_fields": ["updated_at"],
      "swing_fields": null,
      "swing_threshold": 0.30,
      "min_presence_days": 3,
      "stale_hours": 48,
      "null_markers": ["", "n/a", "na", "-", "--", "null", "none", "nan"]
    }

"min_presence_days" counts CONSECUTIVE CAPTURE DATES of the entity (not
calendar days).  Generic anomaly slugs live in the "<source>:<entity>"
namespace; anomaly kinds carry the field name.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import os
import re
import unicodedata

from . import store
from ._shared import sync_lag_hours as _lag_hours
from ._shared import likely_rename as _likely_rename

_DATE_FNAME = re.compile(r"^(\d{4}-\d{2}-\d{2}|\d{8})")
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# synthetic entity id for source-level (schema) events; real entity ids would
# collide with a per-entity anomaly otherwise
SCHEMA_ENTITY = "__schema__"

_ENTITY_CANDIDATES = ("entity", "name", "slug", "id", "product", "repo", "app",
                      "keyword", "sku", "key", "code", "handle", "ticker",
                      "domain", "package", "username")

DEFAULT_CONFIG = {
    "entity_column": None,
    "date_column": None,
    "monotonic_fields": [],
    "identity_fields": [],
    "timestamp_fields": [],
    "swing_fields": None,
    "swing_threshold": 0.30,
    "min_presence_days": 3,
    "stale_hours": 48,
    "null_markers": ["", "n/a", "na", "-", "--", "null", "none", "nan"],
}


_THOUSANDS = re.compile(r"^\d{1,3}(,\d{3})+(\.\d+)?$")


def _text_change(a, b, n=80):
    """Readable description of a text change.

    Short values are shown in full (a rename reads better whole). Long values
    show only the differing middle, because truncating both sides produced two
    identical-looking details for genuinely different changes.
    """
    a = "" if a is None else str(a)
    b = "" if b is None else str(b)
    if len(a) <= n and len(b) <= n:
        return "%r -> %r" % (a, b)
    return _diff_excerpt(a, b, n)


def _diff_excerpt(a, b, n=80):
    """Return the differing middle of two strings, with context.

    Plain truncation showed two identical prefixes when a long text differed
    only past the cut, making two distinct anomalies look like duplicates.
    """
    a = "" if a is None else str(a)
    b = "" if b is None else str(b)
    i = 0
    limit = min(len(a), len(b))
    while i < limit and a[i] == b[i]:
        i += 1
    j = 0
    while j < (limit - i) and a[len(a) - 1 - j] == b[len(b) - 1 - j]:
        j += 1
    mid_a = a[i:len(a) - j] if j else a[i:]
    mid_b = b[i:len(b) - j] if j else b[i:]
    truncated = len(mid_a) > n or len(mid_b) > n
    if len(mid_a) > n:
        mid_a = mid_a[:n] + "…"
    if len(mid_b) > n:
        mid_b = mid_b[:n] + "…"
    ctx = a[max(0, i - 20):i]
    out = "@%d%s%r -> %r" % (i, (" after %r" % ctx) if ctx else "", mid_a, mid_b)
    if truncated:
        # Two long values can differ only inside the truncated middle; without a
        # digest the two anomalies render identically.
        out += " [len %d/%d sha %s/%s]" % (
            len(a), len(b),
            hashlib.sha1(a.encode("utf-8", "replace")).hexdigest()[:6],
            hashlib.sha1(b.encode("utf-8", "replace")).hexdigest()[:6])
    return out


def _clip(s, n=120):
    """Shorten a text value for anomaly details without losing the head."""
    s = "" if s is None else str(s)
    s = " ".join(s.split())
    return s if len(s) <= n else s[:n] + "…"


def _to_num(v):
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    t = str(v).strip()
    if t.startswith("$"):
        t = t[1:].strip()
    if t.endswith("%"):
        t = t[:-1].strip()
    if not t:
        return None
    # commas are ONLY thousands separators in strict 3-digit groups;
    # "12,5" is locale-ambiguous -> refuse to guess, keep as text (宁缺不猜)
    if "," in t:
        if not _THOUSANDS.match(t):
            return None
        t = t.replace(",", "")
    try:
        v = float(t)
    except ValueError:
        return None
    # 'inf' / '1e999' parse to infinity. That is not a measurement, and
    # json.dumps renders it as the literal Infinity, which is invalid JSON and
    # makes the client fail to parse the entire payload rather than one field.
    if v != v or v in (float("inf"), float("-inf")):
        return None
    return v


def _is_null_marker(v, markers):
    """P0-B: 'N/A'/'-' style placeholders are ABSENCE, not facts."""
    if v is None:
        return True
    if not isinstance(v, str):
        return False
    return v.strip().casefold() in markers


def _file_date(path):
    m = _DATE_FNAME.match(os.path.basename(path))
    if not m:
        return None
    d = m.group(1)
    if "-" in d:
        return d if _valid_date(d) else None
    iso = "%s-%s-%s" % (d[:4], d[4:6], d[6:])
    return iso if _valid_date(iso) else None


def _valid_date(s):
    if not s or not _ISO_DATE.match(str(s)):
        return False
    try:
        dt.date.fromisoformat(str(s))
        return True
    except ValueError:
        return False


def _load_records(path):
    low = path.lower()
    if low.endswith(".jsonl"):
        rows = []
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
        return rows
    if low.endswith(".json"):
        with open(path, encoding="utf-8", errors="replace") as f:
            data = json.load(f)
        if isinstance(data, dict):
            if data and all(isinstance(v, dict) for v in data.values()):
                # {entity: {fields}} map
                return [dict(v, __entity_key__=k) for k, v in data.items()]
            return [data]
        return list(data)
    with open(path, encoding="utf-8-sig", errors="replace", newline="") as f:
        return [dict(r) for r in csv.DictReader(f)]


def load_source_config(input_path, explicit_path=None):
    cfg = dict(DEFAULT_CONFIG)
    p = explicit_path
    if not p and os.path.isdir(input_path):
        cand = os.path.join(input_path, "source.json")
        if os.path.exists(cand):
            p = cand
    if p and os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            cfg.update(json.load(f))
    return cfg


def _resolve_entity_column(records, cfg, override):
    """Return (column, candidates_found, was_explicit). P0-C: loud resolution."""
    if override:
        return override, [], True
    if cfg.get("entity_column"):
        return cfg["entity_column"], [], True
    if not records:
        return None, [], False
    if any("__entity_key__" in r for r in records):
        return "__entity_key__", [], True
    keys = list(records[0].keys())
    found = [c for c in _ENTITY_CANDIDATES if c in keys]
    if found:
        return found[0], found, False
    return (keys[0] if keys else None), [], False


def _resolve_date_column(records, cfg):
    """Explicit config > observed_date > date (ambiguous name, warned by caller)."""
    if cfg.get("date_column"):
        return cfg["date_column"], "config"
    if records and "observed_date" in records[0]:
        return "observed_date", "auto"
    if records and "date" in records[0]:
        return "date", "auto-ambiguous"
    return None, None


def _check_namespace(source, entity=None):
    """The anomaly namespace is '<source>:<entity>'. A colon inside either half
    makes the two halves ambiguous ('s' + 't:x' and 's:t' + 'x' both render as
    's:t:x'), so refuse it at the door instead of silently corrupting lookups.
    """
    if not source or ":" in str(source):
        raise ValueError("source name must be non-empty and must not contain ':' "
                         "(it is the anomaly namespace separator); got %r" % (source,))
    if entity is not None and ":" in str(entity):
        raise ValueError("entity id must not contain ':' (it is the anomaly namespace "
                         "separator); got %r" % (entity,))


def import_path(con, source, input_path, config=None, entity_column=None, verbose=True):
    """Import a directory (or single file) of dated CSV/JSON snapshots."""
    _check_namespace(source)
    cfg = config if config is not None else load_source_config(input_path)
    markers = set(m.casefold() for m in (cfg.get("null_markers") or DEFAULT_CONFIG["null_markers"]))
    files = []
    if os.path.isdir(input_path):
        for name in sorted(os.listdir(input_path)):
            p = os.path.join(input_path, name)
            if (os.path.isfile(p) and name.lower() != "source.json"
                    and name.lower().endswith((".csv", ".json", ".jsonl"))):
                files.append(p)
    elif os.path.isfile(input_path):
        files = [input_path]
    else:
        raise FileNotFoundError(input_path)

    stats = {"files": 0, "facts": 0, "skipped_records": 0, "skipped_values": 0,
             "invalid_dates": 0, "errors": 0, "warnings": [],
             "entities": set(), "fields": set(), "dates": set()}
    seen_dates = {}   # date -> first file that provided it (P1-B)
    cleared_dates = set()  # (source,date) already cleared for replace semantics
    resolved = {}
    for path in files:
        fdate = _file_date(path)
        if _DATE_FNAME.match(os.path.basename(path)) and fdate is None:
            stats["warnings"].append("filename date unparseable, rows must carry a valid date column: %s" % path)
        try:
            records = _load_records(path)
        except Exception as e:
            stats["errors"] += 1
            msg = "%s: %s" % (type(e).__name__, e)
            stats["warnings"].append("parse failure %s: %s" % (os.path.basename(path), msg))
            store.log_file(con, path, fdate or "", None, "error",
                           "generic:%s %s" % (source, msg))
            print("[import:%s] ERROR %s: %s" % (source, os.path.basename(path), msg), flush=True)
            continue
        if not records:
            continue
        stats["files"] += 1
        ecol, candidates, explicit = _resolve_entity_column(records, cfg, entity_column)
        date_col, date_col_how = _resolve_date_column(records, cfg)
        # explicit config must be LOUD when wrong (P1-5/Qoder P1-A): a typo'd
        # column name used to silently skip every record with exit code 0
        cols0 = set(records[0].keys())
        bad_col = None
        if ecol and ecol not in cols0:
            bad_col = ("entity_column", ecol)
        elif date_col and date_col not in cols0:
            bad_col = ("date_column", date_col)
        if bad_col:
            msg = ("configured %s %r does not exist in %s; available columns: %s"
                   % (bad_col[0], bad_col[1], os.path.basename(path), ", ".join(sorted(cols0))))
            stats["errors"] += 1
            stats["warnings"].append(msg)
            store.log_file(con, path, fdate or "", None, "error", "generic:%s %s" % (source, msg))
            print("[import:%s] ERROR %s" % (source, msg), flush=True)
            continue
        if not explicit and len(candidates) > 1:
            w = ("entity_column=%s resolved automatically but other candidates exist: %s -- "
                 "verify or pass --entity-column (wrong grouping corrupts every downstream signal)"
                 % (ecol, ", ".join(c for c in candidates if c != ecol)))
            stats["warnings"].append(w)
            print("[import:%s] WARN %s" % (source, w), flush=True)
        if date_col_how == "auto-ambiguous":
            w = ("using column 'date' as capture date (ambiguous name: could be a business field); "
                 "set date_column explicitly in source.json if wrong")
            stats["warnings"].append(w)
            print("[import:%s] WARN %s" % (source, w), flush=True)
        date_source = "column:%s" % date_col if date_col else "filename"
        resolved = {"entity_column": ecol, "date_column": date_col, "date_source": date_source}
        if verbose:
            print("[import:%s] %s: entity_column=%s date_source=%s"
                  % (source, os.path.basename(path), ecol, date_source), flush=True)
        # Two-phase write with per-(source, date) REPLACE semantics: a revised
        # re-import of the same capture date first clears that date's old facts,
        # so a value edited to null/absent cannot survive as a ghost (Codex P0).
        file_dates = set()
        parsed = []
        for rec in records:
            ent = rec.get(ecol) if ecol else None
            ent = str(ent).strip() if ent is not None else ""
            # a colon in an entity id would collide with the anomaly namespace
            _check_namespace(source, ent)
            date = fdate
            if date_col and rec.get(date_col):
                raw_date = str(rec[date_col]).strip()
                cand = raw_date[:10]
                if _valid_date(cand):
                    date = cand
                else:
                    stats["invalid_dates"] += 1
                    stats["skipped_records"] += 1
                    continue  # P0-D: reject rather than guess (11/07/2026 is ambiguous)
            if not ent or not _valid_date(date):
                if ent and date:
                    stats["invalid_dates"] += 1
                stats["skipped_records"] += 1
                continue
            file_dates.add(date)
            stats["dates"].add(date)
            stats["entities"].add(ent)
            for k, v in rec.items():
                if k == ecol or k == date_col or k == "__entity_key__":
                    continue
                if _is_null_marker(v, markers):
                    if not (v is None or (isinstance(v, str) and not v.strip())):
                        stats["skipped_values"] += 1
                    continue  # absent fact -- never zero, never 'N/A'
                num = _to_num(v)
                text = v if isinstance(v, str) else str(v)
                parsed.append((date, ent, str(k), num, text.strip()))
        for d in sorted(file_dates):
            if d not in cleared_dates:
                con.execute("DELETE FROM generic_facts WHERE source=? AND observed_date=?",
                            (source, d))
                cleared_dates.add(d)
        wrote = 0
        for (date, ent, k, num, text) in parsed:
            con.execute(
                "INSERT OR REPLACE INTO generic_facts"
                "(observed_date, source, entity, field, num, text, raw_ref)"
                " VALUES (?,?,?,?,?,?,?)",
                (date, source, ent, k, num, text, path))
            stats["fields"].add(k)
            wrote += 1
        stats["facts"] += wrote
        store.log_file(con, path, sorted(file_dates)[0] if file_dates else (fdate or ""), None,
                       "ok", "generic:%s facts=%d" % (source, wrote))
        # duplicate-date check AFTER the ok log so the more severe status wins
        # (ingest_files.path is the primary key; last write per file counts)
        for d in sorted(file_dates):
            if d in seen_dates:
                w = ("date %s fed by two files (%s then %s): later facts overwrite earlier ones "
                     "(raw_ref keeps only the last); merge files or re-import deliberately"
                     % (d, seen_dates[d], path))
                stats["warnings"].append(w)
                print("[import:%s] WARN %s" % (source, w), flush=True)
                store.log_file(con, path, d, None, "warn",
                               "generic:%s duplicate_date_file (overwrote facts from %s)"
                               % (source, seen_dates[d]))
            else:
                seen_dates[d] = path
    row = con.execute(
        "SELECT COUNT(DISTINCT entity), COUNT(DISTINCT field), MIN(observed_date), MAX(observed_date)"
        " FROM generic_facts WHERE source=?", (source,)).fetchone()
    merged_cfg = dict(cfg)
    merged_cfg["_resolved"] = resolved
    con.execute(
        "INSERT OR REPLACE INTO sources(source, config, first_seen, last_seen, entity_count, field_count)"
        " VALUES (?,?,?,?,?,?)",
        (source, json.dumps(merged_cfg, ensure_ascii=False), row[2], row[3], row[0], row[1]))
    con.commit()
    out = dict(stats, entities=len(stats["entities"]), fields=len(stats["fields"]),
               dates=sorted(stats["dates"]), resolved=resolved)
    if verbose:
        print("[import:%s] files=%d facts=%d entities=%d fields=%d dates=%s "
              "skipped_records=%d skipped_values(null-markers)=%d invalid_dates=%d warnings=%d"
              % (source, out["files"], out["facts"], out["entities"], out["fields"],
                 ",".join(out["dates"]), out["skipped_records"], out["skipped_values"],
                 out["invalid_dates"], len(out["warnings"])), flush=True)
    return out


def _stored_config(con, source):
    row = con.execute("SELECT config FROM sources WHERE source=?", (source,)).fetchone()
    cfg = dict(DEFAULT_CONFIG)
    if row and row[0]:
        try:
            cfg.update(json.loads(row[0]))
        except Exception:
            pass
    return cfg


def detect_generic(con, source, config=None, verbose=True):
    """Run the five generic rules over one source's facts."""
    _check_namespace(source)
    cfg = config if config is not None else _stored_config(con, source)
    ns = source + ":"
    con.execute("DELETE FROM anomalies WHERE substr(slug,1,?)=?", (len(ns), ns))
    counts = {}

    def flag(date, entity, kind, severity, detail):
        store.put_anomaly(con, date, ns + entity, kind, severity, detail)
        base = kind.split(":")[0]
        counts[base] = counts.get(base, 0) + 1

    facts = [tuple(r) for r in con.execute(
        "SELECT observed_date, entity, field, num, text FROM generic_facts"
        " WHERE source=? ORDER BY entity, field, observed_date", (source,))]
    if not facts:
        con.commit()
        if verbose:
            print("[detect:%s] no facts (nothing to check)" % source)
        return counts
    per_ef = {}
    entity_dates = {}
    presence = {}  # (entity, field) -> set(dates)
    for d, ent, fld, num, text in facts:
        per_ef.setdefault((ent, fld), []).append((d, num, text))
        entity_dates.setdefault(ent, set()).add(d)
        presence.setdefault((ent, fld), set()).add(d)

    mono = set(cfg.get("monotonic_fields") or [])
    ident = set(cfg.get("identity_fields") or [])
    tstamp = set(cfg.get("timestamp_fields") or [])
    swing_fields = cfg.get("swing_fields")
    thr = float(cfg.get("swing_threshold") or 0.30)
    stale_h = float(cfg.get("stale_hours") or 48)
    min_pres = int(cfg.get("min_presence_days") or 1)

    # capture cadence: a source captured weekly, or one that stalled for a month,
    # must not have its gap read as "one day later". Two points 30 days apart are
    # still two points, but "+30% since yesterday" is a lie about them.
    src_dates = sorted({d for ds in entity_dates.values() for d in ds})
    cad = _cadence(src_dates, cfg.get("max_gap_days"))
    gap_days = cad["gap_days"]
    gapped = cad["gapped"]
    for d in sorted(gapped):
        ref = cad["reference"][d]
        basis = ("%s day(s) from %d earlier capture(s)" % (ref["reference_gap_days"], ref["samples"])
                 if ref["samples"] else (ref.get("source") or "unknown"))
        flag(d, SCHEMA_ENTITY, "gapped_transition", "info",
             "capture gap of %d day(s) before %s; this source's normal cadence is %s "
             "(threshold %s) -- changes across this boundary span %d days, not one"
             % (gap_days[d], d, basis, ref["limit_days"], gap_days[d]))

    # pass 1: identity-boundary dates per entity (discipline #6 must gate the
    # other rules -- a price swing across an ownership change is not a signal)
    boundaries = {}
    for (ent, fld), series in per_ef.items():
        if fld not in ident:
            continue
        for (d0, n0, t0), (d1, n1, t1) in zip(series, series[1:]):
            if t0 is not None and t1 is not None and t0 != t1 and not _likely_rename(t0, t1):
                boundaries.setdefault(ent, set()).add(d1)

    for (ent, fld), series in per_ef.items():
        bset = boundaries.get(ent, set())
        for (d0, n0, t0), (d1, n1, t1) in zip(series, series[1:]):
            if (fld in mono and d1 not in bset
                    and n0 is not None and n1 is not None and n1 < n0 - 0.005):
                flag(d1, ent, "monotonic_regression:" + fld, "warn",
                     "%s decreased %s -> %s (declared cumulative; list both values, never diff)"
                     % (fld, n0, n1))
            if fld in ident and t0 is not None and t1 is not None and t0 != t1:
                if _likely_rename(t0, t1):
                    flag(d1, ent, "identity_rename_candidate:" + fld, "info",
                         "%s changed %r -> %r but strings overlap; likely a rename (manual confirm)"
                         % (fld, t0, t1))
                else:
                    flag(d1, ent, "identity_change:" + fld, "high",
                         "%s changed %r -> %r; do NOT diff across this boundary"
                         % (fld, t0, t1))
            if fld in tstamp and t1:
                lag = _lag_hours(str(t1), d1)
                if lag is not None and lag > stale_h:
                    flag(d1, ent, "stale_timestamp:" + fld, "warn",
                         "%s=%s lags capture date by %.0f h (> %.0f h threshold)"
                         % (fld, t1, lag, stale_h))
            is_swing = (fld in set(swing_fields)) if swing_fields else (
                fld not in mono and fld not in ident and fld not in tstamp)
            if d1 in bset:
                is_swing = False  # cross-boundary changes are meaningless, not signals
            if is_swing and n0 is not None and n1 is not None and n0 != 0:
                ch = (n1 - n0) / abs(n0)
                if abs(ch) >= thr:
                    span = gap_days.get(d1)
                    extra = ""
                    if d1 in gapped and span:
                        extra = " over %d days (capture gap; not a one-day move)" % span
                    flag(d1, ent, "value_swing:" + fld, "info",
                         "%s moved %s -> %s (%+.0f%%, threshold %.0f%%)%s"
                         % (fld, n0, n1, ch * 100, thr * 100, extra))

    # text drift: content-bearing fields change for reasons that matter to a
    # collector (title renamed, status open->closed, description rewritten) but
    # the numeric rules above are blind to them. Opt-in only: an undeclared text
    # field that changes every capture would flood the anomaly table.
    text_fields = set(cfg.get("track_text_fields") or [])
    for (ent, fld), series in per_ef.items():
        if fld not in text_fields:
            continue
        bset = boundaries.get(ent, set())
        for (d0, n0, t0), (d1, n1, t1) in zip(series, series[1:]):
            if d1 in bset:
                continue  # a different entity after the boundary; not a change
            if t0 is None or t1 is None or t0 == t1:
                continue
            flag(d1, ent, "text_changed:" + fld, "info",
                 "%s changed %s" % (fld, _text_change(t0, t1)))

    # field_disappeared: the GSC lesson, generalized
    for ent, dates in entity_dates.items():
        dlist = sorted(dates)
        for i in range(1, len(dlist)):
            dp, dc = dlist[i - 1], dlist[i]
            for (e2, fld), pres in presence.items():
                if e2 != ent or dp not in pres:
                    continue
                if dc in pres:
                    continue
                streak = 0
                j = i - 1
                while j >= 0 and dlist[j] in pres:
                    streak += 1
                    j -= 1
                if streak >= min_pres:
                    note = ""
                    if dc in boundaries.get(ent, set()):
                        note = (" -- NOTE: identity boundary on this date; absence may belong "
                                "to the ownership change")
                    gap_note = ""
                    if dc in gapped and gap_days.get(dc):
                        gap_note = (" -- after a %d-day capture gap; absence may be normal "
                                    "churn in that window" % gap_days[dc])
                    flag(dc, ent, "field_disappeared:" + fld, "warn",
                         "field '%s' present %d consecutive capture(s) through %s is absent on %s "
                         "(check source AND your parser before concluding removal)%s%s"
                         % (fld, streak, dp, dc, note, gap_note))
    # entity_disappeared: an entry that stops existing altogether (job posting
    # filled, listing delisted, paper withdrawn). field_disappeared covers "one
    # column stopped arriving"; this covers "the whole row stopped arriving".
    # Gated by min_presence_days so a rotating daily top-N list does not scream.
    all_dates = sorted({d for ds in entity_dates.values() for d in ds})
    for i in range(1, len(all_dates)):
        dp, dc = all_dates[i - 1], all_dates[i]
        for ent, dset in entity_dates.items():
            if dp not in dset or dc in dset:
                continue
            streak = 0
            j = i - 1
            while j >= 0 and all_dates[j] in dset:
                streak += 1
                j -= 1
            if streak >= min_pres:
                gap_note = ""
                if dc in gapped and gap_days.get(dc):
                    gap_note = (" -- after a %d-day capture gap; entries can rotate out "
                                "legitimately in that window" % gap_days[dc])
                flag(dc, ent, "entity_disappeared", "warn",
                     "entity absent on %s after %d consecutive capture(s) -- delisted/removed, "
                     "or your crawler missed it; check the source before concluding removal%s"
                     % (dc, streak, gap_note))

    # schema drift: the column set itself changed. Anyone who re-points a scraper
    # at a redesigned page meets this first, and nothing else in the engine would
    # tell them -- field_disappeared is per-entity ("one column stopped arriving
    # for this row"), this is per-source ("the source's shape changed").
    #
    # Reported on the TRANSITION only (prev date -> this date), never re-reported
    # on later dates, and only when the column covers every entity on one side --
    # a column that comes and goes for a few rows is per-entity drift, which
    # field_disappeared already owns.
    vals = {}
    date_fields = {}
    date_entities = {}
    for d, ent, fld, num, text in facts:
        date_fields.setdefault(d, set()).add(fld)
        date_entities.setdefault(d, set()).add(ent)
        vals.setdefault(d, {}).setdefault(fld, {})[ent] = (num, text)

    def _full(d, fld):
        ents = date_entities.get(d, set())
        return bool(ents) and set(vals.get(d, {}).get(fld, {})) >= ents

    def _similar(a, b):
        if a is None or b is None:
            return False
        try:
            fa, fb = float(a), float(b)
        except (TypeError, ValueError):
            return a == b
        m = max(abs(fa), abs(fb))
        return (abs(fa - fb) <= 1e-9) if m == 0 else (abs(fa - fb) / m <= 0.5)

    ordered = sorted(date_fields)
    for i in range(1, len(ordered)):
        dp, d = ordered[i - 1], ordered[i]
        added = sorted(date_fields[d] - date_fields[dp])
        dropped = sorted(date_fields[dp] - date_fields[d])
        added = [f for f in added if _full(d, f)]
        dropped = [f for f in dropped if _full(dp, f)]
        for fld in added:
            flag(d, SCHEMA_ENTITY, "field_appeared:" + fld, "info",
                 "column '%s' appears on %s for every entity -- source redesign or "
                 "your extractor started emitting it; check both" % (fld, d))
        for fld in dropped:
            flag(d, SCHEMA_ENTITY, "field_gone:" + fld, "warn",
                 "no entity reports a value for '%s' on %s (every entity did on %s). "
                 "The column may have been removed from the export, or it may still be "
                 "present but empty -- the fact table stores no null cells, so it "
                 "cannot tell these apart. Check the raw file before concluding the "
                 "schema changed." % (fld, d, dp))
        # rename heuristic: one column vanished and another appeared the same day,
        # carrying values for the same entities. Values usually move too, so this
        # is a candidate with its evidence shown, never a conclusion.
        for gone in dropped:
            gvals = vals.get(dp, {}).get(gone, {})
            for new in added:
                nvals = vals.get(d, {}).get(new, {})
                common = set(gvals) & set(nvals)
                if not common:
                    continue
                close = sum(1 for ent in common if _similar(gvals[ent][0], nvals[ent][0])
                            or (gvals[ent][1] is not None and gvals[ent][1] == nvals[ent][1]))
                if len(common) >= max(2, int(0.8 * len(gvals))) and close / float(len(common)) >= 0.6:
                    flag(d, SCHEMA_ENTITY,
                         "field_renamed_candidate:%s->%s" % (gone, new), "info",
                         "'%s' vanished and '%s' appeared on the same date; same entities "
                         "(%d), similar values (%d/%d) -- likely one column renamed "
                         "(confirm before migrating your config)"
                         % (gone, new, len(common), close, len(common)))

    con.commit()
    if verbose:
        for k in sorted(counts):
            print("[detect:%s] %-28s %d" % (source, k, counts[k]))
    return counts


# ------------------------------------------------------------------ queries

def list_sources(con):
    out = []
    cur = con.execute("SELECT source, config, first_seen, last_seen, entity_count, field_count"
                      " FROM sources ORDER BY source")
    for r in cur.fetchall():
        resolved = None
        try:
            resolved = (json.loads(r[1]) or {}).get("_resolved")
        except Exception:
            pass
        out.append({"source": r[0], "first_seen": r[2], "last_seen": r[3],
                    "entity_count": r[4], "field_count": r[5], "resolved": resolved})
    return out


def query_series(con, source, entity, field, since=None):
    sql = ("SELECT observed_date, num, text, raw_ref FROM generic_facts"
           " WHERE source=? AND entity=? AND field=?")
    params = [source, entity, field]
    if since:
        sql += " AND observed_date >= ?"
        params.append(since)
    sql += " ORDER BY observed_date"
    cur = con.execute(sql, tuple(params))
    return [{"observed_date": r[0], "num": r[1], "text": r[2], "raw_ref": r[3]}
            for r in cur.fetchall()]


def entity_snapshot(con, source, entity, date=None):
    cur = con.execute("SELECT MAX(observed_date) FROM generic_facts WHERE source=? AND entity=?",
                      (source, entity))
    r = cur.fetchone()
    if not r or not r[0]:
        return None
    date = date or r[0]
    fields = {}
    cur = con.execute("SELECT field, num, text, raw_ref FROM generic_facts"
                      " WHERE source=? AND entity=? AND observed_date=?", (source, entity, date))
    rows = cur.fetchall()
    if not rows:
        return None
    for fld, num, text, ref in rows:
        fields[fld] = {"num": num, "text": text}
    anoms = [{"observed_date": a[0], "kind": a[1], "severity": a[2], "detail": a[3]}
             for a in con.execute(
                 "SELECT observed_date, kind, severity, detail FROM anomalies"
                 " WHERE slug=? AND observed_date<=? ORDER BY observed_date DESC, kind LIMIT 30",
                 (source + ":" + entity, date))]
    return {"source": source, "entity": entity, "date": date,
            "fields": fields, "raw_ref": rows[0][3], "anomalies": anoms}


def suggest_entities(con, source, needle, limit=8):
    cur = con.execute(
        "SELECT DISTINCT entity FROM generic_facts WHERE source=? AND entity LIKE ? LIMIT ?",
        (source, "%" + needle + "%", limit))
    return [r[0] for r in cur.fetchall()]


# ---------------------------------------------------------------- generic queries
# Three generic-only capabilities (any bring-your-own CSV/JSON source, no
# vertical coupling). They exist because the most common collector failures are
# not "I cannot read the data" but "my scraper silently stopped emitting a
# field" and "I cannot ask a question of my own dataset". See docs/PATTERNS.md
# disciplines 1 (missing != zero) and 8 (suspect yourself first).


def _ns_prefix(con_sql, ns):
    """Exact prefix predicate for a namespace, with its bind values.

    Never use LIKE here: SQLite's LIKE is case-insensitive for ASCII ('Shop:x'
    matched 'shop:%') and treats '_'/'%' as wildcards ('shop_a:%' matched
    'shopXa:x'). Both are cross-source data loss.
    """
    return "%s.substr(slug,1,?)=?" % con_sql, (len(ns), ns)


def _like_escape(value):
    """Escape a literal string for use as a LIKE pattern.

    Source names are user-supplied and frequently contain '_' (shop_a), which is
    a LIKE wildcard. Unescaped, deleting anomalies for 'shop_a' also deleted
    'shopXa' -- cross-source data loss.
    """
    s = "" if value is None else str(value)
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _cadence(dates, cfg_gap=None):
    """Judge each capture gap against the cadence learned from EARLIER gaps only.

    The previous version used the median of ALL intervals, which is circular:
    with two capture dates the only interval is also the reference, so the
    threshold was always >= that interval and gapped_transition could never
    fire. With three dates the median was dragged by the very gap being judged.

    Using only prior intervals fixes both, and makes "we do not know this
    source's rhythm yet" an explicit answer instead of a silent no-alarm.
    """
    cfg_gap = float(cfg_gap or 0)
    if not dates:
        return {"gap_days": {}, "reference": {}, "gapped": {}, "unknown": [],
                "median_gap_days": None}
    ords = {d: dt.date.fromisoformat(d).toordinal() for d in dates}
    gap_days = {}
    reference = {}
    prior = []
    for a, b in zip(dates, dates[1:]):
        gap_days[b] = ords[b] - ords[a]
        if prior:
            ps = sorted(prior)
            n = len(ps)
            med = ps[n // 2] if n % 2 else (ps[n // 2 - 1] + ps[n // 2]) / 2.0
            reference[b] = {"reference_gap_days": med, "samples": len(prior),
                            "limit_days": max(cfg_gap, 2 * med)}
        elif cfg_gap:
            reference[b] = {"reference_gap_days": None, "samples": 0,
                            "limit_days": cfg_gap, "source": "configured max_gap_days"}
        else:
            reference[b] = {"reference_gap_days": None, "samples": 0,
                            "limit_days": None, "source": "unknown (no prior captures)"}
        prior.append(gap_days[b])
    gapped = {d: gap_days[d] for d, ref in reference.items()
              if ref["limit_days"] and gap_days[d] > ref["limit_days"]}
    unknown = [d for d, ref in reference.items() if not ref["limit_days"]]
    return {"gap_days": gap_days, "reference": reference, "gapped": gapped,
            "unknown": unknown,
            "median_gap_days": (reference.get(dates[-1], {}).get("reference_gap_days")
                                if dates else None)}


def _source_dates(con, source):
    return [r[0] for r in con.execute(
        "SELECT DISTINCT observed_date FROM generic_facts WHERE source=? ORDER BY observed_date",
        (source,))]


def field_coverage(con, source, max_gap_days=None):
    """Per-field presence audit for one generic source.

    Answers the question a collector actually has: which fields are we
    capturing reliably, and which ones silently vanished (scraper break,
    parser regression, upstream schema change)?
    """
    cfg_gap = max_gap_days
    if cfg_gap is None:
        cfg_gap = (_stored_config(con, source) or {}).get("max_gap_days")
    dates = _source_dates(con, source)
    if not dates:
        return None
    latest = dates[-1]
    total_days = len(dates)

    # entities that have any fact on the latest date (the live population)
    live = [r[0] for r in con.execute(
        "SELECT DISTINCT entity FROM generic_facts WHERE source=? AND observed_date=?",
        (source, latest))]

    rows = con.execute("""
        SELECT field,
               COUNT(DISTINCT CASE WHEN num IS NOT NULL OR text IS NOT NULL
                                   THEN observed_date END)  AS present_days,
               COUNT(DISTINCT CASE WHEN num IS NOT NULL OR text IS NOT NULL
                                   THEN entity END)         AS entities_present,
               MIN(observed_date)                         AS first_seen,
               MAX(observed_date)                         AS last_seen,
               SUM(CASE WHEN num IS NULL AND text IS NULL THEN 1 ELSE 0 END) AS blank_rows
        FROM generic_facts WHERE source=?
        GROUP BY field ORDER BY field""", (source,)).fetchall()

    # per-entity latest presence, to spot "had it before, missing now"
    latest_by_field = {r[0]: set() for r in rows}
    for fld, ent in con.execute(
            "SELECT field, entity FROM generic_facts WHERE source=? AND observed_date=? "
            "AND (num IS NOT NULL OR text IS NOT NULL)", (source, latest)):
        if fld in latest_by_field:
            latest_by_field[fld].add(ent)

    ever_by_field = {r[0]: set() for r in rows}
    for fld, ent in con.execute(
            "SELECT field, entity FROM generic_facts WHERE source=? "
            "AND (num IS NOT NULL OR text IS NOT NULL)", (source,)):
        if fld in ever_by_field:
            ever_by_field[fld].add(ent)

    out = []
    for field, present_days, entities_present, first_seen, last_seen, blank_rows in rows:
        now_present = len(latest_by_field.get(field, ()))
        ever_present = len(ever_by_field.get(field, ()))
        live_set = set(live)
        # An entity that stopped existing is NOT evidence that the field stopped
        # arriving. Only entities still present on the latest date can testify
        # about field coverage; the ones that left are reported separately.
        dropped = sorted((ever_by_field.get(field, set()) & live_set)
                         - latest_by_field.get(field, set()))
        exited = sorted(ever_by_field.get(field, set()) - live_set)
        cov = round(100.0 * present_days / total_days, 1) if total_days else 0.0
        out.append({
            "field": field,
            "coverage_pct": cov,
            "present_days": present_days,
            "total_days": total_days,
            "entities_present_latest": now_present,
            "entities_ever": ever_present,
            "entities_live": len(live_set),
            "entities_exited_with_field": len(exited),
            "first_seen": first_seen,
            "last_seen": last_seen,
            "blank_rows": blank_rows,
            "dropped_on_latest": len(dropped),
            "dropped_examples": dropped[:5],
            # discipline #8: a field that used to arrive and now does not is a
            # capture problem until proven otherwise -- never "the source has no
            # such data any more". status is machine-readable; verdict is for humans.
            "status": ("absent_on_latest" if (dropped and now_present == 0) else
                       ("partial_drop" if dropped else "ok")),
            "verdict": (
                "ABSENT-NOW: no still-present entity reports this field on the latest "
                "date. The column may have been removed, renamed or emptied -- the fact "
                "table stores no null cells, so it cannot tell these apart. Check the "
                "raw file before concluding the source changed."
                if (dropped and now_present == 0) else
                ("PARTIAL DROP: %d of %d still-present entities lost this field on the "
                 "latest date (%s). Could be a capture problem, or the field may be "
                 "entity-specific by nature (only listed items have a listing_url) -- "
                 "check both." % (len(dropped), len(live_set), ", ".join(dropped[:3]))
                 if dropped else "ok")),
            "exited_entities_note": (
                "%d entities that once had this field no longer exist on the latest "
                "date; that is entity churn, not field drift" % len(exited)
                if exited else None),
        })
    # schema drift summary: which columns were not there from the start, and which
    # stopped arriving before the latest capture
    first_date = dates[0]
    added = [{"field": f["field"], "first_seen": f["first_seen"]}
             for f in out if f["first_seen"] and f["first_seen"] > first_date]
    # Only fields that still-present entities stopped reporting count as a shape
    # change. A field whose carriers all exited is entity churn, and the field's
    # own status already says "ok" -- the summary must not contradict it.
    removed = [{"field": f["field"], "last_seen": f["last_seen"], "status": f["status"]}
               for f in out if f["status"] == "absent_on_latest"]
    partial = [{"field": f["field"], "lost_by": f["dropped_on_latest"]}
               for f in out if f["status"] == "partial_drop"]
    # cadence: is this source actually being captured at a steady rhythm?
    _cad = _cadence(dates, cfg_gap)
    cadence = {
        "median_gap_days": _cad["median_gap_days"],
        "max_gap_days": max(_cad["gap_days"].values()) if _cad["gap_days"] else None,
        "gaps_over_threshold": [
            {"date": d, "gap_days": _cad["gap_days"][d],
             "reference_gap_days": _cad["reference"][d]["reference_gap_days"],
             "samples": _cad["reference"][d]["samples"]}
            for d in sorted(_cad["gapped"])],
        "cadence_unknown_for": _cad["unknown"],
        "note": ("each gap is judged against the cadence learned from EARLIER gaps "
                 "only. Dates in cadence_unknown_for have no prior capture to learn "
                 "from (or no max_gap_days configured): we do not know whether they "
                 "are late, so nothing is claimed either way."),
    }
    return {"source": source, "dates": total_days, "latest": latest,
            "entities_latest": len(live), "fields": out,
            "cadence": cadence,
            "schema_events": {"fields_added_after_first_capture": added,
                              "fields_missing_on_latest": removed,
                              "fields_partially_missing_on_latest": partial,
                              "note": ("a column that was not there from the start, or "
                                       "whose live entities stopped reporting it, means the "
                                       "observed shape differs from the initial capture -- the "
                                       "column may have been removed, renamed, or emptied. "
                                       "Confirm which before trusting cross-date comparisons")}}


def search_records(con, source, date=None, q=None, filters=None, sort=None,
                   desc=True, limit=20, offset=0):
    """Filter and sort one generic source's records at a capture date.

    filters: [{"field": str, "op": ">="|"<="|">"|"<"|"=="|"!="|"contains", "value": ...}]
    Absent fields never satisfy a numeric comparison (missing != zero).
    """
    dates = _source_dates(con, source)
    if not dates:
        return None
    date = date or dates[-1]
    # A date the source was never captured on is NOT an empty snapshot. Returning
    # zero rows plus a hint about field coverage would send the agent looking for
    # a capture problem that does not exist.
    if date not in dates:
        return {"source": source, "date": date, "total_matched": 0,
                "error": "%r is not a capture date of this source" % (date,),
                "known_dates": dates[-12:], "total_dates": len(dates),
                "hint": "a missing capture is not an empty snapshot"}
    rows = con.execute(
        "SELECT entity, field, num, text, raw_ref FROM generic_facts "
        "WHERE source=? AND observed_date=?", (source, date)).fetchall()
    recs = {}
    for ent, fld, num, text, raw in rows:
        rec = recs.setdefault(ent, {"entity": ent, "fields": {}, "raw_ref": raw})
        rec["fields"][fld] = {"num": num, "text": text}

    _unfiltered = dict(recs) if recs else {}
    ops = {
        ">=": lambda a, b: a >= b, "<=": lambda a, b: a <= b,
        ">": lambda a, b: a > b, "<": lambda a, b: a < b,
        "==": lambda a, b: a == b, "!=": lambda a, b: a != b,
        "contains": lambda a, b: b in str(a),
    }
    NUMERIC_OPS = {">=", "<=", ">", "<"}
    for f in (filters or []):
        fld, op = f.get("field"), f.get("op") or ">="
        want = f.get("value")
        if not fld:
            continue
        fn = ops.get(op)
        if fn is None:
            # Silently dropping an unrecognised operator returns EVERY row while
            # total_matched still looks like a match count -- the exact class of
            # confident wrong answer this engine exists to prevent.
            return {"source": source, "date": date, "total_matched": 0,
                    "error": "unknown filter op %r; allowed: %s"
                             % (op, ", ".join(sorted(ops))),
                    "filters": filters}
        if "value" not in f:
            return {"source": source, "date": date, "total_matched": 0,
                    "error": "filter on %r is missing 'value'; without it '!=' matches "
                             "every row and '>=' matches none" % (fld,),
                    "filters": filters}
        # Coercion must follow the FIELD's stored type, not the literal's. Comparing
        # the string 'cheap' to a numeric column also makes '!=' match every row --
        # the same bug as uncoerced '30', through a narrower doorway.
        # Decide the field's type ONCE, from the unfiltered records at this date.
        # Inferring it from whatever survived earlier filters made the same operator
        # mean different things on different row subsets.
        _all = list(recs.values()) if not filters else list(_unfiltered.values())
        _has_num = any(r["fields"].get(fld) is not None and r["fields"][fld].get("num") is not None
                       for r in _all)
        _has_text = any(r["fields"].get(fld) is not None
                        and r["fields"][fld].get("num") is None
                        and r["fields"][fld].get("text") not in (None, "")
                        for r in _all)
        if _has_num and _has_text and op != "contains":
            return {"source": source, "date": date, "total_matched": 0,
                    "error": "field %r holds both numbers and text; comparison "
                             "semantics would differ per row -- filter a typed field, "
                             "or clean the import" % (fld,),
                    "filters": filters}
        field_is_numeric = _has_num
        if isinstance(want, str) and op != "contains":
            coerced = _to_num(want)
            if coerced is not None:
                want = coerced
            elif field_is_numeric:
                return {"source": source, "date": date, "total_matched": 0,
                        "error": "filter value %r is not numeric, but field '%s' holds "
                                 "numbers; a string comparison would silently match (or "
                                 "fail to match) every row" % (f.get("value"), fld),
                        "filters": filters}
        keep = {}
        for ent, rec in recs.items():
            cell = rec["fields"].get(fld)
            if cell is None:
                continue                      # absent never satisfies a filter
            val = cell["num"] if cell["num"] is not None else cell["text"]
            if val is None:
                continue
            try:
                if fn(val, want):
                    keep[ent] = rec
            except TypeError:
                continue
        recs = keep

    if q:
        needle = q.lower()
        recs = {e: r for e, r in recs.items() if needle in e.lower()}

    out = list(recs.values())
    if sort:
        # Missing values must sort LAST in both directions. The old key
        # (v is None, v) combined with reverse=True floated records that do not
        # have the field at all to the top -- "highest price" returned an entity
        # with no price. Split the sentinel from the direction instead.
        numbers = []
        strings = []
        absent = []
        for rec in out:
            cell = rec["fields"].get(sort)
            if cell is None or (cell.get("num") is None and cell.get("text") in (None, "")):
                absent.append(rec)
            elif cell.get("num") is not None:
                numbers.append((cell["num"], rec))
            else:
                strings.append((str(cell["text"]).lower(), rec))
        # Sorting a mixed column by str() put 10 before 9. Numbers sort as numbers,
        # text sorts as text, and the two groups never interleave.
        numbers.sort(key=lambda pair: pair[0], reverse=bool(desc))
        strings.sort(key=lambda pair: pair[0], reverse=bool(desc))
        out = [rec for _, rec in numbers] + [rec for _, rec in strings] + absent
    else:
        out.sort(key=lambda r: r["entity"])
    total = len(out)
    limit = min(max(int(limit or 20), 1), 500)
    offset = max(int(offset or 0), 0)
    return {"source": source, "date": date, "total_matched": total,
            "offset": offset, "returned": len(out[offset:offset + limit]),
            "has_more": offset + limit < total,
            "records": out[offset:offset + limit]}


def entity_chain(con, source, entity, since=None):
    """All fields of one generic entity across every capture date."""
    sql = ("SELECT observed_date, field, num, text, raw_ref FROM generic_facts "
           "WHERE source=? AND entity=?")
    params = [source, entity]
    if since:
        sql += " AND observed_date>=?"
        params.append(since)
    sql += " ORDER BY observed_date, field"
    rows = con.execute(sql, params).fetchall()
    if not rows:
        return None
    by_date = {}
    for d, fld, num, text, raw in rows:
        rec = by_date.setdefault(d, {"date": d, "fields": {}, "raw_ref": raw})
        if num is not None or text is not None:
            rec["fields"][fld] = {"num": num, "text": text}
    all_fields = sorted({r[1] for r in rows})
    # fields that disappear between dates -- same silent-drop signal as coverage
    vanished = []
    prev = None
    for d in sorted(by_date):
        cur = set(by_date[d]["fields"])
        if prev is not None:
            gone = sorted(prev - cur)
            if gone:
                vanished.append({"date": d, "fields_gone": gone})
        prev = cur
    return {"source": source, "entity": entity,
            "dates": len(by_date), "fields": all_fields,
            "chain": [by_date[d] for d in sorted(by_date)],
            "field_disappearances": vanished}


def diff_snapshots(con, source, from_date=None, to_date=None, limit=200):
    # a source name containing ':' cannot be distinguished from '<source>:<entity>'
    # in the anomaly namespace, so boundary attribution would be ambiguous
    _check_namespace(source)
    """What changed between two captures of one generic source.

    Domain-neutral: works the same for prices, job postings, paper listings or
    changelog text. Reports entity churn (new / gone) and per-field changes
    (numeric delta, text before/after, field appeared / disappeared).
    """
    dates = _source_dates(con, source)
    if not dates:
        return None
    to_date = to_date or dates[-1]
    # Validate an explicitly supplied 'to' BEFORE deriving 'from' from it: with a
    # bogus early 'to' the earlier code reported "only one capture date" instead
    # of naming the unknown date.
    if to_date not in dates:
        return {"source": source, "error": "to date %r is not a capture date of this "
                                           "source" % (to_date,),
                "known_dates": dates[-12:], "total_dates": len(dates),
                "hint": "a missing capture is not an empty snapshot"}
    if from_date is None:
        earlier = [d for d in dates if d < to_date]
        if not earlier:
            return {"source": source, "to": to_date, "from": None,
                    "note": "only one capture date in this source; nothing to compare yet"}
        from_date = earlier[-1]
    # A date the source was never captured on is NOT an empty snapshot. Treating
    # it as one turned "no observation" into "every entity was delisted".
    for label, d in (("from", from_date), ("to", to_date)):
        if d not in dates:
            return {"source": source, "error": "%s date %r is not a capture date of this "
                                               "source" % (label, d),
                    "known_dates": dates[-12:], "total_dates": len(dates),
                    "hint": "pass one of known_dates; a missing capture is not an "
                            "empty snapshot"}
    if from_date > to_date:
        return {"source": source, "error": "from (%s) is later than to (%s)"
                                           % (from_date, to_date),
                "known_dates": dates[-12:]}

    def load(d):
        out = {}
        for ent, fld, num, text in con.execute(
                "SELECT entity, field, num, text FROM generic_facts "
                "WHERE source=? AND observed_date=?", (source, d)):
            if num is None and text is None:
                continue
            out.setdefault(ent, {})[fld] = {"num": num, "text": text}
        return out

    a, b = load(from_date), load(to_date)
    new_entities = sorted(set(b) - set(a))
    gone_entities = sorted(set(a) - set(b))

    # The detector refuses to diff across an identity boundary; the diff tool must
    # refuse too, or the same engine contradicts itself in two outputs.
    _ns = source + ":"
    boundary_rows = con.execute(
        "SELECT DISTINCT slug, observed_date FROM anomalies WHERE substr(slug,1,?)=? "
        "AND kind LIKE 'identity_change:%' AND observed_date>? AND observed_date<=?",
        (len(_ns), _ns, from_date, to_date)).fetchall()
    boundaries_by_entity = {}
    ambiguous = []
    for slug, d in boundary_rows:
        rest = slug[len(_ns):]
        # Legacy rows imported before the namespace constraint existed can still
        # carry a second colon; attributing them by string slicing would hand one
        # source's boundary to another entity. Skip and report instead.
        if ":" in rest:
            ambiguous.append(slug)
            continue
        boundaries_by_entity.setdefault(rest, []).append(d)
    span_days = (dt.date.fromisoformat(to_date) - dt.date.fromisoformat(from_date)).days

    changed = []
    for ent in sorted(set(a) & set(b)):
        fa, fb = a[ent], b[ent]
        deltas = []
        for fld in sorted(set(fa) | set(fb)):
            ca, cb = fa.get(fld), fb.get(fld)
            if ca is None and cb is not None:
                deltas.append({"field": fld, "kind": "field_appeared",
                               "to": cb["num"] if cb["num"] is not None else _clip(cb["text"])})
            elif ca is not None and cb is None:
                deltas.append({"field": fld, "kind": "field_disappeared",
                               "from": ca["num"] if ca["num"] is not None else _clip(ca["text"])})
            elif ca is not None and cb is not None:
                if ca["num"] is not None and cb["num"] is not None:
                    if ca["num"] != cb["num"]:
                        pct = ((cb["num"] - ca["num"]) / abs(ca["num"]) * 100.0) if ca["num"] else None
                        deltas.append({"field": fld, "kind": "numeric",
                                       "from": ca["num"], "to": cb["num"],
                                       "delta_pct": None if pct is None else round(pct, 2)})
                elif (ca["text"] or "") != (cb["text"] or ""):
                    ta, tb = ca["text"] or "", cb["text"] or ""
                    short = len(ta) <= 80 and len(tb) <= 80
                    deltas.append({"field": fld, "kind": "text",
                                   "from": _clip(ca["text"], 200) if short else _diff_excerpt(ta, tb, 60),
                                   "to": _clip(cb["text"], 200) if short else "…",
                                   "excerpt": _text_change(ta, tb)})
        if deltas:
            entry = {"entity": ent, "changes": deltas}
            if ent in boundaries_by_entity:
                entry["across_identity_boundary"] = sorted(boundaries_by_entity[ent])
                for ch in deltas:
                    if ch["kind"] == "numeric":
                        # a percentage across an ownership change is meaningless
                        ch.pop("delta_pct", None)
                        ch["delta_pct"] = None
                        ch["note"] = ("identity boundary inside this window: values are "
                                      "shown side by side, no change rate is computed")
            if span_days != 1:
                entry["span_days"] = span_days
            changed.append(entry)

    total_changes = sum(len(c["changes"]) for c in changed)
    out = {
        "source": source, "from": from_date, "to": to_date, "span_days": span_days,
        "summary": {"new_entities": len(new_entities),
                    "gone_entities": len(gone_entities),
                    "changed_entities": len(changed),
                    "field_changes": total_changes},
        "new_entities": new_entities[:limit],
        "gone_entities": gone_entities[:limit],
        "changed": changed[:limit],
        "truncated": (len(new_entities) > limit or len(gone_entities) > limit
                      or len(changed) > limit),
        "note": ("gone entities are reported, not explained: a delisted listing and a "
                 "crawler miss look identical from here -- check the source before "
                 "concluding removal"),
    }
    if ambiguous:
        out["unscoped_boundary_rows"] = sorted(set(ambiguous))[:10]
        out["unscoped_boundary_note"] = ("these anomaly rows carry an ambiguous namespace and "
                                         "were not attributed to any entity; re-import the "
                                         "source to clear them")
    if boundaries_by_entity:
        out["identity_boundaries"] = {k: sorted(v) for k, v in boundaries_by_entity.items()}
        out["warning"] = ("do NOT read the numeric changes of these entities as growth: "
                          "an identity boundary sits inside this window")
    if span_days > 1:
        out["cadence_note"] = ("these two captures are %d days apart: every change spans "
                               "that whole window, not one capture interval" % span_days)
    return out


# ------------------------------------------------------------ entity resolution
# The second wall a collector hits: step one is "I cannot capture it", step two
# is "I captured it but cannot join it". The same product appears as
# "Acme Widget", "acme-widget" and "ACME_WIDGET" in three exports, becomes three
# entities, and never lines up. These helpers make the collisions VISIBLE. They
# never merge anything: two different things can normalize identically
# ("a/b" vs "a-b"), so a merge is always a human decision with the evidence shown.

_SEP = re.compile(r"[\s\-_\.\u00b7/\\]+")


def normalize_entity(value):
    """Fold an entity id to a comparison key.

    Case, whitespace, and the usual separators (- _ . / backslash) are removed.
    Deliberately conservative: no transliteration, no fuzzy edit distance --
    those produce confident-looking wrong joins, which are worse than no join.
    """
    s = unicodedata.normalize("NFKC", "" if value is None else str(value)).strip().casefold()
    return _SEP.sub("", s)


def list_entities(con, source, limit=100, offset=0):
    """Light inventory of one source's entities (no field payload)."""
    rows = con.execute(
        "SELECT entity, MIN(observed_date), MAX(observed_date), COUNT(DISTINCT observed_date),"
        " COUNT(*) FROM generic_facts WHERE source=? GROUP BY entity ORDER BY entity",
        (source,)).fetchall()
    if not rows:
        return None
    items = [{"entity": e, "first_seen": f, "last_seen": l,
              "days_present": d, "facts": n} for e, f, l, d, n in rows]
    limit = min(max(int(limit or 100), 1), 1000)
    offset = max(int(offset or 0), 0)
    return {"source": source, "total": len(items), "offset": offset,
            "returned": len(items[offset:offset + limit]),
            "has_more": offset + limit < len(items),
            "entities": items[offset:offset + limit]}


def find_duplicate_entities(con, source, limit=50):
    """Entities inside one source that fold to the same comparison key.

    A merge candidate is evidence, not a verdict: the caller decides.
    """
    rows = con.execute(
        "SELECT entity, MIN(observed_date), MAX(observed_date), COUNT(DISTINCT observed_date)"
        " FROM generic_facts WHERE source=? GROUP BY entity", (source,)).fetchall()
    if not rows:
        return None
    groups = {}
    for ent, first, last, days in rows:
        groups.setdefault(normalize_entity(ent), []).append(
            {"entity": ent, "first_seen": first, "last_seen": last,
             "capture_days_present": days})
    out = [{"normalized": key, "entities": sorted(v, key=lambda x: x["entity"]),
            "distinct_entities": len(v),
            "overlapping_dates": None}
           for key, v in groups.items() if len(v) > 1]
    for g in out:
        dates = []
        for e in g["entities"]:
            cur = con.execute(
                "SELECT DISTINCT observed_date FROM generic_facts WHERE source=? AND entity=?",
                (source, e["entity"]))
            dates.append({r[0] for r in cur.fetchall()})
        # Global intersection was wrong for three or more spellings: a-b and a_b
        # coexist on day 1, a-b and 'a b' on day 2, so the intersection of all
        # three is empty even though same-day coexistence demonstrably exists.
        best = 0
        for i in range(len(dates)):
            for j in range(i + 1, len(dates)):
                best = max(best, len(dates[i] & dates[j]))
        overlap = best
        g["max_same_day_overlap"] = best
        g["same_day_overlap_days"] = best
        # Fact only, no verdict. Same-day coexistence rules OUT a rename (a rename
        # cannot have both spellings on one capture), but it does NOT establish
        # identity: two genuinely different ids can normalize to the same key --
        # the collision this module documents. An earlier version exposed
        # 'likely_same_entity' here, which was an identity claim we cannot support.
        # "same_day" must mean "at least one PAIR coexisted", not "all spellings
        # coexisted": with three spellings a rename between B and C is still
        # possible even if A and B shared a date.
        g["overlap_kind"] = "same_day" if overlap else "disjoint"
        if overlap:
            g["overlap_scope"] = ("at least one pair of these spellings appeared on the "
                                  "same capture date; a rename between the others is not "
                                  "excluded")
            # per-pair evidence, because "the group overlaps" is not the same as
            # "every pair in the group overlaps"
            pairs = []
            for i in range(len(g["entities"])):
                for j in range(i + 1, len(g["entities"])):
                    shared = dates[i] & dates[j]
                    if shared:
                        pairs.append({"a": g["entities"][i]["entity"],
                                      "b": g["entities"][j]["entity"],
                                      "same_day_dates": sorted(shared)})
            g["pair_overlaps"] = pairs
        g["interpretation"] = (
            "at least one pair appears together on a capture date, so those two are "
            "not one-renamed-into-the-other; check each pair against its own "
            "same_day_dates before merging (the group may mix a rename with a collision)"
            if overlap else
            "the spellings never appear on the same date: consistent with a rename, "
            "but also with one entity leaving and another arriving")
    out.sort(key=lambda g: (-(g["overlap_kind"] == "same_day"), -g["distinct_entities"]))
    return {"source": source, "candidate_groups": len(out), "returned": len(out[:limit]),
            "truncated": len(out) > limit, "groups": out[:limit],
            "note": ("these are CANDIDATES, not verdicts: normalization strips case "
                     "and separators, so genuinely different ids can collide. "
                     "overlapping_dates > 0 only rules out a rename (both spellings "
                     "cannot be one thing renamed on the same day); it does not "
                     "establish identity. Compare field values before merging.")}


def resolve_entities(con, query, limit=20):
    """Find the same entity across every generic source, by normalized name."""
    qn = normalize_entity(query)
    if not qn:
        return None
    rows = con.execute(
        "SELECT source, entity, MIN(observed_date), MAX(observed_date),"
        " COUNT(DISTINCT observed_date) FROM generic_facts"
        " GROUP BY source, entity").fetchall()
    if not rows:
        return None
    matches = []
    for source, ent, first, last, days in rows:
        ne = normalize_entity(ent)
        if ne == qn:
            kind = "exact_normalized"
        elif qn in ne or ne in qn:
            kind = "substring_normalized"
        else:
            continue
        matches.append({"source": source, "entity": ent, "match": kind,
                        "first_seen": first, "last_seen": last,
                        "capture_days_present": days})
    matches.sort(key=lambda m: (m["match"] != "exact_normalized", m["source"], m["entity"]))
    counts_by_source = {}
    for m in matches:
        counts_by_source[m["source"]] = counts_by_source.get(m["source"], 0) + 1
    by_source = {}
    for m in matches[:limit]:
        by_source.setdefault(m["source"], []).append(m["entity"])
    return {"query": query, "normalized": qn, "matches": len(matches),
            "by_source": by_source,
            "by_source_counts": counts_by_source,
            "by_source_truncated": sum(counts_by_source.values()) > len(matches[:limit]),
            "results": matches[:limit],
            "note": ("matches are name-based only. Two ids that normalize the same "
                     "may be different things; two that look different may be the "
                     "same thing. Treat this as a lead, not a join.")}
