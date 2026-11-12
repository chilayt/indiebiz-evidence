"""cross_check: multi-source verification, with the Codex-review regressions.

Each test pins a discipline: distinct-source counting (no fake corroboration),
provenance preserved (raw_ref + original text per observation), exact numeric
equality, current-vs-stale reporting, and coverage gaps made visible.
"""
import os
import sys
import tempfile
import unittest

PROJ = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(PROJ, "src"))

from indiebiz_evidence import generic, store  # noqa: E402


def obs_sources(entry):
    return sorted({o["source"] for v in entry["values"] for o in v["observations"]})


class TestCrossCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ibe-xcheck-")
        self.addCleanup(self.tmp.cleanup)
        self.con = store.connect(os.path.join(self.tmp.name, "x.db"))
        self.addCleanup(self.con.close)
        store.init_db(self.con)

    def src(self, name, body, day="2099-01-02"):
        d = os.path.join(self.tmp.name, name)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, day + ".csv"), "w", encoding="utf-8", newline="") as f:
            f.write(body)
        generic.import_path(self.con, name, d, verbose=False)

    def test_conflict_surfaced_with_provenance(self):
        self.src("a", "id,price\nAcme,10\n")
        self.src("b", "id,price\nacme,99\n")
        r = generic.cross_check(self.con, "Acme")
        e = r["fields"]["price"]
        self.assertEqual(e["verdict"], "differs")
        self.assertEqual(obs_sources(e), ["a", "b"])
        for v in e["values"]:
            for o in v["observations"]:
                self.assertTrue(o["raw_ref"], "every observation keeps raw_ref")

    def test_agreement_requires_same_value_and_text(self):
        self.src("a", "id,price\nAcme,10\n")
        self.src("b", "id,price\nACME,10\n")
        r = generic.cross_check(self.con, "acme")
        self.assertEqual(r["fields"]["price"]["verdict"], "agrees")
        self.assertEqual(r["fields"]["price"]["reported_by"], 2)

    def test_same_source_two_spellings_is_not_corroboration(self):
        # Codex P1: Acme + ACME in ONE source must not count as 2 agreeing sources
        self.src("a", "id,price\nAcme,10\nACME,10\n")
        r = generic.cross_check(self.con, "Acme")
        self.assertEqual(r["sources_compared"], ["a"])
        self.assertEqual(r["fields"]["price"]["verdict"], "single_source")
        self.assertIn("a", r["identity_ambiguity"])

    def test_raw_ref_and_original_text_preserved_per_observation(self):
        # Codex P1: 10% vs 10 must not fold text; both originals kept
        self.src("a", "id,rate\nAcme,10%\n")
        self.src("b", "id,rate\nAcme,10\n")
        r = generic.cross_check(self.con, "Acme")
        e = r["fields"]["rate"]
        self.assertEqual(e["verdict"], "numbers_match")
        texts = sorted(o["text"] for v in e["values"] for o in v["observations"])
        self.assertEqual(texts, ["10", "10%"])
        self.assertTrue(all(o["raw_ref"] for v in e["values"] for o in v["observations"]))

    def test_numeric_equality_is_exact_not_rounded(self):
        # Codex P2: 0 vs 4e-11 must NOT be merged by round(num,10)
        self.src("a", "id,v\nAcme,0\n")
        self.src("b", "id,v\nAcme,0.00000000004\n")
        r = generic.cross_check(self.con, "Acme")
        self.assertEqual(r["fields"]["v"]["verdict"], "differs")

    def test_stale_report_is_flagged_not_current(self):
        # Codex P1: entity last reported day1, source captured empty day2 -> not current
        self.src("a", "id,price\nAcme,10\n", day="2099-01-01")
        self.src("a", "id,price\n", day="2099-01-02")
        self.src("b", "id,price\nAcme,10\n", day="2099-01-01")
        self.src("b", "id,price\n", day="2099-01-02")
        r = generic.cross_check(self.con, "Acme")
        self.assertFalse(r["source_status"]["a"]["currently_reported"])
        self.assertTrue(any("not currently reported" in c for c in r["caveats"]))

    def test_single_source_is_a_lone_claim(self):
        self.src("a", "id,price\nAcme,10\n")
        r = generic.cross_check(self.con, "Acme")
        self.assertEqual(r["fields"]["price"]["verdict"], "single_source")

    def test_absent_field_is_not_zero(self):
        self.src("a", "id,price,stock\nAcme,10,in_stock\n")
        self.src("b", "id,price\nAcme,10\n")
        r = generic.cross_check(self.con, "Acme")
        stock = r["fields"]["stock"]
        self.assertEqual(stock["verdict"], "single_source")
        self.assertEqual(stock["not_reporting"], ["b"])

    def test_name_match_exact_normalized_not_fuzzy(self):
        self.src("a", "id,price\nAcme Widget,10\n")
        self.src("b", "id,price\nAcme Widgets,99\n")
        r = generic.cross_check(self.con, "Acme Widget")
        self.assertEqual(r["sources_compared"], ["a"])

    def test_specified_date_lists_uncovered_candidate_sources(self):
        # Codex P2: a candidate source with no capture on the date must be visible
        self.src("a", "id,price\nAcme,10\n", day="2099-01-02")
        self.src("b", "id,price\nAcme,10\n", day="2099-01-02")
        self.src("c", "id,price\nAcme,99\n", day="2099-01-01")
        r = generic.cross_check(self.con, "Acme", date="2099-01-02")
        self.assertIn("c", r["candidate_sources"])
        self.assertNotIn("c", r["sources_compared"])
        self.assertEqual(r["fields"]["price"]["not_reporting"], ["c"])

    def test_identity_anomalies_carried(self):
        self.src("a", "id,owner,price\nAcme,Alpha,10\n", day="2099-01-01")
        self.src("a", "id,owner,price\nAcme,Zulu,10\n", day="2099-01-02")
        generic.detect_generic(self.con, "a", config={"entity_column": "id",
                               "identity_fields": ["owner"]}, verbose=False)
        r = generic.cross_check(self.con, "Acme", field="price")
        self.assertTrue(r["identity_anomalies"])

    def test_no_match_returns_note(self):
        self.src("a", "id,price\nAcme,10\n")
        r = generic.cross_check(self.con, "Nonexistent")
        self.assertEqual(r["sources_compared"], [])
        self.assertIn("note", r)


if __name__ == "__main__":
    unittest.main()