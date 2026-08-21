#!/bin/bash
# One automated round per day (triggered by launchd: com.scholaroutflow.daily).
#
# Why daily: the OpenAlex free tier is 1,000 requests per day, resetting at 00:00 UTC.
# Scheduled for 18:00 local (PDT = 01:00 UTC / PST = 02:00 UTC), safely after the reset in
# both daylight-saving regimes.
#
# Tasks are ordered "cheapest and most unlocking first" — one day's quota usually gets partway
# through the list, and the next day continues automatically. Every step is resumable.
#
#   1. traffic snapshot          ~2 req    (GitHub, not OpenAlex quota)
#   2. venue board               ~120 req  one-off; skipped once generated
#   3. whitelist + institutes    ~150 req  one-off; **no author re-harvest needed** —
#                                          institutes were already in the career records,
#                                          the whitelist just used to filter them out
#   4. additional origins        ~600 req per country
#   5. upgrade cn to v2          ~1200 req the most expensive, so last (field by vote over all
#                                          topics instead of the first one)
#
# Switch off: launchctl bootout gui/$(id -u)/com.scholaroutflow.daily

set -u
cd "$(dirname "$0")/.." || exit 1
LOG="data/daily.log"
mkdir -p data
say() { echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }

# Mutex: a manual harvest may overlap with the scheduled one; two processes appending to the
# same JSONL and writing the same state file corrupts the data and mis-marks seeds as done.
# mkdir is atomic, which is all we need.
LOCK="data/.daily.lock"
if ! mkdir "$LOCK" 2>/dev/null; then
  owner=$(cat "$LOCK/pid" 2>/dev/null || echo "?")
  if [ "$owner" != "?" ] && kill -0 "$owner" 2>/dev/null; then
    say "⏭  a round is already running (pid $owner); skipping this one"
    exit 0
  fi
  say "⚠️  stale lock found (pid $owner is gone); clearing it and continuing"
  rm -rf "$LOCK"; mkdir "$LOCK" || exit 1
fi
echo $$ > "$LOCK/pid"
trap 'rm -rf "$LOCK"' EXIT INT TERM

# .env holds OPENALEX_MAILTO and GH_TRAFFIC_PAT (gitignored, never committed)
[ -f .env ] && set -a && . ./.env && set +a

say "===== start ====="

say "[1/5] traffic snapshot (the traffic API keeps 14 days; unsaved means lost)"
python3 scripts/traffic.py >>"$LOG" 2>&1 || say "      fetch failed (usually the token lacks Administration:Read); continuing"

if [ ! -f data-venues.json ]; then
  say "[2/5] venue board"
  python3 scripts/venues.py >>"$LOG" 2>&1 && say "      generated" || say "      not enough quota; retrying tomorrow"
else
  say "[2/5] venue board exists, skipping"
fi

# A non-education type in the whitelist means institutes are already included. Using the data
# itself as the "done" marker beats a separate flag file — files go missing, data doesn't lie.
if ! python3 -c "
import json,sys
w=json.load(open('data/institutions.json'))
sys.exit(0 if any(v.get('type','education')!='education' for v in w.values()) else 1)
" 2>/dev/null; then
  say "[3/5] adding research institutes to the whitelist (CAS / CNRS / NIH etc.; no author re-harvest needed)"
  python3 scripts/institutions.py >>"$LOG" 2>&1 && say "      updated" || say "      not enough quota; retrying tomorrow"
else
  say "[3/5] institutes already in the whitelist, skipping"
fi

# More origins make the cross-origin comparison more convincing — that is the core value of the
# site — so it runs before v2 (which measured at only +1.4%, see below). 12 seeds ≈ 600 requests
# per country.
say "[4/5] additional origin countries"
python3 scripts/harvest.py in ir br ru kr vn pk ng eg tr mx id --seeds 12 >>"$LOG" 2>&1 \
  && say "      all queued origins are complete" || say "      quota spent; resuming tomorrow"

