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
from chronicle import pipeline, steam, writing  # noqa: E402


def open_folder(path):
    if sys.platform == "win32":
        os.startfile(path)  # noqa
    else:
        subprocess.Popen(["xdg-open", path])


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("RimWorld Chronicle —— 存档编年史提取器  v0.2")
        self.geometry("760x680")
        self.minsize(680, 560)
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

        # --- LLM 写作 ---
        row = ttk.LabelFrame(frm, text="④ LLM 小说生成(可选,基于①-③导出的素材;兼容 OpenAI 接口)")
        row.grid(row=3, column=0, sticky="ew", **pad)
        gl = ttk.Frame(row); gl.pack(fill="x", padx=6, pady=4)
        gl.columnconfigure(1, weight=1); gl.columnconfigure(3, weight=1)
        ttk.Label(gl, text="API 地址").grid(row=0, column=0, sticky="w")
        self.llm_base = tk.StringVar(value="https://api.openai.com/v1")
        ttk.Entry(gl, textvariable=self.llm_base).grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Label(gl, text="模型").grid(row=0, column=2, sticky="w")
        self.llm_model = tk.StringVar(value="gpt-4o-mini")
        ttk.Entry(gl, textvariable=self.llm_model).grid(row=0, column=3, sticky="ew", padx=4)
        ttk.Label(gl, text="密钥").grid(row=1, column=0, sticky="w")
        self.llm_key = tk.StringVar()
        self.show_key = tk.BooleanVar(value=False)
        self.key_entry = ttk.Entry(gl, textvariable=self.llm_key, show="*")
        self.key_entry.grid(row=1, column=1, sticky="ew", padx=4)
        ttk.Checkbutton(gl, text="明文显示", variable=self.show_key,
                        command=lambda: self.key_entry.configure(show="" if self.show_key.get() else "*")).grid(row=1, column=2, sticky="w")
        self.remember_key = tk.BooleanVar(value=False)
        ttk.Checkbutton(gl, text="记住密钥", variable=self.remember_key).grid(row=1, column=3, sticky="w")
        ttk.Label(gl, text="章数").grid(row=2, column=0, sticky="w")
        self.nov_chapters = tk.StringVar(value="12")
        ttk.Entry(gl, textvariable=self.nov_chapters, width=8).grid(row=2, column=1, sticky="w", padx=4)
        ttk.Label(gl, text="每章字数").grid(row=2, column=2, sticky="w")
        self.nov_words = tk.StringVar(value="1500")
        ttk.Entry(gl, textvariable=self.nov_words, width=8).grid(row=2, column=3, sticky="w", padx=4)
        bb = ttk.Frame(row); bb.pack(fill="x", padx=6, pady=(0, 6))
        self.btn_llm_test = ttk.Button(bb, text="测试连接", command=self.test_llm)
        self.btn_llm_test.pack(side="left")
        self.btn_novel = ttk.Button(bb, text="生成小说", command=self.start_novel)
        self.btn_novel.pack(side="left", padx=6)
        ttk.Label(bb, text="密钥优先用环境变量 LLM_API_KEY,不落盘更安全").pack(side="left", padx=8)

        # --- 日志 ---
        row = ttk.LabelFrame(frm, text="运行日志")
        row.grid(row=4, column=0, sticky="nsew", **pad)
        frm.rowconfigure(4, weight=1)
        self.log = tk.Text(row, height=10, state="disabled", wrap="word", font=("Microsoft YaHei UI", 9))
        sb = ttk.Scrollbar(row, command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log.pack(fill="both", expand=True, padx=6, pady=4)

        # --- 控制条 ---
        ctl = ttk.Frame(frm); ctl.grid(row=5, column=0, sticky="ew", **pad)
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
        self._set_running(True)
        self.worker = threading.Thread(target=self._run, args=(saves, out, self.game_dir.get() or None, self.want_defs.get()), daemon=True)
        self.worker.start()

    def _run(self, saves, out, gdir, want):
        try:
            pipeline.run(saves, out, rimworld_dir=gdir, want_defs=want, log=lambda s: self.msg_q.put(s))
            self.msg_q.put(("done", out))
        except Exception as e:  # noqa
            self.msg_q.put(("err", f"{type(e).__name__}: {e}"))

    # ---------- LLM ----------
    def _busy(self):
        if self.worker and self.worker.is_alive():
            messagebox.showwarning("Rimworld Chronicle", "正在运行中,请等待完成。")
            return True
        return False

    def _llm_cfg(self):
        def _int(s, d):
            try: return int(str(s).strip())
            except ValueError: return d
        return {"base_url": self.llm_base.get().strip(), "model": self.llm_model.get().strip(),
                "api_key": self.llm_key.get().strip(), "temperature": 0.85,
                "chapters": _int(self.nov_chapters.get(), 12), "chapter_words": _int(self.nov_words.get(), 1500)}

    def test_llm(self):
        if self._busy(): return
        cfg = self._llm_cfg()
        if not cfg["api_key"] and not os.environ.get("LLM_API_KEY"):
            messagebox.showwarning("Rimworld Chronicle", "请先填写 API 密钥(或设置环境变量 LLM_API_KEY)。")
            return
        self._set_running(True)
        def job():
            try:
                self.msg_q.put("测试连接 → " + cfg["base_url"])
                writing.test_connection(cfg, log=lambda s: self.msg_q.put(s))
                self.msg_q.put(("ok", "API 连接正常,模型可用 ✔"))
            except Exception as e:  # noqa
                self.msg_q.put(("err", f"连接失败:{type(e).__name__}: {e}"))
        self._start_thread(job)

    def start_novel(self):
        if self._busy(): return
        out = self.out_dir.get()
        if not os.path.isfile(os.path.join(out, "01_编年史.md")):
            messagebox.showwarning("Rimworld Chronicle", "输出目录里还没有素材文档,请先完成①-③的提取。")
            return
        cfg = self._llm_cfg()
        if not cfg["api_key"] and not os.environ.get("LLM_API_KEY"):
            messagebox.showwarning("Rimworld Chronicle", "请先填写 API 密钥(或设置环境变量 LLM_API_KEY)。")
            return
        self.save_config()
        self._set_running(True)
        self.log_line("=== 开始 LLM 小说生成 ===")
        def job():
            try:
                writing.generate(out, cfg, log=lambda s: self.msg_q.put(s))
                self.msg_q.put(("novel", os.path.join(out, "novel")))
            except Exception as e:  # noqa
                self.msg_q.put(("err", f"生成失败:{type(e).__name__}: {e}"))
        self._start_thread(job)

    def _start_thread(self, job):
        self.worker = threading.Thread(target=job, daemon=True)
        self.worker.start()

    def _set_running(self, running):
        state = ["disabled"] if running else ["!disabled"]
        self.btn.state(state); self.btn_llm_test.state(state); self.btn_novel.state(state)
        self.status.set("运行中…" if running else "就绪")
        if running: self.pb.start(12)
        else: self.pb.stop()

    # ---------- 队列/日志 ----------
    def poll_queue(self):
        try:
            while True:
                m = self.msg_q.get_nowait()
                if isinstance(m, tuple):
                    kind, arg = m
                    if kind == "done":
                        self._set_running(False)
                        if messagebox.askyesno("Rimworld Chronicle", "提取完成,现在打开输出目录吗?"):
                            open_folder(arg)
                    elif kind == "novel":
                        self._set_running(False)
                        if messagebox.askyesno("Rimworld Chronicle", "小说草稿已生成,打开 novel/ 查看?"):
                            open_folder(arg)
                    elif kind == "ok":
                        self._set_running(False)
                        self.log_line("✔ " + arg)
                    elif kind == "err":
                        self._set_running(False)
                        self.log_line("✘ " + arg)
                        messagebox.showerror("Rimworld Chronicle", arg)
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
        llm = {"base_url": self.llm_base.get(), "model": self.llm_model.get(),
               "chapters": self.nov_chapters.get(), "chapter_words": self.nov_words.get()}
        if self.remember_key.get():
            llm["api_key"] = self.llm_key.get()
        try:
            json.dump({"saves": list(self.save_paths), "game_dir": self.game_dir.get(),
                       "out_dir": self.out_dir.get(), "want_defs": self.want_defs.get(), "llm": llm},
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
        llm = c.get("llm") or {}
        if llm.get("base_url"): self.llm_base.set(llm["base_url"])
        if llm.get("model"): self.llm_model.set(llm["model"])
        if llm.get("chapters"): self.nov_chapters.set(str(llm["chapters"]))
        if llm.get("chapter_words"): self.nov_words.set(str(llm["chapter_words"]))
        if llm.get("api_key"):
            self.llm_key.set(llm["api_key"]); self.remember_key.set(True)
        if not c.get("game_dir"):
            info = steam.find_rimworld()
            if info: self.game_dir.set(info["rimworld_dir"]); self.log_line(f"已自动探测游戏目录:{info['rimworld_dir']}")


if __name__ == "__main__":
    App().mainloop()
