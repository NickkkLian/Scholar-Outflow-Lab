#!/usr/bin/env python3
"""
Build a whitelist of real research institutions — universities plus research institutes.

Why it's needed: OpenAlex parses institutions out of free-text affiliation strings, and generic
names like "Capital University" / "Bridge University" / "Zero to Three" get matched to entirely
unrelated entities. Without a filter, the board fills up with junk. Anything with a ROR ID and a
meaningful publication count can reasonably be treated as a real institution.

⚠️ Since 2026-07-26 research institutes (facility/government/nonprofit/healthcare) are included
   too — CAS, CNRS, NIH, Academia Sinica, the Max Planck institutes are major destinations for
   research mobility, and type=education alone drops the whole category.
   But these types carry **noticeably more matching noise**: "Ministry of Education" alone was
   matched to 37 "Chinese researchers who moved there" in each of Romania, Ethiopia and
   Bangladesh — the phrase appears in the affiliation string and gets attached to a random
   namesake. Two countermeasures: ① a **higher output threshold** for non-university types;
   ② a blacklist of generic names (GENERIC_NAMES below).
   Some will still slip through, so the output keeps `type`; the front end offers a
   "universities only / include institutes" filter and the methodology page says so plainly.

Output: data/institutions.json  {id: {name, cc, ror, works, type}}
"""

import json
import os
import time
import urllib.parse
import urllib.request

API = "https://api.openalex.org/institutions"
MAILTO = os.environ.get("OPENALEX_MAILTO", "")   # see harvest.py: kept out of the public repo
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
DATA = os.path.join(ROOT, "data")

# Low bar for universities (names are rarely ambiguous), high bar for institutes (noisy matches)
EDU_TYPES = {"education"}
INST_TYPES = {"facility", "government", "nonprofit", "healthcare"}
MIN_WORKS_EDU = 500
MIN_WORKS_INST = 3000

# Generic-name blacklist: these aren't institution names, they're common phrases inside
# affiliation strings that OpenAlex matched to random entities. The test is "the whole name
# equals the phrase" — not fuzzy containment, which would also kill real entities such as
# "Ministry of Education, Culture, Sports, Science and Technology (Japan)".
GENERIC_NAMES = {
    "ministry of education", "ministry of health", "ministry of science and technology",
    "ministry of agriculture", "department of health", "department of education",
    "national clinical research", "clinical research center", "research center",
    "research institute", "national research council", "academy of medical sciences",
    "division of materials science and engineering", "school of medicine",
    "graduate school", "medical school", "university hospital", "general hospital",
}


def is_generic(name):
    n = (name or "").strip().lower().rstrip(".")
    return n in GENERIC_NAMES


def fetch_group(types, min_works, out, label):
    cursor, page, added, dropped = "*", 0, 0, 0
    type_filter = "|".join(sorted(types))
    while cursor:
        params = {
            "filter": f"type:{type_filter},works_count:>{min_works}",
            "per-page": 200, "cursor": cursor,
            "select": "id,display_name,country_code,ror,works_count,type",
        }
        if MAILTO:
            params["mailto"] = MAILTO
        url = API + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(
            url, headers={"User-Agent": f"mobility-lab (mailto:{MAILTO})" if MAILTO else "mobility-lab"})
        with urllib.request.urlopen(req, timeout=90) as r:
            d = json.loads(r.read().decode())
        for i in d.get("results") or []:
            if not i.get("ror"):
                continue          # no ROR usually means a phantom parsed out of a string
            if is_generic(i.get("display_name")):
                dropped += 1
                continue
            out[i["id"].rsplit("/", 1)[-1]] = {
                "name": i.get("display_name") or "",
                "cc": (i.get("country_code") or "").lower(),
                "ror": i["ror"].rsplit("/", 1)[-1],
                "works": i.get("works_count") or 0,
                "type": i.get("type") or "",
            }
            added += 1
        cursor = d["meta"].get("next_cursor")
        page += 1
        if page % 10 == 0:
            print(f"  [{label}] {page} pages / {len(out)} institutions so far", flush=True)
        time.sleep(0.15)
    print(f"  [{label}] kept {added}, dropped {dropped} by the generic-name blacklist", flush=True)


def main():
    os.makedirs(DATA, exist_ok=True)
    out = {}
    fetch_group(EDU_TYPES, MIN_WORKS_EDU, out, f"universities >{MIN_WORKS_EDU}")
    fetch_group(INST_TYPES, MIN_WORKS_INST, out, f"institutes >{MIN_WORKS_INST}")

    with open(os.path.join(DATA, "institutions.json"), "w") as f:
        json.dump(out, f, ensure_ascii=False)

    import collections
    by_type = collections.Counter(v["type"] for v in out.values())
    print(f"whitelist: {len(out)} institutions -> data/institutions.json")
    for t, n in by_type.most_common():
        print(f"    {t:12} {n}")

    # Self-check: did the blacklist actually stop the known mismatched entities?
    leaks = [v["name"] for v in out.values() if is_generic(v["name"])]
    print("generic-name self-check:", "clean ✅" if not leaks else f"⚠️ leaked {leaks[:5]}")


if __name__ == "__main__":
    main()
