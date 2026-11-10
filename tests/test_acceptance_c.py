"""Independent C01/C02 acceptance tests from the frozen C-SPEC.

Inputs and expected values are literal synthetic data, not production-derived.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

PROJ = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(PROJ, "src"))

from indiebiz_evidence import generic, store  # noqa: E402


class TestAcceptanceC(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ibe-acceptance-c-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.con = store.connect(str(self.root / "acceptance.db"))
        self.addCleanup(self.con.close)
        store.init_db(self.con)

    def _import_csv(self, source, snapshots, config):
        folder = self.root / source
        folder.mkdir()
        for day, text in snapshots.items():
            with (folder / (day + ".csv")).open(
                    "w", encoding="utf-8", newline="") as stream:
                stream.write(text)
        stats = generic.import_path(
            self.con, source, str(folder), config=config, verbose=False)
        self.assertEqual(stats["errors"], 0)
        self.assertEqual(stats["skipped_records"], 0)
        self.assertEqual(stats["invalid_dates"], 0)

    def test_c01_missing_is_absent_and_zero_is_numeric(self):
        source = "acceptance-c01"
        entity = "C01-A"
        self._import_csv(source, {
            "2099-01-01": "id,price,note\nC01-A,10,present\n",
            # No price column at all; note keeps the entity observable.
            "2099-01-02": "id,note\nC01-A,present\n",
            "2099-01-03": "id,price,note\nC01-A,0,present\n",
        }, {"entity_column": "id"})

        facts = self.con.execute(
            "SELECT source, entity, field, observed_date, num, text "
            "FROM generic_facts WHERE source=? AND entity=? AND field=? "
            "ORDER BY observed_date", (source, entity, "price")).fetchall()
        # Exact rows exclude a NULL row as well as a fabricated zero on day 2.
        self.assertEqual(facts, [
            ("acceptance-c01", "C01-A", "price", "2099-01-01", 10.0, "10"),
            ("acceptance-c01", "C01-A", "price", "2099-01-03", 0.0, "0"),
        ])
        series = generic.query_series(self.con, source, entity, "price")
        self.assertEqual([
            (row["observed_date"], row["num"], row["text"]) for row in series
        ], [
            ("2099-01-01", 10.0, "10"),
            ("2099-01-03", 0.0, "0"),
        ])

        middle = generic.search_records(self.con, source, date="2099-01-02")
        self.assertIsInstance(middle, dict)
        self.assertNotIn("error", middle)
        self.assertEqual(middle["source"], "acceptance-c01")
        self.assertEqual(middle["date"], "2099-01-02")
        self.assertEqual(middle["total_matched"], 1)
        self.assertEqual(
            [(row["entity"], row["fields"]) for row in middle["records"]],
            [("C01-A", {"note": {"num": None, "text": "present"}})],
        )

        # > 0 checks the requested filter. == 0 distinguishes absence from zero:
        # both fail > 0, but only the explicit day-3 zero may satisfy == 0.
        for day, op, expected_entities in [
            ("2099-01-01", ">", ["C01-A"]),
            ("2099-01-02", ">", []),
            ("2099-01-03", ">", []),
            ("2099-01-01", "==", []),
            ("2099-01-02", "==", []),
            ("2099-01-03", "==", ["C01-A"]),
        ]:
            with self.subTest(date=day, op=op):
                result = generic.search_records(
                    self.con, source, date=day,
                    filters=[{"field": "price", "op": op, "value": 0}])
                self.assertIsInstance(result, dict)
                self.assertNotIn("error", result)
                self.assertEqual(result["source"], "acceptance-c01")
                self.assertEqual(result["date"], day)
                self.assertEqual(result["total_matched"], len(expected_entities))
                self.assertEqual(result["returned"], len(expected_entities))
                self.assertEqual(
                    [row["entity"] for row in result["records"]],
                    expected_entities,
                )

    def test_c02_price_alert_has_exact_entity_field_and_date(self):
        source = "acceptance-c02"
        config = {
            "entity_column": "id",
            "swing_fields": ["price"],
            "swing_threshold": 0.30,
        }
        self._import_csv(source, {
            "2099-02-01": "id,price\nC02-A,10\nC02-B,10\n",
            "2099-02-02": "id,price\nC02-A,40\nC02-B,10\n",
        }, config)

        facts = self.con.execute(
            "SELECT source, entity, field, observed_date, num, text "
            "FROM generic_facts ORDER BY entity, field, observed_date"
        ).fetchall()
        self.assertEqual(facts, [
            ("acceptance-c02", "C02-A", "price", "2099-02-01", 10.0, "10"),
            ("acceptance-c02", "C02-A", "price", "2099-02-02", 40.0, "40"),
            ("acceptance-c02", "C02-B", "price", "2099-02-01", 10.0, "10"),
            ("acceptance-c02", "C02-B", "price", "2099-02-02", 10.0, "10"),
        ])
        generic.detect_generic(self.con, source, config=config, verbose=False)
        alerts = self.con.execute(
            "SELECT slug, kind, observed_date, detail FROM anomalies "
            "ORDER BY slug, kind, observed_date"
        ).fetchall()
        # The complete list also forbids any price alert on B, any other field,
        # a schema-level attribution, or a first-day alert.
        self.assertEqual([(row[0], row[1], row[2]) for row in alerts], [
            ("acceptance-c02:C02-A", "value_swing:price", "2099-02-02"),
        ])
        detail = alerts[0][3]
        self.assertIsInstance(detail, str)
        self.assertRegex(detail, r"(?<![-\d.])10(?:\.0+)?(?![\d.])")
        self.assertRegex(detail, r"(?<![-\d.])40(?:\.0+)?(?![\d.])")


if __name__ == "__main__":
    unittest.main()
