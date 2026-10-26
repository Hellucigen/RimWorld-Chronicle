# -*- coding: utf-8 -*-
"""LLM 写作:把素材文档(00-05)喂给 OpenAI 兼容 API,先出卷大纲,再逐章生成小说草稿。

- 零第三方依赖:仅用标准库 urllib.request。
- 兼容所有 OpenAI /chat/completions 端点(OpenAI 官方、DeepSeek、Kimi、智谱、通义、
  OpenRouter、本地 Ollama/LM Studio 的 OpenAI 兼容模式等)。
- base_url 可填三种写法,自动补全:
    https://api.openai.com/v1
    https://api.deepseek.com
    https://…/v1/chat/completions
- 密钥来源:优先环境变量 LLM_API_KEY(最安全),其次 config.json 的 llm.api_key。
- 事实约束:system 提示要求"一切人物/事件须能回溯素材,正文零游戏术语,红线不虚构";
  素材按预算截断,避免 token 爆炸。
"""
import os, re, json, time, urllib.request, urllib.error

DEFAULT_BASE = "https://api.openai.com/v1"

SYSTEM_WRITER = (
    "你是历史小说家,把《环世界》殖民战役的存档素材改写成"
    "读起来像真实殖民者一生、而非游戏日志的长篇。硬规则:"
    "(1) 第三人称限知,轮流聚焦少数视角人物,严禁全知伪造内心;"
    "(2) 一切设定、事件、人物关系必须能回溯到提供的素材,不得编造;"
    "(3) 正文禁止出现 tick/Downed/def/存档/mod 等游戏或机制词汇,"
    "把机制翻译成体感(失温→手指不听使唤;启灵→脑子里多了一格空);"
    "(4) 素材未证实的空白(复活机制/未回收伏线等)保持留白,不臆测;"
    "(5) 语言沉静、克制、带荒诞温情;每章按指定字数,章末不做总结陈词。"
)
SYSTEM_PLANNER = (
    "你是长篇小说的结构编辑。根据战役素材规划一部多章小说的卷/章大纲。"
    "章按叙事单元而非逐事件;日常生产与重复袭击压缩为背景。"
    "只输出 JSON,不要解释,不要 markdown 代码块。"
)

def _endpoint(base):
    base = (base or DEFAULT_BASE).strip().rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    # 结尾像补全路径的别名(v1)则拼接,否则当根再拼 v1
    if base.endswith("/v1"):
        return base + "/chat/completions"
    if re.search(r"/v\d+[A-Za-z0-9\-]*$", base):
        return base + "/chat/completions"
    return base + "/v1/chat/completions"

def get_api_key(cfg):
    return os.environ.get("LLM_API_KEY") or (cfg or {}).get("api_key") or ""

def call_chat(cfg, messages, timeout=180, retries=2, log=lambda s: None):
    """POST 一条 chat 请求,返回文本。失败重试,最终抛出 RuntimeError。"""
    key = get_api_key(cfg)
    if not key:
        raise RuntimeError("未设置 API 密钥:请在环境变量 LLM_API_KEY 或配置里填写。")
    url = _endpoint(cfg.get("base_url"))
    payload = {
        "model": cfg.get("model") or "gpt-4o-mini",
        "messages": messages,
        "temperature": float(cfg.get("temperature", 0.85)),
    }
    if cfg.get("max_tokens"):
        payload["max_tokens"] = int(cfg["max_tokens"])
    data = json.dumps(payload).encode("utf-8")
    last = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, data=data, method="POST", headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + key,
            })
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                obj = json.loads(resp.read().decode("utf-8"))
            return obj["choices"][0]["message"]["content"].strip()
        except urllib.error.HTTPError as e:
            body = ""
            try: body = e.read().decode("utf-8", "ignore")[:300]
            except Exception: pass
            last = f"HTTP {e.code} {e.reason}: {body}"
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
        if attempt < retries:
            log(f"  请求失败({last}),重试 {attempt+1}/{retries} …")
            time.sleep(2 * (attempt + 1))
    raise RuntimeError("调用 LLM 失败:" + str(last))

def test_connection(cfg, log=lambda s: None):
    """发一条最小请求验证端点/密钥/模型可用。返回 True 或抛错。"""
    reply = call_chat(cfg, [
        {"role": "system", "content": "只回复两个字:成功"},
        {"role": "user", "content": "ping"},
    ], timeout=min(60, int(cfg.get("timeout", 180))), log=log)
    log("  模型回应:" + reply[:60])
    return True

# ---------- 素材收集 ----------
MAT_FILES = [("总览", "00_总览.md", 3000), ("人物", "02_人物.md", 12000),
             ("编年史", "01_编年史.md", 20000), ("信件与对话", "04_信件与对话.md", 12000),
             ("台词速查", "05_角色台词速查.md", 12000)]

def gather_material(out_dir, total_budget=48000):
    """读素材文档,按各段上限截断后拼成一个事实包字符串。缺文件则跳过。"""
    blocks = []
    used = 0
    for label, fn, cap in MAT_FILES:
        p = os.path.join(out_dir, fn)
        if not os.path.isfile(p):
            continue
        txt = open(p, encoding="utf-8").read()
        txt = txt[:cap]
        blocks.append(f"===== {label}({fn})=====\n{txt}")
        used += len(txt)
        if used >= total_budget:
            break
    if not blocks:
        raise RuntimeError("输出目录里没有素材文档(先跑一次素材提取)。")
    return "\n\n".join(blocks)

# ---------- 大纲 ----------
def _extract_json(text):
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    m = re.search(r"[\[{].*[\]}]", text, re.S)
    if not m:
        raise ValueError("LLM 未返回 JSON:" + text[:200])
    return json.loads(m.group(0))

