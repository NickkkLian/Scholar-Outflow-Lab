#!/usr/bin/env python3
"""
Read GitHub traffic for the repo and **persist it**.

Why persist: the GitHub traffic API **keeps only 14 days**. Without periodic snapshots the
history is gone for good. This script upserts one row per day into data/traffic.jsonl —
append-only history.

Needs a **read-only** fine-grained PAT.
⚠️ The permission to grant is **Administration: Read-only**, not Metadata —
   GitHub's response header for the traffic endpoints is fixed at
   `x-accepted-github-permissions: administration=read`. Still read-only, just one notch above
   Metadata; do not grant Read and write.
    export GH_TRAFFIC_PAT=github_pat_xxx
or put it in .env at the repository root (gitignored, never committed):
    GH_TRAFFIC_PAT=github_pat_xxx

Usage:
    python3 scripts/traffic.py            # fetch, persist, print a summary
    python3 scripts/traffic.py --report   # summarise what's on disk, no network
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
    """Read the token from .env without overriding existing environment variables. .env is gitignored."""
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
                rows[r["date"]] = r          # later rows for the same day win
            except json.JSONDecodeError:
                continue
    return rows


def report(rows):
    if not rows:
        print("No traffic rows yet. Run once without --report first.")
        return
    days = sorted(rows)
    v = sum(rows[d].get("views", 0) for d in days)
    u = sum(rows[d].get("uniques", 0) for d in days)
    c = sum(rows[d].get("clones", 0) for d in days)
    print(f"{len(days)} days on file ({days[0]} → {days[-1]}): "
          f"{v} views / {u} unique visitors / {c} clones")
    print("Last 14 days:")
    for d in days[-14:]:
        r = rows[d]
        print(f"  {d}  views {r.get('views',0):4}  uniques {r.get('uniques',0):4}  "
              f"clones {r.get('clones',0):3}")
    if u == 0:
        print("\nZero unique visitors overall — that is itself a finding; don't wait for it to improve on its own.")


def main():
    os.makedirs(DATA, exist_ok=True)
    rows = read_rows()

    if "--report" in sys.argv:
        report(rows)
        return

    load_env()
    token = os.environ.get("GH_TRAFFIC_PAT", "")
    if not token:
        print("⛔ GH_TRAFFIC_PAT is not set. Create a **read-only** fine-grained PAT "
              "(Repository permissions → Administration: Read-only) and put it in "
              ".env at the repository root, or export it. See the notes at the top of this file.")
        sys.exit(1)

    try:
        views = api("traffic/views", token)
        clones = api("traffic/clones", token)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            print(f"⛔ Token invalid or under-privileged (HTTP {e.code}). "
                  "The traffic endpoints require **Administration: Read-only** (not Metadata) — "
                  "GitHub's header says x-accepted-github-permissions: administration=read. "
                  "In the PAT settings set Repository permissions → Administration to Read-only, "
                  "and make sure this repo is listed under Repository access.")
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

    print(f"{REPO}: fetched {len(by_day)} days, {added} new or changed.")
    report(rows)


if __name__ == "__main__":
    main()
