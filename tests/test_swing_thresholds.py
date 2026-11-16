"""Per-field swing thresholds: volatile fields get a higher bar so they do not
drown the signals that matter. Config-only noise control, no new detector.
"""
import os
import sys
import tempfile
import unittest

PROJ = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(PROJ, "src"))

from indiebiz_evidence import generic, store  # noqa: E402


def cfg(**kw):
    base = {"entity_column": "entity", "swing_fields": ["MRR", "l24h"],
            "min_presence_days": 1}
    base.update(kw)
    return base


class TestSwingThresholds(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ibe-swingthr-")
        self.addCleanup(self.tmp.cleanup)
        self.con = store.connect(os.path.join(self.tmp.name, "x.db"))
        self.addCleanup(self.con.close)
        store.init_db(self.con)

    def run_days(self, c, d1="entity,MRR,l24h\na,100,10\n", d2="entity,MRR,l24h\na,150,100\n"):
        d = os.path.join(self.tmp.name, "s")
        os.makedirs(d, exist_ok=True)
        for day, body in (("2099-01-01", d1), ("2099-01-02", d2)):
            with open(os.path.join(d, day + ".csv"), "w", encoding="utf-8", newline="") as f:
                f.write(body)
        generic.import_path(self.con, "s", d, config=c, verbose=False)
        generic.detect_generic(self.con, "s", config=c, verbose=False)

    def kinds(self):
        return {r[0]: r[1] for r in self.con.execute(
            "SELECT kind, detail FROM anomalies WHERE slug='s:a'")}

    def test_high_threshold_silences_volatile_field_only(self):
        # MRR +50% and l24h +200%: default flags both; l24h override 3.0 flags only MRR
        self.run_days(cfg(swing_thresholds={"l24h": 3.0}),
                      d2="entity,MRR,l24h\na,150,30\n")
        k = self.kinds()
        self.assertIn("value_swing:MRR", k)
        self.assertNotIn("value_swing:l24h", k)

    def test_volatile_field_still_flagged_when_extreme(self):
        self.run_days(cfg(swing_thresholds={"l24h": 3.0}),
                      d2="entity,MRR,l24h\na,150,1000\n")  # +9900%
        self.assertIn("value_swing:l24h", self.kinds())

    def test_lower_threshold_catches_small_move(self):
        self.run_days(cfg(swing_thresholds={"MRR": 0.05}),
                      d2="entity,MRR,l24h\na,110,10\n")  # MRR +10%
        self.assertIn("value_swing:MRR", self.kinds())

    def test_default_behavior_unchanged_without_overrides(self):
        self.run_days(cfg())
        k = self.kinds()
        self.assertIn("value_swing:MRR", k)
        self.assertIn("value_swing:l24h", k)

    def test_detail_reports_the_field_threshold(self):
        self.run_days(cfg(swing_thresholds={"l24h": 3.0}),
                      d2="entity,MRR,l24h\na,150,1000\n")
        self.assertIn("threshold 300%", self.kinds()["value_swing:l24h"])

    def test_override_does_not_touch_monotonic_rule(self):
        c = cfg(monotonic_fields=["alltime"], swing_fields=["MRR", "l24h", "alltime"],
                swing_thresholds={"alltime": 99.0})
        self.run_days(c, d1="entity,MRR,l24h,alltime\na,100,10,5000\n",
                      d2="entity,MRR,l24h,alltime\na,100,10,4000\n")
        k = self.kinds()
        self.assertIn("monotonic_regression:alltime", k)
        self.assertNotIn("value_swing:alltime", k)


if __name__ == "__main__":
    unittest.main()