"""Entity alignment: propose candidates (never auto-link), confirm a human decision,
and cross_check via a stored canonical_id. The decision stays a human's.
"""
import os
import sys
import tempfile
import unittest

PROJ = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(PROJ, "src"))

from indiebiz_evidence import generic, store  # noqa: E402

CFG = {"entity_column": "entity", "min_presence_days": 1}


class TestEntityLinks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ibe-links-")
        self.addCleanup(self.tmp.cleanup)
        self.con = store.connect(os.path.join(self.tmp.name, "x.db"))
        self.addCleanup(self.con.close)
        store.init_db(self.con)

    def import_src(self, name, days):
        d = os.path.join(self.tmp.name, name)
        os.makedirs(d, exist_ok=True)
        for day, body in days.items():
            with open(os.path.join(d, day + ".csv"), "w", encoding="utf-8", newline="") as f:
                f.write(body)
        generic.import_path(self.con, name, d, config=CFG, verbose=False)

    def links_count(self):
        return self.con.execute("SELECT COUNT(*) FROM entity_links").fetchone()[0]

    def test_propose_never_links(self):
        self.import_src("a", {"2099-01-01": "entity,price\nwidget,10\n"})
        self.import_src("b", {"2099-01-01": "entity,price\nwidget,10\n"})
        res = generic.propose_entity_links(self.con, "widget")
        self.assertEqual(len(res["candidates"]), 2)
        self.assertEqual(res["field_evidence"]["price"]["status"], "agrees")
        self.assertEqual(self.links_count(), 0, "propose must NOT create any link")
        self.assertIn("CANDIDATES only", res["note"])

    def test_propose_shows_conflict_as_evidence(self):
        self.import_src("a", {"2099-01-01": "entity,price\nwidget,10\n"})
        self.import_src("b", {"2099-01-01": "entity,price\nwidget,99\n"})
        res = generic.propose_entity_links(self.con, "widget")
        self.assertEqual(res["field_evidence"]["price"]["status"], "differs")
        self.assertEqual(self.links_count(), 0)

    def test_confirm_stores_human_decision(self):
        self.import_src("a", {"2099-01-01": "entity,price\nwidget,10\n"})
        r = generic.confirm_entity_link(self.con, "a", "widget", "thing-1",
                                        decided_by="alice", evidence="same product page")
        self.assertEqual(r["canonical_id"], "thing-1")
        self.assertEqual(r["decided_by"], "alice")
        self.assertTrue(r["decided_at"])
        self.assertEqual(self.links_count(), 1)

    def test_confirm_refuses_phantom(self):
        self.import_src("a", {"2099-01-01": "entity,price\nwidget,10\n"})
        r = generic.confirm_entity_link(self.con, "a", "no-such-entity", "thing-1")
        self.assertIn("error", r)
        self.assertEqual(self.links_count(), 0)

    def test_confirm_refuses_empty_canonical(self):
        self.import_src("a", {"2099-01-01": "entity,price\nwidget,10\n"})
        r = generic.confirm_entity_link(self.con, "a", "widget", "  ")
        self.assertIn("error", r)
        self.assertEqual(self.links_count(), 0)

    def test_cross_check_canonical_links_different_names(self):
        self.import_src("a", {"2099-01-01": "entity,price\nwidget,10\n"})
        self.import_src("c", {"2099-01-01": "entity,price\ngadget,10\n"})
        # names differ, so name-based cross_check finds only one source each
        self.assertEqual(len(generic.cross_check(self.con, "widget")["sources_compared"]), 1)
        generic.confirm_entity_link(self.con, "a", "widget", "thing-1")
        generic.confirm_entity_link(self.con, "c", "gadget", "thing-1")
        res = generic.cross_check(self.con, canonical_id="thing-1")
        self.assertEqual(sorted(res["sources_compared"]), ["a", "c"])
        self.assertEqual(res["fields"]["price"]["verdict"], "agrees")
        self.assertIn("confirmed entity_links", res["match_basis"])

    def test_cross_check_canonical_detects_disagreement(self):
        self.import_src("a", {"2099-01-01": "entity,price\nwidget,10\n"})
        self.import_src("c", {"2099-01-01": "entity,price\ngadget,99\n"})
        generic.confirm_entity_link(self.con, "a", "widget", "thing-1")
        generic.confirm_entity_link(self.con, "c", "gadget", "thing-1")
        res = generic.cross_check(self.con, canonical_id="thing-1")
        self.assertEqual(res["fields"]["price"]["verdict"], "differs")

    def test_cross_check_unknown_canonical(self):
        self.import_src("a", {"2099-01-01": "entity,price\nwidget,10\n"})
        res = generic.cross_check(self.con, canonical_id="nope")
        self.assertEqual(res["sources_compared"], [])
        self.assertIn("confirm_entity_link", res["note"])

    def test_list_groups_by_canonical(self):
        self.import_src("a", {"2099-01-01": "entity,price\nwidget,10\n"})
        self.import_src("c", {"2099-01-01": "entity,price\ngadget,10\n"})
        generic.confirm_entity_link(self.con, "a", "widget", "thing-1")
        generic.confirm_entity_link(self.con, "c", "gadget", "thing-1")
        res = generic.list_entity_links(self.con)
        self.assertEqual(res["canonical_ids"], 1)
        self.assertEqual(res["links"], 2)
        self.assertEqual(len(res["groups"]["thing-1"]), 2)

    def test_reconfirm_replaces(self):
        self.import_src("a", {"2099-01-01": "entity,price\nwidget,10\n"})
        generic.confirm_entity_link(self.con, "a", "widget", "thing-1")
        generic.confirm_entity_link(self.con, "a", "widget", "thing-2")
        self.assertEqual(self.links_count(), 1)
        res = generic.list_entity_links(self.con)
        self.assertIn("thing-2", res["groups"])


if __name__ == "__main__":
    unittest.main()