# -*- coding: utf-8 -*-
"""按说话者聚合全部 RimTalk 台词 → 05_角色台词速查.md。

结构:一、说话者总表(台词数/出场轮次/各窗口分布/最常对话对象);
      二、主要说话者台词抽样(≥8 条者,按时间均匀抽样至多 10 条)。
口吻特征请基于抽样人工补写——本文件是素材,不是结论。
"""
import os, re, json, collections

SPEECH_RE = re.compile(r"^([^:：\n]{1,30}?):\s*(.+)$")

def parse_round(content):
    """-> (participants, [(speaker, text), ...])。首行为参与者名单,其后每行 '名字: 台词';无冒号行并入上一条。"""
    parts, lines = [], []
    for i, ln in enumerate((content or "").split("\n")):
        ln = ln.strip()
        if not ln:
            continue
        if i == 0 and ln.startswith("[对话参与者"):
            parts = [x.strip() for x in ln[len("[对话参与者:"):].rstrip("]").split(",") if x.strip()]
            continue
        m = SPEECH_RE.match(ln)
        if m:
            lines.append((m.group(1).strip(), m.group(2).strip()))
        elif lines:
            sp, tx = lines[-1]
            lines[-1] = (sp, tx + " " + ln)
    return parts, lines

def _sample(rec, k=10):
    ls = [x for x in rec["lines"] if 6 <= len(x[2]) <= 160] or rec["lines"]
    if len(ls) <= k:
        return ls
    step = (len(ls) - 1) / (k - 1)
    return [ls[round(i * step)] for i in range(k)]

def generate(saves, out_dir="story", min_lines=8):
    """saves: extract() dict 列表(按窗口顺序)。返回写出的文件路径。"""
    from .storyline import make_windows
    wins = make_windows(saves)
    total_rounds = 0
    data = collections.defaultdict(lambda: {"lines": [], "rounds": collections.Counter(),
                                            "partners": collections.Counter(), "windows": collections.Counter()})
    seen_tick = set()
    for label, d in wins:
        for r in d.get("rimtalkRounds") or []:
            tk = r.get("tick") or 0
            if (label, tk) in seen_tick:
                continue
            seen_tick.add((label, tk))
            total_rounds += 1
            parts, lines = parse_round(r.get("content"))
            if not lines:
                continue
            seen_sp = set()
            for sp, tx in lines:
                rec = data[sp]
                rec["lines"].append((r["date"], label, tx))
                rec["windows"][label] += 1
                if sp not in seen_sp:
                    rec["rounds"][label] += 1
                    seen_sp.add(sp)
                for p in parts:
                    if p != sp:
                        rec["partners"][p] += 1

    sps = sorted(data.items(), key=lambda kv: -len(kv[1]["lines"]))
    out = ["# 角色台词速查(脚本聚合)", "",
           f"> 数据源:{len(wins)} 个窗口共 {total_rounds} 轮对话;台词按说话者归组,代表台词按时间均匀抽样。", ""]
    out += ["## 一、说话者总表", "", "| 说话者 | 台词数 | 出场轮次 | 窗口 | 最常对话(前3) |", "|---|---|---|---|---|"]
    for sp, rec in sps:
        w = "、".join(f"{lab}×{n}" for lab, n in sorted(rec["windows"].items(), key=lambda x: -x[1]))
        pr = "、".join(f"{p}×{n}" for p, n in rec["partners"].most_common(3)) or "—"
        out.append(f"| {sp} | {len(rec['lines'])} | {sum(rec['rounds'].values())} | {w} | {pr} |")
    out += ["", f"## 二、主要说话者台词抽样(≥{min_lines} 条,时间均匀抽样至多 10 条)"]
    for sp, rec in sps:
        if len(rec["lines"]) < min_lines:
            continue
        out.append(f"\n### {sp}({len(rec['lines'])} 条)")
        for dt, lab, tx in _sample(rec):
            out.append(f"- {dt}〔{lab}〕{tx}")
    os.makedirs(out_dir, exist_ok=True)
    p = os.path.join(out_dir, "05_角色台词速查.md")
    open(p, "w", encoding="utf-8").write("\n".join(out) + "\n")
    return p

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("用法: python -m chronicle.voices 输出目录 存档1.json [存档2.json ...]"); sys.exit(1)
    out_dir, paths = sys.argv[1], sys.argv[2:]
    saves = [json.load(open(p, encoding="utf-8")) for p in paths]
    print("written:", generate(saves, out_dir))
