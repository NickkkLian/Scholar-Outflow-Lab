#!/usr/bin/env python3
"""Generate the synthetic pipeline fixture: 200 career records + an institution whitelist + expected counts.

Nothing here comes from OpenAlex. Origin is `xa` (ISO 3166 reserves XA–XZ for private use), author ids are
`A9000001…`, institutions are `Synthetic …`. Destinations use real country codes only because compute.py
labels them.

The generator decides every person's destination, length of stay and final affiliation **itself** and writes
the counts it intended to `expected.json`. The test then runs the real `scripts/compute.py` on the careers
and compares — an independent oracle, not compute.py checking its own output.

    python3 tests/make_fixture.py        # rewrites tests/fixtures/*  (deterministic: same bytes every run)

THIS_YEAR is pinned to 2026 by the test, so the arrival cutoff is 2021.
"""
import json, os, random

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "fixtures")
ORIGIN = "xa"
THIS_YEAR, FOLLOWUP = 2026, 5
CUTOFF = THIS_YEAR - FOLLOWUP                      # arrivals after this year are not counted
STRATA = {"short": (2, 3), "long": (4, 99), "long6": (6, 99), "all": (2, 99)}
OUTCOMES = ("stay", "dual", "ret", "onward")

INSTS = {  # id -> (name, cc, works, type)
    "I9000001": ("Synthetic University North", "us", 90000, "education"),
    "I9000002": ("Synthetic University South", "us", 70000, "education"),
    "I9000003": ("Synthetic Institute of Research", "us", 50000, "facility"),
    "I9000004": ("Synthetic University Lakeside", "ca", 40000, "education"),
    "I9000005": ("Synthetic Home University", ORIGIN, 30000, "education"),
    "I9000006": ("Synthetic Home Institute", ORIGIN, 20000, "facility"),
    "I9000007": ("Synthetic Onward University", "gb", 35000, "education"),
}
HOME = ["I9000005", "I9000006"]
US = ["I9000001", "I9000002", "I9000003"]
CA = ["I9000004"]
THIRD = "I9000007"


def blank():
    return {k: 0 for k in OUTCOMES} | {"n": 0}


