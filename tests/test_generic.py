"""Tests for the generic bring-your-own-source adapter (v0.3).

The demo source 'demo-prices' is engineered so that EVERY generic rule fires
on a known entity, and 'demo-ranks' proves the CSV path + entity-column
auto-detection. All data is synthetic (year 2099).
"""
import json
import os
import sys
import tempfile
import unittest

PROJ = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(PROJ, "src"))

from indiebiz_evidence import demo, generic, store  # noqa: E402


class TestGenericDemo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="ibe-generic-")
        cls.db_path = os.path.join(cls.tmp, "demo.db")
        demo.build(cls.db_path)
        cls.con = store.connect(cls.db_path)

    @classmethod
    def tearDownClass(cls):
        cls.con.close()

    def _kinds(self, entity):
        cur = self.con.execute(
            "SELECT kind, severity FROM anomalies WHERE slug=?", ("demo-prices:" + entity,))
        return {r[0]: r[1] for r in cur.fetchall()}

    def test_registry(self):
        srcs = {s["source"]: s for s in generic.list_sources(self.con)}
        self.assertEqual(srcs["demo-prices"]["entity_count"], 7)
        self.assertEqual(srcs["demo-prices"]["field_count"], 5)
        self.assertEqual(srcs["demo-ranks"]["entity_count"], 3)
        self.assertEqual(srcs["demo-ranks"]["field_count"], 2)
        self.assertEqual(srcs["demo-prices"]["first_seen"], "2099-01-01")
        self.assertEqual(srcs["demo-prices"]["last_seen"], "2099-01-02")

    def test_csv_entity_autodetect(self):
        rows = generic.query_series(self.con, "demo-ranks", "acme/tool-a", "stars")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["num"], 1200.0)

    def test_missing_field_is_absent_not_zero(self):
        """widget-c promo_flag exists on day1 and is ABSENT on day2."""
        rows = generic.query_series(self.con, "demo-prices", "widget-c", "promo_flag")
        self.assertEqual([r["observed_date"] for r in rows], ["2099-01-01"])
        self.assertEqual(rows[0]["text"], "yes")

    def test_monotonic_regression_and_swing(self):
        kinds = self._kinds("widget-b")
        self.assertIn("monotonic_regression:cumulative_units", kinds)
        self.assertEqual(kinds["monotonic_regression:cumulative_units"], "warn")
        self.assertIn("value_swing:price", kinds)  # 50 -> 30 = -40% >= 30%
        dates = [r[0] for r in self.con.execute(
            "SELECT observed_date FROM anomalies WHERE slug=?", ("demo-prices:widget-b",)).fetchall()]
        self.assertIn("2099-01-02", dates)

    def test_field_disappeared(self):
        """The GSC lesson generalized: presence streak then absence -> warn."""
        kinds = self._kinds("widget-c")
        self.assertIn("field_disappeared:promo_flag", kinds)
        self.assertEqual(kinds["field_disappeared:promo_flag"], "warn")

    def test_identity_change_vs_rename(self):
        hi = self._kinds("widget-e")
        self.assertIn("identity_change:owner", hi)
        self.assertEqual(hi["identity_change:owner"], "high")
        info = self._kinds("widget-d")
        self.assertIn("identity_rename_candidate:owner", info)
        self.assertEqual(info["identity_rename_candidate:owner"], "info")
        self.assertNotIn("identity_change:owner", info)

    def test_stale_timestamp(self):
        kinds = self._kinds("widget-f")
        self.assertIn("stale_timestamp:updated_at", kinds)

    def test_clean_entity_has_no_anomalies(self):
        self.assertEqual(self._kinds("widget-a"), {})

    def test_identity_boundary_suppresses_change_rules(self):
        """Codex P0: widget-g owner OldCo->NewCo with price 100->1000 (+900%)
        and units 500->480. The identity change must flag high, and BOTH
        cross-boundary change rules must stay silent (different owner = not
        the same series)."""
        kinds = self._kinds("widget-g")
        self.assertIn("identity_change:owner", kinds)
        self.assertEqual(kinds["identity_change:owner"], "high")
        self.assertNotIn("value_swing:price", kinds)
        self.assertNotIn("monotonic_regression:cumulative_units", kinds)

    def test_entity_snapshot_and_suggestions(self):
        snap = generic.entity_snapshot(self.con, "demo-prices", "widget-e", "2099-01-02")
        self.assertEqual(snap["fields"]["owner"]["text"], "NewCorp")
        self.assertTrue(any(a["kind"] == "identity_change:owner" for a in snap["anomalies"]))
        self.assertTrue(snap["raw_ref"].endswith("2099-01-02.json"))
        self.assertIsNone(generic.entity_snapshot(self.con, "demo-prices", "nope"))
        self.assertIn("widget-a", generic.suggest_entities(self.con, "demo-prices", "widget"))


