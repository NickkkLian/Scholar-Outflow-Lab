#!/usr/bin/env python3
"""
期刊 / 会议榜（Business-Lab 需求第 4 点的后半）。

从 OpenAlex sources 拉期刊与会议，按学科分组排名。零成本：同样是 CC0 公共数据。

⚠️ 额度：OpenAlex 免费额度是**每天 1000 次请求**（UTC 零点重置），不是无限。
   本脚本约需 80–120 次，跑之前先确认当天额度还够（harvest 很吃额度）。

输出: data-venues.json
用法: OPENALEX_MAILTO=you@example.com python3 scripts/venues.py
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
UA = f"mobility-lab (mailto:{MAILTO})" if MAILTO else "mobility-lab"
MIN_WORKS = 2000          # 产出太少的刊排名没意义
MIN_H = 5                 # h-index 太低的多半不是学术刊
# 实测：不加这条会混进大量**没有被引记录的商业期刊/行业杂志**——
# 「世界週報」「週刊東洋経済」「潮」这类 works 一两万、h=0，全被归进社会科学，
# 把该学科的条目数从几百撑到 3335，V1/V2 的分位线整个被稀释。
# 它们不是排在末尾就没事：分位是按条目数切的，垃圾进来会把真刊往上顶。
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
WEB = ROOT   # 站点直接放仓库根目录：GitHub Pages 走 main 分支根目录

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
            print(f"⛔ OpenAlex 额度用尽（{ra // 3600} 小时后 UTC 零点重置），已抓到的不保存。", flush=True)
            sys.exit(2)
        raise


def retier(venues):
    """学科内按 h-index 排名 + 分位分档。跨学科比 h-index 没意义，所以只在学科内比。"""
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
    """离线重跑过滤与分档，不联网——已有数据时别为了改口径再烧一次额度。"""
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
    print(f"离线重排：{before} → {len(kept)} 本（剔除 h<{MIN_H} 的 {before - len(kept)} 本）")
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
            # 用出现最多的 field 当这本刊的学科归属
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
            print(f"  {page} 页 / {len(out)} 本", flush=True)
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
    print(f"{len(out)} 本期刊/会议 -> {p} ({os.path.getsize(p) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
