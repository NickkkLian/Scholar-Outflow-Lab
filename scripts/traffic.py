#!/usr/bin/env python3
"""
读 GitHub 访问量并**存下来**（Business-Lab 决策需要的成效信号）。

为什么必须存：GitHub traffic API **只保留 14 天**，不定期快照就永久丢失。
所以本脚本按天 upsert 进 data/traffic.jsonl，历史只增不改。

需要一个**只读**令牌（细粒度 PAT）。
⚠️ 权限要勾的是 **Administration: Read-only**，不是 Metadata——
   GitHub 对 traffic 接口的响应头写死了 `x-accepted-github-permissions: administration=read`。
   它仍然是只读，但比 Metadata 高一档，别勾成 Read and write。
    export GH_TRAFFIC_PAT=github_pat_xxx
或写进 mobility-lab/.env（已 gitignore，绝不进公开仓）：
    GH_TRAFFIC_PAT=github_pat_xxx

用法:
    python3 scripts/traffic.py            # 抓取并落盘，打印摘要
    python3 scripts/traffic.py --report   # 只看已存下来的，不联网
"""

import json
import os
import sys
import urllib.error
import urllib.request

REPO = "NickkkLian/Scholar-Outflow-Lab"
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(DATA, "traffic.jsonl")


def load_env():
    """从 .env 读令牌（不覆盖已有环境变量）。.env 已 gitignore。"""
    p = os.path.join(ROOT, ".env")
    if not os.path.exists(p):
        return
    with open(p) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def api(path, token):
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/{path}",
        headers={"Authorization": f"Bearer {token}",
                 "Accept": "application/vnd.github+json",
                 "User-Agent": "scholar-outflow-traffic"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def read_rows():
    if not os.path.exists(OUT):
        return {}
    rows = {}
    with open(OUT) as f:
        for line in f:
            try:
                r = json.loads(line)
                rows[r["date"]] = r          # 同日后写覆盖先写
            except json.JSONDecodeError:
                continue
    return rows


def report(rows):
    if not rows:
        print("还没有任何访问量记录。先跑一次不带 --report 的。")
        return
    days = sorted(rows)
    v = sum(rows[d].get("views", 0) for d in days)
    u = sum(rows[d].get("uniques", 0) for d in days)
    c = sum(rows[d].get("clones", 0) for d in days)
    print(f"累计 {len(days)} 天（{days[0]} → {days[-1]}）："
          f"访问 {v} 次 / 独立访客 {u} / clone {c}")
    print("最近 14 天：")
    for d in days[-14:]:
        r = rows[d]
        print(f"  {d}  访问 {r.get('views',0):4}  独立 {r.get('uniques',0):4}  "
              f"clone {r.get('clones',0):3}")
    if u == 0:
        print("\n独立访客累计为 0——这本身就是结论，别等它自己变好。")


def main():
    os.makedirs(DATA, exist_ok=True)
    rows = read_rows()

    if "--report" in sys.argv:
        report(rows)
        return

    load_env()
    token = os.environ.get("GH_TRAFFIC_PAT", "")
    if not token:
        print("⛔ 没有 GH_TRAFFIC_PAT。建一个**只读**细粒度 PAT"
              "（Repository permissions → Administration: Read-only），"
              "放进 mobility-lab/.env 或 export 出来。详见本文件顶部说明。")
        sys.exit(1)

    try:
        views = api("traffic/views", token)
        clones = api("traffic/clones", token)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            print(f"⛔ 令牌无效或权限不足（HTTP {e.code}）。"
                  "traffic 接口要求 **Administration: Read-only**（不是 Metadata）——"
                  "GitHub 响应头 x-accepted-github-permissions: administration=read。"
                  "去 PAT 设置里把 Repository permissions → Administration 改成 Read-only，"
                  "并确认本仓库在 Repository access 里。")
        else:
            print(f"⛔ HTTP {e.code}: {e.reason}")
        sys.exit(1)

    by_day = {}
    for d in views.get("views", []):
        day = d["timestamp"][:10]
        by_day.setdefault(day, {})["views"] = d["count"]
        by_day[day]["uniques"] = d["uniques"]
    for d in clones.get("clones", []):
        day = d["timestamp"][:10]
        by_day.setdefault(day, {})["clones"] = d["count"]
        by_day[day]["clone_uniques"] = d["uniques"]

    added = 0
    for day, vals in by_day.items():
        prev = rows.get(day)
        row = {"date": day, "views": 0, "uniques": 0, "clones": 0, "clone_uniques": 0} | vals
        if prev != row:
            rows[day] = row
            added += 1

    with open(OUT, "w") as f:
        for day in sorted(rows):
            f.write(json.dumps(rows[day], ensure_ascii=False) + "\n")

    print(f"{REPO}: 抓到 {len(by_day)} 天，其中 {added} 天是新的/有变化。")
    report(rows)


if __name__ == "__main__":
    main()