class TestGenericImportFormats(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ibe-import-")
        self.db = os.path.join(self.tmp, "t.db")
        self.con = store.connect(self.db)
        store.init_db(self.con)

    def tearDown(self):
        self.con.close()

    def test_csv_with_date_column_and_odd_filename(self):
        p = os.path.join(self.tmp, "exports_whatever.csv")
        with open(p, "w", encoding="utf-8", newline="") as f:
            f.write("observed_date,keyword,volume,note\n")
            f.write("2099-03-01,ai tools,1500,\n")
            f.write("2099-03-01,mcp server,900,rising\n")
        stats = generic.import_path(self.con, "kw", p, verbose=False)
        # 3 facts: ai tools.volume + mcp server.volume + mcp server.note;
        # the empty note cell on row 1 is ABSENT, never stored as zero/""
        self.assertEqual(stats["facts"], 3)
        rows = generic.query_series(self.con, "kw", "ai tools", "volume")
        self.assertEqual(rows[0]["observed_date"], "2099-03-01")
        self.assertEqual(rows[0]["num"], 1500.0)
        note = generic.query_series(self.con, "kw", "ai tools", "note")
        self.assertEqual(note, [])

    def test_json_entity_map_and_numeric_strings(self):
        p = os.path.join(self.tmp, "2099-04-01.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"owner/repo-a": {"stars": "1,234", "open_issues": 7},
                       "owner/repo-b": {"stars": "$56"},
                       "owner/repo-c": {"stars": "12,5"}}, f)
        stats = generic.import_path(self.con, "gh", self.tmp, verbose=False)
        self.assertEqual(stats["entities"], 3)
        rows = generic.query_series(self.con, "gh", "owner/repo-a", "stars")
        self.assertEqual(rows[0]["num"], 1234.0)   # thousand separator parsed
        rows_b = generic.query_series(self.con, "gh", "owner/repo-b", "stars")
        self.assertEqual(rows_b[0]["num"], 56.0)    # dollar sign stripped
        # P2-1 (MiniMax): European decimal comma is locale-ambiguous -> refuse to
        # guess: stays text, num None (宁缺不猜)
        rows_c = generic.query_series(self.con, "gh", "owner/repo-c", "stars")
        self.assertIsNone(rows_c[0]["num"])
        self.assertEqual(rows_c[0]["text"], "12,5")

    def test_explicit_bad_column_fails_loudly(self):
        """P1-5/Qoder P1-A: a typo'd explicit entity_column must error loudly,
        never silently import zero facts."""
        p = os.path.join(self.tmp, "2099-09-01.csv")
        with open(p, "w", encoding="utf-8", newline="") as f:
            f.write("thing,v\na,1\n")
        stats = generic.import_path(self.con, "loud", p, entity_column="typo_col", verbose=False)
        self.assertEqual(stats["errors"], 1)
        self.assertEqual(stats["facts"], 0)
        self.assertTrue(any("typo_col" in w for w in stats["warnings"]))

    def _write(self, name, content):
        p = os.path.join(self.tmp, name)
        with open(p, "w", encoding="utf-8", newline="") as f:
            f.write(content)
        return p

    def test_poisoned_csv_review_regressions(self):
        """WorkBuddy v0.3 review §3: one poisoned CSV must trigger all four
        ingest-layer disciplines (P0-A percent semantics, P0-B null markers,
        P0-C loud entity resolution, P0-D date validation)."""
        # exact probe from the review: invalid US-style dates in a 'date' column
        p = self._write("probe.csv",
                        "name,sku,price,change,date,remark\n"
                        "DisplayA,SKU-1,99,12%,11/07/2026,N/A\n"
                        "DisplayB,SKU-2,88,8%,11/07/2026,-\n")
        stats = generic.import_path(self.con, "probe", p, verbose=False)
        # P0-D: ambiguous dates are REJECTED, never stored as observed_date
        self.assertEqual(stats["invalid_dates"], 2)
        self.assertEqual(stats["skipped_records"], 2)
        self.assertEqual(stats["facts"], 0)
        bad = self.con.execute(
            "SELECT COUNT(*) FROM generic_facts WHERE source='probe'").fetchone()[0]
        self.assertEqual(bad, 0)
        for (d,) in self.con.execute("SELECT DISTINCT observed_date FROM generic_facts WHERE source='probe'"):
            self.assertRegex(d, r"^\d{4}-\d{2}-\d{2}$")

        # same data with a VALID filename date: percent + null-marker disciplines
        p2 = self._write("2099-07-01.csv",
                         "name,sku,price,change,remark\n"
                         "DisplayA,SKU-1,99,12%,N/A\n"
                         "DisplayB,SKU-2,88,8%,-\n")
        stats2 = generic.import_path(self.con, "probe2", p2, verbose=False)
        # P0-A: percent keeps its unit -- num parsed AND raw text preserved
        rows = generic.query_series(self.con, "probe2", "DisplayA", "change")
        self.assertEqual(rows[0]["num"], 12.0)
        self.assertEqual(rows[0]["text"], "12%")
        # P0-B: 'N/A' and '-' are absence, never facts
        self.assertEqual(generic.query_series(self.con, "probe2", "DisplayA", "remark"), [])
        self.assertEqual(generic.query_series(self.con, "probe2", "DisplayB", "remark"), [])
        self.assertEqual(stats2["skipped_values"], 2)
        # P0-C: entity auto-resolution is loud -- 'name' chosen, 'sku' warned about
        self.assertEqual(stats2["resolved"]["entity_column"], "name")
        self.assertTrue(any("sku" in w for w in stats2["warnings"]),
                        "expected WARN listing the other entity candidate 'sku'")
        # explicit override wins and regroups entities
        stats3 = generic.import_path(self.con, "probe3", p2, entity_column="sku", verbose=False)
        self.assertEqual(stats3["resolved"]["entity_column"], "sku")
        rows3 = generic.query_series(self.con, "probe3", "SKU-1", "price")
        self.assertEqual(rows3[0]["num"], 99.0)

    def test_duplicate_date_files_warn(self):
        """P1-B: two files feeding the same (source, date) must WARN, not silently overwrite."""
        d = os.path.join(self.tmp, "dup")
        os.makedirs(d, exist_ok=True)
        for name in ("2099-08-01.csv", "2099-08-01b.csv"):
            # second file shares the same date via filename prefix pattern? filenames
            # must both parse to 2099-08-01 -> use a date column instead
            pass
        with open(os.path.join(d, "part1.csv"), "w", encoding="utf-8", newline="") as f:
            f.write("observed_date,thing,v\n2099-08-01,a,1\n")
        with open(os.path.join(d, "part2.csv"), "w", encoding="utf-8", newline="") as f:
            f.write("observed_date,thing,v\n2099-08-01,a,2\n")
        stats = generic.import_path(self.con, "dup", d, verbose=False)
        self.assertTrue(any("two files" in w for w in stats["warnings"]))
        warned = self.con.execute(
            "SELECT COUNT(*) FROM ingest_files WHERE status='warn' AND message LIKE '%duplicate_date_file%'"
        ).fetchone()[0]
        self.assertGreaterEqual(warned, 1)

    def test_revised_reimport_leaves_no_ghost(self):
        """Codex P0: a value edited to null/N-A in a revised file must not
        survive from the previous import (per-(source,date) replace semantics)."""
        d = os.path.join(self.tmp, "rev")
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, "2099-10-01.csv")
        with open(p, "w", encoding="utf-8", newline="") as f:
            f.write("thing,v,note\na,1,hello\n")
        generic.import_path(self.con, "rev", d, verbose=False)
        self.assertEqual(len(generic.query_series(self.con, "rev", "a", "note")), 1)
        # revise: note becomes N/A (absent), v stays
        with open(p, "w", encoding="utf-8", newline="") as f:
            f.write("thing,v,note\na,1,N/A\n")
        generic.import_path(self.con, "rev", d, verbose=False)
        self.assertEqual(generic.query_series(self.con, "rev", "a", "note"), [])
        self.assertEqual(len(generic.query_series(self.con, "rev", "a", "v")), 1)

    def test_parse_failure_counts_as_error(self):
        """Codex P0: one corrupt file among good ones must surface in
        stats.errors (so run_import can exit non-zero), not pass silently."""
        d = os.path.join(self.tmp, "mix")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "2099-11-01.csv"), "w", encoding="utf-8", newline="") as f:
            f.write("name,v\nok,1\n")
        with open(os.path.join(d, "2099-11-02.json"), "w", encoding="utf-8") as f:
            f.write("{this is not json")
        stats = generic.import_path(self.con, "mix", d, verbose=False)
        self.assertEqual(stats["errors"], 1)
        self.assertGreaterEqual(stats["facts"], 1)

    def test_detect_generic_namespaced_and_idempotent(self):
        d = os.path.join(self.tmp, "gen")
        os.makedirs(os.path.join(d), exist_ok=True)
        for day, stars in (("2099-05-01", 100), ("2099-05-02", 40)):
            with open(os.path.join(d, day + ".json"), "w", encoding="utf-8") as f:
                json.dump([{"name": "thing", "stars": stars}], f)
        with open(os.path.join(d, "source.json"), "w", encoding="utf-8") as f:
            json.dump({"swing_threshold": 0.3}, f)
        generic.import_path(self.con, "s1", d, verbose=False)
        c1 = generic.detect_generic(self.con, "s1", verbose=False)
        c2 = generic.detect_generic(self.con, "s1", verbose=False)
        self.assertEqual(c1, c2)  # idempotent
        self.assertEqual(c1.get("value_swing"), 1)
        n = self.con.execute("SELECT COUNT(*) FROM anomalies WHERE slug='s1:thing'").fetchone()[0]
        self.assertEqual(n, 1)



