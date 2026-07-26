#!/bin/bash
# 每天自动跑一轮（由 launchd com.scholaroutflow.daily 触发）。
#
# 为什么是每天：OpenAlex 免费额度每天 1000 次请求、UTC 零点重置。
# 排在本地 18:00（PDT=01:00 UTC / PST=02:00 UTC），两种时令都稳稳在重置之后。
#
# 全部步骤都能断点续跑：撞额度就干净退出，第二天自动接上。
# 关掉：launchctl bootout gui/$(id -u)/com.scholaroutflow.daily

set -u
cd "$(dirname "$0")/.." || exit 1
LOG="data/daily.log"
mkdir -p data
say() { echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }

# .env 里有 OPENALEX_MAILTO 和 GH_TRAFFIC_PAT（已 gitignore，绝不进公开仓）
[ -f .env ] && set -a && . ./.env && set +a

say "===== 开始 ====="

say "-- 访问量快照（traffic API 只留 14 天，不存就永久丢）"
python3 scripts/traffic.py >>"$LOG" 2>&1 || say "   访问量抓取失败（多半是令牌没配），继续"

if [ ! -f data-venues.json ]; then
  say "-- 期刊会议榜（约 80–120 次请求）"
  python3 scripts/venues.py >>"$LOG" 2>&1 && say "   期刊榜已生成" || say "   额度不够，明天再试"
fi

say "-- 多来源国（每国 12 seed ≈ 600 次请求，一天大概只够一个）"
python3 scripts/harvest.py in ir br ru --seeds 12 >>"$LOG" 2>&1 || say "   额度用尽，明天自动接上"

say "-- 重算指标（不联网）"
for cc in cn in ir br ru; do
  if [ -s "data/careers_$cc.jsonl" ]; then
    python3 scripts/compute.py "$cc" >>"$LOG" 2>&1 && say "   $cc 已重算"
  fi
done

# 只有产出物真的变了才提交推送；没变就别制造空提交
if [ -n "$(git status --porcelain -- 'data-*.json' index.html)" ]; then
  say "-- 数据有变化，提交并推送"
  git add -A -- 'data-*.json' index.html
  git -c user.name="Claude" -c user.email="noreply@anthropic.com" \
      commit -q -m "数据自动更新 $(date '+%F')" >>"$LOG" 2>&1
  if git push -q origin main >>"$LOG" 2>&1; then
    say "   已推送，GitHub Pages 会自动重建"
  else
    say "   推送失败（远端可能有新提交），下次自动重试"
  fi
else
  say "-- 产出物无变化，不提交"
fi

say "===== 结束 ====="
echo >>"$LOG"
