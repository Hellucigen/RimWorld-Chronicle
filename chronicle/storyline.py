# -*- coding: utf-8 -*-
"""由 extract() 产出的存档 dict 生成五份人读素材文档:
  00_总览 / 01_编年史 / 02_人物档案 / 03_任务剧情线 / 04_信件与对话

设计:
- 输入是任意多个存档(按添加顺序视作"窗口";同一殖民地的中期档+终局档一起传入即可,
  RimTalk 与信件窗口会自动按 tick 合并去重,标注各自来源)。
- 卷名/派系名/人物名全部取自存档内容,零硬编码;ARC_KEYS 可按你玩的 mod 阵营自行扩充。
- defs 词典(defs.py)可选:缺失时特质/背景显示英文 def 名。
"""
import os, re, json, collections

# 任务主线关键词 → 分组名。按你的 mod 组合自行增删。
ARC_KEYS = [
    ("Milira", "米莉拉帝国线"), ("Koelime", "雪原遗孤/公主线"), ("Ratkin", "鼠族线"), ("Rakinia", "鼠族诸国线"),
    ("Cinder", "灰烬/火车残骸线"), ("Axolotl", "萌螈王朝线"), ("Wolfein", "沃芬公司线"),
    ("HadalMoyo", "深渊舰队线"), ("Kiiro", "隐居乡线"), ("Dragonian", "龙族线"), ("Ancot", "远古造物线"),
    ("OA_", "主线任务链"), ("Fortified", "要塞威胁线"), ("VanillaQuests", "vanilla 支线"),
    ("Embergarden", "余烬花园/复活线"),
]

TALE_DEF_LABEL = {
    "TileSettled":"建寨","MajorThreat":"重大威胁","Captured":"被俘","Marriage":"婚姻",
    "Divorce":"离婚","Breakup":"分手","Death":"死亡","KilledByEnemy":"被敌人杀死","KilledByColonist":"被族人处决",
    "Executed":"处决","DiedOfOldAge":"老死","Disease":"疾病","OrganHarvest":"器官收获","Tame":"驯服",
    "BecameColonist":"加入殖民队","BecamePrisoner":"沦为俘虏","BecameSlave":"沦为奴隶","BecameFree":"获得自由",
    "HypothermiaRevealed":"失温","HeatstrokeRevealed":"中暑","FoodPoisoning":"食物中毒","PrisonerRecruited":"囚犯转化",
    "PrisonerSold":"卖俘","OrganSold":"卖器官","PartBulkSold":"批量卖部件","SurgeryFailed":"手术失败",
    "SurgerySuccess":"手术成功","NewColony":"新殖民地","SiteDiscovered":"发现遗址","FactionGoodwillChanged":"关系变动",
}

REL_KINDS = {
    "Friend": "朋友", "FriendRival": "亦敌亦友", "Enemy": "仇敌", "Rival": "对手",
    "Lover": "恋人", "ExLover": "前任恋人", "Fiance": "未婚夫妻", "EngagedTo": "订婚对象", "Spouse": "配偶",
    "Parent": "父母", "Child": "子女", "Sibling": "兄弟姐妹", "HalfSibling": "同父异母/同母异父兄弟姐妹",
    "Grandparent": "祖父母", "Grandchild": "孙辈", "NieceOrNephew": "侄甥", "AuntOrUncle": "叔伯姑舅姨",
    "Pycnovial": "堂表兄弟姐妹", "Cousin": "表亲", "Bonded": "羁绊伙伴", "Consanguinity": "血亲",
    "Stepparent": "继父母", "Stepchild": "继子女", "Stepsibling": "继兄弟姐妹", "AdoptedParent": "养父母",
    "AdoptedChild": "养子女", "AdoptedSibling": "养兄弟姐妹", "Inlaw": "姻亲", "Coworker": "同事",
    "Neighbor": "邻居", "Overseer": "监督者", "Collateral": "旁系",
}

def make_windows(saves):
    """为每个存档生成窗口标签(派系名;同派系多档时以截止游戏日期区分)。"""
    names = [(d.get("playerFaction") or {}).get("name") or os.path.splitext(d.get("file",""))[0] for d in saves]
    wins = []
    for i, d in enumerate(saves):
        label = names[i] if names.count(names[i]) == 1 else f"{names[i]}·截至{d['time']['now'][:9]}"
        wins.append((label, d))
    return wins