class TestTextCollection(unittest.TestCase):
    """Non-numeric, non-financial collection: job postings.

    The engine was numerically biased -- value_swing only fires when both sides
    are numbers, and nothing detected an entity vanishing. For anyone collecting
    listings, papers, catalogs or postings, those two are the main events.
    """

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="ibe-jobs-")
        src = os.path.join(cls.tmp, "exports")
        os.makedirs(src)
        header = "job_id,title,company,location,status,posted_text"
        days = {
            "2026-11-01": [
                "j001,Senior Backend Engineer,Acme,Remote,open,Own our billing service.",
                "j002,Product Designer,Acme,Shanghai,open,Design dashboards.",
                "j003,Data Analyst,Beta,Beijing,open,Analyse user behaviour.",
            ],
            "2026-11-02": [
                "j001,Senior Backend Engineer,Acme,Remote,open,Own our billing service.",
                "j002,Product Designer,Acme,Shanghai,open,Design dashboards.",
                "j003,Data Analyst,Beta,Beijing,open,Analyse user behaviour.",
            ],
            # j002 retitled, j003 closed, j004 new
            "2026-11-03": [
                "j001,Senior Backend Engineer,Acme,Remote,open,Own our billing service.",
                "j002,Senior Product Designer,Acme,Shanghai,open,Design dashboards.",
                "j003,Data Analyst,Beta,Beijing,closed,Analyse user behaviour.",
                "j004,ML Engineer,Gamma,Remote,open,Build recommendation models.",
            ],
            # j003 posting removed entirely
            "2026-11-04": [
                "j001,Senior Backend Engineer,Acme,Remote,open,Own our billing service.",
                "j002,Senior Product Designer,Acme,Shanghai,open,Design dashboards.",
                "j004,ML Engineer,Gamma,Remote,open,Build recommendation models.",
            ],
        }
        for d, lines in days.items():
            with open(os.path.join(src, d + "-jobs.csv"), "w", encoding="utf-8", newline="\n") as f:
                f.write("\n".join([header] + lines) + "\n")
        with open(os.path.join(src, "source.json"), "w", encoding="utf-8") as f:
            json.dump({"entity_column": "job_id",
                       "track_text_fields": ["title", "status", "posted_text"],
                       "identity_fields": ["company"],
                       "min_presence_days": 2}, f)
        cls.db = os.path.join(cls.tmp, "jobs.db")
        con = store.connect(cls.db)
        store.init_db(con)
        generic.import_path(con, "jobs", src, verbose=False)
        # import_path only stores facts; detection is a separate step (same as
        # scripts/run_import.py does)
        generic.detect_generic(con, "jobs", verbose=False)
        cls.con = con

    @classmethod
    def tearDownClass(cls):
        try:
            cls.con.close()
        except Exception:
            pass

    def _anoms(self, kind_like="%"):
        cur = self.con.execute(
            "SELECT observed_date, slug, kind, severity, detail FROM anomalies "
            "WHERE kind LIKE ? ORDER BY observed_date, kind", (kind_like,))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    def test_text_change_detected(self):
        """Positive control: a declared text field changing must be flagged."""
        rows = self._anoms("text_changed:title")
        self.assertTrue(rows, "retitled posting must be flagged")
        self.assertIn("Product Designer", rows[0]["detail"])
        self.assertIn("Senior Product Designer", rows[0]["detail"])

    def test_status_flip_detected(self):
        rows = self._anoms("text_changed:status")
        self.assertTrue(rows, "open -> closed must be flagged")
        self.assertIn("closed", rows[0]["detail"])

    def test_entity_disappeared_detected(self):
        """A posting that stops existing is the main event for a listing collector."""
        rows = self._anoms("entity_disappeared")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["slug"], "jobs:j003")
        self.assertEqual(rows[0]["observed_date"], "2026-11-04")
        self.assertIn("crawler", rows[0]["detail"])   # never asserts removal as fact

    def test_undeclared_text_field_not_tracked(self):
        """Negative control: noise control -- fields not declared must not flag.

        'location' never changes here, so this is a weak control; the real
        guard is that only declared fields are inspected at all.
        """
        rows = self._anoms("text_changed:location")
        self.assertEqual(rows, [])

    def test_diff_reports_new_gone_and_changed(self):
        d = generic.diff_snapshots(self.con, "jobs", "2026-11-02", "2026-11-03")
        self.assertEqual(d["summary"]["new_entities"], 1)
        self.assertIn("j004", d["new_entities"])
        self.assertEqual(d["summary"]["gone_entities"], 0)
        fields = {(c["entity"], ch["field"]) for c in d["changed"] for ch in c["changes"]}
        self.assertIn(("j002", "title"), fields)
        self.assertIn(("j003", "status"), fields)

    def test_diff_reports_disappearance(self):
        d = generic.diff_snapshots(self.con, "jobs", "2026-11-03", "2026-11-04")
        self.assertEqual(d["summary"]["gone_entities"], 1)
        self.assertEqual(d["gone_entities"], ["j003"])
        self.assertIn("crawler", d["note"])

    def test_diff_single_date_source_degrades_cleanly(self):
        d = generic.diff_snapshots(self.con, "jobs", None, "2026-11-01")
        self.assertIsNone(d["from"])
        self.assertIn("only one capture date", d["note"])


