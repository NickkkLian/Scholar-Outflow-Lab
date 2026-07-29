#!/bin/bash
# 每天自动跑一轮（由 launchd com.scholaroutflow.daily 触发）。
#
# 为什么是每天：OpenAlex 免费额度每天 1000 次请求、UTC 零点重置。
# 排在本地 18:00（PDT=01:00 UTC / PST=02:00 UTC），两种时令都稳稳在重置之后。
#
# 任务按「便宜且解锁多」排序——一天的额度大概只够走到某一步，
# 剩下的第二天自动接着走。每一步都能断点续跑。
#
#   1. 访问量快照         ~2 次   （不吃 OpenAlex 额度，走 GitHub）
#   2. 期刊会议榜         ~120 次  一次性，出完就不再跑
#   3. 机构白名单加研究所  ~150 次  一次性；**不需要重抓作者**，
#                                  履历里本来就有研究所，只是之前被白名单滤掉了
#   4. 多来源国 in/ir/br/ru ~600 次/国
#   5. cn 数据升到 v2      ~1200 次 最贵，排最后（学科按全部 topic 投票而非取第一个）
#
# 关掉：launchctl bootout gui/$(id -u)/com.scholaroutflow.daily

set -u
cd "$(dirname "$0")/.." || exit 1
LOG="data/daily.log"
mkdir -p data
say() { echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }

# .env 里有 OPENALEX_MAILTO 和 GH_TRAFFIC_PAT（已 gitignore，绝不进公开仓）
[ -f .env ] && set -a && . ./.env && set +a

say "===== 开始 ====="

say "[1/5] 访问量快照（traffic API 只留 14 天，不存就永久丢）"
python3 scripts/traffic.py >>"$LOG" 2>&1 || say "      抓取失败（多半是令牌权限没给 Administration:Read），继续"

if [ ! -f data-venues.json ]; then
  say "[2/5] 期刊会议榜"
  python3 scripts/venues.py >>"$LOG" 2>&1 && say "      已生成" || say "      额度不够，明天再试"
else
  say "[2/5] 期刊会议榜 已有，跳过"
fi

# 白名单里出现非 education 类型 = 研究所已纳入。用它当「做过了」的标记，
# 比另存一个 flag 文件可靠——文件会丢，数据本身不会骗人。
if ! python3 -c "
import json,sys
w=json.load(open('data/institutions.json'))
sys.exit(0 if any(v.get('type','education')!='education' for v in w.values()) else 1)
" 2>/dev/null; then
  say "[3/5] 机构白名单加研究所（中科院/CNRS/NIH 这类，不需要重抓作者）"
  python3 scripts/institutions.py >>"$LOG" 2>&1 && say "      已更新" || say "      额度不够，明天再试"
else
  say "[3/5] 研究所已在白名单，跳过"
fi

say "[4/5] 多来源国（每国 12 seed ≈ 600 次请求）"
python3 scripts/harvest.py in ir br ru --seeds 12 >>"$LOG" 2>&1 \
  && say "      四个来源国都齐了" || say "      额度用尽，明天自动接上"

# v2 = 学科按全部 topic 投票。只在前面几步都做完后才动，因为它最贵。
if [ -f data/careers_in.jsonl ] && [ -s data/careers_in.jsonl ] \
   && head -1 data/careers_cn.jsonl 2>/dev/null | grep -q '"v":2'; then
  say "[5/5] cn 已是 v2，跳过"
elif [ -f data/careers_ru.jsonl ] && [ -s data/careers_ru.jsonl ]; then
  say "[5/5] 前面都跑完了，开始把 cn 升到 v2（会先备份 .v1.bak，跨天续跑）"
  python3 scripts/harvest.py cn --seeds 24 --refresh >>"$LOG" 2>&1 \
    && say "      cn 已升到 v2" || say "      额度用尽，明天自动接上"
else
  say "[5/5] 等前面几步跑完再升 v2（它最贵，别抢额度）"
fi

say "-- 重算指标（不联网）"
# ⚠️ 重抓期间 compute.py 会自动改用 .v1.bak（行数多的那份），不会把半截数据推上线。
# 2026-07-28 真踩过：cn 升 v2 抓到 1.9/18 万时撞额度，照常重算发布，
# 线上从 18 万样本/175 所机构变成 1.9 万/3 所。
for cc in cn in ir br ru; do
  if [ -s "data/careers_$cc.jsonl" ] || [ -s "data/careers_$cc.jsonl.v1.bak" ]; then
    python3 scripts/compute.py "$cc" >>"$LOG" 2>&1 && say "   $cc 已重算"
  fi
  # 重抓完成（新数据 ≥ 备份）就删备份，否则几百 MB 一直躺着
  bak="data/careers_$cc.jsonl.v1.bak"
  if [ -f "$bak" ] && [ -s "data/careers_$cc.jsonl" ]; then
    n_new=$(wc -l < "data/careers_$cc.jsonl"); n_bak=$(wc -l < "$bak")
    if [ "$n_new" -ge "$n_bak" ]; then
      rm -f "$bak" "data/careers_$cc.state.json.v1.bak"
      say "   $cc 重抓完成（$n_new ≥ $n_bak），已删除 v1 备份"
    fi
  fi
done

# 只有产出物真的变了才提交推送；没变就别制造空提交
# ⚠️ 只 stage 数据产出物，**别碰 index.html 等源码**——
# 上一版把 index.html 也裹进来，结果我的前端改动被打上「数据自动更新」的标签，
# 提交信息与内容不符，日后翻历史会被误导。
if [ -n "$(git status --porcelain -- 'data-*.json' origins.json)" ]; then
  say "-- 数据有变化，提交并推送"
  git add -A -- 'data-*.json' origins.json
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
