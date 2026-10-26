"""发送序列：列表、排序、导入导出、预设、运行。"""

from __future__ import annotations

import tkinter as tk
from collections import deque
import time
from tkinter import filedialog, messagebox, ttk
from typing import List

from ...model import sequence_io
from ...model.items import Item
from ...recipes import write_test
from ..context import AppContext
from ..theme import C, card, bind_wrap


def _presets():
    return {"板卡链路自检 · 不写 RRAM": write_test.path_check,
            "可选读回核对 · 需支持芯片回包": write_test.readback_check}


class SequencePanel:
    def __init__(self, parent, ctx: AppContext):
        self.ctx = ctx
        self.items: List[Item] = []
        self.states: List[str] = []
        self._rendered_rows = {}
        self._render_job = None
        self._pending_rows = deque()
        self._pending_set = set()
        self._busy = False
        self._edit_controls = []
        self.outer, inner = card(parent, "发送序列", header=self._header)
        self._build(inner)
        self.outer.bind("<Destroy>", self._dispose_render, add="+")

    # ---------------------------------------------------------------- 界面
    def _header(self, head):
        mb = ttk.Menubutton(head, text="诊断步骤")
        m = tk.Menu(mb, tearoff=0, font=self.ctx.fonts.ui, bg=C["card"], fg=C["text"],
                    activebackground=C["selected"], activeforeground=C["text"], bd=0, relief="flat")
        m.add_command(label="载入诊断序列，不会立即发送", state="disabled")
        m.add_separator()
        for name, fn in _presets().items():
            m.add_command(label=name, command=lambda n=name, f=fn: self._load_preset(n, f))
        mb["menu"] = m
        mb.pack(side="right")
        self._edit_controls.append(mb)
        ttk.Button(head, text="导出", command=self.export).pack(side="right", padx=6)
        imp = ttk.Menubutton(head, text="导入")
        import_menu = tk.Menu(imp, tearoff=0, font=self.ctx.fonts.ui)
        import_menu.add_command(label="替换当前序列…", command=self.import_)
        import_menu.add_command(label="追加到序列末尾…", command=lambda: self.import_(append=True))
        imp["menu"] = import_menu
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
        bottom.pack(side="bottom", fill="x", pady=(6, 0))
        self.result_text = tk.StringVar(value="就绪")
        self.result_label = ttk.Label(bottom, textvariable=self.result_text, style="Sub.TLabel", wraplength=400)
        self.result_label.pack(fill="x", pady=(0, 4))
        bind_wrap(self.result_label)
        horizontal = ttk.Scrollbar(p, orient="horizontal", command=tv.xview)
        horizontal.pack(side="bottom", fill="x")
        sb = ttk.Scrollbar(p, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=sb.set, xscrollcommand=horizontal.set)
        sb.pack(side="right", fill="y")
        tv.pack(fill="both", expand=True)
        tv.bind("<Double-1>", self._on_double)
        tv.bind("<Delete>", lambda e: self.delete())
        self.tv = tv

        actions = ttk.Frame(bottom, style="Card.TFrame")
        actions.pack(fill="x", pady=(0, 4))
        edit = ttk.Frame(actions, style="Card.TFrame")
        edit.pack(side="left")
        run = ttk.Frame(actions, style="Card.TFrame")
        run.pack(side="right")
        for txt, cmd in [("上移", lambda: self.move(-1)), ("下移", lambda: self.move(1)), ("删除", self.delete),
                         ("清空", self.clear)]:
            button = ttk.Button(edit, text=txt, command=cmd)
            button.pack(side="left", padx=(0, 6))
            self._edit_controls.append(button)
            if txt == "清空":
                self.btn_clear = button
        self.btn_stop = ttk.Button(run, text="停止任务", style="Danger.TButton",
                                   command=lambda: self.ctx.stop())
        self.btn_stop.pack(side="right")
        self.btn_run = ttk.Button(run, text="运行全部", style="Accent.TButton", command=lambda: self.run(False))
        self.btn_run.pack(side="right", padx=6)
        self.btn_sel = ttk.Button(run, text="运行选中", command=lambda: self.run(True))
        self.btn_sel.pack(side="right")
        self.pb = ttk.Progressbar(bottom, length=110, mode="determinate")
        self.pb.pack(fill="x")
        self._actions_stacked = None
        def fit_actions(event):
            stacked = event.width < edit.winfo_reqwidth() + run.winfo_reqwidth() + 12
            if stacked == self._actions_stacked:
                return
            self._actions_stacked = stacked
            edit.pack_forget()
            run.pack_forget()
            if stacked:
                edit.pack(side="top", anchor="w", pady=(0, 4))
                run.pack(side="top", anchor="e")
            else:
                edit.pack(side="left")
                run.pack(side="right")
        actions.bind("<Configure>", fit_actions)

    # ---------------------------------------------------------------- 数据
    def refresh(self, keep=None) -> None:
        self._cancel_render()
        self.states = (self.states + [""] * len(self.items))[:len(self.items)]
        stale = [iid for iid in self.tv.get_children() if int(iid) >= len(self.items)]
        if stale:
            self.tv.delete(*stale)
            for iid in stale:
                self._rendered_rows.pop(iid, None)
        self._render_rows(range(len(self.items)))
        if keep is not None:
            selected = [i for i in keep if 0 <= i < len(self.items)]
            self._paint_rows([i for i in selected if not self.tv.exists(str(i))])
            self.tv.selection_set([str(i) for i in selected])
        self._update_buttons()

    def _render_rows(self, indices):
        indices = list(indices)
        if len(indices) <= 1500:
            self._paint_rows(indices)
            return
        for index in indices:
            if index not in self._pending_set:
                self._pending_rows.append(index)
                self._pending_set.add(index)
        if self._render_job is None:
            self._update_buttons()
            self._render_chunk()

    @property
    def rendering(self):
        return self._render_job is not None or bool(self._pending_rows)

    def _cancel_render(self):
        if self._render_job is not None:
            self.outer.after_cancel(self._render_job)
            self._render_job = None
        self._pending_rows.clear()
        self._pending_set.clear()

    def _dispose_render(self, event):
        if event.widget == self.outer:
            self._cancel_render()

    def _render_chunk(self):
        self._render_job = None
        batch = []
        while self._pending_rows and len(batch) < 200:
            index = self._pending_rows.popleft()
            self._pending_set.discard(index)
            batch.append(index)
        self._paint_rows(batch, budget_s=.004)
        if self._pending_rows:
            self._render_job = self.outer.after(16, self._render_chunk)
        else:
            self._update_buttons()

    def _paint_rows(self, indices, budget_s=None):
        route = self.ctx.route()
        rows = []
        existing = set(self.tv.get_children())
        changed = {}
        deadline = time.perf_counter() + budget_s if budget_s else None
        for offset, i in enumerate(indices):
            if offset and deadline is not None and time.perf_counter() >= deadline:
                for remaining in reversed(indices[offset:]):
                    if remaining not in self._pending_set:
                        self._pending_rows.appendleft(remaining)
                        self._pending_set.add(remaining)
                break
            if not 0 <= i < len(self.items):
                continue
            it = self.items[i]
            try:
                fr = it.summary(route)
            except Exception:  # noqa: BLE001  内容有误时只影响显示
                fr = "（内容有误）"
            tags = (["odd"] if i % 2 else []) + (["start"] if it.is_start() else [])
            if self.states[i] == "失败":
                tags = ["failed"]
            iid = str(i)
            values, tags = (i + 1, it.desc, fr, self.states[i]), tuple(tags)
            if iid in existing and self._rendered_rows.get(iid) == (values, tags):
                continue
            rows.append((iid, values, tags))
            changed[iid] = (values, tags)
        if rows:
            # Rows remain Tcl list data (never interpolated script text). One
            # call updates/inserts the batch while preserving selection/scroll.
            self.tv.tk.call("apply", (("tree", "rows"), """
                set inserted 0
                foreach row $rows {
                    set id [lindex $row 0]
                    if {[$tree exists $id]} {
                        $tree item $id -values [lindex $row 1] -tags [lindex $row 2]
                    } else {
                        $tree insert {} end -id $id -values [lindex $row 1] -tags [lindex $row 2]
                        set inserted 1
                    }
                }
                if {$inserted} { $tree children {} [lsort -integer [$tree children {}]] }
            """), self.tv, tuple(rows))
            self._rendered_rows.update(changed)

    def selected(self) -> List[int]:
        return sorted(int(i) for i in self.tv.selection())

    def add(self, it: Item) -> None:
        if self._busy or self.rendering:
            return
        sel = self.selected()
        pos = sel[-1] + 1 if sel else len(self.items)
        self.items.insert(pos, it)
        self.states.insert(pos, "")
        self._render_rows(range(pos, len(self.items)))
        if not self.tv.exists(str(pos)):
            self._paint_rows([pos])
        self.tv.selection_set(str(pos))
        self.tv.see(str(pos))

    def replace_selected(self, it: Item) -> bool:
        if self._busy or self.rendering:
            return False
        sel = self.selected()
        if len(sel) != 1:
            return False
        self.items[sel[0]] = it
        self.states[sel[0]] = ""
        self._render_rows(sel)
        return True

    def set_items(self, items: List[Item]) -> None:
        if self._busy:
            return
        self.items, self.states = list(items), [""] * len(items)
        self._cancel_render()
        self.tv.delete(*self.tv.get_children())
        self._rendered_rows.clear()
        self.refresh([])
        self.tv.yview_moveto(0)

    def move(self, d: int) -> None:
        if self._busy or self.rendering:
            return
        idx = self.selected()
        if not idx or (d < 0 and idx[0] == 0) or (d > 0 and idx[-1] == len(self.items) - 1):
            return
        for i in (idx if d < 0 else reversed(idx)):
            self.items[i], self.items[i + d] = self.items[i + d], self.items[i]
            self.states[i], self.states[i + d] = self.states[i + d], self.states[i]
        self._render_rows(sorted(set(idx) | {i + d for i in idx}))
        self.tv.selection_set([str(i + d) for i in idx])

    def delete(self) -> None:
        if self._busy or self.rendering:
            return
        for i in reversed(self.selected()):
            del self.items[i]
            del self.states[i]
        self.refresh([])

    def clear(self) -> None:
        if self._busy:
            return
        self.set_items([])

    def set_state(self, row, state: str) -> None:
        if row is None or not (0 <= row < len(self.items)):
            return
        self.states[row] = state
        self._rendered_rows.pop(str(row), None)
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
        self.result_text.set("{} · {} 条 · 软件总耗时 {:.3f} s{}".format(result.summary, result.sent, result.elapsed_s,
                             " · 指令写入 {:.3f} s".format(result.download_s) if getattr(result, "download_s", 0) else ""))
        color = "err" if result.outcome == "failed" else "warn" if result.outcome in ("cancelled", "sent") else "ok"
        self.result_label.configure(foreground=C[color])

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._update_buttons()

    def _update_buttons(self):
        blocked = self._busy or self.rendering
        for b in (self.btn_run, self.btn_sel, *self._edit_controls):
            disabled = blocked and not (b is self.btn_clear and not self._busy)
            b.config(state="disabled" if disabled else "normal")
        self.btn_stop.config(state="normal")

    # ---------------------------------------------------------------- 动作
    def run(self, selected: bool) -> None:
        if self._busy or self.rendering:
            return
        idx = self.selected() if selected else list(range(len(self.items)))
        if not idx:
            self.ctx.log("info", "提示", "先选中要运行的条目" if selected else "序列是空的")
            return
        for i in idx:
            self.states[i] = ""
        # Admit the task before scheduling a large status repaint. Otherwise
        # App.run would mistake this repaint for an unfinished list import.
        self.ctx.run([self.items[i] for i in idx], idx)
        self.refresh(idx if selected else None)

    def _on_double(self, e) -> None:
        if self._busy or self.rendering:
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
        self.set_items(items)
        self.ctx.log("info", "提示", "已载入预设：" + name)

    def export(self) -> None:
        if not self.items:
            self.ctx.log("info", "提示", "序列是空的")
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

    def import_(self, append=False) -> None:
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
        def obsolete_wait(item):
            return item.kind == "wait" and isinstance(item.meta, dict) and item.meta.get("estimated_execution", False)
        automatic_waits = sum(obsolete_wait(item) for item in items)
        if automatic_waits:
            items = [item for item in items if not obsolete_wait(item)]
            note = (note + "；" if note else "") + "已忽略旧版自动添加的预计执行等待 {} 项".format(automatic_waits)
        if append:
            self.items.extend(items)
            self.states.extend([""] * len(items))
            self.refresh()
        else:
            self.set_items(items)
        self.ctx.log("info", "提示", "已导入 {} 条：{}{}".format(len(items), path, "；" + note if note else ""))