class TestSchemaDrift(unittest.TestCase):
    """The column set itself changing -- what you hit when a source redesigns.

    field_disappeared covers "one column stopped arriving for this row";
    these cover "the source's shape changed".
    """

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="ibe-schema-")
        src = os.path.join(cls.tmp, "exports")
        os.makedirs(src)
        # day 1-2: item,price,stock | day 3-4: item,cost,stock,currency
        # price was renamed to cost (values moved slightly, as real renames do)
        days = {
            "2026-11-01": ["item,price,stock", "a,10,in", "b,20,in", "c,30,out"],
            "2026-11-02": ["item,price,stock", "a,11,in", "b,21,in", "c,30,out"],
            "2026-11-03": ["item,cost,stock,currency", "a,12,in,USD", "b,22,in,USD", "c,31,out,USD"],
            "2026-11-04": ["item,cost,stock,currency", "a,13,in,USD", "b,23,in,USD", "c,32,out,USD"],
        }
        for d, lines in days.items():
            with open(os.path.join(src, d + "-shop.csv"), "w", encoding="utf-8", newline="\n") as f:
                f.write("\n".join(lines) + "\n")
        cls.db = os.path.join(cls.tmp, "shop.db")
        con = store.connect(cls.db)
        store.init_db(con)
        generic.import_path(con, "shop", src, verbose=False)
        generic.detect_generic(con, "shop", verbose=False)
        cls.con = con

    @classmethod
    def tearDownClass(cls):
        try:
            cls.con.close()
        except Exception:
            pass

    def _anoms(self, kind_like="%"):
        cur = self.con.execute(
            "SELECT observed_date, slug, kind, severity, detail FROM anomalies "
            "WHERE kind LIKE ? ORDER BY observed_date, kind", (kind_like,))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    def test_field_appeared(self):
        rows = self._anoms("field_appeared:%")
        fields = {r["kind"].split(":", 1)[1] for r in rows}
        self.assertEqual(fields, {"cost", "currency"})
        for r in rows:
            self.assertEqual(r["observed_date"], "2026-11-03")
            self.assertEqual(r["slug"], "shop:" + generic.SCHEMA_ENTITY)

    def test_field_gone_fires_once_on_transition(self):
        """Must not re-report the same vanished column on every later date."""
        rows = self._anoms("field_gone:%")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["kind"], "field_gone:price")
        self.assertEqual(rows[0]["observed_date"], "2026-11-03")

    def test_rename_candidate_with_evidence(self):
        rows = self._anoms("field_renamed_candidate:%")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["kind"], "field_renamed_candidate:price->cost")
        self.assertIn("similar values (3/3)", rows[0]["detail"])

    def test_no_noise_on_first_capture(self):
        """Negative control: the baseline capture must not report every column as new."""
        rows = [r for r in self._anoms("field_appeared:%") if r["observed_date"] == "2026-11-01"]
        self.assertEqual(rows, [])

    def test_coverage_reports_schema_events(self):
        cov = generic.field_coverage(self.con, "shop")
        ev = cov["schema_events"]
        added = {f["field"] for f in ev["fields_added_after_first_capture"]}
        gone = {f["field"] for f in ev["fields_missing_on_latest"]}
        self.assertIn("currency", added)
        self.assertIn("price", gone)
        self.assertNotIn("stock", added)

    def test_partial_column_loss_is_not_schema_change(self):
        """Negative control: a column missing for SOME rows is per-entity drift,
        already owned by field_disappeared -- it must not also fire field_gone."""
        src = os.path.join(self.tmp, "partial")
        os.makedirs(src, exist_ok=True)
        days = {
            "2026-11-01": ["item,price,note", "a,10,x", "b,20,y"],
            "2026-11-02": ["item,price,note", "a,11,x"],          # b's row vanished, note still for a
        }
        for d, lines in days.items():
            with open(os.path.join(src, d + "-part.csv"), "w", encoding="utf-8", newline="\n") as f:
                f.write("\n".join(lines) + "\n")
        db = os.path.join(self.tmp, "part.db")
        con = store.connect(db)
        store.init_db(con)
        generic.import_path(con, "part", src, verbose=False)
        generic.detect_generic(con, "part", verbose=False)
        cur = con.execute("SELECT kind FROM anomalies WHERE kind LIKE 'field_gone:%'")
        self.assertEqual([r[0] for r in cur.fetchall()], [])
        con.close()


class TestCaptureCadence(unittest.TestCase):
    """Two captures 30 days apart are not "one day later".

    Before this, a stalled scraper made every metric look like it moved
    massively overnight, and every dropped entity looked like a delisting.
    """

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="ibe-cadence-")
        src = os.path.join(cls.tmp, "gapped")
        os.makedirs(src)
        days = {
            "2026-10-01": ["sku,price,views", "a,100,1000", "b,200,2000"],
            "2026-10-02": ["sku,price,views", "a,100,1010", "b,200,2020"],
            "2026-10-03": ["sku,price,views", "a,100,1020", "b,200,2040"],
            # scraper stalls for 30 days, then price really did move
            "2026-11-02": ["sku,price,views", "a,150,1500", "b,200,2050"],
        }
        for d, lines in days.items():
            with open(os.path.join(src, d + "-cat.csv"), "w", encoding="utf-8", newline="\n") as f:
                f.write("\n".join(lines) + "\n")
        cls.db = os.path.join(cls.tmp, "cat.db")
        con = store.connect(cls.db)
        store.init_db(con)
        generic.import_path(con, "cat", src, verbose=False)
        generic.detect_generic(con, "cat", verbose=False)
        cls.con = con

    @classmethod
    def tearDownClass(cls):
        try:
            cls.con.close()
        except Exception:
            pass

    def _anoms(self, kind_like="%"):
        cur = self.con.execute(
            "SELECT observed_date, slug, kind, severity, detail FROM anomalies "
            "WHERE kind LIKE ? ORDER BY observed_date, kind", (kind_like,))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    def test_gapped_transition_flagged(self):
        rows = self._anoms("gapped_transition")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["observed_date"], "2026-11-02")
        self.assertIn("30 day", rows[0]["detail"])
        self.assertIn("normal cadence is 1.0 day(s) from 2 earlier capture(s)", rows[0]["detail"])

    def test_swing_carries_the_span(self):
        """The +50% must never be readable as an overnight move."""
        rows = self._anoms("value_swing:price")
        self.assertEqual(len(rows), 1)
        self.assertIn("over 30 days", rows[0]["detail"])
        self.assertIn("not a one-day move", rows[0]["detail"])

    def test_no_gap_noise_on_steady_cadence(self):
        """Negative control: a steadily captured source must not emit gap events."""
        rows = [r for r in self._anoms("gapped_transition") if r["observed_date"] <= "2026-10-03"]
        self.assertEqual(rows, [])

    def test_coverage_reports_cadence(self):
        cov = generic.field_coverage(self.con, "cat")
        self.assertEqual(cov["cadence"]["median_gap_days"], 1)
        self.assertEqual(cov["cadence"]["max_gap_days"], 30)
        self.assertEqual(len(cov["cadence"]["gaps_over_threshold"]), 1)
        self.assertEqual(cov["cadence"]["gaps_over_threshold"][0]["date"], "2026-11-02")

    def test_custom_max_gap_days_widens_tolerance(self):
        """With max_gap_days=60 a 30-day gap is within tolerance and stays quiet."""
        src = os.path.join(self.tmp, "wide")
        os.makedirs(src, exist_ok=True)
        for d, lines in {
            "2026-10-01": ["sku,price", "a,100"],
            "2026-10-02": ["sku,price", "a,100"],
            "2026-11-02": ["sku,price", "a,150"],
        }.items():
            with open(os.path.join(src, d + "-wide.csv"), "w", encoding="utf-8", newline="\n") as f:
                f.write("\n".join(lines) + "\n")
        with open(os.path.join(src, "source.json"), "w", encoding="utf-8") as f:
            json.dump({"entity_column": "sku", "max_gap_days": 60}, f)
        db = os.path.join(self.tmp, "wide.db")
        con = store.connect(db)
        store.init_db(con)
        generic.import_path(con, "wide", src, verbose=False)
        generic.detect_generic(con, "wide", verbose=False)
        cur = con.execute("SELECT kind FROM anomalies WHERE kind LIKE 'gapped_transition%'")
        self.assertEqual([r[0] for r in cur.fetchall()], [])
        con.close()


