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

# 来源国越多，跨来源对比越有说服力——那是本站的核心价值，
# 所以它排在 v2 前面（v2 实测只值 +1.4%，见下）。每国 12 seed ≈ 600 次请求。
say "[4/5] 多来源国"
python3 scripts/harvest.py in ir br ru kr vn pk ng eg tr mx id --seeds 12 >>"$LOG" 2>&1 \
  && say "      所有排队的来源国都齐了" || say "      额度用尽，明天自动接上"

# v2 = 学科按全部 topic 投票。
# ⚠️ **原假设已被实测推翻，别再以为这一步是在修 CS 归类**（2026-07-28）：
#   拿 v2 的 5.9 万人与 v1 备份的重叠 3.96 万人比对——
#   计算机 3656 → 3708（+1.4%），工程 8901 → 9984；CS→工程 287 人 vs 工程→CS 222 人，净流出。
#   17.1% 的人归类变了，但对 CS 的净效果≈0。
#   真正的根因是 OpenAlex 的 topic→field 分类本身把偏应用的 CS 挂在 Engineering 下，
#   多取几个 topic 投票没用——那些 topic 也指向 Engineering。
# 仍然让它跑完：额度每天刷新且此时已无其它排队任务，机会成本≈0，
# 跑完还能清掉「半完成」状态（否则 pick_source 的备份守卫会永久生效）。
# 附带收益是 top_fields（前三学科及票数），以后要看跨学科的人用得上。
# 下一个待验证方向（**验证前别开新的重抓**）：改用 topic 的 subfield 而非 field，
# 或自建映射把 AI/ML/CV/信息系统等 CS 相邻 subfield 拉进「计算机」桶。
# 只需几次请求就能先看清 subfield 数据长什么样，验通了再决定重抓。
if head -1 data/careers_cn.jsonl 2>/dev/null | grep -q '"v":2' \
   && [ "$(wc -l < data/careers_cn.jsonl)" -ge "$(wc -l < data/careers_cn.jsonl.v1.bak 2>/dev/null || echo 0)" ]; then
  say "[5/5] cn v2 已完整，跳过"
else
  say "[5/5] 续跑 cn v2（不是在修 CS 归类——那个假设已被推翻，见注释）"
  python3 scripts/harvest.py cn --seeds 24 --refresh >>"$LOG" 2>&1 \
    && say "      cn v2 已跑完" || say "      额度用尽，明天自动接上"
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
