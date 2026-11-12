#!/usr/bin/env python3
"""A 30-second, realistic multi-source verification example.

You track two products across three retailer sites. On day 2:
  - site-b's scraper mis-parses a decimal: 49 becomes 490 (a 10x error);
  - site-c silently stops outputting the stock column;
  - "Nova Fan" is only reported by site-a (a lone claim).

Run:  python examples/cross_check_prices/run_example.py
It builds the sources in a temp dir, imports them, and cross-checks — no data
of your own needed. Everything is synthetic (year 2099).
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "src"))

from indiebiz_evidence import generic, store  # noqa: E402

SOURCES = {
    "site-a": {
        "2099-01-01": "id,price,stock\nAurora Lamp,49,in_stock\nNova Fan,29,in_stock\n",
        "2099-01-02": "id,price,stock\nAurora Lamp,49,in_stock\nNova Fan,29,in_stock\n",
    },
    "site-b": {
        "2099-01-01": "id,price,stock\nAurora Lamp,49,in_stock\n",
        # decimal mis-parse: 49 -> 490
        "2099-01-02": "id,price,stock\nAurora Lamp,490,in_stock\n",
    },
    "site-c": {
        "2099-01-01": "id,price,stock\nAurora Lamp,49,in_stock\n",
        # stock column silently dropped on day 2
        "2099-01-02": "id,price\nAurora Lamp,49\n",
    },
}


def main():
    tmp = tempfile.mkdtemp(prefix="ibe-example-")
    con = store.connect(os.path.join(tmp, "example.db"))
    store.init_db(con)
    for name, days in SOURCES.items():
        d = os.path.join(tmp, name)
        os.makedirs(d)
        for day, body in days.items():
            with open(os.path.join(d, day + ".csv"), "w", encoding="utf-8", newline="") as f:
                f.write(body)
        generic.import_path(con, name, d, verbose=False)

    print("Scenario: Aurora Lamp tracked by 3 sites; on day 2 site-b mis-parses 49 as 490,")
    print("site-c drops the stock column, and Nova Fan is only reported by site-a.\n")

    for ent in ("Aurora Lamp", "Nova Fan"):
        r = generic.cross_check(con, ent)
        print("=" * 64)
        print("cross_check: %s   (sources: %s)" % (ent, ", ".join(r["sources_compared"])))
        for fld, e in r["fields"].items():
            print("  %-8s -> %s  (%d distinct sources)" % (fld, e["verdict"], e["reported_by"]))
            for v in e["values"]:
                for o in v["observations"]:
                    print("      %-8s from %-7s @ %s" % (o["text"], o["source"], o["date"]))
            if e.get("not_reporting"):
                print("      not reporting: %s  (absent, NOT zero)" % ", ".join(e["not_reporting"]))
        print()

    print("Read it:")
    print("  * Aurora price DIFFERS: 49 (site-a, site-c) vs 490 (site-b). That 10x jump is")
    print("    almost certainly a scraper decimal error -- check site-b before believing 490.")
    print("  * Aurora stock: site-c stopped reporting it. Absent, not zero.")
    print("  * Nova Fan is a LONE CLAIM (only site-a). Not cross-verified.")
    con.close()


if __name__ == "__main__":
    main()