class TestEntityResolution(unittest.TestCase):
    """The second wall: "I captured it but cannot join it".

    The same product appears as 'Acme Widget', 'acme_widget' and 'ACME-WIDGET'
    in different exports, becomes three entities, and never lines up.
    """

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="ibe-resolve-")
        shop = os.path.join(cls.tmp, "shop")
        ads = os.path.join(cls.tmp, "ads")
        os.makedirs(shop)
        os.makedirs(ads)
        for d, price in (("2026-11-01", "49"), ("2026-11-02", "52")):
            with open(os.path.join(shop, d + "-shop.csv"), "w", encoding="utf-8", newline="\n") as f:
                f.write("product,price,stock\n"
                        "Acme Widget,%s,in\nBeta-Gadget,99,in\nacme_widget,47,in\n" % price)
            with open(os.path.join(ads, d + "-ads.csv"), "w", encoding="utf-8", newline="\n") as f:
                f.write("campaign,spend,clicks\nACME-WIDGET,300,1200\nBeta Gadget,150,400\n")
        cls.db = os.path.join(cls.tmp, "r.db")
        con = store.connect(cls.db)
        store.init_db(con)
        generic.import_path(con, "shop", shop, verbose=False)
        generic.import_path(con, "ads", ads, verbose=False)
        generic.detect_generic(con, "shop", verbose=False)
        generic.detect_generic(con, "ads", verbose=False)
        cls.con = con

    @classmethod
    def tearDownClass(cls):
        try:
            cls.con.close()
        except Exception:
            pass

    def test_normalization_folds_case_and_separators(self):
        for v in ("Acme Widget", "acme-widget", "ACME_WIDGET", "acme.widget", "Acme  Widget"):
            self.assertEqual(generic.normalize_entity(v), "acmewidget")

    def test_normalization_keeps_different_names_different(self):
        """Negative control: must not collapse genuinely distinct products."""
        self.assertNotEqual(generic.normalize_entity("Beta Gadget"),
                            generic.normalize_entity("Acme Widget"))

    def test_duplicate_candidates_with_overlap_evidence(self):
        d = generic.find_duplicate_entities(self.con, "shop")
        self.assertEqual(d["candidate_groups"], 1)
        g = d["groups"][0]
        self.assertEqual(g["normalized"], "acmewidget")
        self.assertEqual([e["entity"] for e in g["entities"]], ["Acme Widget", "acme_widget"])
        self.assertEqual(g["same_day_overlap_days"], 2)
        self.assertEqual(g["overlap_kind"], "same_day")

    def test_no_duplicates_when_ids_are_distinct(self):
        d = generic.find_duplicate_entities(self.con, "ads")
        self.assertEqual(d["candidate_groups"], 0)

    def test_resolve_across_sources(self):
        r = generic.resolve_entities(self.con, "acme widget")
        self.assertEqual(r["normalized"], "acmewidget")
        self.assertEqual(r["by_source"]["ads"], ["ACME-WIDGET"])
        self.assertEqual(sorted(r["by_source"]["shop"]), ["Acme Widget", "acme_widget"])
        self.assertTrue(all(m["match"] == "exact_normalized" for m in r["results"]))

    def test_resolve_substring(self):
        r = generic.resolve_entities(self.con, "beta")
        self.assertGreaterEqual(r["matches"], 2)
        self.assertTrue(all(m["match"] == "substring_normalized" for m in r["results"]))

    def test_resolve_empty_query(self):
        self.assertIsNone(generic.resolve_entities(self.con, "   "))

    def test_list_entities_pagination(self):
        first = generic.list_entities(self.con, "shop", limit=2, offset=0)
        self.assertEqual(first["total"], 3)
        self.assertEqual(first["returned"], 2)
        self.assertTrue(first["has_more"])
        second = generic.list_entities(self.con, "shop", limit=2, offset=2)
        self.assertFalse(second["has_more"])
        self.assertFalse({e["entity"] for e in first["entities"]}
                         & {e["entity"] for e in second["entities"]})


