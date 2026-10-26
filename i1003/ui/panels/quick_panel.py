"""器件配置：设置目标与参数，仅生成序列；执行入口统一在发送序列。"""

from __future__ import annotations

import tkinter as tk
from dataclasses import fields
from tkinter import messagebox, ttk
from typing import Dict

from rram_console.hardware import RRAM_ARRAY

from ...protocol.isa import CHIP_CLK_HZ, CellEncoding
from ...recipes import write_test as W
from ..context import AppContext
from ..theme import C, FormViewport, info_box, bind_wrap

OP_LABELS = {W.OP_SET: "SET（写 1）", W.OP_RESET: "RESET（写 0）"}
LABELS = dict(pe="PE", array="阵列", row_from="行", row_to="行", col_from="列", col_to="列", repeat="每个器件重复",
              wwv_base="基时间", wwv_times="时间倍数", verify_times="验证次数")
SCOPES = {
    "单个器件": "选择一个器件；操作类型和重复次数在下方设置。",
    "一整行": "同一行第0～127列；每个器件按下方设置的次数执行。",
    "自定义范围": "按行、列起止范围逐个操作；操作类型和重复次数在下方设置。",
}


def _set_text(variable, text):
    if variable.get() != text:
        variable.set(text)


def duration_text(seconds):
    if seconds < .001:
        return "{:.3f} µs".format(seconds * 1e6)
    if seconds < 1:
        return "{:.3f} ms".format(seconds * 1000)
    return "{:.6f} s".format(seconds)


