#!/bin/bash
# 额度恢复后接着跑（OpenAlex 免费额度每天 1000 次请求，UTC 零点重置）。
# 全部可断点续跑：撞额度会干净退出，第二天原样再跑一次即可接上。
set -u
cd "$(dirname "$0")/.."
: "${OPENALEX_MAILTO:?请先 export OPENALEX_MAILTO=你的邮箱（进 OpenAlex 礼貌池）}"

echo "== 1/3 期刊会议榜（约 80–120 次请求）=="
python3 scripts/venues.py || echo "   ↑ 额度不够，明天再跑这一步"

echo "== 2/3 多来源国对照（每国 12 seed ≈ 600 次请求，一天大概只够 1 个）=="
python3 scripts/harvest.py in ir br ru --seeds 12 || echo "   ↑ 额度用尽，明天原样重跑会自动续上"

echo "== 3/3 重算指标（不联网）=="
for cc in cn in ir br ru; do
  [ -f "data/careers_$cc.jsonl" ] && python3 scripts/compute.py "$cc"
done

echo
echo "完成。本地预览： python3 -m http.server 8791   →  http://localhost:8791"
echo "推上线：        git add -A && git commit -m '更新数据' && git push"