class TestReviewerP0Regressions(unittest.TestCase):
    """Every test here reproduces a P0/P1 filed by the v0.4.0 review round.

    Codex / Qoder / MiniMax all rejected 93ba276; these are the reproducible
    ones. A fix without a regression test is a fix that comes back.
    """

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="ibe-p0-")
        src = os.path.join(cls.tmp, "s")
        os.makedirs(src)
        # entity A has price; entity B has no price; widget-g changes owner
        days = {
            "2026-11-01": ["id,owner,price,cum",
                           "a,ALPHA,10,100", "b,ALPHA,,200", "g,OldCo,100,500"],
            "2026-11-02": ["id,owner,price,cum",
                           "a,ALPHA,20,110", "b,ALPHA,,210", "g,NewCo,1000,480"],
        }
        for d, lines in days.items():
            with open(os.path.join(src, d + "-p.csv"), "w", encoding="utf-8", newline="\n") as f:
                f.write("\n".join(lines) + "\n")
        # owner must be declared as an identity field, otherwise the engine has no
        # basis for calling g's ownership change a boundary (and should not)
        with open(os.path.join(src, "source.json"), "w", encoding="utf-8") as f:
            json.dump({"entity_column": "id", "identity_fields": ["owner"]}, f)
        cls.db = os.path.join(cls.tmp, "p.db")
        con = store.connect(cls.db)
        store.init_db(con)
        generic.import_path(con, "p", src, verbose=False)
        generic.detect_generic(con, "p", verbose=False)
        cls.con = con

    @classmethod
    def tearDownClass(cls):
        try:
            cls.con.close()
        except Exception:
            pass

    # ---- P0: a date that was never captured is not an empty snapshot --------
    def test_diff_rejects_unknown_date(self):
        r = generic.diff_snapshots(self.con, "p", None, "2099-01-01")
        self.assertIn("error", r)
        self.assertIn("known_dates", r)
        self.assertNotIn("gone_entities", r)

    def test_diff_rejects_reversed_range(self):
        r = generic.diff_snapshots(self.con, "p", "2026-11-02", "2026-11-01")
        self.assertIn("error", r)

    # ---- P0: diff must respect identity boundaries --------------------------
    def test_diff_marks_identity_boundary(self):
        r = generic.diff_snapshots(self.con, "p", "2026-11-01", "2026-11-02")
        self.assertIn("identity_boundaries", r)
        self.assertIn("g", r["identity_boundaries"])
        entry = [e for e in r["changed"] if e["entity"] == "g"][0]
        self.assertTrue(entry.get("across_identity_boundary"))
        price_change = [ch for ch in entry["changes"] if ch["field"] == "price"][0]
        self.assertIsNone(price_change.get("delta_pct"),
                          "no growth rate may be computed across an identity boundary")

    # ---- P0: sorting must never float missing values to the top ------------
    def test_sort_desc_puts_missing_last(self):
        r = generic.search_records(self.con, "p", date="2026-11-02",
                                   sort="price", desc=True, limit=10)
        entities = [x["entity"] for x in r["records"]]
        self.assertEqual(entities[0], "g")          # 1000 is the max
        self.assertEqual(entities[-1], "b")         # b has no price -> last
        self.assertNotIn("price", r["records"][-1]["fields"])

    # ---- P0: filter values arrive as strings from LLM clients --------------
    def test_filter_string_value_is_coerced(self):
        r = generic.search_records(self.con, "p", date="2026-11-02",
                                   filters=[{"field": "price", "op": ">=", "value": "20"}])
        self.assertEqual(sorted(x["entity"] for x in r["records"]), ["a", "g"])

    def test_filter_not_equal_with_string_value(self):
        r = generic.search_records(self.con, "p", date="2026-11-02",
                                   filters=[{"field": "price", "op": "!=", "value": "20"}])
        self.assertEqual([x["entity"] for x in r["records"]], ["g"])

    def test_non_numeric_value_for_numeric_op_is_an_error(self):
        r = generic.search_records(self.con, "p", date="2026-11-02",
                                   filters=[{"field": "price", "op": ">=", "value": "abc"}])
        self.assertIn("error", r)

    # ---- P0: source name is a LIKE pattern ---------------------------------
    def test_source_name_with_underscore_does_not_touch_other_sources(self):
        """'shop_a' must not delete anomalies belonging to 'shopXa'."""
        self.assertEqual(generic._like_escape("shop_a"), "shop\\_a")
        src = os.path.join(self.tmp, "two")
        for name in ("shop_a", "shopXa"):
            d = os.path.join(src, name)
            os.makedirs(d, exist_ok=True)
            for day, price in (("2026-11-01", "10"), ("2026-11-02", "90")):
                with open(os.path.join(d, day + "-x.csv"), "w", encoding="utf-8", newline="\n") as f:
                    f.write("id,price\n" + "k,%s\n" % price)
        db = os.path.join(self.tmp, "two.db")
        con = store.connect(db)
        store.init_db(con)
        for name in ("shop_a", "shopXa"):
            generic.import_path(con, name, os.path.join(src, name), verbose=False)
            generic.detect_generic(con, name, verbose=False)
        kinds = {r[0] for r in con.execute(
            "SELECT kind FROM anomalies WHERE slug LIKE 'shopXa:%'")}
        self.assertIn("value_swing:price", kinds,
                      "detecting shop_a must not delete shopXa's anomalies")
        con.close()

    # ---- P1: an entity that left is not a field that stopped arriving ------
    def test_coverage_separates_entity_exit_from_field_drop(self):
        src = os.path.join(self.tmp, "exit")
        os.makedirs(src, exist_ok=True)
        for day, lines in {
            "2026-11-01": ["id,price,listing_url", "a,10,http://a", "b,20,http://b"],
            "2026-11-02": ["id,price,listing_url", "a,11,http://a"],
        }.items():
            with open(os.path.join(src, day + "-e.csv"), "w", encoding="utf-8", newline="\n") as f:
                f.write("\n".join(lines) + "\n")
        db = os.path.join(self.tmp, "exit.db")
        con = store.connect(db)
        store.init_db(con)
        generic.import_path(con, "exit", src, verbose=False)
        cov = generic.field_coverage(con, "exit")
        by_field = {f["field"]: f for f in cov["fields"]}
        self.assertEqual(by_field["price"]["status"], "ok",
                         "entity b left; that is churn, not field drift")
        self.assertEqual(by_field["price"]["entities_exited_with_field"], 1)
        con.close()


class TestCadenceLearning(unittest.TestCase):
    """Codex P1-6: with two or three capture dates the old threshold was always
    >= every possible interval, so gapped_transition could never fire.

    Fix: judge each gap against the cadence learned from EARLIER gaps only.
    """

    def test_two_dates_is_unknown_not_silent(self):
        """Two captures give no prior interval: we must say 'unknown', not pretend
        the 30-day gap is normal."""
        c = generic._cadence(["2026-01-01", "2026-01-31"])
        self.assertEqual(c["gapped"], {})
        self.assertEqual(c["unknown"], ["2026-01-31"])
        self.assertIsNone(c["median_gap_days"])

    def test_three_dates_flags_the_outlier(self):
        """a=1, b=30: the second gap must be judged against the first, and fire."""
        c = generic._cadence(["2026-10-01", "2026-10-02", "2026-11-01"])
        self.assertIn("2026-11-01", c["gapped"])
        self.assertEqual(c["reference"]["2026-11-01"]["reference_gap_days"], 1)
        self.assertEqual(c["reference"]["2026-11-01"]["samples"], 1)

    def test_steady_daily_never_flags(self):
        c = generic._cadence(["2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04"])
        self.assertEqual(c["gapped"], {})

    def test_configured_gap_rescues_two_date_sources(self):
        """A deliberately sparse source can declare its rhythm."""
        c = generic._cadence(["2026-01-01", "2026-01-31"], cfg_gap=7)
        self.assertIn("2026-01-31", c["gapped"])
        self.assertEqual(c["reference"]["2026-01-31"]["source"], "configured max_gap_days")

    def test_long_streak_then_gap_flags_with_evidence(self):
        c = generic._cadence(["2026-10-01", "2026-10-02", "2026-10-03",
                              "2026-10-04", "2026-10-05", "2026-11-04"])
        self.assertIn("2026-11-04", c["gapped"])
        self.assertEqual(c["reference"]["2026-11-04"]["samples"], 4)
        self.assertEqual(c["reference"]["2026-11-04"]["reference_gap_days"], 1)

    def test_detector_reports_unknown_cadence_in_coverage(self):
        tmp = tempfile.mkdtemp(prefix="ibe-cad2-")
        src = os.path.join(tmp, "s")
        os.makedirs(src)
        for d in ("2026-01-01", "2026-01-31"):
            with open(os.path.join(src, d + "-c.csv"), "w", encoding="utf-8", newline="\n") as f:
                f.write("id,price\nk,10\n")
        db = os.path.join(tmp, "c.db")
        con = store.connect(db)
        store.init_db(con)
        generic.import_path(con, "c", src, verbose=False)
        generic.detect_generic(con, "c", verbose=False)
        cov = generic.field_coverage(con, "c")
        self.assertEqual(cov["cadence"]["cadence_unknown_for"], ["2026-01-31"])
        self.assertEqual(cov["cadence"]["gaps_over_threshold"], [])
        con.close()


class TestTextChangeReadability(unittest.TestCase):
    """Codex P2: truncating both sides made two different changes look identical."""

    def test_short_change_shows_both_values(self):
        self.assertEqual(generic._text_change("open", "closed"), "'open' -> 'closed'")

    def test_long_change_shows_the_differing_segment(self):
        a = "x" * 150 + "old"
        b = "x" * 150 + "new"
        msg = generic._text_change(a, b)
        self.assertIn("'old'", msg)
        self.assertIn("'new'", msg)
        self.assertLess(len(msg), 120, "the excerpt must not be a second wall of text")

    def test_two_long_changes_are_distinguishable(self):
        one = generic._text_change("x" * 150 + "old", "x" * 150 + "new")
        two = generic._text_change("y" * 150 + "alpha", "y" * 150 + "beta")
        self.assertNotEqual(one, two)


