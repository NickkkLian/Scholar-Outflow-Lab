#!/bin/bash
# Resume once the quota is back (OpenAlex free tier: 1,000 requests/day, resets at 00:00 UTC).
# Every step is resumable: hitting the quota exits cleanly, and re-running the same command the
# next day picks up where it stopped.
set -u
cd "$(dirname "$0")/.."
: "${OPENALEX_MAILTO:?export OPENALEX_MAILTO=you@example.com first (OpenAlex polite pool)}"

echo "== 1/3 venue board (about 80–120 requests) =="
python3 scripts/venues.py || echo "   ↑ not enough quota left; retry this step tomorrow"

echo "== 2/3 additional origin countries (12 seeds ≈ 600 requests per country; about one per day) =="
python3 scripts/harvest.py in ir br ru --seeds 12 || echo "   ↑ quota spent; re-run tomorrow and it resumes"

echo "== 3/3 recompute metrics (offline) =="
for cc in cn in ir br ru; do
  [ -f "data/careers_$cc.jsonl" ] && python3 scripts/compute.py "$cc"
done

echo
echo "Done. Preview locally:  python3 -m http.server 8791   →  http://localhost:8791"
echo "Publish:                git add -A && git commit -m 'Refresh data' && git push"
