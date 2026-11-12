"""cross_check: the multi-source verification centerpiece.

A lone source is not verification. These tests pin that cross_check surfaces
agreement, disagreement and lone claims WITH provenance, and keeps the
disciplines (absent != zero, name match is a lead, caliber is not assumed).
"""
import os
import sys
import tempfile
import unittest

PROJ = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(PROJ, "src"))

from indiebiz_evidence import generic, store  # noqa: E402


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

    def test_conflict_is_surfaced_with_provenance(self):
        self.src("a", "id,price\nAcme,10\n")
        self.src("b", "id,price\nacme,99\n")
        r = generic.cross_check(self.con, "Acme")
        self.assertEqual(r["fields"]["price"]["verdict"], "differs")
        vals = {v["num"]: [s["source"] for s in v["sources"]] for v in r["fields"]["price"]["values"]}
        self.assertEqual(vals, {10.0: ["a"], 99.0: ["b"]})
        self.assertIn("note", r["fields"]["price"])

    def test_agreement_is_corroboration(self):
        self.src("a", "id,price\nAcme,10\n")
        self.src("b", "id,price\nACME,10\n")
        r = generic.cross_check(self.con, "acme")
        self.assertEqual(r["fields"]["price"]["verdict"], "agrees")
        self.assertEqual(r["fields"]["price"]["reported_by"], 2)

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
        # b must NOT appear as reporting stock=0 or stock=""
        self.assertEqual(len(stock["values"]), 1)

    def test_name_match_is_exact_normalized_not_fuzzy(self):
        self.src("a", "id,price\nAcme Widget,10\n")
        self.src("b", "id,price\nAcme Widgets,99\n")  # different thing, plural
        r = generic.cross_check(self.con, "Acme Widget")
        self.assertEqual(r["sources_compared"], ["a"])
        self.assertEqual(r["fields"]["price"]["verdict"], "single_source")

    def test_field_filter(self):
        self.src("a", "id,price,stock\nAcme,10,in_stock\n")
        self.src("b", "id,price,stock\nAcme,99,out\n")
        r = generic.cross_check(self.con, "Acme", field="price")
        self.assertEqual(list(r["fields"].keys()), ["price"])

    def test_no_match_returns_note(self):
        self.src("a", "id,price\nAcme,10\n")
        r = generic.cross_check(self.con, "Nonexistent")
        self.assertEqual(r["sources_compared"], [])
        self.assertIn("note", r)

    def test_different_dates_are_flagged(self):
        self.src("a", "id,price\nAcme,10\n", day="2099-01-01")
        self.src("b", "id,price\nAcme,99\n", day="2099-01-05")
        r = generic.cross_check(self.con, "Acme")
        self.assertTrue(any("different dates" in c for c in r["caveats"]))


if __name__ == "__main__":
    unittest.main()