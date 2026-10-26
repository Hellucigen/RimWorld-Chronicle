# -*- coding: utf-8 -*-
"""def 词典:把存档里的 backstory/trait/xenotype 的 def 名解析成中文标签。

流程(合并了原 defs_lookup/defs_core/defs_lang 三步,单次遍历 mods 目录):
  1. 从存档 dict 收集需要的 def 名;
  2. 扫描 Mods/ 与创意工坊 XML,匹配 BackstoryDef/TraitDef/XenotypeDef;
     路径里含 ChineseSimplified/Chinese (Simplified) 目录的视为语言包(DefInjected),做中文覆盖;
  3. 扫描游戏 Data/ 补官方 Core/DLC 的 def;
  4. 解包 Data/Core/Languages 下的中文 .tar 再覆盖一轮;
  5. 结果写 defs.json(存在则增量,已解析的 def 不重扫)。

游戏目录缺失时优雅降级:词典为空,素材文档里显示英文 def 名。
"""
import os, re, json, time, tarfile, glob
import xml.etree.ElementTree as ET

def has_cjk(s): return any('\u4e00' <= c <= '\u9fff' for c in s or "")

def needed_names(saves):
    story, trait, xeno = set(), set(), set()
    for d in saves:
        for key in ("mapPawns", "deadWorldPawns", "mothballedWorldPawns"):
            for p in d.get(key) or []:
                for t in p.get("traits") or []:
                    if t.get("def"): trait.add(t["def"])
                for k in ("childhood", "adulthood"):
                    if p.get(k): story.add(p[k])
                if p.get("xenotype"): xeno.add(p["xenotype"])
    return story, trait, xeno

def _story_li(li):
    return {"title": (li.findtext("title") or li.findtext("titleShort") or "").strip(),
            "body": (li.findtext("body") or "").strip(),
            "workDescriptions": [ (x.text or "").strip() for x in li.findall("./workDescriptions/li") ]}

def _trait_li(li):
    deg = [{"degree": dd.findtext("degree"),
            "label": (dd.findtext("label") or "").strip(),
            "description": (dd.findtext("description") or "").strip()}
           for dd in li.findall("./degreeDatas/li")]
    return {"label": (li.findtext("label") or "").strip(),
            "description": (li.findtext("description") or "").strip(), "degrees": deg}

