#!/usr/bin/env python3
"""
Journal / conference board.

Pulls journals and conferences from OpenAlex `sources` and ranks them within each field.
Zero cost: the same CC0 public data.

⚠️ Quota: the OpenAlex free tier is **1,000 requests per day** (resets at 00:00 UTC), not
   unlimited. This script needs roughly 80–120 requests; make sure enough of the day's quota is
   left before running it (the harvester is the hungry one).

Output: data/data-venues.json
Usage:  OPENALEX_MAILTO=you@example.com python3 scripts/venues.py
"""

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.openalex.org/sources"
MAILTO = os.environ.get("OPENALEX_MAILTO", "")
UA = f"Scholar-Outflow-Lab (mailto:{MAILTO})" if MAILTO else "Scholar-Outflow-Lab"
MIN_WORKS = 2000          # ranking venues with tiny output is meaningless
MIN_H = 5                 # a very low h-index usually means it isn't an academic venue
# Measured: without this floor, large numbers of **uncited commercial / trade magazines** get in —
# weekly business and news magazines with 10–20k works and h=0, all classified as Social
# Sciences, inflating that field from a few hundred entries to 3,335 and diluting the V1/V2
# percentile lines. Sitting at the bottom isn't harmless: percentiles are cut by entry count,
# so junk pushes real venues upward.
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
WEB = os.path.join(ROOT, "data")   # the published JSON: Pages serves main's root and the page reads data/

# Stored field labels (Chinese); the web UI maps them to English client-side by exact key, and
# the English original is kept in `field_en`. Keep in step with the front-end dictionary.
FIELD_ZH = {
    "Medicine": "医学", "Engineering": "工程", "Computer Science": "计算机",
    "Materials Science": "材料", "Chemistry": "化学", "Physics and Astronomy": "物理天文",
    "Biochemistry, Genetics and Molecular Biology": "生化遗传",
    "Agricultural and Biological Sciences": "农业生物",
    "Environmental Science": "环境科学", "Earth and Planetary Sciences": "地球科学",
    "Social Sciences": "社会科学", "Mathematics": "数学",
    "Economics, Econometrics and Finance": "经济金融",
    "Business, Management and Accounting": "商管", "Psychology": "心理学",
    "Energy": "能源", "Chemical Engineering": "化工",
    "Immunology and Microbiology": "免疫微生物", "Neuroscience": "神经科学",
    "Pharmacology, Toxicology and Pharmaceutics": "药学",
    "Arts and Humanities": "人文艺术", "Nursing": "护理",
    "Health Professions": "卫生职业", "Veterinary": "兽医",
    "Dentistry": "口腔", "Decision Sciences": "决策科学",
}
TYPE_ZH = {"journal": "期刊", "conference": "会议", "book series": "丛书", "repository": "仓储"}


def fetch(params):
    if MAILTO:
        params["mailto"] = MAILTO
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 429:
            ra = int(e.headers.get("retry-after") or 0)
            print(f"⛔ OpenAlex quota spent (resets at 00:00 UTC, in {ra // 3600} h); nothing partial is saved.", flush=True)
            sys.exit(2)
        raise


def retier(venues):
    """Rank by h-index within each field and cut into percentile tiers. Comparing h-index
    across fields is meaningless, so the comparison is strictly within-field."""
    by_field = {}
    for v in venues:
        by_field.setdefault(v["field"] or "其他", []).append(v)
    for vs in by_field.values():
        vs.sort(key=lambda x: -x["h"])
        n = len(vs)
        for i, v in enumerate(vs):
            v["field_rank"] = i + 1
            v["field_total"] = n
            q = i / n
            v["tier"] = "V1" if q < 0.1 else "V2" if q < 0.3 else "V3" if q < 0.6 else "V4"
    return by_field