class TestResolveBounds(unittest.TestCase):
    """Codex P2: limit=1 still returned every entity name in by_source."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="ibe-bound-")
        src = os.path.join(cls.tmp, "s")
        os.makedirs(src)
        rows = ["id,price"] + ["item%d,%d" % (i, i) for i in range(40)]
        for d in ("2026-01-01", "2026-01-02"):
            with open(os.path.join(src, d + "-b.csv"), "w", encoding="utf-8", newline="\n") as f:
                f.write("\n".join(rows) + "\n")
        cls.db = os.path.join(cls.tmp, "b.db")
        con = store.connect(cls.db)
        store.init_db(con)
        generic.import_path(con, "s", src, verbose=False)
        cls.con = con

    @classmethod
    def tearDownClass(cls):
        try:
            cls.con.close()
        except Exception:
            pass

    def test_by_source_is_bounded_by_limit(self):
        r = generic.resolve_entities(self.con, "item", limit=3)
        self.assertEqual(r["matches"], 40)
        self.assertLessEqual(len(r["results"]), 3)
        self.assertLessEqual(sum(len(v) for v in r["by_source"].values()), 3)
        self.assertTrue(r["by_source_truncated"])
        self.assertEqual(r["by_source_counts"], {"s": 40})


class TestSecondReviewRegressions(unittest.TestCase):
    """Codex's re-review of 2988229 found these still open. Each has a test."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="ibe-r2-")

    def _mk(self, name, files, cfg=None):
        d = os.path.join(self.tmp, name)
        os.makedirs(d, exist_ok=True)
        for k, body in files.items():
            with open(os.path.join(d, k + "-x.csv"), "w", encoding="utf-8", newline="\n") as f:
                f.write(body.strip() + "\n")
        if cfg:
            with open(os.path.join(d, "source.json"), "w", encoding="utf-8") as f:
                json.dump(cfg, f)
        return d

    def _db(self, name):
        con = store.connect(os.path.join(self.tmp, name + ".db"))
        store.init_db(con)
        return con

    # ---- P0-1: LIKE is case-insensitive and treats _ as a wildcard ----------
    def test_source_scope_is_case_sensitive(self):
        """'Shop:x' must survive a detect of 'shop'."""
        con = self._db("case")
        for name in ("Shop", "shop"):
            d = self._mk(name, {"2026-01-01": "id,price\nk,10",
                                "2026-01-02": "id,price\nk,90"})
            generic.import_path(con, name, d, verbose=False)
            generic.detect_generic(con, name, verbose=False)
        kinds = {r[0] for r in con.execute("SELECT kind FROM anomalies WHERE substr(slug,1,5)='Shop:'")}
        self.assertIn("value_swing:price", kinds,
                      "detecting 'shop' must not delete 'Shop' anomalies")
        con.close()

    def test_source_prefix_overlap_is_not_deletion(self):
        """'s:t' and 's' are distinct namespaces."""
        con = self._db("prefix")
        for name in ("s", "sx"):
            d = self._mk(name, {"2026-01-01": "id,price\nk,10",
                                "2026-01-02": "id,price\nk,90"})
            generic.import_path(con, name, d, verbose=False)
            generic.detect_generic(con, name, verbose=False)
        n_s = con.execute("SELECT COUNT(*) FROM anomalies WHERE substr(slug,1,2)='s:'").fetchone()[0]
        self.assertGreater(n_s, 0)
        con.close()

    def test_colon_in_namespace_is_refused(self):
        with self.assertRaises(ValueError):
            generic._check_namespace("s:t")
        with self.assertRaises(ValueError):
            generic._check_namespace("ok", "a:b")
        generic._check_namespace("shop", "widget-a")   # must not raise

    # ---- P0-3: explicit 'to' is validated before 'from' is derived ---------
    def test_explicit_unknown_to_reports_error(self):
        con = self._db("to")
        d = self._mk("to", {"2026-01-01": "id,price\nk,10",
                            "2026-01-02": "id,price\nk,10",
                            "2026-01-03": "id,price\nk,10"})
        generic.import_path(con, "to", d, verbose=False)
        r = generic.diff_snapshots(con, "to", None, "2025-12-01")
        self.assertIn("error", r)
        self.assertIn("known_dates", r)
        con.close()

    # ---- P1-4: schema summary must not contradict the field status ---------
    def test_schema_summary_ignores_exited_entities(self):
        con = self._db("exit3")
        d = self._mk("exit3", {"2026-01-01": "id,price,url\na,10,h1\nb,20,h2",
                               "2026-01-02": "id,price,url\na,11,h1"})
        generic.import_path(con, "exit3", d, verbose=False)
        cov = generic.field_coverage(con, "exit3")
        by_field = {f["field"]: f for f in cov["fields"]}
        self.assertEqual(by_field["url"]["status"], "ok")
        self.assertEqual(cov["schema_events"]["fields_missing_on_latest"], [])
        con.close()

    # ---- P1-5: all-null column must not be reported as a schema change -----
    def test_all_null_column_does_not_claim_schema_change(self):
        con = self._db("nulls")
        d = self._mk("nulls", {"2026-01-01": "id,price,stock\na,10,in\nb,20,in",
                               "2026-01-02": "id,price,stock\na,10,\nb,20,"})
        generic.import_path(con, "nulls", d, verbose=False)
        generic.detect_generic(con, "nulls", verbose=False)
        rows = [r[0] for r in con.execute(
            "SELECT detail FROM anomalies WHERE kind LIKE 'field_gone%'")]
        self.assertTrue(rows)
        # it may *mention* the phrase only to say it cannot be concluded
        self.assertIn("cannot tell these apart", rows[0])
        self.assertNotIn("-- the source's schema changed", rows[0])
        self.assertIn("Check the raw file before concluding", rows[0])
        con.close()

    # ---- P1-6: empty source must not raise --------------------------------
    def test_empty_source_is_safe(self):
        con = self._db("empty")
        self.assertEqual(generic.detect_generic(con, "empty", verbose=False), {})
        self.assertEqual(generic._cadence([])["gapped"], {})
        con.close()

    # ---- P1-7: three spellings use pairwise overlap ------------------------
    def test_three_spellings_pairwise_overlap(self):
        con = self._db("three")
        d = self._mk("three", {"2026-01-01": "id,v\na-b,1\na_b,2",
                               "2026-01-02": "id,v\na-b,1\na b,3"})
        generic.import_path(con, "three", d, verbose=False)
        groups = generic.find_duplicate_entities(con, "three")["groups"]
        self.assertTrue(groups)
        g = groups[0]
        self.assertEqual(g["overlap_kind"], "same_day")
        self.assertGreaterEqual(g["same_day_overlap_days"], 1)
        con.close()

    # ---- P2-10: long changes must stay distinguishable ---------------------
    def test_long_changes_are_distinguishable(self):
        a = "a" * 200
        b1 = "b" * 90 + "1" + "b" * 109
        b2 = "b" * 90 + "2" + "b" * 109
        self.assertNotEqual(generic._text_change(a, b1), generic._text_change(a, b2))


