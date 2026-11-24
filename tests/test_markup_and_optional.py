"""Two config-level guards driven by a real capture run:

1. text_contains_markup -- a declared text field that still carries markup was
   copied from a rendered page. That poisons identity comparison (the same person
   reads as two: "X" vs "[X](url)"), so it is reported once per field per capture.
2. optional_fields -- entity-specific columns (only listed items have a price) must
   not be reported as a permanent "partial drop", or the section becomes wallpaper.
"""
import os
import sys
import tempfile
import unittest

PROJ = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(PROJ, "src"))

from indiebiz_evidence import generic, store  # noqa: E402


class TestTextContainsMarkup(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ibe-markup-")
        self.addCleanup(self.tmp.cleanup)
        self.con = store.connect(os.path.join(self.tmp.name, "x.db"))
        self.addCleanup(self.con.close)
        store.init_db(self.con)

    def run_src(self, days, cfg, name="s"):
        d = os.path.join(self.tmp.name, name)
        os.makedirs(d, exist_ok=True)
        for day, body in days.items():
            with open(os.path.join(d, day + ".csv"), "w", encoding="utf-8", newline="") as f:
                f.write(body)
        generic.import_path(self.con, name, d, config=cfg, verbose=False)
        generic.detect_generic(self.con, name, config=cfg, verbose=False)

    def markup(self, name="s"):
        return self.con.execute(
            "SELECT observed_date, detail, severity FROM anomalies "
            "WHERE kind LIKE 'text_contains_markup%' AND substr(slug,1,?)=?",
            (len(name) + 1, name + ":")).fetchall()

    def test_flags_markdown_link_in_declared_field(self):
        cfg = {"entity_column": "entity", "identity_fields": ["owner"], "min_presence_days": 1}
        self.run_src({"2099-01-01": "entity,owner\na,[Ann](http://x/ann)\n"}, cfg)
        rows = self.markup()
        self.assertEqual(len(rows), 1)
        self.assertIn("raw markup", rows[0][1])

    def test_one_row_per_field_per_capture_not_per_entity(self):
        cfg = {"entity_column": "entity", "identity_fields": ["owner"], "min_presence_days": 1}
        self.run_src({"2099-01-01":
                      "entity,owner\na,[Ann](http://x/a)\nb,[Bob](http://x/b)\nc,[Cy](http://x/c)\n"},
                      cfg)
        rows = self.markup()
        self.assertEqual(len(rows), 1, "must aggregate at the source level")
        self.assertIn("3 of 3", rows[0][1])
        self.assertEqual(rows[0][2], "warn")

    def test_single_occurrence_is_info_not_warn(self):
        cfg = {"entity_column": "entity", "identity_fields": ["owner"], "min_presence_days": 1}
        self.run_src({"2099-01-01":
                      "entity,owner\na,[Ann](http://x/a)\nb,plain\nc,plain2\n"}, cfg)
        rows = self.markup()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][2], "info")

    def test_undeclared_field_not_checked(self):
        cfg = {"entity_column": "entity", "min_presence_days": 1}
        self.run_src({"2099-01-01": "entity,note\na,[Ann](http://x/ann)\n"}, cfg)
        self.assertEqual(self.markup(), [])

    def test_plain_text_with_ampersand_or_angle_not_flagged(self):
        cfg = {"entity_column": "entity", "identity_fields": ["owner"], "min_presence_days": 1}
        self.run_src({"2099-01-01":
                      "entity,owner\na,R&D Lab\nb,a < b and c > d\nc,Tom & Jerry\n"}, cfg)
        self.assertEqual(self.markup(), [])

    def test_html_tag_and_entity_detected(self):
        cfg = {"entity_column": "entity", "identity_fields": ["owner"], "min_presence_days": 1}
        self.run_src({"2099-01-01":
                      "entity,owner\na,<b>Ann</b>\nb,Tom&nbsp;Jerry\nc,[Cy](http://x/c)\n"}, cfg)
        rows = self.markup()
        self.assertEqual(len(rows), 1)
        self.assertIn("3 of 3", rows[0][1])


class TestOptionalFields(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ibe-optional-")
        self.addCleanup(self.tmp.cleanup)
        self.con = store.connect(os.path.join(self.tmp.name, "x.db"))
        self.addCleanup(self.con.close)
        store.init_db(self.con)

    def run_src(self, cfg):
        d = os.path.join(self.tmp.name, "s")
        os.makedirs(d, exist_ok=True)
        files = {
            "2099-01-01": "entity,price,ask\na,10,99\nb,20,\n",
            "2099-01-02": "entity,price,ask\na,10,99\nb,20,\n",
            # a loses ask, b keeps it: a genuine PARTIAL drop (not a whole-column loss)
            "2099-01-03": "entity,price,ask\na,10,\nb,20,55\n",
        }
        for day, body in files.items():
            with open(os.path.join(d, day + ".csv"), "w", encoding="utf-8", newline="") as f:
                f.write(body)
        generic.import_path(self.con, "s", d, config=cfg, verbose=False)
        generic.detect_generic(self.con, "s", config=cfg, verbose=False)
        return generic.field_coverage(self.con, "s")

    def test_declared_optional_is_not_partial_drop(self):
        cov = self.run_src({"entity_column": "entity", "optional_fields": ["ask"],
                            "min_presence_days": 3})
        ask = [f for f in cov["fields"] if f["field"] == "ask"][0]
        self.assertEqual(ask["status"], "optional")
        self.assertIn("OPTIONAL", ask["verdict"])
        ev = cov["schema_events"]
        self.assertEqual([x["field"] for x in ev["fields_partially_missing_on_latest"]], [])
        self.assertIn("ask", [x["field"] for x in ev["optional_fields_missing_on_latest"]])

    def test_undeclared_field_still_reports_partial_drop(self):
        cov = self.run_src({"entity_column": "entity", "min_presence_days": 3})
        ask = [f for f in cov["fields"] if f["field"] == "ask"][0]
        self.assertEqual(ask["status"], "partial_drop")
        self.assertIn("ask", [x["field"] for x in
                              cov["schema_events"]["fields_partially_missing_on_latest"]])

    def test_optional_does_not_hide_a_full_disappearance(self):
        # declaring a field optional must not excuse a column that vanished entirely
        d = os.path.join(self.tmp.name, "s2")
        os.makedirs(d, exist_ok=True)
        for day, body in {"2099-01-01": "entity,ask\na,1\n",
                          "2099-01-02": "entity,ask\na,1\n",
                          "2099-01-03": "entity\na\n"}.items():
            with open(os.path.join(d, day + ".csv"), "w", encoding="utf-8", newline="") as f:
                f.write(body)
        cfg = {"entity_column": "entity", "optional_fields": ["ask"], "min_presence_days": 3}
        generic.import_path(self.con, "s2", d, config=cfg, verbose=False)
        generic.detect_generic(self.con, "s2", config=cfg, verbose=False)
        cov = generic.field_coverage(self.con, "s2")
        ask = [f for f in cov["fields"] if f["field"] == "ask"][0]
        self.assertEqual(ask["status"], "optional")
        self.assertEqual(ask["dropped_on_latest"], 1)


if __name__ == "__main__":
    unittest.main()