def pawn_name_index(d):
    idx = {}
    for key in ("mapPawns", "deadWorldPawns", "mothballedWorldPawns"):
        for p in d.get(key) or []:
            pid = p.get("id") or ""
            nm = p.get("name") or (pid.replace("Thing_", "") if pid else None)
            if nm:
                idx[pid] = nm
                if pid.startswith("Thing_"): idx[pid[6:]] = nm
                else: idx["Thing_"+pid] = nm
    return idx

def pname(name_idx, pid):
    if not pid: return "?"
    return name_idx.get(pid, pid)

def trait_zh(DEFS, t):
    d = t["def"] or "?"
    deg = t.get("degree", 0)
    info = (DEFS.get("trait") or {}).get(d)
    if not info: return d + (f"({deg})" if deg else "")
    lbl = info.get("label") or d
    dds = info.get("degrees") or []
    matched = None
    for dd in dds:
        try: dv = int(float(dd.get("degree") or 0))
        except (TypeError, ValueError): dv = None
        if dv == deg:
            matched = dd; break
    if matched is None and deg == 0 and len(dds) == 1 and dds[0].get("degree") is None:
        matched = dds[0]
    if matched and matched.get("label"):
        lbl = matched["label"]
    return f"{lbl}" + (f"·{deg:+d}" if deg else "")

def story_zh(DEFS, sid):
    if not sid: return None
    info = (DEFS.get("story") or {}).get(sid)
    if not info: return sid
    return info.get("title") or sid

