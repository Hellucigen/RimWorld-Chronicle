# -*- coding: utf-8 -*-
"""RimWorld 1.6 .rws 存档 → 结构化 dict/JSON。

.rws 是未压缩 XML(数百 MB 全量 DOM 解析,实测 70MB 存档约 6s、内存数百 MB)。
只提取与"故事"相关的部分:年表(tales)、任务(quests)、信件/消息/对话归档、
人物(地图上的+世界层死亡/休眠的)、RimTalk AI 对话记忆、意识形态、派系等。
输出 dict 里不写本机绝对路径(只存文件名),可安全分享 JSON。
"""
import os, re, sys, json, time
import xml.etree.ElementTree as ET

TICKS_PER_DAY = 60000
QUADRAMS = ["春季", "夏季", "秋季", "冬季"]

def fmt_date(tick, start_year=5500):
    d = tick / TICKS_PER_DAY
    year = start_year + int(d // 60)
    rem = d % 60
    q = int(rem // 15)
    day = int(rem % 15) + 1
    hour = int((rem - int(rem)) * 24)
    return f"{year}-{QUADRAMS[q]}{day:02d} {hour:02d}:00"

def txt(el, path, default=None):
    if el is None: return default
    v = el.findtext(path)
    if v is None: return default
    v = v.strip()
    return default if v in ("", "null") else v

def name_of(nel):
    """Extract display name from a <name> element."""
    if nel is None: return None
    n = (nel.text or "").strip()
    if n and n != "null":
        return n
    first = (nel.findtext("first") or "").strip()
    last = (nel.findtext("last") or "").strip()
    nick = (nel.findtext("nick") or "").strip()
    single = (nel.findtext("name") or "").strip()
    if single and single != "null": return single
    if first or last:
        return f"{first}·{last}" if first and last else (first or last)
    return None

def clean(s):
    if not s: return ""
    s = re.sub(r"<color[^>]*>", "", s)
    s = s.replace("</color>", "").replace("<i>", "").replace("</i>", "")
    s = re.sub(r"\(\*[A-Za-z]+\)", "", s)
    s = re.sub(r"\(/[A-Za-z]+\)", "", s)
    s = re.sub(r"<size=\d+>", "", s)
    s = s.replace("</size>", "")
    return s.strip()

def extract(path):
    """解析一个 .rws 存档文件,返回 dict。"""
    t0 = time.time()
    root = ET.parse(path).getroot()
    game = root.find("game")
    out = {"file": os.path.basename(path), "extractSeconds": round(time.time()-t0,1)}

    meta = root.find("meta")
    out["gameVersion"] = txt(meta, "gameVersion")
    for tag in ("modIds", "modSteamIds", "modNames"):
        node = meta.find(tag)
        if node is not None:
            items = [ (c.text or "").strip() for c in node ]
            if not items:
                items = [s for s in (node.text or "").strip().split("|") if s]
            out[tag] = items

    # scenario
    scen = game.find("scenario")
    sc = {"name": txt(scen,"name"), "summary": txt(scen,"summary"), "description": clean(txt(scen,"description") or "")}
    startdialog = None; letters = []; traits=[]; incidents=[]
    for p in scen.findall("parts/li"):
        cls = p.get("Class") or ""
        if cls == "ScenPart_GameStartDialog": startdialog = clean(txt(p,"text") or "")
        if "Letter" in cls: letters.append({"label": txt(p,"letterLabel"), "text": clean(txt(p,"letterText") or "")})
        if cls == "ScenPart_ForcedTrait": traits.append(txt(p,"trait"))
        if cls == "ScenPart_CreateIncident": incidents.append(txt(p,"incident"))
    sc.update(startDialog=startdialog, scenarioLetters=letters, forcedTraits=traits, forcedIncidents=incidents)
    out["scenario"] = sc

    # time
    tm = game.find("tickManager")
    ticks = int(float(txt(tm,"ticksGame","0"))); sy = int(float(txt(tm,"startingYear","5500")))
    out["time"] = {"ticksGame": ticks, "startingYear": sy, "now": fmt_date(ticks, sy),
                   "days": round(ticks/TICKS_PER_DAY,1),
                   "realPlayTimeHours": round(float(txt(game.find("info"),"realPlayTimeInteracting","0"))/3600,1)}
    out["_startYear"] = sy

    # factions (world factionManager holds all incl. player)
    facs = []
    for f in game.findall("./world/factionManager/allFactions/li"):
        facs.append({"id": f"Fac_{txt(f,'loadID')}", "loadID": txt(f,"loadID"), "def": txt(f,"def"),
                     "name": txt(f,"name"), "leader": txt(f,"leader")})
    out["factions"] = facs
    winfo = game.find("./world/info")
    out["planet"] = {"name": txt(winfo,"name"), "seed": txt(winfo,"seedString"),
                     "rainfall": txt(winfo,"overallRainfall"), "temperature": txt(winfo,"overallTemperature")}
    fac_name = {f["loadID"]: f["name"] for f in facs if f["loadID"]}
    pfac = next((f for f in facs if f["def"] in ("PlayerFaction","RK_PlayerFaction")), None)
    out["playerFaction"] = pfac

    # tales
    tales = []
    for t in game.findall("./taleManager/tales/li"):
        d = txt(t,"def"); tick = int(float(txt(t,"date","0")))
        entry = {"tick": tick, "date": fmt_date(tick, sy), "def": d,
                 "label": clean(txt(t,"customLabel") or "")}
        pawns = []
        for pdnode in t:
            tag = pdnode.tag
            if tag.endswith("PawnData"):
                pawns.append({
                    "id": txt(pdnode,"pawn"), "kind": txt(pdnode,"kind"),
                    "faction": fac_name.get(txt(pdnode,"faction","").replace("Faction_",""), txt(pdnode,"faction")),
                    "gender": txt(pdnode,"gender"), "age": txt(pdnode,"age"),
                    "name": name_of(pdnode.find("name")),
                    "relation": clean(txt(pdnode,"relationInfo") or ""),
                    "leader": txt(pdnode,"isFactionLeader"),
                })
        if pawns: entry["pawns"] = pawns
        dd = t.find("defData")
        if dd is not None: entry["defData"] = txt(dd,"defName")
        out_hidden = txt(t,"hidden")
        if out_hidden: entry["hidden"] = out_hidden
        tales.append(entry)
    tales.sort(key=lambda x: x["tick"])
    out["tales"] = tales

    # quests
    quests = []
    for q in game.findall("./questManager/quests/li"):
        ap = txt(q,"appearanceTick")
        entry = {"name": clean(txt(q,"name") or ""),
                 "description": clean(txt(q,"description") or ""),
                 "appearanceTick": int(float(ap)) if ap else None,
                 "acceptanceTick": int(float(txt(q,"acceptanceTick","0")) or 0) or None,
                 "endTick": int(float(txt(q,"cleanupTick","0")) or 0) or None,
                 "outcome": txt(q,"endOutcome"), "acceptedBy": txt(q,"acceptedBy"),
                 "root": txt(q,"root"), "tags": [ (x.text or "").strip() for x in q.findall("./tags/li") ],
                 "targets": []}
        if entry["appearanceTick"]: entry["date"] = fmt_date(entry["appearanceTick"], sy)
        for tg in q.iter():
            if tg.tag == "tile" and tg.text: entry["targets"].append(tg.text.strip())
        quests.append(entry)
    quests.sort(key=lambda x: x["appearanceTick"] or 0)
    out["quests"] = quests

    # archived letters / messages / dialogs (recent window)
    letters = []; messages = []; dialogs = []
    for a in game.findall("./history/archive/archivables/li"):
        cls = a.get("Class") or ""
        tick = txt(a,"arrivalTick") or txt(a,"startingTick") or txt(a,"createdTick")
        tick = int(float(tick)) if tick else None
        base = {"tick": tick, "date": fmt_date(tick, sy) if tick else None, "def": txt(a,"def"),
                "faction": fac_name.get((txt(a,"relatedFaction") or "").replace("Faction_",""), None)}
        if "Letter" in cls:
            base["label"] = clean(txt(a,"label") or ""); base["text"] = clean(txt(a,"text") or "")
            letters.append(base)
        elif cls == "Message":
            base["text"] = clean(txt(a,"text") or ""); messages.append(base)
        elif cls == "ArchivedDialog":
            base["title"] = clean(txt(a,"title") or ""); base["text"] = clean(txt(a,"text") or ""); dialogs.append(base)
    out["letters"], out["messages"], out["dialogs"] = letters, messages, dialogs
    for a in game.findall("./letterStack/letters/li"):
        tick = txt(a,"arrivalTick")
        out.setdefault("activeLetters", []).append({"label": txt(a,"label"), "text": clean(txt(a,"text") or ""),
                                                    "date": fmt_date(int(float(tick)), sy) if tick else None})

    def pawn_brief(th):
        story = th.find("story")
        p = {"id": txt(th,"id"), "def": txt(th,"def"), "kind": txt(th,"kindDef"),
             "faction": fac_name.get((txt(th,"faction") or "").replace("Faction_",""), txt(th,"faction")),
             "factionId": txt(th,"faction"), "gender": txt(th,"gender"),
             "name": name_of(th.find("name")),
             "spawnedTick": txt(th,"spawnedTick"), "despawnedTick": txt(th,"despawnedTick")}
        q = [(x.text or "").strip() for x in th.findall("./questTags/li")] if th.find("questTags") is not None else []
        if q: p["questTags"] = q
        age = txt(th, "ageTracker/ageBiologicalTicks") or txt(th, "ageTracker/ageChronologicalTicks") \
              or txt(th, "ageTracker/ageBiological") or txt(th, "biologicAgeBiological")
        if age:
            try:
                v = float(age)
                p["age"] = round(v/3600000) if v > 1e6 else round(v)
            except ValueError: pass
        if story is not None:
            p["childhood"] = txt(story, "childhood"); p["adulthood"] = txt(story, "adulthood")
            p["traits"] = [{"def": t.findtext("def"), "degree": int(float(t.findtext("degree") or 0))}
                           for t in story.findall("./traits/allTraits/li")]
            p["xenotype"] = txt(story, "xenotype") or txt(th, "xenotype/xenotypeDef") or txt(th,"xenotype")
        rels = []
        for r in th.findall("./social/directRelations/li"):
            rels.append({"def": txt(r,"def"), "other": txt(r,"otherPawn"), "since": txt(r,"startTicks")})
        if rels: p["relations"] = rels
        return p

    # map pawns (living)
    pawns = []
    for th in game.findall("./maps/li/things/thing"):
        if th.get("Class") != "Pawn": continue
        story = th.find("story")
        p = {"id": txt(th,"id"), "def": txt(th,"def"), "kind": txt(th,"kindDef"),
             "faction": fac_name.get((txt(th,"faction") or "").replace("Faction_",""), txt(th,"faction")),
             "factionId": txt(th,"faction"), "gender": txt(th,"gender"),
             "name": name_of(th.find("name")),
             "spawnedTick": txt(th,"spawnedTick")}
        age = txt(th, "ageTracker/ageBiologicalTicks") or txt(th, "ageTracker/ageChronologicalTicks") \
              or txt(th, "ageTracker/ageBiological") or txt(th, "biologicAgeBiological")
        if age:
            try:
                v = float(age)
                p["age"] = round(v/3600000) if v > 1e6 else round(v)
            except ValueError: pass
        if story is not None:
            p["childhood"] = txt(story, "childhood"); p["adulthood"] = txt(story, "adulthood")
            p["traits"] = [{"def": t.findtext("def"), "degree": int(float(t.findtext("degree") or 0))}
                           for t in story.findall("./traits/allTraits/li")]
            p["xenotype"] = txt(story, "xenotype") or txt(th, "xenotype/xenotypeDef") or txt(th,"xenotype")
            p["titles"] = [txt(t,"def") or (t.text or "").strip() for t in th.findall("./royalty/titles/li")][:6]
        rels = []
        for r in th.findall("./social/directRelations/li"):
            rels.append({"def": txt(r,"def"), "other": txt(r,"otherPawn"), "since": txt(r,"startTicks")})
        if rels: p["relations"] = rels
        sk = th.find("./skillTracker/skills")
        if sk is not None:
            lv = []
            for s in sk.findall("li"):
                sd = txt(s,"def"); level = txt(s,"level")
                try: level = int(level)
                except: level = None
                if sd and level: lv.append((sd, level))
            lv.sort(key=lambda x:-x[1])
            p["topSkills"] = [f"{d}:{l}" for d,l in lv[:6]]
        hed = th.findall("./health/hediffSet/hediffs/li")
        nw = []
        for h in hed:
            hd = txt(h,"def"); sev = txt(h,"severity"); part = txt(h,"partLabel")
            if hd and sev and float(sev) > 0.05:
                nw.append({"def": hd, "severity": round(float(sev),2), "part": part})
        if nw: p["hediffs"] = nw
        eq = [ txt(e,"def") for e in th.findall("./equipment/equipment/innerList/li") ]
        ap_ = [ txt(e,"def") for e in th.findall("./apparel/wornApparel/li") ]
        p["equipment"] = [x for x in eq if x][:4]
        p["apparel"] = [x for x in ap_ if x][:4]
        pawns.append(p)
    out["mapPawns"] = pawns

    # world pawns: dead & mothballed (full pawn objects)
    wdead = []
    for th in game.findall("./world/worldPawns/pawnsDead/li"):
        b = pawn_brief(th)
        sk = th.find("./skillTracker/skills")
        if sk is not None:
            lv = []
            for s in sk.findall("li"):
                sd = txt(s,"def"); level = txt(s,"level")
                try: level = int(level)
                except: level = None
                if sd and level: lv.append((sd, level))
            lv.sort(key=lambda x:-x[1])
            b["topSkills"] = [f"{d}:{l}" for d,l in lv[:4]]
        wdead.append(b)
    out["deadWorldPawns"] = wdead
    wmo = []
    for th in game.findall("./world/worldPawns/pawnsMothballed/li"):
        wmo.append(pawn_brief(th))
    out["mothballedWorldPawns"] = wmo
    out["keptWorldPawnIds"] = [ (x.text or "").strip() for x in game.findall("./world/worldPawns/pawnsForcefullyKeptAsWorldPawns/li") ]

    # RimTalk memories (AI chat rounds)
    rounds = []
    for c in game.findall("components/li"):
        if c.get("Class") == "RimTalk.Memory.RoundMemoryManager":
            for m in c.findall("./RoundMemories/li"):
                ts = txt(m,"timestamp")
                rounds.append({"tick": int(float(ts)) if ts else None,
                               "date": fmt_date(int(float(ts)), sy) if ts else None,
                               "importance": txt(m,"importance"),
                               "content": clean((m.findtext("content") or "").strip())})
    rounds.sort(key=lambda x: x["tick"] or 0)
    out["rimtalkRounds"] = rounds

    # auto-recorder groups (collections)
    groups = []
    for g in game.findall("./history/autoRecorderGroups/li"):
        gname = txt(g,"label") or txt(g,"name")
        items = []
        for idnode in g.iter():
            if idnode.tag == "li" and (idnode.text or "").strip().startswith(("Thing_","CollectibleArt_")):
                items.append(idnode.text.strip())
        groups.append({"label": gname, "items": items[:30]})
    out["collectorGroups"] = groups

    # storyteller
    st = game.find("storyteller")
    out["storyteller"] = {"def": txt(st,"def"), "difficulty": txt(st,"difficulty"),
                          "custom": {t.tag: (t.text or "").strip() for t in (st.findall("customDifficulty/*") if st.find("customDifficulty") is not None else [])}}

    # research completed (def names)
    res = []
    rm = game.find("researchManager")
    if rm is not None:
        for node in rm:
            if "omplete" in node.tag or "Finished" in node.tag or "finished" in node.tag:
                res = [ (x.text or "").strip() for x in node.iter("li") ]
    out["researchCompletedCount"] = len(res)
    out["researchCompleted"] = res

    # misc small story components
    misc = {}
    for c in list(game.find("world/components")) + list(game.find("components")):
        cls = c.get("Class") or ""
        if any(k in cls for k in ("Story", "BertEvent", "QuestChains", "RelationshipLevel")):
            if len(ET.tostring(c)) < 60000:
                misc[cls] = ET.tostring(c, encoding="unicode")
    out["storyComponentsRaw"] = misc

    # colonies (maps) & ideologies
    colonies = []
    for mp in game.findall("./maps/li"):
        mi = mp.find("mapInfo")
        colonies.append({"uniqueID": txt(mp, "uniqueID"), "name": txt(mi, "name"),
                         "biome": txt(mi, "biome"), "worldTile": txt(mi, "tile") or txt(mp, "generatedId")})
    out["colonies"] = colonies
    ideos = []
    for i in game.findall("./world/ideoManager/ideos/li"):
        ideos.append({
            "name": txt(i, "name"), "type": txt(i, "type"), "faction": txt(i, "faction"),
            "description": clean(txt(i, "description") or ""),
            "founder": txt(i, "founder"),
            "meme": txt(i, "baseMeme/def"),
            "precepts": [ txt(p, "def") for p in i.findall("./precepts/li") ][:40],
        })
    out["ideologies"] = ideos

    # map storyState
    ms = game.find("./maps/li/storyState")
    if ms is not None:
        out["mapStoryState"] = {c.tag: (c.text or "").strip()[:200] for c in ms}
    ws = game.find("./world/storyState")
    if ws is not None:
        out["worldStoryState"] = {c.tag: (c.text or "").strip()[:200] for c in ws}
    sw = game.find("storyWatcher")
    if sw is not None:
        out["storyWatcherRaw"] = ET.tostring(sw, encoding="unicode")[:40000]

    return out

def save_json(data, out_dir):
    """把 extract() 的 dict 写成 out_dir/<存档名>.json,返回路径。"""
    os.makedirs(out_dir, exist_ok=True)
    tag = os.path.splitext(data["file"])[0]
    fp = os.path.join(out_dir, f"{tag}.json")
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    return fp

def brief(data):
    """一行统计摘要,供 GUI 日志与 CLI 打印。"""
    return (f"{data['file']}: 年表{len(data['tales'])} 任务{len(data['quests'])} 信{len(data['letters'])} "
            f"消息{len(data['messages'])} 对话{len(data['dialogs'])} 殖民者{len(data['mapPawns'])} "
            f"RimTalk{len(data['rimtalkRounds'])} 截于{data['time']['now']} 用时{data['extractSeconds']}s")

if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print("用法: python -m chronicle.extract 存档.rws [输出目录]"); sys.exit(1)
    out_dir = args[1] if len(args) > 1 else "out"
    d = extract(args[0])
    print("written:", save_json(d, out_dir))
    print(brief(d))
