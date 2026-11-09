"""Small helpers shared by the generic engine (and by vertical add-ons).

They live here rather than in the modules that originally needed them, so the
generic engine carries no import edge into a vertical layer.
"""
from __future__ import annotations

import datetime as dt
import re

_WS = re.compile(r"\s+")


def sync_lag_hours(synced_at, observed_date):
    """Approximate lag between a source timestamp and the capture date.

    Computed against 12:00 UTC of the capture date, so the number is explicitly
    approximate -- callers must say so (docs/PATTERNS.md discipline 3).
    """
    if not synced_at:
        return None
    try:
        s = str(synced_at).replace("Z", "+00:00")
        t = dt.datetime.fromisoformat(s)
        if t.tzinfo is None:
            t = t.replace(tzinfo=dt.timezone.utc)
        noon = dt.datetime.fromisoformat(str(observed_date) + "T12:00:00+00:00")
        return round((noon - t).total_seconds() / 3600.0, 2)
    except Exception:
        return None


def norm_name(value):
    return _WS.sub(" ", str(value or "").strip().lower())


def likely_rename(a, b):
    """True when one label is essentially contained in the other.

    'Acme Labs (old handle)' -> 'Acme Labs' is a rename, not a different actor. This is
    only ever a CANDIDATE: the caller reports it as info and never suppresses
    comparisons on the strength of it alone.
    """
    na, nb = norm_name(a), norm_name(b)
    if not na or not nb:
        return False
    return na in nb or nb in na
