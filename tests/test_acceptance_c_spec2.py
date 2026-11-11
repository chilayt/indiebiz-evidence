"""Independent C03-C08 acceptance tests from the frozen C-SPEC.

Same rules as test_acceptance_c.py: inputs are literal synthetic CSV built by
the test, expected values are written from the spec, and no production helper
computes an expectation.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

PROJ = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(PROJ, "src"))

from indiebiz_evidence import generic, store  # noqa: E402


class AcceptanceBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ibe-c-spec-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.con = store.connect(str(self.root / "a.db"))
        self.addCleanup(self.con.close)
        store.init_db(self.con)

    def import_csv(self, source, snapshots, config=None, allow_empty_replace=False):
        folder = self.root / source
        folder.mkdir(exist_ok=True)
        for day, text in snapshots.items():
            with (folder / (day + ".csv")).open("w", encoding="utf-8", newline="") as fh:
                fh.write(text)
        if config:
            with (folder / "source.json").open("w", encoding="utf-8") as fh:
                json.dump(config, fh)
        return generic.import_path(self.con, source, str(folder), verbose=False,
                                   allow_empty_replace=allow_empty_replace)

    def alerts(self, source):
        return self.con.execute(
            "SELECT slug, kind, observed_date FROM anomalies WHERE substr(slug,1,?)=? "
            "ORDER BY observed_date, slug, kind", (len(source) + 1, source + ":")).fetchall()


class TestC03IdentityBoundary(AcceptanceBase):
    """C03: a change across an identity boundary must not be reported as growth."""

    def test_c03_no_growth_across_boundary(self):
        source = "c03"
        self.import_csv(source, {
            "2099-03-01": "id,owner,price\nX,ALPHA,10\n",
            # owner changes AND price is absent on the same day
            "2099-03-02": "id,owner\nX,ZULU\n",
            "2099-03-03": "id,owner,price\nX,ZULU,900\n",
        }, {"entity_column": "id", "identity_fields": ["owner"],
            "swing_fields": ["price"], "swing_threshold": 0.30})
        generic.detect_generic(self.con, source, verbose=False)
        kinds = [k for _s, k, _d in self.alerts(source)]
        self.assertIn("identity_change:owner", kinds, "the boundary itself must be visible")
        self.assertFalse([k for k in kinds if k.startswith("value_swing")],
                         "no price growth may be computed across an identity boundary")

        # Diff the window that actually CROSSES the boundary (03-01 -> 03-03). The
        # default (last two dates) would not cross it. Field changes are nested under
        # each entity's "changes"; the old assertion looked for "field" at the entity
        # level and never ran (Codex 2026-11-11 caught the vacuous test).
        diff = generic.diff_snapshots(self.con, source,
                                      from_date="2099-03-01", to_date="2099-03-03")
        self.assertEqual(diff["from"], "2099-03-01")
        self.assertEqual(diff["to"], "2099-03-03")
        price_changes = [fc for ent in diff.get("changed", [])
                         for fc in ent.get("changes", []) if fc.get("field") == "price"]
        self.assertTrue(price_changes, "the price change across the boundary must be present")
        for fc in price_changes:
            self.assertIsNone(fc.get("delta_pct"),
                              "delta_pct must be null when the window spans an identity boundary")
        crossed = [ent for ent in diff.get("changed", []) if ent.get("across_identity_boundary")]
        self.assertTrue(crossed, "the entity must be flagged as crossing an identity boundary")
        self.assertIn("2099-03-02", crossed[0]["across_identity_boundary"])


class TestC04GapSpan(AcceptanceBase):
    """C04: a change across a 30-day gap must state the real span."""

    def test_c04_span_is_real(self):
        source = "c04"
        self.import_csv(source, {
            "2099-04-01": "id,price\nA,10\n",
            "2099-04-02": "id,price\nA,11\n",
            "2099-04-03": "id,price\nA,12\n",
            "2099-05-03": "id,price\nA,40\n",
        }, {"entity_column": "id", "swing_fields": ["price"], "swing_threshold": 0.30})
        generic.detect_generic(self.con, source, verbose=False)
        diff = generic.diff_snapshots(self.con, source)
        self.assertEqual(diff["from"], "2099-04-03")
        self.assertEqual(diff["to"], "2099-05-03")
        self.assertEqual(diff["span_days"], 30, "the span must be the real distance")
        self.assertIn("cadence_note", diff, "a 30-day jump over a daily cadence needs saying")
        self.assertIn("30", str(diff["cadence_note"]))
        # every change entry must carry the same real span, not a nominal 1 day
        spans = {c.get("span_days") for c in diff.get("changed", [])}
        if spans:
            self.assertEqual(spans, {30}, "per-change span must also be the real distance")


class TestC05EmptySnapshot(AcceptanceBase):
    """C05: an empty snapshot, a parse failure and no capture are different things.

    A dated empty export is a capture that produced nothing: it must appear on the
    timeline, and re-importing a date as empty must clear that date's old facts
    (the same REPLACE semantics as a non-empty re-import). Clearing existing facts
    is destructive, so it must be warned, never silent.
    """

    def test_c05a_new_empty_capture_leaves_a_trace(self):
        source = "c05a"
        self.import_csv(source, {"2099-06-01": "id,price\nA,10\n"})
        # a second capture that produced no facts at all (header only)
        self.import_csv(source, {"2099-06-02": "id,price\n"})
        self.assertEqual(generic._source_dates(self.con, source),
                         ["2099-06-01", "2099-06-02"],
                         "a capture that imported nothing must still be on the timeline")

    def test_c05b_reimport_as_empty_clears_old_facts(self):
        source = "c05b"
        self.import_csv(source, {"2099-06-01": "id,price\nA,10\nB,20\n"})
        # DEFAULT: a zero-fact re-import of a date that has facts is REFUSED, because
        # an empty export is usually a broken scraper. Old facts are kept (C-SPEC
        # allows "clear OR explicitly refuse"; Codex 2026-11-11 chose refuse-by-default).
        stats = self.import_csv(source, {"2099-06-01": "id,price\n"})
        left = self.con.execute(
            "SELECT COUNT(*) FROM generic_facts WHERE source=?", (source,)).fetchone()[0]
        self.assertEqual(left, 2, "default must refuse the destructive empty replace and keep facts")
        self.assertEqual(stats["refused_empty_replace"], 1)
        self.assertTrue(any("refused" in w for w in stats["warnings"]),
                        "the refusal must be reported, not silent")
        # EXPLICIT --allow-empty-replace: now the clear happens, and it is warned.
        stats2 = self.import_csv(source, {"2099-06-01": "id,price\n"}, allow_empty_replace=True)
        left2 = self.con.execute(
            "SELECT COUNT(*) FROM generic_facts WHERE source=?", (source,)).fetchone()[0]
        self.assertEqual(left2, 0, "with --allow-empty-replace the old facts are cleared")
        self.assertTrue(any("cleared" in w for w in stats2["warnings"]),
                        "the destructive clear must be warned, not silent")

    def test_c05c_empty_latest_capture_visible_in_list_sources(self):
        # A new empty capture must not hide behind the last date that had facts:
        # list_sources must expose latest_capture_date separately (Codex 2026-11-11).
        source = "c05c"
        self.import_csv(source, {"2099-06-01": "id,price\nA,10\n"})
        self.import_csv(source, {"2099-06-02": "id,price\n"})
        info = {s["source"]: s for s in generic.list_sources(self.con)}[source]
        self.assertEqual(info["latest_fact_date"], "2099-06-01")
        self.assertEqual(info["latest_capture_date"], "2099-06-02")
        self.assertTrue(info["latest_capture_empty"])


class TestC06ReimportConsistency(AcceptanceBase):
    """C06: re-importing a corrected snapshot leaves no stale field and is idempotent."""

    def test_c06_no_stale_field_and_idempotent(self):
        source = "c06"
        self.import_csv(source, {"2099-07-01": "id,price,note\nA,10,hello\n"})
        # corrected export: price changed, note column gone
        self.import_csv(source, {"2099-07-01": "id,price\nA,11\n"})
        rows = self.con.execute(
            "SELECT field, num FROM generic_facts WHERE source=? ORDER BY field",
            (source,)).fetchall()
        self.assertEqual(rows, [("price", 11.0)], "the removed field must not survive")
        # repeat the import and the detection: the result must not drift
        before = self.alerts(source)
        self.import_csv(source, {"2099-07-01": "id,price\nA,11\n"})
        generic.detect_generic(self.con, source, verbose=False)
        first = self.alerts(source)
        generic.detect_generic(self.con, source, verbose=False)
        self.assertEqual(self.alerts(source), first, "repeated detection must be stable")
        self.assertEqual(first, before)


class TestC07EncodingAndProvenance(AcceptanceBase):
    """C07: a GBK export with two different Chinese ids stays two entities, and every
    fact can be traced back to the file it came from.
    """

    def test_c07_gbk_entities_and_raw_ref(self):
        source = "c07"
        folder = self.root / "中文 目录"
        folder.mkdir(parents=True, exist_ok=True)
        body = "id,price\n商品甲,10\n商品乙,20\n"
        with (folder / "2099-08-01.csv").open("w", encoding="gbk", newline="") as fh:
            fh.write(body)
        stats = generic.import_path(self.con, source, str(folder), verbose=False)
        self.assertEqual(stats["errors"], 0)
        names = sorted(r[0] for r in self.con.execute(
            "SELECT DISTINCT entity FROM generic_facts WHERE source=?", (source,)))
        self.assertEqual(names, ["商品乙", "商品甲"], "two ids must stay two entities")
        facts = self.con.execute(
            "SELECT entity, num, raw_ref FROM generic_facts WHERE source=? ORDER BY entity",
            (source,)).fetchall()
        self.assertEqual([(e, n) for e, n, _r in facts], [("商品乙", 20.0), ("商品甲", 10.0)])
        for _e, _n, raw_ref in facts:
            self.assertTrue(raw_ref, "every fact must carry a raw_ref")
            self.assertTrue(os.path.exists(raw_ref), "raw_ref must point at a real file")
            self.assertIn("中文 目录", raw_ref)


class TestC08IsolationAndErrors(AcceptanceBase):
    """C08: similarly named sources stay separate, and an uncaptured date errors."""

    def test_c08_sources_do_not_mix(self):
        self.import_csv("shop", {"2099-09-01": "id,v\na,1\n"})
        self.import_csv("workshop", {"2099-09-09": "id,v\nb,2\n"})
        self.assertEqual(generic._source_dates(self.con, "shop"), ["2099-09-01"])
        self.assertEqual(generic._source_dates(self.con, "workshop"), ["2099-09-09"])
        # shop has a single capture, so it must degrade explicitly rather than
        # borrow workshop's later date and pretend there are two snapshots
        diff = generic.diff_snapshots(self.con, "shop")
        self.assertEqual(diff["to"], "2099-09-01")
        self.assertIsNone(diff["from"])
        self.assertIn("only one capture date", diff["note"])
        other = generic.diff_snapshots(self.con, "workshop")
        self.assertEqual(other["to"], "2099-09-09")

    def test_c08_uncaptured_date_errors(self):
        self.import_csv("c08", {"2099-10-01": "id,v\na,1\n"})
        result = generic.search_records(self.con, "c08", date="2099-10-05")
        self.assertIn("error", result, "a missing capture is not an empty snapshot")
        self.assertIn("not a capture date", result["error"])
        self.assertEqual(result["known_dates"], ["2099-10-01"])


if __name__ == "__main__":
    unittest.main()