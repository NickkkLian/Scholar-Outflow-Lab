#!/usr/bin/env python3
"""
Aggregate careers_*.jsonl into "where did they end up" metrics and emit the JSON the web UI reads.

Definitions (written verbatim into the output meta; the page must show them as-is, no hedging):
  Sample      random sample of OpenAlex authors who ever published under an origin-country
              affiliation and have ≥5 works
  Home start  the earliest career year includes the origin country — i.e. researchers who
              *started* at home
  Arrival     a later (arrival year ≥ start year) foreign affiliation spanning ≥2 calendar years
  Window      only arrivals with year ≤ this_year − FOLLOWUP count; otherwise "hasn't left yet"
              gets misread as "stayed"

  ⭐ Strata (the core of the site — unstratified numbers are diluted to meaninglessness by
     visiting scholars):
    short  2–3 years at the destination — mostly visiting scholars / joint training, who were
           always going to go home
    long   ≥4 years — closer to PhD studies / long-term positions (default)
    long6  ≥6 years — putting down roots
    all    any length

  Four mutually exclusive outcomes (sum to 100%), judged on ALL affiliation countries in the
  last known year:
    stay    final countries include the destination, not the origin
    dual    both  ← very common among Chinese researchers; kept separate so neither side is inflated
    ret     final countries include the origin, not the destination
    onward  neither (moved on to a third country)

  ⚠️ A proxy built from academic affiliation records — not visa/immigration statistics and not
     immigration advice. Absolute values are sensitive to sampling; **only compare institutions
     and countries against each other**.
"""

import collections
import datetime
import json
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
DATA = os.path.join(ROOT, "data")
WEB = os.path.join(ROOT, "data")   # the published JSON: Pages serves main's root and the page reads data/

THIS_YEAR = datetime.date.today().year
FOLLOWUP = 5
MIN_N_INST = 25          # minimum sample per institution in the default stratum
MIN_N_COUNTRY = 60
MIN_N_FIELD = 15

# stratum key -> (min years, max years)
STRATA = {"short": (2, 3), "long": (4, 99), "long6": (6, 99), "all": (2, 99)}
DEFAULT_STRATUM = "long"
OUTCOMES = ("stay", "dual", "ret", "onward")

# Canonical display labels stored in the data files (Chinese). The web UI is bilingual and
# derives English labels client-side — countries via Intl.DisplayNames from the ISO code that
# every record carries, fields via a dictionary keyed on these exact strings. Changing a label
# here therefore changes the dictionary key on the front end; keep the two in step.
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

