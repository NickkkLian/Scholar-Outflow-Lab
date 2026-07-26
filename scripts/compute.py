#!/usr/bin/env python3
"""
把 careers_*.jsonl 聚合成「出去之后落在哪」的指标，输出 web/ 用的 JSON。

口径（原样写进输出 meta，网页上必须照抄展示，不许含糊）：
  样本    OpenAlex 中「曾在来源国机构署名、且发表 ≥5 篇」的学者随机抽样
  本土起步 履历最早年份所在国包含来源国 —— 即「在本国起步」的科研人员
  一次到达 之后（到达年 ≥ 起点年）在某境外机构挂名跨 ≥2 个年份
  观察期  只统计到达年 ≤ 今年-FOLLOWUP 的人，否则「还没来得及走」会被算成留下

  ⭐ 分层（这是本站的核心，不分层的数字会被访问学者稀释到没意义）：
    short  在目的机构 2–3 年 —— 多为访问学者/联合培养，绝大多数本来就要回国
    long   ≥4 年 —— 更像读博/长期职位（默认口径）
    long6  ≥6 年 —— 长期扎根
    all    不限时长

  终局四分类（互斥、合计 100%），按最后已知年份的全部任职国判定：
    留下 stay   末位国含目的国、不含来源国
    双挂 dual   末位国同时含两边  ← 中国学者极常见，单列以免高估任何一边
    回流 ret    末位国含来源国、不含目的国
    转道 onward 两个都不含（去了第三国）

  ⚠️ 学术履历代理指标，不是签证/移民统计，也不构成移民建议。
     绝对值受抽样口径影响很大，**只看机构/国家之间的相对高低**。
"""

import collections
import datetime
import json
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
DATA = os.path.join(ROOT, "data")
WEB = ROOT   # 站点直接放仓库根目录：GitHub Pages 走 main 分支根目录

THIS_YEAR = datetime.date.today().year
FOLLOWUP = 5
MIN_N_INST = 25          # 默认分层下的机构最小样本量
MIN_N_COUNTRY = 60
MIN_N_FIELD = 15

# 分层: key -> (最短年数, 最长年数)
STRATA = {"short": (2, 3), "long": (4, 99), "long6": (6, 99), "all": (2, 99)}
DEFAULT_STRATUM = "long"
OUTCOMES = ("stay", "dual", "ret", "onward")

CC_NAME = {
    "us": "美国", "gb": "英国", "ca": "加拿大", "au": "澳大利亚", "de": "德国",
    "fr": "法国", "jp": "日本", "sg": "新加坡", "hk": "中国香港", "tw": "中国台湾",
    "mo": "中国澳门", "kr": "韩国", "nl": "荷兰", "ch": "瑞士", "se": "瑞典",
    "it": "意大利", "es": "西班牙", "be": "比利时", "dk": "丹麦", "no": "挪威",
    "fi": "芬兰", "at": "奥地利", "ie": "爱尔兰", "nz": "新西兰", "il": "以色列",
    "ru": "俄罗斯", "in": "印度", "br": "巴西", "za": "南非", "pt": "葡萄牙",
    "pl": "波兰", "cz": "捷克", "sa": "沙特", "ae": "阿联酋", "my": "马来西亚",
    "th": "泰国", "cn": "中国大陆", "ir": "伊朗", "tr": "土耳其", "mx": "墨西哥",
    "gr": "希腊", "hu": "匈牙利", "cl": "智利", "ar": "阿根廷", "vn": "越南",
    "id": "印尼", "ph": "菲律宾", "pk": "巴基斯坦", "eg": "埃及", "ng": "尼日利亚",
}

FIELD_ZH = {
    "Medicine": "医学", "Engineering": "工程", "Computer Science": "计算机",
    "Materials Science": "材料", "Chemistry": "化学", "Physics and Astronomy": "物理天文",
    "Biochemistry, Genetics and Molecular Biology": "生化遗传",
    "Agricultural and Biological Sciences": "农业生物",
    "Environmental Science": "环境科学", "Earth and Planetary Sciences": "地球科学",
    "Social Sciences": "社会科学", "Mathematics": "数学", "Economics, Econometrics and Finance": "经济金融",
    "Business, Management and Accounting": "商管", "Psychology": "心理学",
    "Energy": "能源", "Chemical Engineering": "化工", "Immunology and Microbiology": "免疫微生物",
    "Neuroscience": "神经科学", "Pharmacology, Toxicology and Pharmaceutics": "药学",
    "Arts and Humanities": "人文艺术", "Nursing": "护理", "Health Professions": "卫生职业",
    "Veterinary": "兽医", "Dentistry": "口腔", "Decision Sciences": "决策科学",
}


def blank():
    return dict.fromkeys(OUTCOMES, 0) | {"n": 0}


def load_jsonl(path):
    rows = []
    with open(path) as f:
        for line in f:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def wilson(k, n, z=1.96):
    """Wilson 95% 区间——小样本下比正态近似靠谱，页面用它标误差棒。"""
    if not n:
        return None
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5)
    return [round((c - m) / d, 4), round((c + m) / d, 4)]


