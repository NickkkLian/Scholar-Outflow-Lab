#!/usr/bin/env python3
"""
拉一份「真实科研机构白名单」——高校 + 研究所。

为什么需要：OpenAlex 的机构是从论文署名字符串自动解析的，会把
"Capital University" / "Bridge University" / "Zero to Three" 这类通用名
错配到八竿子打不着的实体上——不过滤的话榜单里会混进垃圾。
带 ROR 且有一定产出量的，基本可以认为是真机构。

⚠️ 2026-07-26 起把研究所（facility/government/nonprofit/healthcare）也纳入，
   因为中科院、CNRS、NIH、Academia Sinica、马普所这类是科研迁移的重要目的地，
   只收 type=education 会整批漏掉。
   但这几类的**错配噪音明显更重**：实测「Ministry of Education」在罗马尼亚/埃塞俄比亚/
   孟加拉各被匹配到 37 个「中国学者迁过去」——那是署名里出现该短语被误挂。
   对策两条：① 非高校类走**更高的产出量门槛**；② 通用名黑名单（下方 GENERIC_NAMES）。
   仍会有漏网，所以输出保留 type，前端可按「只看高校 / 含研究所」筛，口径页照实说明。

输出: data/institutions.json  {id: {name, cc, ror, works, type}}
"""

import json
import os
import time
import urllib.parse
import urllib.request

API = "https://api.openalex.org/institutions"
MAILTO = os.environ.get("OPENALEX_MAILTO", "")   # 见 harvest.py 注释：不写进公开仓
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
DATA = os.path.join(ROOT, "data")

# 高校门槛低（名字歧义少），研究所门槛高（错配噪音重）
EDU_TYPES = {"education"}
INST_TYPES = {"facility", "government", "nonprofit", "healthcare"}
MIN_WORKS_EDU = 500
MIN_WORKS_INST = 3000

# 通用名黑名单：这些不是机构名，是署名里的常见短语，被 OpenAlex 匹配到了随机实体。
# 判定方式是「整名等于该短语」或「以该短语开头且不含更具体的限定」——不做模糊包含，
# 免得误杀「Ministry of Education, Culture, Sports, Science and Technology (Japan)」这种真实体。
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
                continue          # 无 ROR 的多半是解析出来的幽灵机构
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
            print(f"  [{label}] {page} 页 / 累计 {len(out)} 所", flush=True)
        time.sleep(0.15)
    print(f"  [{label}] 收 {added} 所，按通用名黑名单剔除 {dropped} 所", flush=True)


def main():
    os.makedirs(DATA, exist_ok=True)
    out = {}
    fetch_group(EDU_TYPES, MIN_WORKS_EDU, out, f"高校 >{MIN_WORKS_EDU}")
    fetch_group(INST_TYPES, MIN_WORKS_INST, out, f"研究所 >{MIN_WORKS_INST}")

    with open(os.path.join(DATA, "institutions.json"), "w") as f:
        json.dump(out, f, ensure_ascii=False)

    import collections
    by_type = collections.Counter(v["type"] for v in out.values())
    print(f"白名单 {len(out)} 所 -> data/institutions.json")
    for t, n in by_type.most_common():
        print(f"    {t:12} {n}")

    # 自检：黑名单是不是真的挡住了那批已知的错配实体
    leaks = [v["name"] for v in out.values() if is_generic(v["name"])]
    print("通用名自检:", "干净 ✅" if not leaks else f"⚠️ 漏了 {leaks[:5]}")


if __name__ == "__main__":
    main()