def main():
    rng = random.Random(20260916)
    careers = []
    exp_inst = {iid: {s: blank() for s in STRATA} for iid in US + CA}
    exp_ctry = {cc: {s: blank() for s in STRATA} for cc in ("us", "ca")}
    exp_movers = 0
    pid = 0

    def person(spans, field):
        nonlocal pid
        pid += 1
        start = min(s["y0"] for s in spans)
        end = max(s["y1"] for s in spans)
        start_ccs = sorted({s["cc"] for s in spans if s["y0"] == start})
        end_ccs = sorted({s["cc"] for s in spans if s["y1"] == end})
        rec = {"v": 2, "id": f"A9{pid:06d}", "origin_q": ORIGIN, "start": start, "end": end,
               "start_ccs": start_ccs, "end_cc": end_ccs[0], "end_ccs": end_ccs, "works": rng.randint(5, 80),
               "field": field, "spans": spans}
        careers.append(rec)
        return rec

    def span(iid, y0, y1):
        name, cc, _, typ = INSTS[iid]
        return {"id": iid, "name": name, "cc": cc, "type": typ, "y0": y0, "y1": y1}

    fields = ["Computer Science", "Medicine", "Engineering", "Physics and Astronomy"]

    # 1) 30 people who never leave (count toward home_start, not movers)
    for _ in range(30):
        y0 = rng.randint(2000, 2015)
        person([span(rng.choice(HOME), y0, y0 + rng.randint(2, 10))], rng.choice(fields))

    # 2) 160 movers to the US or Canada with a planned duration and a planned final affiliation
    plan = []
    for _ in range(160):
        dest = rng.choices(US + CA, weights=[3, 3, 2, 2])[0]
        dur = rng.choice([2, 3, 4, 4, 5, 5, 6, 7, 9])
        oc = rng.choices(OUTCOMES, weights=[5, 2, 3, 1])[0]
        plan.append((dest, dur, oc))
    for dest, dur, oc in plan:
        y_home = rng.randint(2000, 2010)
        arr = rng.randint(max(y_home + 1, 2005), CUTOFF - 1)   # strictly after home start, within the window
        dep = arr + dur - 1
        home_iid = rng.choice(HOME)
        spans = [span(home_iid, y_home, arr - 1), span(dest, arr, dep)]
        last = max(dep, arr) + 1 + rng.randint(0, 2)
        if oc == "stay":
            spans[1]["y1"] = dep = max(dep, last)                # still at the destination at the end
        elif oc == "dual":
            spans[1]["y1"] = max(dep, last)
            spans.append(span(home_iid, last, last))             # home co-appointment in the final year
        elif oc == "ret":
            spans.append(span(home_iid, dep + 1, dep + 1 + rng.randint(0, 3)))
        else:
            spans.append(span(THIRD, dep + 1, dep + 1 + rng.randint(0, 3)))
        # recompute the planned duration after the edits above
        d = spans[1]["y1"] - spans[1]["y0"] + 1
        person(spans, rng.choice(fields))
        dest_cc = INSTS[dest][1]
        exp_movers += 1
        for s, (lo, hi) in STRATA.items():
            if lo <= d <= hi:
                exp_inst[dest][s]["n"] += 1; exp_inst[dest][s][oc] += 1
                exp_ctry[dest_cc][s]["n"] += 1; exp_ctry[dest_cc][s][oc] += 1

    # 3) 10 records that must NOT count as arrivals, one per rule in compute.py
    y = 2008
    person([span(HOME[0], 2003, 2007), span(US[0], y, y)], "Medicine")                      # single year = visit
    person([span(HOME[0], 2003, 2007), span(US[0], CUTOFF + 1, CUTOFF + 4)], "Medicine")    # arrived inside the follow-up window
    person([span(HOME[0], 2003, 2012), span(US[0], 2003, 2012)], "Medicine")                # already in the US in year one
    person([span(HOME[0], 2003, 2012), span(CA[0], 2003, 2009)], "Engineering")             # already in Canada in year one
    person([span(US[1], 2002, 2004), span(HOME[1], 2006, 2015)], "Engineering")             # started abroad: not a home start
    person([span(US[1], 2002, 2004), span(CA[0], 2006, 2015)], "Engineering")               # never at home at all
    person([span(HOME[0], 2010, 2012), span(US[2], 2008, 2011)], "Physics and Astronomy")   # earliest span is abroad: not a home start
    person([span(HOME[1], 2004, 2010), span(HOME[0], 2011, 2016)], "Medicine")              # moved within the origin
    person([span(HOME[1], 2004, 2010), span(US[0], 2012, 2012), span(US[1], 2014, 2014)], "Medicine")  # two single years
    person([span(HOME[1], 2004, 2009), span(CA[0], CUTOFF + 2, CUTOFF + 3)], "Medicine")    # too recent to judge

    rng.shuffle(careers)
    assert len(careers) == 200, len(careers)
    home_start = sum(1 for r in careers if ORIGIN in r["start_ccs"])

    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, f"careers_{ORIGIN}.jsonl"), "w") as f:
        for r in careers:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
    wl = {iid: {"name": n, "ror": f"synthetic-{iid[-2:]}", "cc": cc, "works": w, "type": t}
          for iid, (n, cc, w, t) in INSTS.items()}
    with open(os.path.join(OUT, "institutions.json"), "w") as f:
        json.dump(wl, f, ensure_ascii=False, indent=1, sort_keys=True)
    with open(os.path.join(OUT, "expected.json"), "w") as f:
        json.dump({"origin": ORIGIN, "this_year": THIS_YEAR, "sampled": len(careers), "home_start": home_start,
                   "movers": exp_movers, "institutions": exp_inst, "countries": exp_ctry},
                  f, indent=1, sort_keys=True)
    print(f"wrote {len(careers)} careers ({home_start} home starts, {exp_movers} planned movers) to {OUT}")


if __name__ == "__main__":
    main()