def pct(d):
    n = d["n"]
    out = {"n": n}
    for k in OUTCOMES:
        out[k] = round(d[k] / n, 4) if n else None
    ci = wilson(d["stay"], n)
    out["stay_ci"] = ci
    # 保守下界：排序用它而不是原始比率。样本 25 人的 40% 和样本 300 人的 30%，
    # 前者的真实值可能低得多——按下界排，小样本的侥幸高分自己会掉下去。
    out["stay_lb"] = ci[0] if ci else None
    return out


def outcome(dest_cc, origin, ends):
    has_d, has_o = dest_cc in ends, origin in ends
    if has_d and not has_o:
        return "stay"
    if has_d and has_o:
        return "dual"
    if has_o:
        return "ret"
    return "onward"


def write_manifest():
    """扫出已生成的来源国，写 origins.json 供前端做来源切换。

    没有这份清单，前端只能写死一个来源国——数据抓回来了页面上也看不见。
    严格匹配 data-<两位国码>.json，别把 data-venues.json 算进来。
    """
    out = []
    for fn in sorted(os.listdir(WEB)):
        m = re.fullmatch(r"data-([a-z]{2})\.json", fn)
        if not m:
            continue
        try:
            d = json.load(open(os.path.join(WEB, fn)))
            meta = d["meta"]
        except (json.JSONDecodeError, OSError, KeyError):
            continue
        out.append({"cc": m.group(1), "name": meta.get("origin_name", m.group(1).upper()),
                    "sampled": meta.get("sampled_authors", 0),
                    "movers": meta.get("movers", 0),
                    "institutions": len(d.get("institutions", []))})
    out.sort(key=lambda x: -x["sampled"])
    with open(os.path.join(WEB, "origins.json"), "w") as f:
        json.dump({"origins": out}, f, ensure_ascii=False, separators=(",", ":"))
    return out


