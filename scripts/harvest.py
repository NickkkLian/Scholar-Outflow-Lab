#!/usr/bin/env python3
"""
Sample researchers' institutional careers from OpenAlex into JSONL for the mobility metrics.

Source: OpenAlex (https://openalex.org) — CC0 public domain, no API key; a mailto gets you into
the polite pool. Zero cost: no money, no account.

Usage:
    python3 harvest.py cn --seeds 20            # sample researchers with a Chinese affiliation history
    python3 harvest.py cn in ir --seeds 20      # several origin countries
    python3 harvest.py cn --seeds 24 --refresh  # re-harvest an outdated file from scratch (backs up to .v1.bak first)

Each seed draws 10,000 people (the OpenAlex sample cap); seeds overlap, so records are de-duplicated
by author id. Output: data/careers_<country>.jsonl — safe to re-run, it resumes with the seeds not
yet completed.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.openalex.org/authors"
# Polite-pool contact address: not a credential, but **kept out of the public repo**.
# Pass it via the environment:
#   export OPENALEX_MAILTO=you@example.com
# Runs without it too, just on the public pool with stricter rate limits.
MAILTO = os.environ.get("OPENALEX_MAILTO", "")
SAMPLE = 10000          # OpenAlex per-sample cap
PER_PAGE = 200          # per-page cap
MIN_WORKS = 5           # fewer than 5 works is mostly noise / leftovers of merged namesakes
DATA_VERSION = 2        # v2: field by vote over all topics; v1 used topics[0] only
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
DATA = os.path.join(ROOT, "data")

SELECT = "id,display_name,affiliations,last_known_institutions,works_count,topics"


UA = f"mobility-lab (mailto:{MAILTO})" if MAILTO else "mobility-lab"


class BudgetExhausted(Exception):
    """The OpenAlex free quota is spent (1,000 requests/day, resets at 00:00 UTC)."""


def fetch(params, tries=3):
    if not MAILTO:
        params.pop("mailto", None)
    url = API + "?" + urllib.parse.urlencode(params)
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                # Two kinds of 429: a transient rate limit (wait a moment) and the daily quota
                # being spent (wait until 00:00 UTC). Retrying the latter is pointless; exit
                # cleanly instead, or the seed gets mis-marked as completed.
                retry_after = int(e.headers.get("retry-after") or 0)
                if retry_after > 600:
                    raise BudgetExhausted(f"daily quota spent; resets in {retry_after//3600} h (00:00 UTC)")
                time.sleep(min(retry_after or 30, 120))
                continue
            if attempt == tries - 1:
                print(f"    ! giving up: {e}", flush=True)
                return None
            time.sleep(2 ** attempt * 2)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            if attempt == tries - 1:
                print(f"    ! giving up: {e}", flush=True)
                return None
            time.sleep(2 ** attempt * 2)
    return None


def career(author, origin_cc):
    """Compress one author into a career record. Affiliations without years are dropped —
    no year means no ordering."""
    spans = []
    for a in author.get("affiliations") or []:
        inst = a.get("institution") or {}
        years = [y for y in (a.get("years") or []) if isinstance(y, int)]
        cc = (inst.get("country_code") or "").lower()
        if not years or not inst.get("id") or not cc:
            continue
        spans.append({
            "id": inst["id"].rsplit("/", 1)[-1],
            "name": inst.get("display_name") or "",
            "cc": cc,
            "type": inst.get("type") or "",
            "y0": min(years),
            "y1": max(years),
        })
    if not spans:
        return None

    start = min(s["y0"] for s in spans)
    end = max(s["y1"] for s in spans)
    # Starting countries: the countries of the earliest-year affiliations. Several are kept if
    # they span countries; downstream tests "does it include the origin".
    start_ccs = sorted({s["cc"] for s in spans if s["y0"] == start})
    # Ending country: the latest-year batch. last_known (OpenAlex's own judgement) takes
    # precedence, else the latest year.
    last_known = [
        (i.get("country_code") or "").lower()
        for i in (author.get("last_known_institutions") or [])
        if i.get("country_code")
    ]
    end_ccs = sorted({s["cc"] for s in spans if s["y1"] == end})
    end_cc = last_known[0] if last_known else (end_ccs[0] if end_ccs else "")

    # Field: **vote by count over all topics**, not topics[0].
    # v1 took the first topic's field, which pushed much of computer science into
    # "Engineering" — OpenAlex's topic ordering isn't guaranteed to be representative, so a
    # single topic is too brittle. The top three are kept alongside for later checks on
    # whether someone is interdisciplinary.
    topics = author.get("topics") or []
    votes = {}
    for t in topics[:25]:
        f = (t.get("field") or {}).get("display_name")
        if f:
            votes[f] = votes.get(f, 0) + (t.get("count") or 1)
    field = max(votes, key=votes.get) if votes else ""
    top_fields = sorted(votes.items(), key=lambda x: -x[1])[:3]

    return {
        "v": 2,                          # data version: v2 = voted field, v1 = topics[0]
        "id": author["id"].rsplit("/", 1)[-1],
        "origin_q": origin_cc,           # the origin filter used when sampling
        "start": start,
        "end": end,
        "start_ccs": start_ccs,
        "end_cc": end_cc,
        "end_ccs": end_ccs,
        "works": author.get("works_count") or 0,
        "field": field,
        "top_fields": top_fields,
        "spans": spans,
    }


def needs_refresh(out_path):
    """Is the existing file an old version (v1: field = topics[0], not a vote)?

    Only the first line is checked — a file never mixes versions, because a refresh always
    starts over from scratch.
    """
    if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
        return False
    with open(out_path) as f:
        line = f.readline()
    try:
        return json.loads(line).get("v", 1) < DATA_VERSION
    except json.JSONDecodeError:
        return False


def harvest(cc, seeds, refresh=False):
    os.makedirs(DATA, exist_ok=True)
    out_path = os.path.join(DATA, f"careers_{cc}.jsonl")
    state_path = os.path.join(DATA, f"careers_{cc}.state.json")

    if refresh and needs_refresh(out_path):
        # ⚠️ Without a refresh, the old state file marks every seed "done" and the whole run is
        # skipped — the new fields would never be filled in. Back the old file up instead of
        # deleting it: a re-harvest spans days and must stay reversible mid-way.
        bak = out_path + ".v1.bak"
        os.replace(out_path, bak)
        if os.path.exists(state_path):
            os.replace(state_path, state_path + ".v1.bak")
        print(f"[{cc}] v1 data detected; backed up to {os.path.basename(bak)}, re-harvesting as v{DATA_VERSION}", flush=True)

    seen, done_seeds = set(), set()
    if os.path.exists(out_path):
        with open(out_path) as f:
            for line in f:
                try:
                    seen.add(json.loads(line)["id"])
                except Exception:
                    pass
    if os.path.exists(state_path):
        done_seeds = set(json.load(open(state_path)).get("seeds", []))
    print(f"[{cc}] {len(seen)} authors on file, seeds completed: {sorted(done_seeds)}", flush=True)

    out = open(out_path, "a")
    for seed in range(1, seeds + 1):
        if seed in done_seeds:
            continue
        added, pages_ok = 0, 0
        for page in range(1, SAMPLE // PER_PAGE + 1):
            d = fetch({
                "filter": f"affiliations.institution.country_code:{cc},works_count:>{MIN_WORKS - 1}",
                "sample": SAMPLE, "seed": seed, "per-page": PER_PAGE, "page": page,
                "select": SELECT, "mailto": MAILTO,
            })
            if d is None:
                break
            rows = d.get("results") or []
            pages_ok += 1
            if not rows:
                break
            for a in rows:
                aid = (a.get("id") or "").rsplit("/", 1)[-1]
                if not aid or aid in seen:
                    continue
                rec = career(a, cc)
                if rec:
                    seen.add(aid)
                    out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    added += 1
            time.sleep(0.2)
        out.flush()
        # ⚠️ A seed only counts as done when every page came back.
        # An earlier version marked it done regardless; one rate-limited run flagged six seeds
        # as "completed, 0 people", and resumes skipped them forever — the data never came back.
        if pages_ok == SAMPLE // PER_PAGE:
            done_seeds.add(seed)
            json.dump({"seeds": sorted(done_seeds)}, open(state_path, "w"))
            print(f"[{cc}] seed {seed} +{added} authors, total {len(seen)}", flush=True)
        else:
            print(f"[{cc}] seed {seed} fetched only {pages_ok}/{SAMPLE // PER_PAGE} pages; not marked done, "
                  f"will resume next run (+{added} this round)", flush=True)
    out.close()
    return len(seen)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    seeds = 20
    if "--seeds" in sys.argv:
        seeds = int(sys.argv[sys.argv.index("--seeds") + 1])
        args = [a for a in args if a != str(seeds)]
    refresh = "--refresh" in sys.argv
    if not args:
        print(__doc__)
        sys.exit(1)
    for cc in args:
        if cc.isdigit():
            continue
        try:
            n = harvest(cc.lower(), seeds, refresh)
            print(f"[{cc}] done, {n} authors -> data/careers_{cc}.jsonl", flush=True)
        except BudgetExhausted as e:
            print(f"\n⛔ {e}\n   Everything fetched so far is on disk; re-run the same command once the quota resets and it resumes.", flush=True)
            sys.exit(2)