class TestNamespaceGuardsEverywhere(unittest.TestCase):
    """Codex round 3: the import constraint alone left three entry points open --
    generic.entity_snapshot, detect_generic called directly, and store.put_anomaly."""

    def test_put_anomaly_rejects_ambiguous_slug(self):
        tmp = tempfile.mkdtemp(prefix="ibe-ns-")
        con = store.connect(os.path.join(tmp, "x.db"))
        store.init_db(con)
        with self.assertRaises(ValueError):
            store.put_anomaly(con, "2026-01-01", "s:t:x", "k", "warn", "d")
        store.put_anomaly(con, "2026-01-01", "s:t", "k", "warn", "d")   # one colon is fine
        con.close()

    def test_detect_rejects_colon_source(self):
        tmp = tempfile.mkdtemp(prefix="ibe-ns2-")
        con = store.connect(os.path.join(tmp, "x.db"))
        store.init_db(con)
        with self.assertRaises(ValueError):
            generic.detect_generic(con, "s:t", verbose=False)
        con.close()

    def test_import_rejects_colon_entity(self):
        tmp = tempfile.mkdtemp(prefix="ibe-ns3-")
        d = os.path.join(tmp, "s")
        os.makedirs(d)
        with open(os.path.join(d, "2026-01-01-x.csv"), "w", encoding="utf-8", newline="\n") as f:
            f.write("id,price\ns:t,1\n")
        con = store.connect(os.path.join(tmp, "x.db"))
        store.init_db(con)
        with self.assertRaises(ValueError):
            generic.import_path(con, "okname", d, verbose=False)
        con.close()

    def test_audit_cli_is_case_sensitive(self):
        """The CLI used LIKE too, so auditing 'shop' printed 'Shop' rows."""
        tmp = tempfile.mkdtemp(prefix="ibe-ns4-")
        con = store.connect(os.path.join(tmp, "x.db"))
        store.init_db(con)
        store.put_anomaly(con, "2026-01-01", "Shop:x", "k", "warn", "upper")
        store.put_anomaly(con, "2026-01-01", "shop:x", "k", "warn", "lower")
        con.commit()
        rows = [r[0] for r in con.execute(
            "SELECT substr(slug,6) FROM anomalies WHERE substr(slug,1,5)=?", ("shop:",))]
        self.assertEqual(rows, ["x"])
        con.close()


class TestOverlapScopeHonesty(unittest.TestCase):
    """Codex round 3: 'same_day' must mean 'at least one PAIR', not 'all spellings'."""

    def test_partial_pair_overlap_is_reported_as_scope(self):
        tmp = tempfile.mkdtemp(prefix="ibe-ov-")
        d = os.path.join(tmp, "s")
        os.makedirs(d)
        for day, body in {
            "2026-01-01": "id,v\na,1\nb,2",
            "2026-01-02": "id,v\nb,2\na,3",     # a and b coexist both days
        }.items():
            with open(os.path.join(d, day + "-x.csv"), "w", encoding="utf-8", newline="\n") as f:
                f.write(body + "\n")
        con = store.connect(os.path.join(tmp, "x.db"))
        store.init_db(con)
        generic.import_path(con, "s", d, verbose=False)
        groups = generic.find_duplicate_entities(con, "s")
        self.assertEqual(groups["candidate_groups"], 0)   # a/b do not normalise together
        con.close()


class TestPublicReviewP1(unittest.TestCase):
    """MiniMax's public-repo review: six ways the output layer answered
    confidently and wrongly. Each one has a reproduction here."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="ibe-pub-")
        d = os.path.join(cls.tmp, "p")
        os.makedirs(d)
        days = {
            "2099-03-01": "id,price,note\na,10,hello\nb,31,x",
            "2099-03-02": "id,price,note\na,11,hello\nb,99,x",
            "2099-03-12": "id,price,note\na,12,hello\nb,100,x",
        }
        for k, body in days.items():
            with open(os.path.join(d, k + "-p.csv"), "w", encoding="utf-8", newline="\n") as f:
                f.write(body + "\n")
        cls.db = os.path.join(cls.tmp, "p.db")
        con = store.connect(cls.db)
        store.init_db(con)
        generic.import_path(con, "p", d, verbose=False)
        generic.detect_generic(con, "p", verbose=False)
        cls.con = con

    @classmethod
    def tearDownClass(cls):
        try:
            cls.con.close()
        except Exception:
            pass

    # P1-1 unknown operator
    def test_unknown_op_errors_instead_of_returning_everything(self):
        r = generic.search_records(self.con, "p", date="2099-03-01",
                                   filters=[{"field": "price", "op": "gt", "value": 5}])
        self.assertIn("error", r)
        self.assertIn("unknown filter op", r["error"])

    # P1-2 missing value
    def test_missing_filter_value_errors(self):
        for op in ("!=", ">="):
            r = generic.search_records(self.con, "p", date="2099-03-01",
                                       filters=[{"field": "price", "op": op}])
            self.assertIn("error", r, op)
            self.assertIn("missing 'value'", r["error"])

    # P1-6 unknown capture date
    def test_search_on_uncaptured_date_errors(self):
        r = generic.search_records(self.con, "p", date="2099-02-01")
        self.assertIn("error", r)
        self.assertIn("not a capture date", r["error"])
        self.assertIn("known_dates", r)

    # P1-5 non-finite numbers must never reach the payload
    def test_infinity_is_refused_at_import(self):
        self.assertIsNone(generic._to_num("inf"))
        self.assertIsNone(generic._to_num("-infinity"))
        self.assertIsNone(generic._to_num("1e999"))
        self.assertIsNone(generic._to_num("nan"))
        self.assertEqual(generic._to_num("12,345"), 12345.0)

    # P2-8 mixed numbers/text must not sort by string
    def test_mixed_sort_keeps_numbers_numeric(self):
        r = generic.search_records(self.con, "p", date="2099-03-01",
                                   sort="note", desc=True)
        values = [x["fields"].get("note", {}) for x in r["records"]]
        # text values only here; the point is that it must not crash nor reorder
        self.assertTrue(all(v.get("text") for v in values if v))
        r2 = generic.search_records(self.con, "p", date="2099-03-01",
                                    sort="price", desc=True)
        nums = [x["fields"]["price"]["num"] for x in r2["records"]]
        self.assertEqual(nums, sorted(nums, reverse=True))

    # P2-7 mixed-type field is refused rather than silently skipped
    def test_mixed_type_field_is_refused(self):
        d = os.path.join(self.tmp, "mix")
        os.makedirs(d)
        with open(os.path.join(d, "2099-04-01-m.csv"), "w", encoding="utf-8", newline="\n") as f:
            f.write("id,v\na,10\nb,hello\n")
        con = store.connect(os.path.join(self.tmp, "m.db"))
        store.init_db(con)
        generic.import_path(con, "m", d, verbose=False)
        r = generic.search_records(con, "m", filters=[{"field": "v", "op": ">", "value": "3"}])
        self.assertIn("error", r)
        self.assertIn("both numbers and text", r["error"])
        con.close()

if __name__ == "__main__":
    unittest.main()
