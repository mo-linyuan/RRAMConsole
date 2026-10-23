"""发送序列：列表、排序、导入导出、预设、运行。"""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import List

from ...model import sequence_io
from ...model.items import Item
from ...recipes import write_test
from ..context import AppContext
from ..theme import C, card


def _presets():
    out = {"通路检查：写读 reg[8]": write_test.path_check}
    for name in write_test.SCENES:
        out[name] = (lambda n=name: write_test.plan(write_test.scene(n)).items)
    return out


class SequencePanel:
    def __init__(self, parent, ctx: AppContext):
        self.ctx = ctx
        self.items: List[Item] = []
        self.states: List[str] = []
        self.outer, inner = card(parent, "发送序列", header=self._header)
        self._build(inner)

    # ---------------------------------------------------------------- 界面
    def _header(self, head):
        mb = ttk.Menubutton(head, text="预设流程")
        m = tk.Menu(mb, tearoff=0, font=self.ctx.fonts.ui)
        for name, fn in _presets().items():
            m.add_command(label=name, command=lambda n=name, f=fn: self._load_preset(n, f))
        mb["menu"] = m
        mb.pack(side="right")
        ttk.Button(head, text="导出", command=self.export).pack(side="right", padx=6)
        ttk.Button(head, text="导入", command=self.import_).pack(side="right")

    def _build(self, p):
        cols = ("no", "desc", "frame", "st")
        tv = ttk.Treeview(p, columns=cols, show="headings", selectmode="extended")
        for c, t, w, st in [("no", "#", 40, False), ("desc", "说明", 210, False), ("frame", "报文", 330, True),
                            ("st", "状态", 60, False)]:
            tv.heading(c, text=t, anchor="w")
            tv.column(c, width=w, stretch=st, anchor="w")
        tv.tag_configure("odd", background=C["stripe"])
        tv.tag_configure("start", foreground=C["warn"])
        bottom = ttk.Frame(p, style="Card.TFrame")
        bottom.pack(side="bottom", fill="x", pady=(10, 0))
        sb = ttk.Scrollbar(p, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        tv.pack(fill="both", expand=True)
        tv.bind("<Double-1>", self._on_double)
        tv.bind("<Delete>", lambda e: self.delete())
        self.tv = tv

        for txt, cmd in [("上移", lambda: self.move(-1)), ("下移", lambda: self.move(1)), ("删除", self.delete),
                         ("清空", self.clear)]:
            ttk.Button(bottom, text=txt, command=cmd).pack(side="left", padx=(0, 6))
        self.btn_stop = ttk.Button(bottom, text="停止", style="Danger.TButton", state="disabled",
                                   command=lambda: self.ctx.stop())
        self.btn_stop.pack(side="right")
        self.btn_run = ttk.Button(bottom, text="运行全部", style="Accent.TButton", command=lambda: self.run(False))
        self.btn_run.pack(side="right", padx=6)
        self.btn_sel = ttk.Button(bottom, text="运行选中", command=lambda: self.run(True))
        self.btn_sel.pack(side="right")
        self.pb = ttk.Progressbar(bottom, length=110, mode="determinate")
        self.pb.pack(side="right", padx=10)

    # ---------------------------------------------------------------- 数据
    def refresh(self, keep=None) -> None:
        self.tv.delete(*self.tv.get_children())
        route = self.ctx.route()
        self.states = (self.states + [""] * len(self.items))[:len(self.items)]
        for i, it in enumerate(self.items):
            try:
                fr = it.summary(route)
            except Exception:  # noqa: BLE001  内容有误时只影响显示
                fr = "（内容有误）"
            tags = (["odd"] if i % 2 else []) + (["start"] if it.is_start() else [])
            self.tv.insert("", "end", iid=str(i), values=(i + 1, it.desc, fr, self.states[i]), tags=tags)
        if keep:
            self.tv.selection_set([str(i) for i in keep if 0 <= i < len(self.items)])

    def selected(self) -> List[int]:
        return sorted(int(i) for i in self.tv.selection())

    def add(self, it: Item) -> None:
        sel = self.selected()
        pos = sel[-1] + 1 if sel else len(self.items)
        self.items.insert(pos, it)
        self.states.insert(pos, "")
        self.refresh([pos])
        self.tv.see(str(pos))

    def replace_selected(self, it: Item) -> bool:
        sel = self.selected()
        if len(sel) != 1:
            return False
        self.items[sel[0]] = it
        self.refresh(sel)
        return True

    def set_items(self, items: List[Item]) -> None:
        self.items, self.states = list(items), [""] * len(items)
        self.refresh()

    def move(self, d: int) -> None:
        idx = self.selected()
        if not idx or (d < 0 and idx[0] == 0) or (d > 0 and idx[-1] == len(self.items) - 1):
            return
        for i in (idx if d < 0 else reversed(idx)):
            self.items[i], self.items[i + d] = self.items[i + d], self.items[i]
        self.refresh([i + d for i in idx])

    def delete(self) -> None:
        for i in reversed(self.selected()):
            del self.items[i]
            del self.states[i]
        self.refresh()

    def clear(self) -> None:
        if self.items and messagebox.askyesno("清空序列", "确定清空全部 {} 条？".format(len(self.items))):
            self.set_items([])

    def set_state(self, row, state: str) -> None:
        if row is None or not (0 <= row < len(self.items)):
            return
        self.states[row] = state
        if self.tv.exists(str(row)):
            self.tv.set(str(row), "st", state)
            self.tv.see(str(row))

    def set_progress(self, done: int, total: int) -> None:
        self.pb["maximum"] = max(total, 1)
        self.pb["value"] = done

    def set_busy(self, busy: bool) -> None:
        for b in (self.btn_run, self.btn_sel):
            b.config(state="disabled" if busy else "normal")
        self.btn_stop.config(state="normal" if busy else "disabled")

    # ---------------------------------------------------------------- 动作
    def run(self, selected: bool) -> None:
        idx = self.selected() if selected else list(range(len(self.items)))
        if not idx:
            messagebox.showinfo("提示", "先选中要运行的条目" if selected else "序列是空的")
            return
        for i in idx:
            self.states[i] = ""
        self.refresh(idx if selected else None)
        self.ctx.run([self.items[i] for i in idx], idx)

    def _on_double(self, e) -> None:
        row = self.tv.identify_row(e.y)
        if row:
            self.ctx.edit_item(self.items[int(row)])

    def _load_preset(self, name, fn) -> None:
        if self.items and not messagebox.askyesno("载入预设", "载入“{}”会替换当前序列，继续？".format(name)):
            return
        self.set_items(fn())
        self.ctx.log("info", "提示", "已载入预设：" + name)

    def export(self) -> None:
        if not self.items:
            messagebox.showinfo("提示", "序列是空的")
            return
        path = filedialog.asksaveasfilename(defaultextension=".json", title="导出序列", filetypes=[
            ("调试台序列（推荐）", "*.json"), ("网络调试助手批量发送", "*.ini"), ("纯文本 HEX", "*.txt")])
        if not path:
            return
        route = self.ctx.route()
        try:
            if path.lower().endswith(".json"):
                sequence_io.save_json(path, self.items, {"core": route.core, "src": "{}{}".format(route.sx, route.sy),
                                                         "rgn": route.rgn})
                self.ctx.log("info", "提示", "已导出序列：" + path)
                return
            fn = sequence_io.export_netassist if path.lower().endswith(".ini") else sequence_io.export_text
            n, skipped = fn(path, self.items, route, True)
            msg = "已导出 {} 行（按目标核 {} 展开）".format(n, route.core)
            if skipped:
                msg += "，等待类条目无法用报文表示，跳过 {} 条".format(skipped)
            self.ctx.log("info", "提示", msg)
        except OSError as e:
            messagebox.showerror("导出失败", str(e))

    def import_(self) -> None:
        path = filedialog.askopenfilename(title="导入序列", filetypes=[
            ("所有支持的格式", "*.json *.ini *.txt"), ("调试台序列", "*.json"), ("网络调试助手批量发送", "*.ini"),
            ("文本", "*.txt")])
        if not path:
            return
        try:
            items, header, note = sequence_io.load_any(path, self.ctx.route())
        except (OSError, ValueError, KeyError) as e:
            messagebox.showerror("导入失败", str(e))
            return
        if header:
            self.ctx.apply_header(header)
        if self.items and messagebox.askyesno("导入", "追加到当前序列末尾？\n选“否”则替换当前序列。"):
            self.items.extend(items)
            self.states.extend([""] * len(items))
            self.refresh()
        else:
            self.set_items(items)
        self.ctx.log("info", "提示", "已导入 {} 条：{}{}".format(len(items), path, "；" + note if note else ""))