# OpenAlex field name -> stored label. The English original is kept alongside as `field_en`.
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
    """Wilson 95% interval — far better behaved than the normal approximation at small n.
    The page draws its error bars from this."""
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
    # Conservative lower bound: rankings use this, not the raw rate. 40% of a 25-person sample
    # versus 30% of 300 — the former's true value may be far lower. Ranking by the bound lets
    # small-sample flukes sink on their own, with no extra rules.
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
    """Scan the generated origins and write origins.json, which drives the origin switcher.

    Without this manifest the front end can only hard-code one origin — harvested data would
    never become visible. Match data-<two-letter code>.json strictly so data-venues.json is
    not mistaken for an origin.
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
                    "home": meta.get("home_start_authors", 0),
                    "movers": meta.get("movers", 0),
                    # The number of qualifying institutions is driven almost entirely by the
                    # number of movers (measured: Indonesia 3.9% movers → 7 institutions,
                    # China 13.1% → 175). The front end uses this to explain "why does this
                    # origin only have a handful" — otherwise it reads as a broken site.
                    "mover_rate": meta.get("mover_rate"),
                    "institutions": len(d.get("institutions", []))})
    out.sort(key=lambda x: -x["sampled"])
    with open(os.path.join(WEB, "origins.json"), "w") as f:
        json.dump({"origins": out}, f, ensure_ascii=False, separators=(",", ":"))
    return out


def pick_source(origin):
    """While a re-harvest is in progress, use whichever file has more rows — never publish a
    half-finished dataset.

    Upgrading to v2 means re-harvesting the whole file across several days of quota. Mid-way,
    `careers_cn.jsonl` holds only part of the population; computing from it directly would turn
    mainland China on the live site from 180k authors / 175 institutions into 19k / 3 — **this actually happened**
    (the 2026-07-28 scheduled run pushed exactly that). The rule is dumb but reliable: more rows
    wins. Once the new harvest overtakes the backup it switches automatically, with no extra
    state flag to get out of sync.
    """
    cur = os.path.join(DATA, f"careers_{origin}.jsonl")
    bak = cur + ".v1.bak"
    if not os.path.exists(bak):
        return cur, None
    n_cur = sum(1 for _ in open(cur)) if os.path.exists(cur) else 0
    n_bak = sum(1 for _ in open(bak))
    if n_bak > n_cur:
        return bak, f"re-harvest in progress (new {n_cur} < backup {n_bak}); publishing from the backup this round"
    return cur, f"new data has overtaken the backup ({n_cur} ≥ {n_bak}); switching back to it"


def build(origin):
    src, note = pick_source(origin)
    if note:
        print(f"[{origin}] {note}")
    rows = load_jsonl(src)
    whitelist = json.load(open(os.path.join(DATA, "institutions.json")))
    base = [r for r in rows if origin in r.get("start_ccs", [])]
    cutoff = THIS_YEAR - FOLLOWUP

    # inst[iid][stratum] / ctry[cc][stratum]
    inst = collections.defaultdict(lambda: {s: blank() for s in STRATA})
    # Field breakdowns are computed per stratum — otherwise switching strata would leave the
    # field filter pointing at numbers from a different population.
    ifields = collections.defaultdict(lambda: {s: collections.defaultdict(blank) for s in STRATA})
    ctry = collections.defaultdict(lambda: {s: blank() for s in STRATA})
    movers = 0

    for r in base:
        ends = set(r.get("end_ccs") or [])
        if r.get("end_cc"):
            ends.add(r["end_cc"])
        seen = collections.defaultdict(dict)   # cc -> stratum -> outcome (one count per person per country)
        moved = False
        start_ccs = set(r.get("start_ccs") or [])
        for s in r["spans"]:
            if s["cc"] == origin or s["y0"] < r["start"] or s["y0"] > cutoff:
                continue
            # Already affiliated with that country in the very first year → not a move, they
            # were there all along. Without this filter, people who were always in Taiwan /
            # Hong Kong get counted as "moved there and stayed" and push stay rates through the
            # roof (measured: 15.2% of ≥4-year arrivals; a few Taiwanese universities topped
            # the board because of it).
            if s["cc"] in start_ccs:
                continue
            dur = s["y1"] - s["y0"] + 1
            if dur < 2:
                continue        # a single year = co-authorship / short visit, not an arrival
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
            # education = universities; everything else is research institutes / hospitals /
            # government labs. The front end offers a "universities only" filter on this because
            # the non-university records carry noticeably more affiliation-matching noise
            # (see the notes in institutions.py).
            "type": w.get("type", "education"),
            "kind": "edu" if w.get("type", "education") == "education" else "inst",
            "strata": {k: pct(v) for k, v in per.items()},
            "fields": fields,
        })

    # Tier: quartiles R1–R4 on the **Wilson lower bound** of the default-stratum stay rate.
    # Percentiles, not absolute cutoffs — absolute values drift with sampling; percentiles keep
    # "relative position within the same batch" comparable.
    # The bound, not the raw rate — 40% of 25 people doesn't hold up; ranked by the bound it
    # sinks on its own.
    # Dual is excluded from the ranking because its meaning is inherently ambiguous.
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
            # Stored verbatim (Chinese); the web UI translates them client-side by prefix match.
            # Do not rephrase casually — a changed sentence falls back to untranslated text.
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
                "榜单含高校与研究所（中科院/CNRS/NIH/Academia Sinica 这类）。"
                "研究所那批的错配噪音明显更重——署名里出现「Ministry of Education」这种通用短语时，"
                "OpenAlex 会挂到随机国家的同名实体上。已加更高产出门槛 + 通用名黑名单，"
                "仍不敢说干净，**怀疑某条时用「只看高校」筛一遍再下结论**",
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

    # Only write when the substance changed. generated_at differs on every run; without
    # excluding it, the daily job would produce a "timestamp-only" commit every day and turn
    # the git history into noise.
    if os.path.exists(path):
        try:
            old = json.load(open(path))
            if {**old, "meta": {**old.get("meta", {}), "generated_at": None}} == \
               {**out, "meta": {**out["meta"], "generated_at": None}}:
                print(f"[{origin}] no substantive change; leaving the file untouched (timestamp not bumped)")
                write_manifest()   # keep the manifest present even when data is unchanged (first-run case)
                return out
        except (json.JSONDecodeError, OSError):
            pass          # a corrupt old file is simply overwritten

    with open(path, "w") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    write_manifest()
    m = out["meta"]
    print(f"[{origin}] sampled {m['sampled_authors']} / home start {m['home_start_authors']} / "
          f"movers {movers} ({(m['mover_rate'] or 0):.1%}) → {len(countries)} countries, {len(ranked)} institutions")
    print(f"        {path} ({os.path.getsize(path)/1024:.0f} KB)")
    return out


if __name__ == "__main__":
    for cc in (sys.argv[1:] or ["cn"]):
        build(cc.lower())
