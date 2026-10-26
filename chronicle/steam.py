# -*- coding: utf-8 -*-
"""自动探测 Steam 与 RimWorld 安装目录(Windows 为主,失败返回 None,不影响主流程)。

需要定位三类目录:
  rimworld_dir : <steam>/steamapps/common/RimWorld        —— 游戏本体(Data/ 用于官方 def 与 Core 中文语言包)
  mods_dirs    : 游戏 Mods/ + workshop content/294100     —— 扫描 mod Defs 与 DefInjected 语言包
registry 与 libraryfolders.vdf 都读,失败则回退常见安装路径。
"""
import os, re

RIMWORLD_APPID = "294100"

def _steam_roots():
    """候选 Steam 根目录(去重保序)。"""
    roots = []
    # 1) registry
    try:
        import winreg
        for hive, sub in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
                          (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam"),
                          (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam")):
            try:
                with winreg.OpenKey(hive, sub) as k:
                    v, _ = winreg.QueryValueEx(k, "SteamPath")
                    if v: roots.append(os.path.normpath(v))
            except OSError:
                pass
    except ImportError:
        pass
    # 2) 常见路径
    for drive in "CDEFGH":
        for p in (f"{drive}:/Steam", f"{drive}:/steam", f"{drive}:/Program Files/Steam",
                  f"{drive}:/Program Files (x86)/Steam"):
            roots.append(p)
    seen, uniq = set(), []
    for r in roots:
        rn = os.path.normcase(os.path.abspath(r)) if r else ""
        if rn and rn not in seen and os.path.isdir(r):
            seen.add(rn); uniq.append(r)
    return uniq

def _libraries(steam_root):
    """Steam 根 + libraryfolders.vdf 里登记的其他库。"""
    libs = [steam_root]
    vdf = os.path.join(steam_root, "steamapps", "libraryfolders.vdf")
    if os.path.isfile(vdf):
        try:
            text = open(vdf, encoding="utf-8", errors="ignore").read()
            for m in re.finditer(r'"path"\s+"([^"]+)"', text):
                p = m.group(1).replace("\\\\", "\\")
                if os.path.isdir(p): libs.append(p)
        except OSError:
            pass
    return libs

def find_rimworld():
    """返回 dict(rimworld_dir, data_dir, mods_dirs, workshop_dir) 或 None。"""
    for sr in _steam_roots():
        for lib in _libraries(sr):
            rw = os.path.join(lib, "steamapps", "common", "RimWorld")
            if os.path.isdir(rw):
                mods = [os.path.join(rw, "Mods")]
                ws = os.path.join(lib, "steamapps", "workshop", "content", RIMWORLD_APPID)
                if os.path.isdir(ws): mods.append(ws)
                return {"rimworld_dir": rw, "data_dir": os.path.join(rw, "Data"),
                        "mods_dirs": mods, "workshop_dir": ws if os.path.isdir(ws) else None,
                        "steam_root": sr}
    return None

def validate(path, kind):
    """用户手选目录的粗校验。kind: 'game' 指 RimWorld 安装目录,'mods' 指任一 mod 容器目录。"""
    if not path or not os.path.isdir(path): return False
    if kind == "game":
        return os.path.isdir(os.path.join(path, "Data")) or os.path.isdir(os.path.join(path, "Mods"))
    return True