# v2 = field assigned by voting over all topics.
# ⚠️ **The original hypothesis was refuted by measurement — don't mistake this step for a fix
#   of the CS classification** (2026-07-28):
#   Comparing 59k v2 authors against the 39.6k overlap in the v1 backup —
#   Computer Science 3,656 → 3,708 (+1.4%), Engineering 8,901 → 9,984; CS→Engineering 287
#   people vs Engineering→CS 222: a net outflow. 17.1% of people changed field, but the net
#   effect on CS ≈ 0. The real root cause is OpenAlex's own topic→field taxonomy, which files
#   applied CS under Engineering; voting over more topics doesn't help — those topics point at
#   Engineering too.
# It still runs to completion: the quota refreshes daily and nothing else is queued by then, so
# the opportunity cost ≈ 0, and finishing clears the "half-done" state (otherwise pick_source's
# backup guard stays in force forever). Side benefit: top_fields (top three fields with vote
# counts) for any future look at interdisciplinary researchers.
# Next direction to validate (**before starting any new re-harvest**): use topic subfield
# instead of field, or a hand-built mapping that pulls AI/ML/CV/information-systems subfields
# into the CS bucket. A handful of requests is enough to inspect subfield data first.
if head -1 data/careers_cn.jsonl 2>/dev/null | grep -q '"v":2' \
   && [ "$(wc -l < data/careers_cn.jsonl)" -ge "$(wc -l < data/careers_cn.jsonl.v1.bak 2>/dev/null || echo 0)" ]; then
  say "[5/5] cn v2 complete, skipping"
else
  say "[5/5] resuming cn v2 (not a CS-classification fix — that hypothesis was refuted, see comments)"
  python3 scripts/harvest.py cn --seeds 24 --refresh >>"$LOG" 2>&1 \
    && say "      cn v2 finished" || say "      quota spent; resuming tomorrow"
fi

say "-- recompute metrics (offline)"
done_ccs=""
# ⚠️ During a re-harvest compute.py automatically uses the .v1.bak (whichever has more rows), so
# a half-finished dataset never goes live.
# 2026-07-28, for real: the cn v2 harvest hit the quota at 19k of 180k, the recompute published
# anyway, and the live site went from 180k authors / 175 institutions to 19k / 3.
# ⚠️ Derive the country list **from the files on disk, never hard-code it**.
# 2026-08-01, for real: eight new origins were added to the harvest command above but the
# hard-coded list here wasn't updated — South Korea (108,768 authors) and Vietnam (57,440) were
# harvested and then never computed, never published.
for f in data/careers_*.jsonl data/careers_*.jsonl.v1.bak; do
  [ -e "$f" ] || continue
  cc=$(basename "$f" | sed -E 's/^careers_([a-z]{2})\.jsonl(\.v1\.bak)?$/\1/')
  case "$cc" in [a-z][a-z]) ;; *) continue ;; esac
  case " $done_ccs " in *" $cc "*) continue ;; esac
  done_ccs="$done_ccs $cc"
  if [ -s "data/careers_$cc.jsonl" ] || [ -s "data/careers_$cc.jsonl.v1.bak" ]; then
    python3 scripts/compute.py "$cc" >>"$LOG" 2>&1 && say "   $cc recomputed"
  fi
  # Once the re-harvest is complete (new ≥ backup) delete the backup; otherwise hundreds of MB sit around
  bak="data/careers_$cc.jsonl.v1.bak"
  if [ -f "$bak" ] && [ -s "data/careers_$cc.jsonl" ]; then
    n_new=$(wc -l < "data/careers_$cc.jsonl"); n_bak=$(wc -l < "$bak")
    if [ "$n_new" -ge "$n_bak" ]; then
      rm -f "$bak" "data/careers_$cc.state.json.v1.bak"
      say "   $cc re-harvest complete ($n_new ≥ $n_bak); v1 backup removed"
    fi
  fi
done

# Commit and push only when the outputs actually changed; no empty commits.
# ⚠️ Stage data outputs only — **never index.html or other source**.
# A previous version swept index.html in as well, so hand-made front-end changes got labelled
# "automated data refresh": a commit message at odds with its content, which misleads anyone
# reading the history later.
if [ -n "$(git status --porcelain -- 'data-*.json' origins.json)" ]; then
  say "-- data changed; committing and pushing"
  git add -A -- 'data-*.json' origins.json
  git -c user.name="Claude" -c user.email="noreply@anthropic.com" \
      commit -q -m "Automated data refresh $(date '+%F')" >>"$LOG" 2>&1
  if git push -q origin main >>"$LOG" 2>&1; then
    say "   pushed; GitHub Pages will rebuild"
  else
    say "   push failed (remote may have new commits); retrying next run"
  fi
else
  say "-- outputs unchanged; nothing to commit"
fi

say "===== end ====="
echo >>"$LOG"