def plan_outline(material, cfg, chapters=None, log=lambda s: None):
    spec = (f"素材如下,请规划全书大纲。目标约 {chapters} 章(可±3)。输出 JSON:"
            '{"title":"书名","subtitle":"副标题","parts":[{"name":"部名","chapters":'
            '[{"no":1,"title":"章名","pov":"视角人物","summary":"80字内本章梗概",'
            '"anchors":["用到的素材关键词/事实点"]}]}]}。\n\n' + material)
    raw = call_chat(cfg, [{"role": "system", "content": SYSTEM_PLANNER},
                          {"role": "user", "content": spec}], log=log)
    return _extract_json(raw)

def flatten_outline(plan):
    chs = []
    for part in plan.get("parts", []):
        for c in part.get("chapters", []):
            c["part"] = part.get("name", "")
            chs.append(c)
    if not chs and "chapters" in plan:  # 容错:模型直接给了平铺 chapters
        chs = plan["chapters"]
    return chs

# ---------- 正文 ----------
def chapter_prompt(ch, prev_tail, material_tail, cfg):
    words = int(cfg.get("chapter_words", 1500))
    ctx = ""
    if prev_tail:
        ctx += f"【上一章结尾(承接用,勿重复)】\n{prev_tail}\n\n"
    return (f"请撰写《{ch.get('title','')}》整章正文,约 {words} 字。"
            f"视角人物:{ch.get('pov','群像')};本章梗概:{ch.get('summary','')};"
            f"须落实的事实点:{', '.join(ch.get('anchors', [])) or '见梗概'}。\n\n"
            f"【相关素材(节选)】\n{material_tail[:int(cfg.get('chapter_material_chars', 8000))]}\n\n"
            f"直接输出正文,不要标题以外的元信息。")

def _tail(text, n=400):
    text = (text or "").strip()
    return text[-n:] if len(text) > n else text

def generate(out_dir, cfg, log=lambda s: None, chapters=None):
    """主流程:素材→大纲→逐章,写到 out_dir/novel/。返回 (大纲路径, [章节路径])。"""
    cfg = dict(cfg or {})
    log("收集素材 …")
    material = gather_material(out_dir)
    log(f"  事实包约 {len(material)} 字符")

    log("规划大纲 …")
    plan = plan_outline(material, cfg, chapters=chapters or cfg.get("chapters"), log=log)
    chs = flatten_outline(plan)
    if not chs:
        raise RuntimeError("大纲解析后无章节,请重试或调低章数。")
    log(f"  大纲就绪:{len(plan.get('parts', []))} 部 / {len(chs)} 章")

    ndir = os.path.join(out_dir, "novel")
    os.makedirs(ndir, exist_ok=True)
    title = plan.get("title", "编年史")
    toc_path = os.path.join(ndir, "00_大纲.md")
    _write_toc(toc_path, plan, title)
    log("  " + toc_path)

    # 供逐章注入的素材尾段:优先人物+台词速查(口吻),再编年史
    material_tail = _chapter_material_slice(out_dir)
    files, prev_tail = [], ""
    for i, ch in enumerate(chs, 1):
        no = ch.get("no", i)
        log(f"[{i}/{len(chs)}] 第{no}章《{ch.get('title','')}》生成中 …")
        user = chapter_prompt(ch, prev_tail, material_tail, cfg)
        try:
            body = call_chat(cfg, [{"role": "system", "content": SYSTEM_WRITER},
                                   {"role": "user", "content": user}], log=log)
        except RuntimeError as e:
            log(f"  ✘ 第{no}章失败:{e}"); continue
        safe = re.sub(r'[\\/:*?"<>|]', "_", f"{ch.get('title','')}")[:60]
        fp = os.path.join(ndir, f"第{int(no):02d}_{safe}.md")
        open(fp, "w", encoding="utf-8").write(f"## 第{no}章 {ch.get('title','')}\n\n{body}\n")
        files.append(fp)
        prev_tail = _tail(body)
        log("  " + os.path.basename(fp) + f"({len(body)} 字)")
    log(f"完成 ✔ 共 {len(files)} 章 → novel/")
    return toc_path, files

def _chapter_material_slice(out_dir):
    parts = []
    for label, fn, cap in [("人物", "02_人物.md", 9000), ("台词速查", "05_角色台词速查.md", 9000),
                           ("编年史", "01_编年史.md", 12000)]:
        p = os.path.join(out_dir, fn)
        if os.path.isfile(p):
            parts.append(f"[{label}]\n" + open(p, encoding="utf-8").read()[:cap])
    return "\n\n".join(parts)

def _write_toc(path, plan, title):
    lines = [f"# {title}"+(f"——{plan['subtitle']}" if plan.get("subtitle") else ""), ""]
    for part in plan.get("parts", []):
        lines.append(f"\n## {part.get('name','')}")
        for c in part.get("chapters", []):
            lines.append(f"- 第{c.get('no','?')}章 {c.get('title','')}(视角:{c.get('pov','')})——{c.get('summary','')}")
    open(path, "w", encoding="utf-8").write("\n".join(lines) + "\n")

if __name__ == "__main__":
    import sys
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "output"
    cfg = {}
    for p in (os.path.join(out_dir, "..", "config.json"), os.path.join(os.getcwd(), "config.json")):
        if os.path.isfile(p):
            cfg = (json.load(open(p, encoding="utf-8")).get("llm") or {}) or {}
            if cfg: break
    if not cfg.get("model"):
        print("提示:未检测到 llm 配置,使用默认(可在 config.json 的 llm 段填写)。")
    generate(out_dir, cfg, log=print, chapters=cfg.get("chapters"))
