"""The real scripts/compute.py, run on a synthetic fixture, against counts the fixture generator planned itself.

Standard library only (unittest), like the rest of the pipeline:  python3 -m unittest discover -s tests -v
"""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "tests", "fixtures")
BREAK = os.environ.get("SOL_BREAK") == "1"


def read_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_compute():
    path = os.environ.get("SOL_COMPUTE") or os.path.join(ROOT, "scripts", "compute.py")   # tests/mutations.py swaps in broken copies
    spec = importlib.util.spec_from_file_location("compute_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Sandbox:
    """compute.py reads DATA/ and writes WEB/ through module globals; point both at a temp dir."""

    def __init__(self, careers_lines, this_year=2026, min_inst=None, min_country=None, whitelist=None):
        self.dir = tempfile.mkdtemp(prefix="sol-test-")
        self.data = os.path.join(self.dir, "data")
        self.web = os.path.join(self.dir, "web")
        os.makedirs(self.data)
        os.makedirs(self.web)
        with open(os.path.join(self.data, "careers_xa.jsonl"), "w") as f:
            f.writelines(line if line.endswith("\n") else line + "\n" for line in careers_lines)
        wl_src = whitelist if whitelist is not None else read_json(os.path.join(FIX, "institutions.json"))
        with open(os.path.join(self.data, "institutions.json"), "w") as f:
            json.dump(wl_src, f)
        self.c = load_compute()
        self.c.DATA, self.c.WEB, self.c.THIS_YEAR = self.data, self.web, this_year
        if min_inst is not None:
            self.c.MIN_N_INST = min_inst
        if min_country is not None:
            self.c.MIN_N_COUNTRY = min_country

    def build(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            result = self.c.build("xa")
        return result, out.getvalue()

    def close(self):
        shutil.rmtree(self.dir, ignore_errors=True)


def fixture_lines():
    lines = read_text(os.path.join(FIX, "careers_xa.jsonl")).splitlines()
    if BREAK:
        # --break: move one planned "stay" person's final affiliation back home. The generator's plan no longer
        # matches the data, so the oracle comparison must fail.
        for i, line in enumerate(lines):
            r = json.loads(line)
            dest = [s for s in r["spans"] if s["cc"] in ("us", "ca")]
            if len(r["spans"]) == 2 and dest and r["end_ccs"] == [dest[0]["cc"]] and "xa" in r["start_ccs"]:
                r["spans"].append({**r["spans"][0], "y0": r["end"] + 1, "y1": r["end"] + 1})
                r["end"] += 1
                r["end_ccs"] = ["xa"]
                r["end_cc"] = "xa"
                lines[i] = json.dumps(r, sort_keys=True)
                break
    return lines


def rec(spans, **kw):
    start = min(s["y0"] for s in spans)
    end = max(s["y1"] for s in spans)
    end_ccs = sorted({s["cc"] for s in spans if s["y1"] == end})
    r = {"v": 2, "id": kw.get("id", "A9999999"), "start": start, "end": end,
         "start_ccs": sorted({s["cc"] for s in spans if s["y0"] == start}),
         "end_cc": end_ccs[0], "end_ccs": end_ccs, "works": 10, "field": kw.get("field", "Medicine"), "spans": spans}
    return json.dumps(r)


def sp(iid, cc, y0, y1):
    return {"id": iid, "name": iid, "cc": cc, "type": "education", "y0": y0, "y1": y1}


class TestFixtureAgainstPlan(unittest.TestCase):
    """200 synthetic careers → compute.build() → every published count equals the generator's plan."""

    @classmethod
    def setUpClass(cls):
        cls.expected = read_json(os.path.join(FIX, "expected.json"))
        cls.box = Sandbox(fixture_lines(), this_year=cls.expected["this_year"])
        cls.out, cls.log = cls.box.build()

    @classmethod
    def tearDownClass(cls):
        cls.box.close()

    def test_population_counts(self):
        m = self.out["meta"]
        self.assertEqual(m["sampled_authors"], self.expected["sampled"])
        self.assertEqual(m["home_start_authors"], self.expected["home_start"])
        self.assertEqual(m["movers"], self.expected["movers"])
        self.assertEqual(m["arrival_year_cutoff"], self.expected["this_year"] - 5)

    def test_institution_counts_match_plan(self):
        published = {i["id"]: i for i in self.out["institutions"]}
        floor = self.box.c.MIN_N_INST
        checked = 0
        for iid, strata in self.expected["institutions"].items():
            if strata["long"]["n"] < floor:
                self.assertNotIn(iid, published, f"{iid} has {strata['long']['n']} < {floor} and must not be published")
                continue
            self.assertIn(iid, published)
            for s, want in strata.items():
                got = published[iid]["strata"][s]
                self.assertEqual(got["n"], want["n"], f"{iid}/{s} n")
                for oc in ("stay", "dual", "ret", "onward"):
                    frac = round(want[oc] / want["n"], 4) if want["n"] else None
                    self.assertEqual(got[oc], frac, f"{iid}/{s} {oc}")
            checked += 1
        self.assertGreaterEqual(checked, 3, "the fixture must exercise at least three published institutions")

    def test_country_counts_match_plan(self):
        published = {c["cc"]: c for c in self.out["countries"]}
        floor = self.box.c.MIN_N_COUNTRY
        for cc, strata in self.expected["countries"].items():
            if strata["long"]["n"] < floor:
                self.assertNotIn(cc, published)
                continue
            for s, want in strata.items():
                got = published[cc]["strata"][s]
                self.assertEqual(got["n"], want["n"], f"{cc}/{s} n")
                self.assertEqual(got["stay"], round(want["stay"] / want["n"], 4) if want["n"] else None)

    def test_manifest_written(self):
        man = read_json(os.path.join(self.box.web, "origins.json"))["origins"]
        self.assertEqual([o["cc"] for o in man], ["xa"])
        self.assertEqual(man[0]["institutions"], len(self.out["institutions"]))


class TestRules(unittest.TestCase):
    """One record per rule in compute.py, with thresholds lowered to 1 so a single person is visible."""

    def run_one(self, *lines, this_year=2026):
        box = Sandbox(list(lines), this_year=this_year, min_inst=1, min_country=1,
                      whitelist={"IUS1": {"name": "US one", "ror": "x", "cc": "us", "works": 1, "type": "education"},
                                 "IUS2": {"name": "US two", "ror": "x", "cc": "us", "works": 1, "type": "education"}})
        try:
            out, _ = box.build()
        finally:
            box.close()
        return out

    def inst(self, out, iid):
        return next((i for i in out["institutions"] if i["id"] == iid), None)

    def test_dual_affiliation_is_its_own_outcome(self):
        out = self.run_one(rec([sp("IH", "xa", 2005, 2009), sp("IUS1", "us", 2010, 2016), sp("IH", "xa", 2016, 2016)]))
        s = self.inst(out, "IUS1")["strata"]["long"]
        self.assertEqual((s["n"], s["dual"], s["stay"]), (1, 1.0, 0.0))

    def test_stay_ret_onward(self):
        out = self.run_one(
            rec([sp("IH", "xa", 2005, 2009), sp("IUS1", "us", 2010, 2016)], id="A1"),
            rec([sp("IH", "xa", 2005, 2009), sp("IUS1", "us", 2010, 2014), sp("IH", "xa", 2015, 2016)], id="A2"),
            rec([sp("IH", "xa", 2005, 2009), sp("IUS1", "us", 2010, 2014), sp("IGB", "gb", 2015, 2016)], id="A3"))
        s = self.inst(out, "IUS1")["strata"]["long"]
        self.assertEqual(s["n"], 3)
        self.assertEqual([s["stay"], s["ret"], s["onward"], s["dual"]], [0.3333, 0.3333, 0.3333, 0.0])

    def test_single_year_is_a_visit_not_an_arrival(self):
        out = self.run_one(rec([sp("IH", "xa", 2005, 2009), sp("IUS1", "us", 2012, 2012)]))
        self.assertEqual(out["meta"]["movers"], 0)
        self.assertIsNone(self.inst(out, "IUS1"))

    def test_strata_boundaries(self):
        out = self.run_one(
            rec([sp("IH", "xa", 2000, 2004), sp("IUS1", "us", 2005, 2007)], id="A3y"),   # 3 years
            rec([sp("IH", "xa", 2000, 2004), sp("IUS1", "us", 2005, 2008)], id="A4y"),   # 4 years
            rec([sp("IH", "xa", 2000, 2004), sp("IUS1", "us", 2005, 2010)], id="A6y"))   # 6 years
        s = self.inst(out, "IUS1")["strata"]
        self.assertEqual({k: v["n"] for k, v in s.items()}, {"short": 1, "long": 2, "long6": 1, "all": 3})

    def test_follow_up_window(self):
        # this_year 2026 → cutoff 2021: an arrival in 2021 counts, 2022 does not
        out = self.run_one(rec([sp("IH", "xa", 2010, 2020), sp("IUS1", "us", 2021, 2025)], id="A21"),
                           rec([sp("IH", "xa", 2010, 2021), sp("IUS2", "us", 2022, 2026)], id="A22"))
        self.assertIsNotNone(self.inst(out, "IUS1"))
        self.assertIsNone(self.inst(out, "IUS2"))

    def test_already_there_in_the_first_year_is_not_a_move(self):
        out = self.run_one(rec([sp("IH", "xa", 2005, 2015), sp("IUS1", "us", 2005, 2015)]))
        self.assertEqual(out["meta"]["home_start_authors"], 1)
        self.assertEqual(out["meta"]["movers"], 0)

    def test_started_abroad_is_outside_the_frame(self):
        out = self.run_one(rec([sp("IUS1", "us", 2003, 2006), sp("IH", "xa", 2007, 2015)]))
        self.assertEqual(out["meta"]["home_start_authors"], 0)

    def test_country_counts_a_person_once_institutions_count_spans(self):
        out = self.run_one(rec([sp("IH", "xa", 2000, 2004), sp("IUS1", "us", 2005, 2009), sp("IUS2", "us", 2010, 2016)]))
        us = next(c for c in out["countries"] if c["cc"] == "us")
        self.assertEqual(us["strata"]["long"]["n"], 1)
        self.assertEqual(self.inst(out, "IUS1")["strata"]["long"]["n"] + self.inst(out, "IUS2")["strata"]["long"]["n"], 2)

    def test_ranking_uses_the_lower_bound_not_the_raw_rate(self):
        # IUS1: 10 of 25 stayed (40%, Wilson lower bound 0.234). IUS2: 90 of 300 stayed (30%, lower bound 0.251).
        # Ranked by raw rate IUS1 would be first; ranked by the bound, the small sample sinks below the large one.
        lines, k = [], 0
        for iid, stayed, n in (("IUS1", 10, 25), ("IUS2", 90, 300)):
            for j in range(n):
                k += 1
                tail = [] if j < stayed else [sp("IH", "xa", 2016, 2016)]
                y1 = 2016 if j < stayed else 2015
                lines.append(rec([sp("IH", "xa", 2005, 2009), sp(iid, "us", 2010, y1)] + tail, id=f"A{k:07d}"))
        out = self.run_one(*lines)
        order = [i["id"] for i in sorted(out["institutions"], key=lambda i: i["rank"])]
        self.assertEqual(order, ["IUS2", "IUS1"])
        self.assertEqual([self.inst(out, "IUS1")["strata"]["long"]["stay"], self.inst(out, "IUS2")["strata"]["long"]["stay"]], [0.4, 0.3])

    def test_non_whitelisted_institution_is_dropped_but_country_still_counts(self):
        out = self.run_one(rec([sp("IH", "xa", 2000, 2004), sp("IZZ", "us", 2005, 2012)]))
        self.assertEqual(out["institutions"], [])
        self.assertEqual(next(c for c in out["countries"] if c["cc"] == "us")["strata"]["long"]["n"], 1)


class TestPublishingGuards(unittest.TestCase):

    def test_idempotent_no_timestamp_only_rewrite(self):
        box = Sandbox(read_text(os.path.join(FIX, "careers_xa.jsonl")).splitlines())
        try:
            box.build()
            path = os.path.join(box.web, "data-xa.json")
            with open(path, "rb") as f:
                first = f.read()
            _, log = box.build()
            self.assertIn("no substantive change", log)
            with open(path, "rb") as f:
                self.assertEqual(f.read(), first)
        finally:
            box.close()

    def test_backup_with_more_rows_wins(self):
        lines = read_text(os.path.join(FIX, "careers_xa.jsonl")).splitlines()
        box = Sandbox(lines[:20])
        try:
            with open(os.path.join(box.data, "careers_xa.jsonl.v1.bak"), "w") as f:
                f.write("\n".join(lines) + "\n")
            out, log = box.build()
            self.assertIn("publishing from the backup", log)
            self.assertEqual(out["meta"]["sampled_authors"], len(lines))
        finally:
            box.close()

    def test_wilson_interval(self):
        c = load_compute()
        self.assertIsNone(c.wilson(0, 0))
        lo, hi = c.wilson(0, 10)
        self.assertEqual(lo, 0.0)
        lo, hi = c.wilson(10, 10)
        self.assertEqual(hi, 1.0)
        lo, hi = c.wilson(35, 38)                       # a published row: 92.11% of 38 → [0.792, 0.9728]
        self.assertEqual([lo, hi], [0.792, 0.9728])
        self.assertLess(c.wilson(10, 25)[0], c.wilson(90, 300)[0])   # 40% of 25 ranks below 30% of 300


if __name__ == "__main__":
    unittest.main()
