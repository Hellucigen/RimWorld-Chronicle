# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包(单文件、无控制台窗口的 GUI exe)。

用法:  pyinstaller build.spec        (或  python -m PyInstaller build.spec)
输出:  dist/RimworldChronicle.exe

conda/Miniforge 环境的 PyInstaller 有时不会把 Tcl/Tk 资源收全,
这里按当前解释器的布局自动探测并显式补上;标准 CPython 下探测不到就留空,
由 PyInstaller 自带的 tkinter hook 处理。
"""
import os, sys

binaries, datas = [], []

def _add_if_exists(src, dest):
    if src and os.path.exists(src):
        (binaries if not os.path.isdir(src) else datas).append((src, dest))

prefix = sys.prefix
# conda 布局: <prefix>/Library/bin(tcl86t.dll…) <prefix>/Library/lib(tcl8.6…)
lib_bin = os.path.join(prefix, "Library", "bin")
lib_lib = os.path.join(prefix, "Library", "lib")
for dll in ("tcl86t.dll", "tk86t.dll", "zlib1.dll", "tcl86.dll", "tk86.dll"):
    _add_if_exists(os.path.join(lib_bin, dll), ".")
for folder, dest in (("tcl8.6", "_tcl_data"), ("tk8.6", "_tk_data"),
                     ("dde1.4", "_tcl_data/dde1.4"), ("itcl4.2", "_tcl_data/itcl4.2")):
    _add_if_exists(os.path.join(lib_lib, folder), dest)
# 标准 CPython 布局: <prefix>/DLLs 与 <prefix>/tcl
_add_if_exists(os.path.join(prefix, "tcl", "tcl8.6"), "_tcl_data")
_add_if_exists(os.path.join(prefix, "tcl", "tk8.6"), "_tk_data")

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='RimworldChronicle',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
