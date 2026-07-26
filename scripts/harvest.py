#!/usr/bin/env python3
"""
从 OpenAlex 采样学者的「机构履历」，落成 jsonl 供后续算迁移指标。

数据源：OpenAlex(https://openalex.org) —— CC0 公共领域，免 API key，礼貌池带 mailto 即可。
零成本：不花钱、不需要账号。

用法:
    python3 harvest.py cn --seeds 20            # 采样中国背景学者
    python3 harvest.py cn in ir --seeds 20      # 多个来源国

每个 seed 采 10000 人（OpenAlex sample 上限），seed 之间会有重复，按 author id 去重。
输出: data/careers_<country>.jsonl（可重复运行，自动续采已有 seed 之外的部分）
"""

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.openalex.org/authors"
# 礼貌池联系邮箱：不是凭据，但**不写进公开仓**。用环境变量传：
#   export OPENALEX_MAILTO=you@example.com
# 不设也能跑，只是走公共池、限速更严。
MAILTO = os.environ.get("OPENALEX_MAILTO", "")
SAMPLE = 10000          # OpenAlex 单次 sample 上限
PER_PAGE = 200          # 单页上限
MIN_WORKS = 5           # 少于 5 篇的多为噪音/重名合并残留，排除
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
DATA = os.path.join(ROOT, "data")

SELECT = "id,display_name,affiliations,last_known_institutions,works_count,topics"


UA = f"mobility-lab (mailto:{MAILTO})" if MAILTO else "mobility-lab"


class BudgetExhausted(Exception):
    """OpenAlex 免费额度用完（每天 1000 次请求，UTC 零点重置）。"""


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
                # 429 分两种：瞬时限速（等一下就好）和当日额度耗尽（等到 UTC 零点）。
                # 后者重试多少次都没用，必须干净退出，否则会把 seed 误标成已完成。
                retry_after = int(e.headers.get("retry-after") or 0)
                if retry_after > 600:
                    raise BudgetExhausted(f"当日额度已用尽，{retry_after//3600} 小时后（UTC 零点）重置")
                time.sleep(min(retry_after or 30, 120))
                continue
            if attempt == tries - 1:
                print(f"    ! 放弃: {e}", flush=True)
                return None
            time.sleep(2 ** attempt * 2)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            if attempt == tries - 1:
                print(f"    ! 放弃: {e}", flush=True)
                return None
            time.sleep(2 ** attempt * 2)
    return None


def career(author, origin_cc):
    """把一个 author 压成一条履历记录。年份缺失的机构直接丢掉——没有年份就没有先后。"""
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
    # 起点国：最早年份那批机构的国家。跨多国则记多国，后面按「是否含 origin」判断。
    start_ccs = sorted({s["cc"] for s in spans if s["y0"] == start})
    # 终点国：最晚年份那批。last_known 优先（OpenAlex 自己的判断），否则用最晚年份。
    last_known = [
        (i.get("country_code") or "").lower()
        for i in (author.get("last_known_institutions") or [])
        if i.get("country_code")
    ]
    end_ccs = sorted({s["cc"] for s in spans if s["y1"] == end})
    end_cc = last_known[0] if last_known else (end_ccs[0] if end_ccs else "")

    topics = author.get("topics") or []
    field = ""
    if topics:
        f = (topics[0].get("field") or {}).get("display_name")
        field = f or ""

    return {
        "id": author["id"].rsplit("/", 1)[-1],
        "origin_q": origin_cc,           # 采样时用的来源国口径
        "start": start,
        "end": end,
        "start_ccs": start_ccs,
        "end_cc": end_cc,
        "end_ccs": end_ccs,
        "works": author.get("works_count") or 0,
        "field": field,
        "spans": spans,
    }


def harvest(cc, seeds):
    os.makedirs(DATA, exist_ok=True)
    out_path = os.path.join(DATA, f"careers_{cc}.jsonl")
    state_path = os.path.join(DATA, f"careers_{cc}.state.json")

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
    print(f"[{cc}] 已有 {len(seen)} 人，已跑过 seed {sorted(done_seeds)}", flush=True)

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
        # ⚠️ 只有整轮页都取到了才算这个 seed 跑完。
        # 之前不判断就标 done，结果限速那次把 6 个 seed 全标成「已完成、0 人」，
        # 续跑时会直接跳过——数据永远补不回来。
        if pages_ok == SAMPLE // PER_PAGE:
            done_seeds.add(seed)
            json.dump({"seeds": sorted(done_seeds)}, open(state_path, "w"))
            print(f"[{cc}] seed {seed} +{added} 人，累计 {len(seen)}", flush=True)
        else:
            print(f"[{cc}] seed {seed} 只取到 {pages_ok}/{SAMPLE // PER_PAGE} 页，不标完成，"
                  f"下次续跑（本轮 +{added} 人）", flush=True)
    out.close()
    return len(seen)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    seeds = 20
    if "--seeds" in sys.argv:
        seeds = int(sys.argv[sys.argv.index("--seeds") + 1])
    if not args:
        print(__doc__)
        sys.exit(1)
    for cc in args:
        if cc.isdigit():
            continue
        try:
            n = harvest(cc.lower(), seeds)
            print(f"[{cc}] 完成，共 {n} 人 -> data/careers_{cc}.jsonl", flush=True)
        except BudgetExhausted as e:
            print(f"\n⛔ {e}\n   已抓到的都已落盘，额度恢复后重跑同一条命令会自动续上。", flush=True)
            sys.exit(2)
