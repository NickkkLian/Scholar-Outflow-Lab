"""Invariants on the data the live site actually serves: every data-<cc>.json in data/ and data/origins.json.

These run on the real 13-origin output, not a fixture, so a bad recompute is caught before it is published.
"""
import glob
import json
import os
import re
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.environ.get("SOL_DATA_ROOT") or os.path.join(REPO, "data")  # mutations.py points this at broken copies
OUTCOMES = ("stay", "dual", "ret", "onward")
ROUNDING = 4 * 0.00005 + 1e-9        # four fractions each rounded to 4 decimals


def origins_on_disk():
    return sorted(re.fullmatch(r"data-([a-z]{2})\.json", os.path.basename(p)).group(1)
                  for p in glob.glob(os.path.join(ROOT, "data-??.json")))


def load(cc):
    with open(os.path.join(ROOT, f"data-{cc}.json")) as f:
        return json.load(f)


class TestManifest(unittest.TestCase):

    def test_manifest_matches_files(self):
        with open(os.path.join(ROOT, "origins.json")) as f:
            man = json.load(f)["origins"]
        self.assertEqual(sorted(o["cc"] for o in man), origins_on_disk())
        self.assertGreaterEqual(len(man), 13)

    def test_manifest_numbers_match_each_file(self):
        with open(os.path.join(ROOT, "origins.json")) as f:
            manifest = json.load(f)["origins"]
        for o in manifest:
            d = load(o["cc"])
            m = d["meta"]
            with self.subTest(cc=o["cc"]):
                self.assertEqual(o["sampled"], m["sampled_authors"])
                self.assertEqual(o["home"], m["home_start_authors"])
                self.assertEqual(o["movers"], m["movers"])
                self.assertEqual(o["institutions"], len(d["institutions"]))


class TestEveryOrigin(unittest.TestCase):

    def each(self):
        for cc in origins_on_disk():
            yield cc, load(cc)

    def check_block(self, where, b):
        if not b["n"]:
            return
        total = sum(b[k] for k in OUTCOMES)
        self.assertLessEqual(abs(total - 1), ROUNDING, f"{where}: outcomes sum to {total}")
        for k in OUTCOMES:
            self.assertTrue(0 <= b[k] <= 1, f"{where}: {k}={b[k]}")
        lo, hi = b["stay_ci"]
        self.assertTrue(lo - 1e-9 <= b["stay"] <= hi + 1e-9, f"{where}: stay {b['stay']} outside CI {b['stay_ci']}")
        self.assertEqual(b["stay_lb"], lo)

    def test_outcomes_sum_to_one_everywhere(self):
        blocks = 0
        for cc, d in self.each():
            for c in d["countries"]:
                for s, b in c["strata"].items():
                    self.check_block(f"{cc}→{c['cc']}/{s}", b); blocks += 1
            for i in d["institutions"]:
                for s, b in i["strata"].items():
                    self.check_block(f"{cc}→{i['id']}/{s}", b); blocks += 1
                for s, fl in i.get("fields", {}).items():
                    for f in fl:
                        self.check_block(f"{cc}→{i['id']}/{s}/{f['field_en']}", f); blocks += 1
        self.assertGreater(blocks, 1000, "suspiciously few blocks checked")

    def test_ranking_follows_the_wilson_lower_bound(self):
        for cc, d in self.each():
            default = d["meta"]["default_stratum"]
            insts = sorted(d["institutions"], key=lambda x: x["rank"])
            with self.subTest(cc=cc):
                self.assertEqual([i["rank"] for i in insts], list(range(1, len(insts) + 1)))
                lbs = [i["strata"][default]["stay_lb"] or 0 for i in insts]
                self.assertEqual(lbs, sorted(lbs, reverse=True))
                n = len(insts)
                for pos, i in enumerate(insts):
                    q = pos / n
                    want = "R1" if q < 0.25 else "R2" if q < 0.5 else "R3" if q < 0.75 else "R4"
                    self.assertEqual(i["tier"], want, i["id"])

    def test_thresholds_and_strata_nesting(self):
        for cc, d in self.each():
            m = d["meta"]
            default = m["default_stratum"]
            with self.subTest(cc=cc):
                for i in d["institutions"]:
                    s = {k: v["n"] for k, v in i["strata"].items()}
                    self.assertGreaterEqual(s[default], m["min_n_inst"])
                    # each span lands in exactly one of short/long, and always in all
                    self.assertEqual(s["short"] + s["long"], s["all"], i["id"])
                    self.assertLessEqual(s["long6"], s["long"])
                for c in d["countries"]:
                    s = {k: v["n"] for k, v in c["strata"].items()}
                    self.assertGreaterEqual(s[default], m["min_n_country"])
                    # a person counts once per country per stratum, but may appear in both short and long
                    self.assertLessEqual(max(s["short"], s["long"]), s["all"], c["cc"])
                    self.assertLessEqual(s["all"], s["short"] + s["long"], c["cc"])
                    self.assertLessEqual(s["long6"], s["long"])
                ns = [c["strata"][default]["n"] for c in d["countries"]]
                self.assertEqual(ns, sorted(ns, reverse=True))

    def test_meta_is_consistent(self):
        for cc, d in self.each():
            m = d["meta"]
            with self.subTest(cc=cc):
                self.assertEqual(m["origin"], cc)
                self.assertLessEqual(m["movers"], m["home_start_authors"])
                self.assertLessEqual(m["home_start_authors"], m["sampled_authors"])
                self.assertEqual(m["mover_rate"], round(m["movers"] / m["home_start_authors"], 4))
                self.assertEqual(m["arrival_year_cutoff"] + m["followup_years"] >= 2026, True)


class TestHeadlineFinding(unittest.TestCase):
    """The README table and the site's first screen quote these numbers; they must be what the data says."""

    # stored fraction, n — the page shows (v*100).toFixed(1), so 0.5245 displays as 52.4%
    HEADLINE = [("ir", 0.7452, 3006), ("in", 0.5245, 3926), ("br", 0.4022, 1442), ("cn", 0.1908, 8610)]

    def test_us_four_plus_years(self):
        for cc, stay, n in self.HEADLINE:
            us = next(c for c in load(cc)["countries"] if c["cc"] == "us")["strata"]["long"]
            with self.subTest(cc=cc):
                self.assertEqual((us["stay"], us["n"]), (stay, n))

    def test_readme_quotes_the_same_numbers(self):
        with open(os.path.join(REPO, "README.md"), encoding="utf-8") as f:
            readme = f.read()
        for cc, stay, n in self.HEADLINE:
            with self.subTest(cc=cc):
                self.assertIn(f"| {stay * 100:.1f}% | {n:,} |", readme)


if __name__ == "__main__":
    unittest.main()
