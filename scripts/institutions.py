#!/usr/bin/env python3
"""
拉一份「真实高校白名单」（OpenAlex institutions, type=education）。

为什么需要：OpenAlex 的机构是从论文署名字符串自动解析的，会把
"Capital University" / "Bridge University" / "Zero to Three" 这类通用名
错配到八竿子打不着的实体上——不过滤的话榜单里会混进垃圾。
带 ROR 且有一定产出量的，基本可以认为是真机构。

输出: data/institutions.json  {id: {name, cc, ror, works}}
"""

import json
import os
import time
import urllib.parse
import urllib.request

API = "https://api.openalex.org/institutions"
MAILTO = "you@example.com"
MIN_WORKS = 500
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
DATA = os.path.join(ROOT, "data")


def main():
    os.makedirs(DATA, exist_ok=True)
    out, cursor, page = {}, "*", 0
    while cursor:
        url = API + "?" + urllib.parse.urlencode({
            "filter": f"type:education,works_count:>{MIN_WORKS}",
            "per-page": 200, "cursor": cursor,
            "select": "id,display_name,country_code,ror,works_count,display_name_alternatives",
            "mailto": MAILTO,
        })
        req = urllib.request.Request(url, headers={"User-Agent": f"mobility-lab (mailto:{MAILTO})"})
        with urllib.request.urlopen(req, timeout=90) as r:
            d = json.loads(r.read().decode())
        for i in d.get("results") or []:
            if not i.get("ror"):
                continue          # 无 ROR 的多半是解析出来的幽灵机构
            out[i["id"].rsplit("/", 1)[-1]] = {
                "name": i.get("display_name") or "",
                "cc": (i.get("country_code") or "").lower(),
                "ror": i["ror"].rsplit("/", 1)[-1],
                "works": i.get("works_count") or 0,
            }
        cursor = d["meta"].get("next_cursor")
        page += 1
        if page % 10 == 0:
            print(f"  {page} 页 / {len(out)} 所", flush=True)
        time.sleep(0.12)
    with open(os.path.join(DATA, "institutions.json"), "w") as f:
        json.dump(out, f, ensure_ascii=False)
    print(f"白名单 {len(out)} 所高校 -> data/institutions.json")


if __name__ == "__main__":
    main()
