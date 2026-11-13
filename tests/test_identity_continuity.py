"""Identity-continuity hint on cumulative regression (Codex-reviewed design).

A hint, never a verdict: appended to monotonic_regression.detail only when the
source enables it, identity fields are declared, and the entity has no usable
identity value anywhere up to the regression capture. It must NOT create an
identity boundary, suppress value_swing, or change diff/cross-source behavior.
"""
import os
import sys
import tempfile
import unittest

PROJ = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(PROJ, "src"))

from indiebiz_evidence import generic, store  # noqa: E402


def cfg(hint=True, ident=("founder",)):
    return {"entity_column": "entity", "monotonic_fields": ["alltime"],
            "identity_fields": list(ident), "identity_continuity_hint": hint,
            "swing_fields": [], "min_presence_days": 1}


class TestIdentityContinuityHint(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ibe-ich-")
        self.addCleanup(self.tmp.cleanup)
        self.con = store.connect(os.path.join(self.tmp.name, "x.db"))
        self.addCleanup(self.con.close)
        store.init_db(self.con)

    def run_src(self, name, days, config):
        d = os.path.join(self.tmp.name, name)
        os.makedirs(d, exist_ok=True)
        for day, body in days.items():
            with open(os.path.join(d, day + ".csv"), "w", encoding="utf-8", newline="") as f:
                f.write(body)
        generic.import_path(self.con, name, d, config=config, verbose=False)
        generic.detect_generic(self.con, name, config=config, verbose=False)

    def reg(self, name, ent):
        return self.con.execute(
            "SELECT kind, detail FROM anomalies WHERE slug=? AND kind LIKE 'monotonic_regression%'",
            (name + ":" + ent,)).fetchall()

    def test_hint_appended_when_identity_always_empty(self):
        self.run_src("s", {
            "2099-01-01": "entity,alltime,founder\nA,1000,\n",
            "2099-01-02": "entity,alltime,founder\nA,200,\n",
        }, cfg(hint=True))
        rows = self.reg("s", "A")
        self.assertEqual(len(rows), 1)
        self.assertIn("identity continuity cannot be verified", rows[0][1])
        self.assertIn("NOT confirmed", rows[0][1])
        self.assertIn("2099-01-01 -> 2099-01-02", rows[0][1])

    def test_no_hint_when_disabled(self):
        self.run_src("s", {
            "2099-01-01": "entity,alltime,founder\nA,1000,\n",
            "2099-01-02": "entity,alltime,founder\nA,200,\n",
        }, cfg(hint=False))
        rows = self.reg("s", "A")
        self.assertEqual(len(rows), 1)
        self.assertNotIn("identity continuity", rows[0][1])

    def test_no_hint_when_identity_fields_not_declared(self):
        self.run_src("s", {
            "2099-01-01": "entity,alltime\nA,1000\n",
            "2099-01-02": "entity,alltime\nA,200\n",
        }, cfg(hint=True, ident=()))
        rows = self.reg("s", "A")
        self.assertEqual(len(rows), 1)
        self.assertNotIn("identity continuity", rows[0][1])

    def test_no_hint_if_any_identity_field_ever_valid(self):
        self.run_src("s", {
            "2099-01-01": "entity,alltime,founder,country\nA,1000,,US\n",
            "2099-01-02": "entity,alltime,founder,country\nA,200,,\n",
        }, cfg(hint=True, ident=("founder", "country")))
        rows = self.reg("s", "A")
        self.assertEqual(len(rows), 1)
        self.assertNotIn("identity continuity", rows[0][1])

    def test_no_hint_if_identity_valid_then_recently_empty(self):
        self.run_src("s", {
            "2099-01-01": "entity,alltime,founder\nA,1000,zoe\n",
            "2099-01-02": "entity,alltime,founder\nA,900,\n",
            "2099-01-03": "entity,alltime,founder\nA,200,\n",
        }, cfg(hint=True))
        rows = self.reg("s", "A")
        self.assertTrue(rows)
        for _k, detail in rows:
            self.assertNotIn("identity continuity", detail)

    def test_hint_survives_identity_appearing_later(self):
        self.run_src("s", {
            "2099-01-01": "entity,alltime,founder\nA,1000,\n",
            "2099-01-02": "entity,alltime,founder\nA,200,\n",
            "2099-01-03": "entity,alltime,founder\nA,250,zoe\n",
        }, cfg(hint=True))
        rows = self.reg("s", "A")
        self.assertEqual(len(rows), 1)
        self.assertIn("identity continuity", rows[0][1])

    def test_hint_does_not_create_identity_boundary(self):
        self.run_src("s", {
            "2099-01-01": "entity,alltime,founder,price\nA,1000,,10\n",
            "2099-01-02": "entity,alltime,founder,price\nA,200,,90\n",
        }, cfg(hint=True))
        kinds = [r[0] for r in self.con.execute("SELECT kind FROM anomalies WHERE slug='s:A'")]
        self.assertFalse([k for k in kinds if k.startswith("identity_change")])
        diff = generic.diff_snapshots(self.con, "s")
        self.assertEqual(diff.get("identity_boundaries", {}), {})

    def test_no_hint_on_increase_or_tolerance(self):
        self.run_src("s", {
            "2099-01-01": "entity,alltime,founder\nA,1000,\n",
            "2099-01-02": "entity,alltime,founder\nA,2000,\n",
        }, cfg(hint=True))
        self.assertEqual(self.reg("s", "A"), [])

    def test_rerun_no_duplicate(self):
        days = {
            "2099-01-01": "entity,alltime,founder\nA,1000,\n",
            "2099-01-02": "entity,alltime,founder\nA,200,\n",
        }
        self.run_src("s", days, cfg(hint=True))
        generic.detect_generic(self.con, "s", config=cfg(hint=True), verbose=False)
        rows = self.reg("s", "A")
        self.assertEqual(len(rows), 1)


if __name__ == "__main__":
    unittest.main()