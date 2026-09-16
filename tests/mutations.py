#!/usr/bin/env python3
"""Prove the tests can fail: break one rule in compute.py, or one number in the published data, at a time, and
require the test that guards it to go red. A test that stays green under its own mutation is not guarding anything.

    python3 tests/mutations.py        # exit 0 only if every mutation is caught
"""
import json, os, shutil, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMPUTE = open(os.path.join(ROOT, "scripts", "compute.py"), encoding="utf-8").read()

# (label, exact text in compute.py, replacement, test that must fail)
CODE = [
    ("dual counted as stay", 'if has_d and not has_o:\n        return "stay"', 'if has_d:\n        return "stay"',
     "test_pipeline.TestRules.test_dual_affiliation_is_its_own_outcome"),
    ("single-year visits count as arrivals", "if dur < 2:\n                continue", "if dur < 1:\n                continue",
     "test_pipeline.TestRules.test_single_year_is_a_visit_not_an_arrival"),
    ("first-year affiliation counted as a move", 'if s["cc"] in start_ccs:\n                continue', 'if False:\n                continue',
     "test_pipeline.TestRules.test_already_there_in_the_first_year_is_not_a_move"),
    ("follow-up window ignored", 's["y0"] > cutoff', 's["y0"] > cutoff + 50',
     "test_pipeline.TestRules.test_follow_up_window"),
    ("long stratum starts at 3 years", '"long": (4, 99)', '"long": (3, 99)',
     "test_pipeline.TestRules.test_strata_boundaries"),
    ("ranking by raw rate instead of the Wilson bound", 'key=lambda x: -(x["strata"][DEFAULT_STRATUM]["stay_lb"] or 0)',
     'key=lambda x: -(x["strata"][DEFAULT_STRATUM]["stay"] or 0)', "test_pipeline.TestRules.test_ranking_uses_the_lower_bound_not_the_raw_rate"),
    ("timestamp-only rewrites", '"generated_at": None}} == \\', '"generated_at": 1}} == \\',
     "test_pipeline.TestPublishingGuards.test_idempotent_no_timestamp_only_rewrite"),
    ("partial re-harvest published", "if n_bak > n_cur:", "if n_bak < n_cur:",
     "test_pipeline.TestPublishingGuards.test_backup_with_more_rows_wins"),
]


def data_mutation(fn):
    def apply(d):
        fn(d)
        return d
    return apply


def bump_stay(d):            # outcomes no longer sum to 1
    d["institutions"][0]["strata"]["long"]["stay"] += 0.01
def swap_ranks(d):           # rank order no longer follows the lower bound
    a, b = d["institutions"][0], d["institutions"][-1]
    a["rank"], b["rank"] = b["rank"], a["rank"]
def break_nesting(d):        # short + long != all for one institution
    d["institutions"][0]["strata"]["short"]["n"] += 1
def under_threshold(d):      # a country below the publication floor
    d["countries"][-1]["strata"]["long"]["n"] = 1
def headline_drift(d):       # the README number is no longer what the data says
    us = next(c for c in d["countries"] if c["cc"] == "us")
    us["strata"]["long"]["stay"] = 0.2

DATA = [
    ("outcome fractions do not sum to 1", "cn", bump_stay, "test_published_data.TestEveryOrigin.test_outcomes_sum_to_one_everywhere"),
    ("ranks out of order", "ir", swap_ranks, "test_published_data.TestEveryOrigin.test_ranking_follows_the_wilson_lower_bound"),
    ("strata do not nest", "br", break_nesting, "test_published_data.TestEveryOrigin.test_thresholds_and_strata_nesting"),
    ("country below the floor", "in", under_threshold, "test_published_data.TestEveryOrigin.test_thresholds_and_strata_nesting"),
    ("headline changed", "cn", headline_drift, "test_published_data.TestHeadlineFinding.test_us_four_plus_years"),
]


def run(test, env):
    # PYTHONDONTWRITEBYTECODE: mutants written in the same second with the same size would otherwise reuse the
    # previous mutant's cached bytecode (seen 2026-09-16: one mutant silently ran another's code).
    r = subprocess.run([sys.executable, "-m", "unittest", test], cwd=os.path.join(ROOT, "tests"),
                       env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", **env}, capture_output=True, text=True)
    return r.returncode


def main():
    missed = 0
    # sanity: every targeted test passes on the unmutated code/data, otherwise "caught" means nothing
    for label, _, _, test in CODE:
        if run(test, {}) != 0:
            print(f"BROKEN BASELINE  {test} fails without any mutation"); return 2
    for _, _, _, test in DATA:
        if run(test, {}) != 0:
            print(f"BROKEN BASELINE  {test} fails without any mutation"); return 2
    with tempfile.TemporaryDirectory() as td:
        for k, (label, old, new, test) in enumerate(CODE):
            if COMPUTE.count(old) != 1:
                print(f"STALE MUTATION   {label}: target text not found exactly once in compute.py"); missed += 1; continue
            path = os.path.join(td, f"compute_mut_{k}.py")          # one file per mutant, never reused
            open(path, "w", encoding="utf-8").write(COMPUTE.replace(old, new))
            caught = run(test, {"SOL_COMPUTE": path}) != 0
            missed += not caught
            print(f"{'caught' if caught else 'MISSED'}  compute.py · {label}")
        for label, cc, fn, test in DATA:
            root = os.path.join(td, f"data-{cc}-{fn.__name__}")
            os.makedirs(root)
            for f in os.listdir(ROOT):
                if f.startswith("data-") and f.endswith(".json") or f in ("origins.json", "README.md"):
                    shutil.copy(os.path.join(ROOT, f), root)
            p = os.path.join(root, f"data-{cc}.json")
            d = json.load(open(p)); fn(d); json.dump(d, open(p, "w"))
            caught = run(test, {"SOL_DATA_ROOT": root}) != 0
            missed += not caught
            print(f"{'caught' if caught else 'MISSED'}  data-{cc}.json · {label}")
    total = len(CODE) + len(DATA)
    print(f"\n{total - missed}/{total} mutations caught")
    with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as f:
        if f"{total} mutations" not in f.read():
            print(f"README does not say \"{total} mutations\" — update the Tests section"); return 1
    return 0 if not missed else 1


if __name__ == "__main__":
    sys.exit(main())