def refilter_existing():
    """Re-run the filter and tiering offline — don't burn another day's quota just to change
    a threshold when the data is already on disk."""
    p = os.path.join(WEB, "data-venues.json")
    d = json.load(open(p))
    before = len(d["venues"])
    kept = [v for v in d["venues"] if v.get("h", 0) >= MIN_H]
    by_field = retier(kept)
    kept.sort(key=lambda x: -x["h"])
    d["venues"] = kept
    d["meta"]["count"] = len(kept)
    d["meta"]["min_h"] = MIN_H
    d["meta"]["fields"] = sorted(by_field.keys())
    d["meta"]["notes"] = [n for n in d["meta"]["notes"] if "h-index" not in n or "分级" in n]
    d["meta"]["notes"].insert(1, f"只收录 h-index ≥{MIN_H} 的——否则会混进大量无被引记录的行业杂志，"
                                 f"把学科条目数撑大、分位线稀释")
    json.dump(d, open(p, "w"), ensure_ascii=False, separators=(",", ":"))
    print(f"offline re-tier: {before} → {len(kept)} venues (dropped {before - len(kept)} with h<{MIN_H})")
    for f, vs in sorted(by_field.items(), key=lambda x: -len(x[1]))[:6]:
        print(f"    {f:8} {len(vs)}")


def main():
    if "--retier" in sys.argv:
        return refilter_existing()
    out, cursor, page = [], "*", 0
    while cursor:
        d = fetch({
            "filter": f"type:journal|conference,works_count:>{MIN_WORKS}",
            "per-page": 200, "cursor": cursor,
            "select": "id,display_name,type,host_organization_name,country_code,"
                      "works_count,cited_by_count,summary_stats,is_oa,is_in_doaj,topics",
        })
        for s in d.get("results") or []:
            st = s.get("summary_stats") or {}
            topics = s.get("topics") or []
            # The venue's field is the most frequent field across its topics
            counts = {}
            for t in topics[:25]:
                f = (t.get("field") or {}).get("display_name")
                if f:
                    counts[f] = counts.get(f, 0) + (t.get("count") or 1)
            field = max(counts, key=counts.get) if counts else ""
            out.append({
                "id": s["id"].rsplit("/", 1)[-1],
                "name": s.get("display_name") or "",
                "type": TYPE_ZH.get(s.get("type") or "", s.get("type") or ""),
                "type_raw": s.get("type") or "",
                "publisher": s.get("host_organization_name") or "",
                "cc": (s.get("country_code") or "").lower(),
                "works": s.get("works_count") or 0,
                "cited": s.get("cited_by_count") or 0,
                "h": st.get("h_index") or 0,
                "i10": st.get("i10_index") or 0,
                "impact": round(st.get("2yr_mean_citedness") or 0, 3),
                "oa": bool(s.get("is_oa")),
                "doaj": bool(s.get("is_in_doaj")),
                "field": FIELD_ZH.get(field, field),
                "field_en": field,
            })
        cursor = d["meta"].get("next_cursor")
        page += 1
        if page % 10 == 0:
            print(f"  {page} pages / {len(out)} venues", flush=True)
        time.sleep(0.2)

    out = [v for v in out if v["h"] >= MIN_H]
    by_field = retier(out)
    out.sort(key=lambda x: -x["h"])
    payload = {
        "meta": {
            "source": "OpenAlex (CC0) — api.openalex.org/sources",
            "generated_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
            "count": len(out),
            "min_works": MIN_WORKS,
            "fields": sorted(by_field.keys()),
            # Stored verbatim (Chinese); translated client-side by prefix match.
            "notes": [
                "只收录产出 ≥%d 篇的期刊与会议" % MIN_WORKS,
                "分级 V1–V4 是**学科内**按 h-index 的分位，跨学科比 h-index 没有意义",
                "h-index / 2 年篇均被引来自 OpenAlex summary_stats，与 JCR 影响因子不是同一口径",
                "OA / DOAJ 标记仅供参考，不代表版面费高低",
            ],
        },
        "venues": out,
    }
    os.makedirs(WEB, exist_ok=True)
    p = os.path.join(WEB, "data-venues.json")
    with open(p, "w") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    print(f"{len(out)} journals/conferences -> {p} ({os.path.getsize(p) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
