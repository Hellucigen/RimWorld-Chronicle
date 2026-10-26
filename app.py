# -*- coding: utf-8 -*-
"""RimWorld Chronicle —— 把环世界存档整理成编年史素材的桌面小工具。

流水线:选择 .rws 存档(可多个) → 解析 → (可选)扫描游戏目录生成中文词典 → 导出 00-05 素材文档。
纯标准库(tkinter + xml),无需安装任何第三方包。
"""
import os, sys, json, threading, queue, subprocess

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(BASE_DIR, "config.json")

sys.path.insert(0, BASE_DIR)
from chronicle import pipeline, steam  # noqa: E402


def open_folder(path):
    if sys.platform == "win32":
        os.startfile(path)  # noqa
    else:
        subprocess.Popen(["xdg-open", path])


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("RimWorld Chronicle —— 存档编年史提取器  v0.1")
        self.geometry("720x560")
        self.minsize(640, 480)
        self.msg_q = queue.Queue()
        self.worker = None

        pad = dict(padx=8, pady=4)
        frm = ttk.Frame(self); frm.pack(fill="both", expand=True, **pad)
        frm.columnconfigure(0, weight=1)

        # --- 存档列表 ---
        row = ttk.LabelFrame(frm, text="① 存档文件(.rws,按游玩先后顺序添加;同一战役的中期档+终局档可一起放入)")
        row.grid(row=0, column=0, sticky="ew", **pad)
        self.save_paths = []
        self.lst = ttk.Treeview(row, show="tree", height=5)
        self.lst.pack(fill="x", expand=True, padx=6, pady=4)
        bar = ttk.Frame(row); bar.pack(fill="x", padx=6, pady=(0, 6))
        ttk.Button(bar, text="添加存档", command=self.add_saves).pack(side="left")
        ttk.Button(bar, text="移除选中", command=self.del_saves).pack(side="left", padx=4)
        ttk.Button(bar, text="上移", command=lambda: self.move_sel(-1)).pack(side="left", padx=4)
        ttk.Button(bar, text="下移", command=lambda: self.move_sel(1)).pack(side="left")

        # --- 游戏目录 ---
        row = ttk.LabelFrame(frm, text="② RimWorld 游戏目录(用于把特质/背景译成中文;可留空自动探测)")
        row.grid(row=1, column=0, sticky="ew", **pad)
        g = ttk.Frame(row); g.pack(fill="x", padx=6, pady=4)
        self.game_dir = tk.StringVar()
        ttk.Entry(g, textvariable=self.game_dir).pack(side="left", fill="x", expand=True)
        ttk.Button(g, text="浏览…", command=self.browse_game).pack(side="left", padx=4)
        ttk.Button(g, text="自动探测", command=self.autodetect).pack(side="left")
        self.want_defs = tk.BooleanVar(value=True)
        ttk.Checkbutton(row, text="生成中文词典(首次扫描较大 mod 集需要几分钟,之后增量复用)",
                        variable=self.want_defs).pack(anchor="w", padx=8, pady=(0, 4))

        # --- 输出目录 ---
        row = ttk.LabelFrame(frm, text="③ 输出目录")
        row.grid(row=2, column=0, sticky="ew", **pad)
        o = ttk.Frame(row); o.pack(fill="x", padx=6, pady=6)
        self.out_dir = tk.StringVar(value=os.path.join(BASE_DIR, "output"))
        ttk.Entry(o, textvariable=self.out_dir).pack(side="left", fill="x", expand=True)
        ttk.Button(o, text="浏览…", command=self.browse_out).pack(side="left", padx=4)

        # --- 日志 ---
        row = ttk.LabelFrame(frm, text="运行日志")
        row.grid(row=3, column=0, sticky="nsew", **pad)
        frm.rowconfigure(3, weight=1)
        self.log = tk.Text(row, height=10, state="disabled", wrap="word", font=("Microsoft YaHei UI", 9))
        sb = ttk.Scrollbar(row, command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log.pack(fill="both", expand=True, padx=6, pady=4)

        # --- 控制条 ---
        ctl = ttk.Frame(frm); ctl.grid(row=4, column=0, sticky="ew", **pad)
        self.btn = ttk.Button(ctl, text="开始提取", command=self.start)
        self.btn.pack(side="left")
        ttk.Button(ctl, text="打开输出目录", command=self.open_out).pack(side="left", padx=6)
        self.pb = ttk.Progressbar(ctl, mode="indeterminate", length=140)
        self.pb.pack(side="left", padx=8)
        self.status = tk.StringVar(value="就绪")
        ttk.Label(ctl, textvariable=self.status).pack(side="right")

        self.load_config()
        self.log_line("欢迎。选择存档 → (可选)指定游戏目录 → 开始提取。")
        self.after(100, self.poll_queue)

    # ---------- 存档列表 ----------
    def add_saves(self):
        fs = filedialog.askopenfilenames(title="选择 .rws 存档",
                                         filetypes=[("RimWorld 存档", "*.rws"), ("所有文件", "*.*")])
        for f in fs or ():
            if f not in self.save_paths:
                self.save_paths.append(f)
                self.lst.insert("", "end", text=f)

    def del_saves(self):
        for iid in self.lst.selection():
            self.save_paths.remove(self.lst.item(iid, "text"))
            self.lst.delete(iid)

    def move_sel(self, d):
        sel = self.lst.selection()
        if not sel: return
        children = self.lst.get_children()
        i = children.index(sel[0]); n = i + d
        if 0 <= n < len(children):
            self.save_paths[i], self.save_paths[n] = self.save_paths[n], self.save_paths[i]
            for k, iid in enumerate(children):
                self.lst.move(iid, "", k)
            self.lst.selection_set(self.lst.get_children()[n])

    # ---------- 路径 ----------
    def browse_game(self):
        p = filedialog.askdirectory(title="选择 RimWorld 安装目录(含 Data/ 与 Mods/)")
        if p: self.game_dir.set(p)

    def browse_out(self):
        p = filedialog.askdirectory(title="选择输出目录")
        if p: self.out_dir.set(p)

    def autodetect(self):
        info = steam.find_rimworld()
        if info:
            self.game_dir.set(info["rimworld_dir"])
            self.log_line(f"探测到:{info['rimworld_dir']}(工坊:{info['workshop_dir'] or '无'})")
        else:
            messagebox.showinfo("Rimworld Chronicle", "未能自动探测到 RimWorld 安装目录,请手动浏览选择。")

    def open_out(self):
        p = self.out_dir.get()
        if os.path.isdir(p): open_folder(p)
        else: messagebox.showwarning("Rimworld Chronicle", "输出目录还不存在,先跑一次。")

    # ---------- 运行 ----------
    def start(self):
        if self.worker and self.worker.is_alive():
            messagebox.showwarning("Rimworld Chronicle", "正在运行中,请等待完成。")
            return
        saves = list(self.save_paths)
        if not saves:
            messagebox.showwarning("Rimworld Chronicle", "请先添加至少一个 .rws 存档。")
            return
        missing = [p for p in saves if not os.path.isfile(p)]
        if missing:
            messagebox.showerror("Rimworld Chronicle", "存档不存在:\n" + "\n".join(missing))
            return
        self.save_config()
        out = self.out_dir.get(); os.makedirs(out, exist_ok=True)
        self.btn.state(["disabled"])
        self.pb.start(12)
        self.status.set("运行中…")
        self.worker = threading.Thread(target=self._run, args=(saves, out, self.game_dir.get() or None, self.want_defs.get()), daemon=True)
        self.worker.start()

    def _run(self, saves, out, gdir, want):
        try:
            pipeline.run(saves, out, rimworld_dir=gdir, want_defs=want, log=lambda s: self.msg_q.put(s))
            self.msg_q.put(("done", out))
        except Exception as e:  # noqa
            self.msg_q.put(("err", f"{type(e).__name__}: {e}"))

    # ---------- 队列/日志 ----------
    def poll_queue(self):
        try:
            while True:
                m = self.msg_q.get_nowait()
                if isinstance(m, tuple) and m[0] == "done":
                    self.pb.stop(); self.btn.state(["!disabled"])
                    self.status.set("完成")
                    if messagebox.askyesno("Rimworld Chronicle", "提取完成,现在打开输出目录吗?"):
                        open_folder(m[1])
                elif isinstance(m, tuple) and m[0] == "err":
                    self.pb.stop(); self.btn.state(["!disabled"])
                    self.status.set("出错")
                    self.log_line("✘ " + m[1])
                    messagebox.showerror("Rimworld Chronicle", "运行出错:\n" + m[1])
                else:
                    self.log_line(m)
        except queue.Empty:
            pass
        self.after(100, self.poll_queue)

    def log_line(self, s):
        self.log.configure(state="normal")
        self.log.insert("end", s + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    # ---------- 配置持久化 ----------
    def save_config(self):
        try:
            json.dump({"saves": list(self.save_paths), "game_dir": self.game_dir.get(),
                       "out_dir": self.out_dir.get(), "want_defs": self.want_defs.get()},
                      open(CONFIG, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        except OSError:
            pass

    def load_config(self):
        try:
            c = json.load(open(CONFIG, encoding="utf-8"))
        except (OSError, ValueError):
            return
        for p in c.get("saves") or []:
            if os.path.isfile(p) and p not in self.save_paths:
                self.save_paths.append(p)
                self.lst.insert("", "end", text=p)
        self.game_dir.set(c.get("game_dir") or "")
        if c.get("out_dir"): self.out_dir.set(c["out_dir"])
        self.want_defs.set(bool(c.get("want_defs", True)))
        if not c.get("game_dir"):
            info = steam.find_rimworld()
            if info: self.game_dir.set(info["rimworld_dir"]); self.log_line(f"已自动探测游戏目录:{info['rimworld_dir']}")


if __name__ == "__main__":
    App().mainloop()