def build(origin):
    rows = load_jsonl(os.path.join(DATA, f"careers_{origin}.jsonl"))
    whitelist = json.load(open(os.path.join(DATA, "institutions.json")))
    base = [r for r in rows if origin in r.get("start_ccs", [])]
    cutoff = THIS_YEAR - FOLLOWUP

    # inst[iid][stratum] / ctry[cc][stratum] / fields 只在默认分层上算
    inst = collections.defaultdict(lambda: {s: blank() for s in STRATA})
    # 学科分解按分层各算一份——不然切了分层，学科筛选就对不上号了
    ifields = collections.defaultdict(lambda: {s: collections.defaultdict(blank) for s in STRATA})
    ctry = collections.defaultdict(lambda: {s: blank() for s in STRATA})
    movers = 0

    for r in base:
        ends = set(r.get("end_ccs") or [])
        if r.get("end_cc"):
            ends.add(r["end_cc"])
        seen = collections.defaultdict(dict)   # cc -> stratum -> outcome（同一人同一国只记一次）
        moved = False
        start_ccs = set(r.get("start_ccs") or [])
        for s in r["spans"]:
            if s["cc"] == origin or s["y0"] < r["start"] or s["y0"] > cutoff:
                continue
            # 起步那年就已经挂在该国 → 不是「迁过去」，是本来就在。
            # 不排掉的话，「一直在台湾/香港的人」会被当成迁过去又留下，把留下率顶上天
            # （实测占 ≥4 年 arrival 的 15.2%，台湾几所校因此霸榜）。
            if s["cc"] in start_ccs:
                continue
            dur = s["y1"] - s["y0"] + 1
            if dur < 2:
                continue        # 只挂 1 年 = 合作署名/短访，不算「去过」
            moved = True
            oc = outcome(s["cc"], origin, ends)
            in_strata = [k for k, (lo, hi) in STRATA.items() if lo <= dur <= hi]

            if s["id"] in whitelist:
                for k in in_strata:
                    d = inst[s["id"]][k]
                    d["n"] += 1
                    d[oc] += 1
                    if r.get("field"):
                        fd = ifields[s["id"]][k][r["field"]]
                        fd["n"] += 1
                        fd[oc] += 1
            for k in in_strata:
                seen[s["cc"]].setdefault(k, oc)
        for cc, per in seen.items():
            for k, oc in per.items():
                d = ctry[cc][k]
                d["n"] += 1
                d[oc] += 1
        if moved:
            movers += 1

    countries = sorted(
        [{"cc": cc, "name": CC_NAME.get(cc, cc.upper()),
          "strata": {k: pct(v) for k, v in per.items()}}
         for cc, per in ctry.items() if per[DEFAULT_STRATUM]["n"] >= MIN_N_COUNTRY],
        key=lambda x: -x["strata"][DEFAULT_STRATUM]["n"])

    insts = []
    for iid, per in inst.items():
        if per[DEFAULT_STRATUM]["n"] < MIN_N_INST:
            continue
        w = whitelist[iid]
        fields = {}
        for k in STRATA:
            fl = sorted(
                [{"field": FIELD_ZH.get(f, f), "field_en": f} | pct(fd)
                 for f, fd in ifields[iid][k].items() if fd["n"] >= MIN_N_FIELD],
                key=lambda x: -x["n"])[:8]
            if fl:
                fields[k] = fl
        insts.append({
            "id": iid, "name": w["name"], "ror": w["ror"], "cc": w["cc"],
            "country": CC_NAME.get(w["cc"], (w["cc"] or "??").upper()),
            "works": w["works"],
            "strata": {k: pct(v) for k, v in per.items()},
            "fields": fields,
        })

    # Tier：按默认分层留下率的 **Wilson 下界** 分位切 R1–R4。
    # 用分位不用绝对线——绝对值随抽样口径漂移，分位保证「同一批里的相对位置」可比。
    # 用下界不用原始比率——25 人样本的 40% 站不住脚，按下界排它自己会掉下去。
    # 双挂不计入排序，因为它的含义本身就是暧昧的。
    ranked = sorted(insts, key=lambda x: -(x["strata"][DEFAULT_STRATUM]["stay_lb"] or 0))
    n = len(ranked)
    for i, it in enumerate(ranked):
        q = i / n if n else 0
        it["tier"] = "R1" if q < 0.25 else "R2" if q < 0.5 else "R3" if q < 0.75 else "R4"
        it["rank"] = i + 1

    out = {
        "meta": {
            "origin": origin,
            "origin_name": CC_NAME.get(origin, origin.upper()),
            "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "source": "OpenAlex (CC0) — api.openalex.org",
            "sampled_authors": len(rows),
            "home_start_authors": len(base),
            "movers": movers,
            "mover_rate": round(movers / len(base), 4) if base else None,
            "followup_years": FOLLOWUP,
            "arrival_year_cutoff": cutoff,
            "default_stratum": DEFAULT_STRATUM,
            "strata": {k: {"min": lo, "max": hi} for k, (lo, hi) in STRATA.items()},
            "min_works": 5,
            "min_n_inst": MIN_N_INST,
            "min_n_country": MIN_N_COUNTRY,
            "whitelist_size": len(whitelist),
            "caveats": [
                "学术履历代理指标，不是签证/移民官方统计，也不构成移民或法律建议",
                "只覆盖在 OpenAlex 有署名记录的科研人群，不代表留学生或技术移民整体",
                "样本框是「曾在来源国机构署名发表」的人——本科即出国、在国内没发过论文的那批人不在其中",
                "「留下」= 最后已知署名机构在该国，不等于取得工签或永居",
                "「双挂」= 末位同时挂目的国与来源国；中国学者中很常见，单列以免高估任何一边",
                f"只统计到达年 ≤ {cutoff} 的人（留足 {FOLLOWUP} 年观察期）",
                "在目的机构须跨 ≥2 个年份才算「去过」；2–3 年多为访问学者，务必用时长分层看",
                "起步那年就已挂在该国的不计为「迁过去」——否则一直在当地的人会被算成迁移又留下",
                "机构由 OpenAlex 从署名字符串自动解析，已用 ROR + 产出量白名单过滤，仍可能有错配",
                "学科取自作者最高频 topic 的 field，颗粒很粗——大量做计算机的人被归进「工程」，"
                "所以「计算机」这一类的覆盖机构数偏少（当前仅港新几所达标），别当成「美国没有 CS 数据」",
                "绝对值会随口径漂移，请只做机构/国家之间的横向比较",
            ],
        },
        "countries": countries,
        "institutions": ranked,
    }
    os.makedirs(WEB, exist_ok=True)
    path = os.path.join(WEB, f"data-{origin}.json")

    # 只有实质内容变了才落盘。generated_at 每次都不同，不排除它的话，
    # 每天的定时任务都会产生一个「只有时间戳变了」的空提交，把 git 历史刷成噪音。
    if os.path.exists(path):
        try:
            old = json.load(open(path))
            if {**old, "meta": {**old.get("meta", {}), "generated_at": None}} == \
               {**out, "meta": {**out["meta"], "generated_at": None}}:
                print(f"[{origin}] 实质内容无变化，保持原文件不动（不刷时间戳）")
                write_manifest()   # 数据没变也要保证清单在（首次加清单时会走到这条分支）
                return out
        except (json.JSONDecodeError, OSError):
            pass          # 旧文件坏了就正常覆盖

    with open(path, "w") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    write_manifest()
    m = out["meta"]
    print(f"[{origin}] 样本 {m['sampled_authors']} / 本土起步 {m['home_start_authors']} / "
          f"出海 {movers} ({m['mover_rate']:.1%}) → 国家 {len(countries)}、机构 {len(ranked)}")
    print(f"        {path} ({os.path.getsize(path)/1024:.0f} KB)")
    return out


if __name__ == "__main__":
    for cc in (sys.argv[1:] or ["cn"]):
        build(cc.lower())