class QuickPanel:
    def __init__(self, parent, ctx: AppContext):
        self.ctx = ctx
        first = "单器件只打一次"
        d = W.scene(first)
        self.scene = tk.StringVar(value=first)
        self.scene_display = tk.StringVar(value="单个器件")
        self.scope_mode = tk.StringVar(value="")  # Empty restores legacy ranges by inference.
        self.scene_description = tk.StringVar(value=SCOPES["单个器件"])
        # 每个 spec 字段对应一个界面变量
        self.vars: Dict[str, tk.Variable] = {}
        for f in fields(W.WriteTestSpec):
            if f.name in ("pulse_ms", "hold_s", "poll_after", "check_reg8", "check_inst", "remind_4200"):
                continue
            v = getattr(d, f.name)
            self.vars[f.name] = tk.BooleanVar(value=v) if isinstance(v, bool) else tk.StringVar(value=str(v))
        self.op_display = tk.StringVar(value=OP_LABELS[d.op])
        self.show_details = tk.BooleanVar(value=False)
        self.total_time_text = tk.StringVar(value="—")
        self.time_description = tk.StringVar(value="")
        self._coordinate_mode = "单个器件"
        self._coordinate_layout = None
        self._syncing_coordinates = self._changing_scope = False
        self._build(parent)
        for v in self.vars.values():
            v.trace_add("write", lambda *a: self.update())
        for key in ("row_from", "col_from"):
            self.vars[key].trace_add("write", self._sync_coordinate_ends)
        self.update()

    def settings_vars(self) -> Dict[str, tk.Variable]:
        return dict(self.vars, scene=self.scene, scope=self.scope_mode)

    # ---------------------------------------------------------------- 界面
    def _build(self, p):
        self.viewport = FormViewport(p, min_width=round(640 * p.winfo_fpixels("1i") / 96))
        self.viewport.pack(fill="both", expand=True)
        p = self.viewport.content
        row = ttk.Frame(p, style="Card.TFrame")
        row.pack(fill="x")
        ttk.Label(row, text="操作范围", style="Card.TLabel").pack(side="left", padx=(0, 8))
        cb = ttk.Combobox(row, textvariable=self.scene_display, values=list(SCOPES), state="readonly", width=32)
        self.scope_combo = cb
        cb.pack(side="left", fill="x", expand=True)
        cb.bind("<<ComboboxSelected>>", self._select_scene)
        hint = ttk.Label(p, textvariable=self.scene_description, style="Sub.TLabel", wraplength=600, justify="left")
        hint.pack(fill="x", pady=(3, 0))
        bind_wrap(hint, padding=8)

        g = ttk.Frame(p, style="Card.TFrame", padding=(0, 3, 0, 0))
        g.pack(fill="x")
        V = self.vars

        def sec(r, text):
            ttk.Label(g, text=text, style="Sec.TLabel").grid(row=r, column=0, columnspan=8, sticky="w", pady=(7, 3))

        def lab(r, c, text):
            widget = ttk.Label(g, text=text, style="Card.TLabel")
            widget.grid(row=r, column=c, sticky="w", padx=(0, 6), pady=2)
            return widget

        def spin(r, c, key, lo, hi, w=4):
            widget = ttk.Spinbox(g, textvariable=V[key], from_=lo, to=hi, width=w)
            widget.grid(row=r, column=c, sticky="w", pady=2, padx=(0, 8))
            return widget

        def combo(r, c, var, values, w, span=1):
            ttk.Combobox(g, textvariable=var, values=values, state="readonly", width=w).grid(
                row=r, column=c, columnspan=span, sticky="w", pady=2, padx=(0, 8))

        def entry(r, c, key, w=7):
            ttk.Entry(g, textvariable=V[key], width=w).grid(row=r, column=c, sticky="w", pady=2, padx=(0, 8))

        sec(0, "目标器件 · {} 阵列".format(RRAM_ARRAY.label))
        lab(1, 0, "操作")
        operation = ttk.Combobox(g, textvariable=self.op_display, values=list(OP_LABELS.values()), state="readonly", width=18)
        operation.grid(row=1, column=1, columnspan=3, sticky="ew", pady=2, padx=(0, 12))
        operation.bind("<<ComboboxSelected>>", lambda e: V["op"].set(
            next(key for key, value in OP_LABELS.items() if value == self.op_display.get())))
        lab(1, 4, "地址编码"); combo(1, 5, V["encoding"], CellEncoding.ALL, 18, 3)
        lab(2, 0, "PE"); spin(2, 1, "pe", 0, 7)
        lab(2, 2, "阵列"); spin(2, 3, "array", 0, 7)
        self.coordinates = {
            "row_label": lab(3, 0, "行"), "row_from": spin(3, 1, "row_from", 0, 127),
            "row_to_label": lab(3, 2, "到"), "row_to": spin(3, 3, "row_to", 0, 127),
            "col_label": lab(3, 4, "列"), "col_from": spin(3, 5, "col_from", 0, 127),
            "col_to_label": lab(3, 6, "到"), "col_to": spin(3, 7, "col_to", 0, 127),
        }
        self.row_columns_hint = ttk.Label(g, text="全部128列（0～127）", style="Sub.TLabel")
        sec(4, "脉冲参数")
        lab(5, 0, "基时间"); spin(5, 1, "wwv_base", 1, 255)
        lab(5, 2, "时间倍数"); spin(5, 3, "wwv_times", 1, 255)
        lab(5, 4, "验证次数"); spin(5, 5, "verify_times", 0, 255)
        lab(6, 0, "重复次数"); entry(6, 1, "repeat")
        timing = ttk.Frame(g, style="Card.TFrame")
        timing.grid(row=6, column=2, columnspan=6, sticky="w")
        ttk.Label(timing, text="选通累计（名义）", style="Card.TLabel").pack(side="left", padx=(0, 10))
        ttk.Label(timing, textvariable=self.total_time_text, style="Sec.TLabel",
                  font=self.ctx.fonts.mono).pack(side="left")
        timing_hint = ttk.Label(g, textvariable=self.time_description, style="Sub.TLabel", justify="left", wraplength=600)
        timing_hint.grid(row=7, column=0, columnspan=8, sticky="ew", pady=(4, 6))
        bind_wrap(timing_hint, padding=8)

        preview = ttk.Frame(p, style="Card.TFrame")
        preview.pack(fill="x", pady=(6, 0))
        ttk.Label(preview, text="参数预览", style="Sec.TLabel").pack(side="left")
        ttk.Checkbutton(preview, text="详细参数", variable=self.show_details, command=self.update,
                        style="Card.TCheckbutton").pack(side="right")
        self.lbl = info_box(p, self.ctx.fonts, wrap=600)
        bind_wrap(self.lbl, padding=24)

    # ---------------------------------------------------------------- 逻辑
    def _select_scene(self, _event=None):
        self._changing_scope = True
        try:
            self._apply_scope()
        finally:
            self._changing_scope = False
        self.update()

    def _apply_scope(self):
        scope = self.scene_display.get()
        self.scope_mode.set(scope)
        row = self.vars["row_from"].get()
        column = self.vars["col_from"].get()
        if scope == "单个器件":
            self.vars["row_to"].set(row)
            self.vars["col_to"].set(column)
            self.scene.set("单器件只打一次")
        elif scope == "一整行":
            self.vars["row_to"].set(row)
            self.vars["col_from"].set("0")
            self.vars["col_to"].set("127")
            self.scene.set("一行遍历 128 个器件（I1000 traversal）")
        elif scope == "自定义范围":
            if self._coordinate_mode == "自定义范围":
                return
            # Supply a small editable range rather than a second copy of the
            # single-cell/full-row preset. Operation and pulse fields stay put.
            try:
                start = min(126, int(column))
            except ValueError:
                start = 0
            self.vars["row_to"].set(row)
            self.vars["col_from"].set(str(start))
            self.vars["col_to"].set(str(start + 1))

    def _sync_coordinate_ends(self, *args):
        if self._syncing_coordinates or self._changing_scope or getattr(self, "_applying_scene", False):
            return
        self._syncing_coordinates = True
        try:
            if self._coordinate_mode in ("单个器件", "一整行"):
                self.vars["row_to"].set(self.vars["row_from"].get())
            if self._coordinate_mode == "单个器件":
                self.vars["col_to"].set(self.vars["col_from"].get())
        finally:
            self._syncing_coordinates = False

    def _show_coordinates(self, scope):
        if scope == self._coordinate_layout:
            return
        self._coordinate_layout = scope
        widgets = self.coordinates
        for widget in widgets.values():
            widget.grid_remove()
        self.row_columns_hint.grid_remove()
        widgets["row_label"].grid()
        widgets["row_from"].grid()
        if scope == "单个器件":
            widgets["col_label"].grid(column=2)
            widgets["col_from"].grid(column=3)
        elif scope == "一整行":
            self.row_columns_hint.grid(row=3, column=2, columnspan=6, sticky="w")
        else:
            for name in ("row_to_label", "row_to", "col_to_label", "col_to"):
                widgets[name].grid()
            widgets["col_label"].grid(column=4)
            widgets["col_from"].grid(column=5)

    def apply_scene(self) -> None:
        spec = W.scene(self.scene.get())
        self.scope_mode.set("")
        keep_repeat = W.scene_key(self.scene.get()) in W.VARIABLE_REPEAT_SCENES
        self._applying_scene = True
        try:
            for k, v in spec.to_dict().items():
                if k == "repeat" and keep_repeat:
                    continue
                if k in self.vars:
                    self.vars[k].set(v)
        finally:
            self._applying_scene = False
        self.update()

    def spec(self) -> W.WriteTestSpec:
        d = {}
        values = {key: variable.get() for key, variable in self.vars.items()}
        scope = self.scope_mode.get()
        if scope in ("单个器件", "一整行"):
            values["row_to"] = values["row_from"]
        if scope == "单个器件":
            values["col_to"] = values["col_from"]
        elif scope == "一整行":
            values["col_from"], values["col_to"] = "0", "127"
        for f in fields(W.WriteTestSpec):
            if f.name not in self.vars:
                continue
            raw = values[f.name]
            try:
                d[f.name] = raw if f.type in ("str", str) else (bool(raw) if f.type in ("bool", bool) else
                                                                (float(raw) if f.type in ("float", float) else int(raw)))
            except (ValueError, TypeError):
                raise W.SpecError("“{}”需要填数字".format(LABELS.get(f.name, f.name)))
        return W.WriteTestSpec(**d)

    def plan(self) -> W.Plan:
        return W.plan(self.spec())

    def _set_preview(self, text, color):
        state = (text, color)
        if state != getattr(self, "_preview_state", None):
            self._preview_state = state
            self.lbl.configure(text=text, fg=color)

    def update(self) -> None:
        if not hasattr(self, "lbl") or self._syncing_coordinates or self._changing_scope or getattr(self, "_applying_scene", False):
            return
        if self.vars["op"].get() == W.OP_FORMING:
            # Former Forming used the same RESET opcode; keep its command bits
            # while removing external experiment terminology from the controls.
            self.vars["op"].set(W.OP_RESET)
        if self.scene.get() == "单器件持续选通 8 s（配合 4200 测量）":
            self.scene.set(next(iter(W.SCENES)))
        try:
            key = W.scene_key(self.scene.get())
        except ValueError:
            key = next(iter(W.SCENES))
        try:
            scope = self.scope_mode.get()
            if scope not in SCOPES:
                rf, rt, cf, ct = (int(self.vars[field].get()) for field in ("row_from", "row_to", "col_from", "col_to"))
                scope = "单个器件" if rf == rt and cf == ct else "一整行" if rf == rt and cf == 0 and ct == 127 else "自定义范围"
            _set_text(self.scene_display, scope)
            _set_text(self.scene_description, SCOPES[scope])
            self._coordinate_mode = scope
            self._show_coordinates(scope)
        except ValueError:
            pass
        _set_text(self.op_display, OP_LABELS.get(self.vars["op"].get(), self.vars["op"].get()))
        try:
            plan = self.plan()
            gap_s = self.ctx.route_bar.options().download_gap_s
            _set_text(self.total_time_text, duration_text(plan.nominal_selection_s))
            _set_text(self.time_description,
                "单次 {} · 每器件 {} · {} 个器件\n"
                "写入 {} 条（含STOP）· 间隔 {:g} ms · 写入等待预算 {}".format(
                    duration_text(plan.wwv.cycles / CHIP_CLK_HZ), duration_text(plan.per_cell_selection_s),
                    plan.cells, plan.instructions + 1, gap_s * 1000,
                    duration_text(plan.download_gap_budget_s(gap_s))))
            text = plan.summary if self.show_details.get() else (
                "reg[8]={:08X} · WRITEB={:08X} · 指令{}条（含STOP）".format(
                    plan.wwv.word, plan.first_word, plan.instructions + 1))
            self._set_preview(text, C["text"])
        except (W.SpecError, ValueError) as e:
            _set_text(self.total_time_text, "—")
            _set_text(self.time_description, "参数不完整或超出范围，请检查下方提示。")
            self._set_preview(str(e), C["err"])

    def _plan_or_warn(self):
        try:
            return self.plan()
        except (W.SpecError, ValueError) as e:
            messagebox.showerror("填写有误", str(e))
            return None

    def to_sequence(self) -> None:
        p = self._plan_or_warn()
        if p:
            self.ctx.sequence_set(p.items)
            self.ctx.log("info", "提示", "已生成 {} 条序列条目，可以在右侧检查、修改或导出".format(len(p.items)))

