# -*- coding: utf-8 -*-
"""总编排:存档 → JSON → def 词典 → 素材文档(00-05)。GUI 与命令行共用。"""
import os, sys, json

from . import extract as _ex
from . import defs as _defs
from . import storyline as _sl
from . import voices as _vo
from . import steam as _steam

def game_paths_from(rimworld_dir):
    """由游戏根目录推出 data_dir 与 mods_dirs(含工坊)。"""
    data_dir = os.path.join(rimworld_dir, "Data")
    mods = [os.path.join(rimworld_dir, "Mods")]
    info = _steam.find_rimworld()
    if info and os.path.normcase(info["rimworld_dir"]) == os.path.normcase(rimworld_dir) and info.get("workshop_dir"):
        mods.append(info["workshop_dir"])
    return data_dir, [m for m in mods if os.path.isdir(m)]

def run(save_paths, out_dir, rimworld_dir=None, want_defs=True, log=lambda s: None):
    """执行整条流水线,返回 {json:[...], docs:[...], defs:path|None}。"""
    os.makedirs(out_dir, exist_ok=True)
    log(f"共 {len(save_paths)} 个存档,输出到 {out_dir}")

    # 1) 解析存档
    saves = []
    for i, p in enumerate(save_paths, 1):
        log(f"[{i}/{len(save_paths)}] 解析 {os.path.basename(p)} …")
        d = _ex.extract(p)
        _ex.save_json(d, out_dir)
        log("  " + _ex.brief(d))
        saves.append(d)

    # 2) def 词典
    DEFS = {}
    defs_path = None
    if want_defs:
        data_dir, mods_dirs = (None, [])
        if rimworld_dir and os.path.isdir(rimworld_dir):
            data_dir, mods_dirs = game_paths_from(rimworld_dir)
        elif _steam.find_rimworld():
            found = _steam.find_rimworld()
            data_dir, mods_dirs = (found["data_dir"], found["mods_dirs"])
            log(f"自动探测到游戏目录:{found['rimworld_dir']}")
        if data_dir or mods_dirs:
            log("扫描 mod 词典(大 mod 集需数分钟,可等待)…")
            defs_path = os.path.join(out_dir, "defs.json")
            DEFS = _defs.build_defs(saves, data_dir=data_dir, mods_dirs=mods_dirs,
                                    out_defs_path=defs_path, log=log)
        else:
            log("未找到游戏目录,跳过中文词典(特质/背景将显示英文 def 名)")
    else:
        log("已跳过词典生成")

    # 3+4) 素材文档与台词速查
    log("生成素材文档 00-04 …")
    docs = _sl.generate(saves, DEFS, out_dir)
    log("生成台词速查 05 …")
    docs.append(_vo.generate(saves, out_dir))
    for p in docs:
        log("  " + os.path.basename(p) + f"({os.path.getsize(p)//1024} KB)")
    log("完成 ✔")
    return {"saves": saves, "docs": docs, "defs": defs_path}

if __name__ == "__main__":
    args = [a for a in sys.argv[1:]]
    if not args:
        print("用法: python -m chronicle.pipeline 输出目录 存档1.rws [存档2.rws …] [--game-dir RimWorld目录] [--no-defs]")
        sys.exit(1)
    out_dir = args[0]
    rwd = None
    if "--game-dir" in args:
        rwd = args[args.index("--game-dir") + 1]
        del args[args.index("--game-dir"):args.index("--game-dir")+2]
    want = "--no-defs" not in args
    paths = [a for a in args[1:] if not a.startswith("--")]
    run(paths, out_dir, rimworld_dir=rwd, want_defs=want, log=print)