def fmt_tick_date(d, tick):
    if tick is None: return None
    sy = d.get("_startYear", 5500)
    days = tick/60000.0
    y = sy + int(days//60); rem = days % 60
    return f"{y}-{['春','夏','秋','冬'][int(rem//15)]}{int(rem%15)+1:02d}日"

def rel_zh(DEFS, name_idx, r):
    kind = REL_KINDS.get(r["def"], r["def"])
    return f"{kind}·{pname(name_idx, r.get('other'))}"

def core_relations(DEFS, name_idx, p):
    return [rel_zh(DEFS, name_idx, r) for r in p.get("relations") or [] if r.get("def") in REL_KINDS]

def is_colonist(d, p):
    pf = (d.get("playerFaction") or {}).get("loadID")
    fid = (p.get("factionId") or "").replace("Faction_", "")
    return fid == pf

def is_mech(p):
    s = (p.get("def") or "") + "|" + (p.get("kind") or "")
    return "Mech" in s or "Mechanoid" in s

def arc_of(q):
    s = (q.get("root") or "") + "|" + "|".join(q.get("tags") or []) + "|" + (q.get("name") or "")
    for pat, name in ARC_KEYS:
        if pat.lower() in s.lower(): return name
    return "通用/本地支线"

# =========================================================
def generate(saves, DEFS=None, out_dir="story"):
    """saves: extract() 的 dict 列表(按游玩顺序);返回写出的文件路径列表。"""
    DEFS = DEFS or {}
    os.makedirs(out_dir, exist_ok=True)
    wins = make_windows(saves)
    NIDX = {label: pawn_name_index(d) for label, d in wins}
    written = []

    # ---------- 00 总览 ----------
    lines = ["# 战役素材总览", "",
             f"> {len(saves)} 个存档窗口,按添加顺序排列;同一殖民地的中期档与终局档可一起传入。", ""]
    for label, d in wins:
        scen = d.get("scenario") or {}
        lines += [f"## {label} — {d['file']}",
          f"- 游戏版本:{d.get('gameVersion','?')}  累计游玩约 {d['time']['realPlayTimeHours']} 小时({d['time']['days']} 天)",
          f"- 结束于游戏日期:{d['time']['now']}",
          f"- 开局场景:{scen.get('name')}:{scen.get('summary')}",
          f"- 剧情叙述者:{d['storyteller']['def']}  难度:{d['storyteller']['difficulty']}",
          f"- mod 清单:{len(d.get('modNames') or [])} 个"]
        for l in (scen.get("scenarioLetters") or []):
            if l and (l.get("text") or l.get("label")):
                lines.append(f"- 开场信《{l['label']}》:{l['text']}")
        lines.append("")
    lines += ["## 世界设定速览"]
    for label, d in wins:
        names = sorted({f["name"] for f in d["factions"] if f["name"]})
        lines.append(f"- {label} 星球:{(d.get('planet') or {}).get('name','?')}  势力(部分):" + "、".join(names[:25]))
    st_custom = (wins[-1][1]["storyteller"].get("custom") or {})
    lines += ["", "## 特殊规则(开局/难度设定,写作时留意)"]
    for k, v in st_custom.items():
        lines.append(f"- {k} = {v}")
    forced = (wins[0][1].get("scenario") or {}).get("forcedTraits") or []
    if forced:
        lines.append("- 开局强制特质:" + "、".join(trait_zh(DEFS, {"def": t, "degree": 0}) for t in forced[:8]))
    lines += ["", "## 这些文档怎么用",
      "1. 以《01_编年史》为主干挑高潮事件;",
      "2. 用《02_人物档案》定主角与关系,以最新窗口为准,旧窗口作前史;",
      "3. 需要台词与氛围时直接引用《04_信件与对话》里的 RimTalk 原文;",
      "4. 《03_任务剧情线》提供外部势力的完整支线;",
      "5. 《05_角色台词速查》按说话者聚合全部台词,适合校准角色口吻。"]
    p = os.path.join(out_dir, "00_总览.md"); open(p, "w", encoding="utf-8").write("\n".join(lines) + "\n"); written.append(p)

    # ---------- 01 编年史 ----------
    out = ["# 编年史(按游戏内日期,绝对 tick 换算)", ""]
    for label, d in wins:
        out.append(f"## {label} — {(d.get('scenario') or {}).get('name','?')}")
        events = []
        for t in d["tales"]:
            events.append({"tick": t["tick"], "def": t["def"], "label": t.get("label",""), "pawns": t.get("pawns") or []})
        for q in d["quests"]:
            if not q.get("appearanceTick"): continue
            acc = q.get("acceptedBy") not in (None,"null") or bool(q.get("acceptanceTick"))
            events.append({"tick": q["appearanceTick"], "def": "Quest", "label": q.get("name",""),
                           "desc": q.get("description",""), "outcome": q.get("outcome"), "accepted": acc})
        events.sort(key=lambda x: x["tick"])
        i = 0
        while i < len(events):
            e = events[i]
            if e["def"] == "MajorThreat":
                j = i; agg = [e]
                while j+1 < len(events) and events[j+1]["def"] == "MajorThreat" and events[j+1]["label"] == e["label"] \
                      and events[j+1]["tick"] - events[j]["tick"] < 60000*8:
                    j += 1; agg.append(events[j])
                rng = f"{fmt_tick_date(d,agg[0]['tick'])} ~ {fmt_tick_date(d,agg[-1]['tick'])}"
                out.append(f"- {rng}  ⚔️ {e['label']} ×{len(agg)}" if len(agg) > 1
                           else f"- {fmt_tick_date(d,e['tick'])}  ⚔️ {e['label']}")
                i = j + 1
                continue
            line = f"- {fmt_tick_date(d,e['tick'])}  "
            if e["def"] == "Quest":
                mark = "📜" + ("[已接受]" if e.get("accepted") else "[未接受]") + ("[" + e["outcome"] + "]" if e.get("outcome") else "")
                line += f"{mark} 任务《{e['label']}》"
                if e.get("desc") and e.get("accepted"):
                    line += f" —— {re.sub(r'\\s+', ' ', e['desc'])[:110]}…"
            else:
                zh = TALE_DEF_LABEL.get(e["def"], e["def"])
                who = ", ".join(p.get("name") or "?" for p in e["pawns"]) if e["pawns"] else ""
                lab = e["label"] or zh
                if e["pawns"] and e["def"] not in ("MajorThreat","TileSettled"):
                    rel = " / ".join(p.get("relation","") for p in e["pawns"] if p.get("relation"))
                    line += f"🎭 {lab}:{who}"
                    if rel: line += f"(关系:{re.sub(r'\\s+',' ',rel)[:120]})"
                else:
                    line += f"🎭 {lab}"
                if e.get("hidden"): line += "(隐)"
            out.append(line)
            i += 1
        out.append("")
    p = os.path.join(out_dir, "01_编年史.md"); open(p, "w", encoding="utf-8").write("\n".join(out) + "\n"); written.append(p)

    # ---------- 02 人物档案 ----------
    out = ["# 人物档案", "", "> 读最新窗口的现状;旧窗口的名录用于前史与死亡人物。"]
    for label, d in reversed(wins):
        ni = NIDX[label]
        colonists = [p_ for p_ in d["mapPawns"] if is_colonist(d, p_)]
        mechs = [p_ for p_ in colonists if is_mech(p_)]
        others = [p_ for p_ in colonists if p_ not in mechs and p_.get("gender") in (None,"None")]
        living = [p_ for p_ in colonists if p_ not in mechs and p_ not in others]
        dead = [p_ for p_ in d.get("deadWorldPawns") or []
                if (p_.get("factionId") or "").replace("Faction_","") == (d["playerFaction"] or {}).get("loadID")
                and not is_mech(p_)]
        out.append(f"## {label}({d['file']})")
        out.append(f"\n### 在世殖民者 {len(living)} 人\n")
        for p_ in sorted(living, key=lambda x: x.get("name") or ""):
            bits = [f"**{p_.get('name') or p_['id']}**", f"{p_.get('def')}", f"{p_.get('gender')}",
                    f"{p_.get('age')}岁" if p_.get("age") else "年龄未知"]
            if p_.get("titles"): bits.append("头衔:" + ",".join(t for t in p_["titles"] if t))
            out.append("- " + " · ".join(str(b) for b in bits))
            ch = story_zh(DEFS, p_.get("childhood")); ad = story_zh(DEFS, p_.get("adulthood"))
            if ch or ad: out.append(f"  - 背景:{ch}(童年)/ {ad}(成年)")
            if p_.get("traits"):
                seen = []
                for t in p_["traits"]:
                    s = trait_zh(DEFS, t)
                    if s not in seen: seen.append(s)
                out.append("  - 特质:" + ";".join(seen))
            if p_.get("topSkills"): out.append("  - 擅长:" + ", ".join(p_["topSkills"]))
            rels = core_relations(DEFS, ni, p_)
            if rels: out.append("  - 关系:" + ";".join(rels))
            if p_.get("hediffs"):
                notable = [h for h in p_["hediffs"] if (h.get("part") or "Scar" in (h.get("def") or "")
                             or "Missing" in (h.get("def") or "") or "Amputat" in (h.get("def") or "") or (h.get("severity") or 0) > 0.5)]
                if notable: out.append("  - 伤病:" + ";".join(f"{h['part'] or ''}{h['def']}({h['severity']})" for h in notable[:6]))
            if p_.get("equipment"): out.append("  - 装备:" + ",".join(p_["equipment"][:3]))
        if others:
            out.append(f"\n### 同伴动物/其他 {len(others)}\n")
            for p_ in others[:20]:
                out.append(f"- {p_.get('name') or p_['id']}({p_.get('def')})")
        if mechs:
            out.append(f"\n### 机械体 {len(mechs)} 台\n")
            for p_ in mechs[:20]:
                ov = [pname(ni, r.get("other")) for r in p_.get("relations") or [] if r.get("def")=="Overseer"]
                out.append(f"- {p_.get('name') or p_['id']}({p_.get('kind') or p_.get('def')}) 监督:{','.join(ov)}")
        if dead:
            out.append(f"\n### 已故成员(世界记录,排除机械体){len(dead)} 人\n")
            for p_ in dead[:40]:
                out.append(f"- {p_['name'] or p_['id']}({p_.get('def')}, {p_.get('age')}岁, 卒于 {fmt_tick_date(d, float(p_.get('despawnedTick') or 0))})")
        out.append("")
    p = os.path.join(out_dir, "02_人物.md"); open(p, "w", encoding="utf-8").write("\n".join(out) + "\n"); written.append(p)

    # ---------- 03 任务剧情线 ----------
    out = ["# 任务剧情线(按主线/支线分组)", ""]
    grouped = collections.defaultdict(list)
    for wi, (label, d) in enumerate(wins):
        for q in d["quests"]:
            if not (q.get("description") or q.get("name")): continue
            grouped[arc_of(q)].append((wi, label, q))
    byname_all = collections.defaultdict(set)
    for arc, items in grouped.items():
        for wi, label, q in items:
            byname_all[re.sub(r"\s+","", q.get("name") or q.get("root") or "?")].add(wi)
    for arc, items in sorted(grouped.items()):
        out.append(f"\n## {arc}\n")
        byname = collections.defaultdict(list)
        for wi, label, q in items:
            byname[re.sub(r"\s+","", q.get("name") or q.get("root") or "?")].append((wi, label, q))
        for key, lst in byname.items():
            vols = {wi for wi, _, _ in lst}
            dupmark = "  ⟪多窗口重复,取一份即可⟫" if len(vols) > 1 else ""
            t0q = sorted(lst, key=lambda x: x[2].get("appearanceTick") or 0)[0][2]
            name = t0q.get("name") or t0q.get("root")
            dates = ", ".join(f"{q.get('date')}" for _, _, q in lst if q.get("date"))[:2] or ""
            outcome = ",".join(filter(None, [q.get("outcome") for _, _, q in lst]))
            out.append(f"### 《{name}》 {dates} 状态:{'已接受' if any(q.get('acceptanceTick') for _,_,q in lst) else '未接受'}{(' 结果:'+outcome) if outcome else ''}{dupmark}")
            for wi, label, q in sorted(lst, key=lambda x: x[2].get("appearanceTick") or 0):
                desc = re.sub(r"\s*\n\s*", " ", q.get("description") or "").strip()
                if desc:
                    d0 = wins[wi][1]
                    out.append(f"- [{fmt_tick_date(d0, q['appearanceTick']) if q.get('appearanceTick') else ''}] {desc[:420]}")
    p = os.path.join(out_dir, "03_任务线.md"); open(p, "w", encoding="utf-8").write("\n".join(out) + "\n"); written.append(p)

    # ---------- 04 信件与对话 ----------
    out = ["# 信件、报告与对话素材", ""]
    seen_ticks = set()
    for label, d in wins:
        out.append(f"## {label}")
        ls = [l for l in (d.get("letters") or []) if (l.get("tick") or 0) not in seen_ticks]
        seen_ticks.update(l.get("tick") or 0 for l in ls)
        if ls:
            out.append(f"\n### 最近信件存档({len(ls)} 封)\n")
            for l in ls[-40:]:
                out.append(f"- {l['date']} 《{l['label']}》:{l['text'][:240]}")
        if d.get("dialogs"):
            out.append("\n### 剧情对话\n")
            for dl in d["dialogs"]:
                out.append(f"- {dl['date']} {dl['title']}:{dl['text'][:200]}")
        if d.get("activeLetters"):
            out.append("\n### 未处理(进行中)事件\n")
            for l in d["activeLetters"]:
                out.append(f"- 《{l['label']}》:{l['text'][:200]}")
        out.append("")
    out.append("## RimTalk AI 对话记忆(角色口吻素材)")
    seen_rt = set()
    for label, d in wins:
        rounds = [r for r in (d.get("rimtalkRounds") or []) if (r.get("tick") or 0) not in seen_rt]
        seen_rt.update(r.get("tick") or 0 for r in rounds)
        if not rounds: continue
        out.append(f"\n### {label}({len(rounds)} 条,时间序)")
        for r in rounds:
            c = (r.get("content") or "").replace("\n", " ")
            out.append(f"- {r['date']} [重要度{r['importance']}] {c[:300]}")
    p = os.path.join(out_dir, "04_信件与对话.md"); open(p, "w", encoding="utf-8").write("\n".join(out) + "\n"); written.append(p)

    return written

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("用法: python -m chronicle.storyline 输出目录 存档1.json [存档2.json ...]"); sys.exit(1)
    out_dir, paths = sys.argv[1], sys.argv[2:]
    saves = [json.load(open(p, encoding="utf-8")) for p in paths]
    DEFS = {}
    dp = os.path.join(out_dir, "defs.json")
    if os.path.isfile(dp): DEFS = json.load(open(dp, encoding="utf-8"))
    for p_ in generate(saves, DEFS, out_dir): print("written:", p_)