def build_defs(saves, data_dir=None, mods_dirs=(), out_defs_path=None, log=lambda s: None):
    """saves: extract() 产出的 dict 列表。返回 defs dict {story, trait, xeno}。"""
    defs = {"story": {}, "trait": {}, "xeno": {}}
    if out_defs_path and os.path.isfile(out_defs_path):
        try:
            loaded = json.load(open(out_defs_path, encoding="utf-8"))
            for k in defs: defs[k].update(loaded.get(k) or {})
            log(f"复用已有词典: {len(defs['story'])} 背景 / {len(defs['trait'])} 特质 / {len(defs['xeno'])} 基因型")
        except (OSError, ValueError):
            pass

    need_s, need_t, need_x = needed_names(saves)
    todo_s, todo_t, todo_x = need_s - set(defs["story"]), need_t - set(defs["trait"]), need_x - set(defs["xeno"])
    log(f"需要解析: {len(todo_s)} 背景, {len(todo_t)} 特质, {len(todo_x)} 基因型")
    if not (todo_s | todo_t | todo_x):
        return defs

    hits = 0
    def apply_li(li):
        nonlocal hits
        dn = (li.findtext("defName") or "").strip()
        if not dn: return
        if dn in need_s:
            title = (li.findtext("title") or li.findtext("titleShort") or "").strip()
            body = (li.findtext("body") or li.findtext("baseDesc") or "").strip()
            if has_cjk(title) or (dn not in defs["story"] and title):
                cur = defs["story"].setdefault(dn, {})
                if title: cur["title"] = title
                if body: cur["body"] = body
                hits += 1
        elif dn in need_t:
            label = (li.findtext("label") or "").strip()
            cur = defs["trait"].setdefault(dn, {"label": "", "description": "", "degrees": []})
            if label and (has_cjk(label) or not cur["label"]):
                cur["label"] = label; hits += 1
            desc = (li.findtext("description") or "").strip()
            if desc and has_cjk(desc): cur["description"] = desc
            for dd in li.findall("./degreeDatas/li"):
                dl = (dd.findtext("label") or "").strip()
                if dl and has_cjk(dl):
                    dnum = dd.findtext("degree")
                    matched = False
                    for deg in cur.get("degrees", []):
                        if str(deg.get("degree")) == str(dnum):
                            deg["label"] = dl; matched = True; break
                    if not matched and len(cur.get("degrees", [])) == 1:
                        cur["degrees"][0]["label"] = dl
                    hits += 1
        elif dn in need_x:
            label = (li.findtext("label") or "").strip()
            if label and dn not in defs["xeno"]:
                defs["xeno"][dn] = {"label": label}; hits += 1

    def apply_langdata(root):
        nonlocal hits
        for el in root:
            key, val = el.tag, (el.text or "").strip()
            parts = key.split(".")
            dn = parts[0]
            if len(parts) < 2 or not val or not has_cjk(val): continue
            if dn in need_s:
                fld = ".".join(parts[1:])
                cur = defs["story"].setdefault(dn, {})
                if fld == "title": cur["title"] = val; hits += 1
                elif fld in ("body", "baseDesc"): cur["body"] = val
                elif fld in ("titleShort", "titleFemale", "titleShortFemale") and not cur.get("title"): cur["title"] = val; hits += 1
            elif dn in need_t:
                cur = defs["trait"].setdefault(dn, {"label": "", "description": "", "degrees": []})
                if parts[1] == "label": cur["label"] = val; hits += 1
                elif parts[1] == "description": cur["description"] = val
                elif len(parts) >= 4 and parts[1] == "degreeDatas":
                    dname, fld = parts[2], parts[3]
                    for deg in cur.get("degrees", []):
                        if (deg.get("label") or "").lower().replace(" ", "_").replace("-", "_") == dname:
                            if fld == "label": deg["label"] = val; hits += 1
                            break
                    else:
                        if len(cur.get("degrees", [])) == 1 and fld == "label":
                            cur["degrees"][0]["label"] = val; hits += 1

    def process_xml(fp):
        try:
            t = open(fp, encoding="utf-8-sig", errors="ignore").read()
        except OSError:
            return
        if "<defName" not in t and "LanguageData" not in t:
            return
        try:
            root = ET.fromstring(t)
        except ET.ParseError:
            return
        if root.tag == "LanguageData":
            apply_langdata(root)
        else:
            for li in root: apply_li(li)

    lang_re = re.compile(r"chinese[- ]?(simplified|\(simplified)?", re.I)

    def is_lang_dir(dirpath):
        return any(lang_re.search(part) for part in os.path.normpath(dirpath).split(os.sep))

    # --- 1+2) mods 与工坊:Defs + 语言包,单遍历 ---
    t0 = time.time(); nscanned = 0
    for base in mods_dirs or ():
        if not base or not os.path.isdir(base): continue
        for dirpath, _, files in os.walk(base):
            lang = is_lang_dir(dirpath)
            for fn in files:
                if not fn.endswith(".xml"): continue
                fp = os.path.join(dirpath, fn)
                try:
                    if os.path.getsize(fp) > 8_000_000 and not lang: continue
                except OSError: continue
                process_xml(fp)
                nscanned += 1
                if nscanned % 5000 == 0:
                    log(f"扫描中… {nscanned} 个 XML,已解析 {len(defs['story'])+len(defs['trait'])+len(defs['xeno'])} 项")
    log(f"Mods 扫描完成: {nscanned} 个 XML,用时 {time.time()-t0:.0f}s")

    # --- 3) 官方 Data ---
    if data_dir and os.path.isdir(data_dir):
        t0 = time.time(); n = 0
        for dirpath, _, files in os.walk(data_dir):
            for fn in files:
                if fn.endswith(".xml"):
                    process_xml(os.path.join(dirpath, fn)); n += 1
        log(f"Data 扫描完成: {n} 个 XML,用时 {time.time()-t0:.0f}s")
    else:
        log("未找到游戏 Data 目录,跳过官方 def 扫描")

    # --- 4) Core 中文语言包 tar ---
    if data_dir:
        for tp in glob.glob(os.path.join(data_dir, "Core", "Languages", "ChineseSimplified*.tar")):
            try:
                with tarfile.open(tp) as tf:
                    for m in tf.getmembers():
                        if m.name.endswith(".xml"):
                            text = tf.extractfile(m).read().decode("utf-8", "ignore")
                            try:
                                root = ET.fromstring(text)
                                if root.tag == "LanguageData": apply_langdata(root)
                                else:
                                    for li in root: apply_li(li)
                            except ET.ParseError:
                                pass
                log(f"已应用 Core 中文语言包: {os.path.basename(tp)}")
            except (OSError, tarfile.TarError):
                pass

    still = len(need_s - set(defs["story"])) + len(need_t - set(defs["trait"])) + len(need_x - set(defs["xeno"]))
    log(f"词典就绪: 背景 {len(defs['story'])} / 特质 {len(defs['trait'])} / 基因型 {len(defs['xeno'])}"
        + (f",仍有 {still} 项未解析(将显示英文 def 名)" if still else ""))

    if out_defs_path:
        os.makedirs(os.path.dirname(out_defs_path) or ".", exist_ok=True)
        json.dump(defs, open(out_defs_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return defs
