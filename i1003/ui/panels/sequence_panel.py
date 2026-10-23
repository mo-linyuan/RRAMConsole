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


def _presets(repeat_provider=None):
    def build(name):
        spec = write_test.scene(name)
        if repeat_provider is not None and name in write_test.VARIABLE_REPEAT_SCENES:
            try:
                spec.repeat = int(repeat_provider())
            except (TypeError, ValueError):
                raise write_test.SpecError("请在上方填写有效的重复次数")
        return write_test.plan(spec).items

    out = {"通信检查 · 写入并读回配置": write_test.path_check}
    for name in write_test.SCENES:
        out[write_test.SCENE_LABELS[name]] = (lambda n=name: build(n))
    return out


class SequencePanel:
    def __init__(self, parent, ctx: AppContext):
        self.ctx = ctx
        self.items: List[Item] = []
        self.states: List[str] = []
        self._busy = False
        self._edit_controls = []
        self.outer, inner = card(parent, "发送序列", header=self._header)
        self._build(inner)

    # ---------------------------------------------------------------- 界面
    def _header(self, head):
        mb = ttk.Menubutton(head, text="载入测试步骤")
        m = tk.Menu(mb, tearoff=0, font=self.ctx.fonts.ui, bg=C["card"], fg=C["text"],
                    activebackground=C["selected"], activeforeground=C["text"], bd=0, relief="flat")
        m.add_command(label="仅载入序列，不会立即执行", state="disabled")
        m.add_separator()
        for name, fn in _presets(lambda: self.ctx.quick.vars["repeat"].get()).items():
            m.add_command(label=name, command=lambda n=name, f=fn: self._load_preset(n, f))
        mb["menu"] = m
        mb.pack(side="right")
        self._edit_controls.append(mb)
        ttk.Button(head, text="导出", command=self.export).pack(side="right", padx=6)
        imp = ttk.Button(head, text="导入", command=self.import_)
        imp.pack(side="right")
        self._edit_controls.append(imp)

    def _build(self, p):
        cols = ("no", "desc", "frame", "st")
        tv = ttk.Treeview(p, columns=cols, show="headings", selectmode="extended")
        scale = p.winfo_fpixels("1i") / 96
        for c, t, w, st in [("no", "#", 40, False), ("desc", "说明", 210, False), ("frame", "报文", 330, True),
                            ("st", "状态", 80, False)]:
            tv.heading(c, text=t, anchor="w")
            tv.column(c, width=round(w * scale), minwidth=round(40 * scale), stretch=st, anchor="w")
        tv.tag_configure("odd", background=C["stripe"])
        tv.tag_configure("start", foreground=C["warn"])
        tv.tag_configure("failed", foreground=C["err"])
        bottom = ttk.Frame(p, style="Card.TFrame")
        bottom.pack(side="bottom", fill="x", pady=(10, 0))
        self.result_text = tk.StringVar(value="就绪")
        self.result_label = ttk.Label(bottom, textvariable=self.result_text, style="Sub.TLabel", wraplength=400)
        self.result_label.pack(fill="x", pady=(0, 6))
        self.result_label.bind("<Configure>", lambda event: self.result_label.configure(wraplength=max(100, event.width)))
        horizontal = ttk.Scrollbar(p, orient="horizontal", command=tv.xview)
        horizontal.pack(side="bottom", fill="x")
        sb = ttk.Scrollbar(p, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=sb.set, xscrollcommand=horizontal.set)
        sb.pack(side="right", fill="y")
        tv.pack(fill="both", expand=True)
        tv.bind("<Double-1>", self._on_double)
        tv.bind("<Delete>", lambda e: self.delete())
        self.tv = tv

        edit = ttk.Frame(bottom, style="Card.TFrame")
        edit.pack(fill="x", pady=(0, 8))
        for txt, cmd in [("上移", lambda: self.move(-1)), ("下移", lambda: self.move(1)), ("删除", self.delete),
                         ("清空", self.clear)]:
            button = ttk.Button(edit, text=txt, command=cmd)
            button.pack(side="left", padx=(0, 6))
            self._edit_controls.append(button)
        self.btn_stop = ttk.Button(bottom, text="停止发送", style="Danger.TButton", state="disabled",
                                   command=lambda: self.ctx.stop())
        self.btn_stop.pack(side="right")
        self.btn_run = ttk.Button(bottom, text="运行全部", style="Accent.TButton", command=lambda: self.run(False))
        self.btn_run.pack(side="right", padx=6)
        self.btn_sel = ttk.Button(bottom, text="运行选中", command=lambda: self.run(True))
        self.btn_sel.pack(side="right")
        self.pb = ttk.Progressbar(bottom, length=110, mode="determinate")
        self.pb.pack(side="left", fill="x", expand=True, padx=(0, 10))

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
            if self.states[i] == "失败":
                tags = ["failed"]
            self.tv.insert("", "end", iid=str(i), values=(i + 1, it.desc, fr, self.states[i]), tags=tags)
        if keep:
            self.tv.selection_set([str(i) for i in keep if 0 <= i < len(self.items)])

    def selected(self) -> List[int]:
        return sorted(int(i) for i in self.tv.selection())

    def add(self, it: Item) -> None:
        if self._busy:
            return
        sel = self.selected()
        pos = sel[-1] + 1 if sel else len(self.items)
        self.items.insert(pos, it)
        self.states.insert(pos, "")
        self.refresh([pos])
        self.tv.see(str(pos))

    def replace_selected(self, it: Item) -> bool:
        if self._busy:
            return False
        sel = self.selected()
        if len(sel) != 1:
            return False
        self.items[sel[0]] = it
        self.states[sel[0]] = ""
        self.refresh(sel)
        return True

    def set_items(self, items: List[Item]) -> None:
        if self._busy:
            return
        self.items, self.states = list(items), [""] * len(items)
        self.refresh()

    def move(self, d: int) -> None:
        if self._busy:
            return
        idx = self.selected()
        if not idx or (d < 0 and idx[0] == 0) or (d > 0 and idx[-1] == len(self.items) - 1):
            return
        for i in (idx if d < 0 else reversed(idx)):
            self.items[i], self.items[i + d] = self.items[i + d], self.items[i]
            self.states[i], self.states[i + d] = self.states[i + d], self.states[i]
        self.refresh([i + d for i in idx])

    def delete(self) -> None:
        if self._busy:
            return
        for i in reversed(self.selected()):
            del self.items[i]
            del self.states[i]
        self.refresh()

    def clear(self) -> None:
        if self._busy:
            return
        if self.items and messagebox.askyesno("清空序列", "确定清空全部 {} 条？".format(len(self.items))):
            self.set_items([])

    def set_state(self, row, state: str) -> None:
        if row is None or not (0 <= row < len(self.items)):
            return
        self.states[row] = state
        if self.tv.exists(str(row)):
            self.tv.set(str(row), "st", state)
            if state == "失败":
                self.tv.item(str(row), tags=("failed",))
            self.tv.see(str(row))

    def set_progress(self, done: int, total: int) -> None:
        self.pb["maximum"] = max(total, 1)
        self.pb["value"] = done
        self.result_text.set("运行中 · 已发送 {} 条 / 预计 {} 条（不含 Ready 查询，轮询次数可增加）".format(done, total))
        self.result_label.configure(foreground=C["sub"])

    def set_result(self, result):
        self.result_text.set("{} · {} 条 · {:.2f} s".format(result.summary, result.sent, result.elapsed_s))
        color = "err" if result.outcome == "failed" else "warn" if result.outcome in ("cancelled", "sent") else "ok"
        self.result_label.configure(foreground=C[color])

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        for b in (self.btn_run, self.btn_sel, *self._edit_controls):
            b.config(state="disabled" if busy else "normal")
        self.btn_stop.config(state="normal" if busy else "disabled")

    # ---------------------------------------------------------------- 动作
    def run(self, selected: bool) -> None:
        if self._busy:
            return
        idx = self.selected() if selected else list(range(len(self.items)))
        if not idx:
            messagebox.showinfo("提示", "先选中要运行的条目" if selected else "序列是空的")
            return
        for i in idx:
            self.states[i] = ""
        self.refresh(idx if selected else None)
        self.ctx.run([self.items[i] for i in idx], idx)

    def _on_double(self, e) -> None:
        if self._busy:
            return
        row = self.tv.identify_row(e.y)
        if row:
            self.ctx.edit_item(self.items[int(row)])

    def _load_preset(self, name, fn) -> None:
        if getattr(self, "_busy", False):
            return
        try:
            items = fn()
        except (TypeError, ValueError) as exc:
            messagebox.showerror("参数有误", str(exc))
            return
        if self.items and not messagebox.askyesno("载入预设", "载入“{}”会替换当前序列，继续？".format(name)):
            return
        self.set_items(items)
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
                sequence_io.save_json(path, self.items, {"chip_family": self.ctx.chip_family_id(),
                                                         "core": route.core, "src": "{}{}".format(route.sx, route.sy),
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
        if self._busy:
            return
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
        try:
            self.ctx.apply_header(header)
        except ValueError as exc:
            messagebox.showerror("芯片系列不匹配", str(exc))
            return
        if self.items and messagebox.askyesno("导入", "追加到当前序列末尾？\n选“否”则替换当前序列。"):
            self.items.extend(items)
            self.states.extend([""] * len(items))
            self.refresh()
        else:
            self.set_items(items)
        self.ctx.log("info", "提示", "已导入 {} 条：{}{}".format(len(items), path, "；" + note if note else ""))
