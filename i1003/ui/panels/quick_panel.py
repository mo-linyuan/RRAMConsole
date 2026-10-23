"""一键测试：选场景、改几个数，生成并运行整套 RRAM 写测试。表单和 WriteTestSpec 一一对应。"""

from __future__ import annotations

import tkinter as tk
from dataclasses import fields
from tkinter import messagebox, ttk
from typing import Dict

from rram_console.hardware import RRAM_ARRAY

from ...protocol.isa import CHIP_CLK_HZ, CellEncoding, WwvConfig
from ...recipes import write_test as W
from ..context import AppContext
from ..theme import C, FormViewport, info_box

AFTER = ["等待后查询结束状态", "仅等待预计时间"]
LEGACY_AFTER = {"等预计时间后读 reg[0] 确认结束": AFTER[0], "只等预计时间": AFTER[1]}
OP_LABELS = {W.OP_SET: "SET（写 1）", W.OP_RESET: "RESET（写 0）", W.OP_FORMING: "Forming（反向）"}
LABELS = dict(pe="PE", array="阵列", row_from="行", row_to="行", col_from="列", col_to="列", repeat="每个器件重复",
              wwv_base="基时间", wwv_times="时间倍数", verify_times="验证次数")


def duration_text(seconds):
    if seconds < .001:
        return "{:.3f} µs".format(seconds * 1e6)
    if seconds < 1:
        return "{:.3f} ms".format(seconds * 1000)
    return "{:.6f} s".format(seconds)


class QuickPanel:
    def __init__(self, parent, ctx: AppContext):
        self.ctx = ctx
        first = next(iter(W.SCENES))
        d = W.scene(first)
        self.scene = tk.StringVar(value=first)
        self.scene_display = tk.StringVar(value=W.SCENE_LABELS[first])
        self.scene_description = tk.StringVar(value=W.SCENE_DESCRIPTIONS[first])
        # 每个 spec 字段对应一个界面变量
        self.vars: Dict[str, tk.Variable] = {}
        for f in fields(W.WriteTestSpec):
            if f.name in ("pulse_ms", "hold_s"):
                continue
            v = getattr(d, f.name)
            self.vars[f.name] = tk.BooleanVar(value=v) if isinstance(v, bool) else tk.StringVar(value=str(v))
        self.after = tk.StringVar(value=AFTER[1])
        self.op_display = tk.StringVar(value=OP_LABELS[d.op])
        self.show_details = tk.BooleanVar(value=False)
        self.total_time_text = tk.StringVar(value="—")
        self.time_description = tk.StringVar(value="")
        self._build(parent)
        for v in list(self.vars.values()) + [self.after]:
            v.trace_add("write", lambda *a: self.update())
        self.update()

    def settings_vars(self) -> Dict[str, tk.Variable]:
        return dict(self.vars, scene=self.scene, after=self.after)

    # ---------------------------------------------------------------- 界面
    def _build(self, p):
        btns = ttk.Frame(p, style="Card.TFrame", padding=(0, 10, 0, 0))
        btns.pack(side="bottom", fill="x")
        ttk.Button(btns, text="一键运行", style="Accent.TButton", command=self.run).pack(side="left")
        ttk.Button(btns, text="生成到序列", command=self.to_sequence).pack(side="left", padx=8)
        ttk.Button(btns, text="检查板卡通信", command=self.path_check).pack(side="left")
        self.viewport = FormViewport(p)
        self.viewport.pack(fill="both", expand=True)
        p = self.viewport.content
        row = ttk.Frame(p, style="Card.TFrame")
        row.pack(fill="x")
        ttk.Label(row, text="参数模板", style="Card.TLabel").pack(side="left", padx=(0, 8))
        cb = ttk.Combobox(row, textvariable=self.scene_display, values=list(W.SCENE_LABELS.values()), state="readonly", width=32)
        cb.pack(side="left", fill="x", expand=True)
        cb.bind("<<ComboboxSelected>>", self._select_scene)
        hint = ttk.Label(p, textvariable=self.scene_description, style="Sub.TLabel", wraplength=600, justify="left")
        hint.pack(fill="x", pady=(6, 0))
        hint.bind("<Configure>", lambda e: hint.configure(wraplength=max(100, e.width - 8)))

        g = ttk.Frame(p, style="Card.TFrame", padding=(0, 6, 0, 0))
        g.pack(fill="x")
        V = self.vars

        def sec(r, text):
            ttk.Label(g, text=text, style="Sec.TLabel").grid(row=r, column=0, columnspan=8, sticky="w", pady=(12, 4))

        def lab(r, c, text):
            ttk.Label(g, text=text, style="Card.TLabel").grid(row=r, column=c, sticky="w", padx=(0, 6), pady=2)

        def spin(r, c, key, lo, hi, w=4):
            ttk.Spinbox(g, textvariable=V[key], from_=lo, to=hi, width=w).grid(row=r, column=c, sticky="w", pady=2, padx=(0, 12))

        def combo(r, c, var, values, w, span=1):
            ttk.Combobox(g, textvariable=var, values=values, state="readonly", width=w).grid(
                row=r, column=c, columnspan=span, sticky="w", pady=2, padx=(0, 12))

        def entry(r, c, key, w=7):
            ttk.Entry(g, textvariable=V[key], width=w).grid(row=r, column=c, sticky="w", pady=2, padx=(0, 12))

        sec(0, "目标器件 · {} 阵列".format(RRAM_ARRAY.label))
        lab(1, 0, "操作")
        operation = ttk.Combobox(g, textvariable=self.op_display, values=list(OP_LABELS.values()), state="readonly", width=18)
        operation.grid(row=1, column=1, columnspan=3, sticky="ew", pady=2, padx=(0, 12))
        operation.bind("<<ComboboxSelected>>", lambda e: V["op"].set(
            next(key for key, value in OP_LABELS.items() if value == self.op_display.get())))
        lab(1, 4, "地址编码"); combo(1, 5, V["encoding"], CellEncoding.ALL, 18, 3)
        lab(2, 0, "PE"); spin(2, 1, "pe", 0, 7)
        lab(2, 2, "阵列"); spin(2, 3, "array", 0, 7)
        lab(3, 0, "行"); spin(3, 1, "row_from", 0, RRAM_ARRAY.rows - 1)
        lab(3, 2, "到"); spin(3, 3, "row_to", 0, RRAM_ARRAY.rows - 1)
        lab(3, 4, "列"); spin(3, 5, "col_from", 0, RRAM_ARRAY.columns - 1)
        lab(3, 6, "到"); spin(3, 7, "col_to", 0, RRAM_ARRAY.columns - 1)
        sec(4, "脉冲与运行")
        lab(5, 0, "基时间"); spin(5, 1, "wwv_base", 1, 255)
        lab(5, 2, "时间倍数"); spin(5, 3, "wwv_times", 1, 255)
        lab(5, 4, "验证次数"); spin(5, 5, "verify_times", 0, 255)
        lab(6, 0, "重复次数"); entry(6, 1, "repeat")
        timing = ttk.Frame(g, style="Card.TFrame")
        timing.grid(row=6, column=2, columnspan=6, sticky="w")
        ttk.Label(timing, text="总选通（名义）", style="Card.TLabel").pack(side="left", padx=(0, 10))
        ttk.Label(timing, textvariable=self.total_time_text, style="Sec.TLabel",
                  font=self.ctx.fonts.mono).pack(side="left")
        timing_hint = ttk.Label(g, textvariable=self.time_description, style="Sub.TLabel", justify="left", wraplength=600)
        timing_hint.grid(row=7, column=0, columnspan=8, sticky="ew", pady=(4, 6))
        timing_hint.bind("<Configure>", lambda e: timing_hint.configure(wraplength=max(100, e.width - 8)))
        lab(8, 0, "启动后"); combo(8, 1, self.after, AFTER, 25, 5)
        cf = ttk.Frame(g, style="Card.TFrame")
        cf.grid(row=9, column=0, columnspan=8, sticky="w", pady=(2, 0))
        for key, text in [("check_reg8", "核对 reg[8]"), ("check_inst", "核对首条指令"),
                          ("remind_4200", "提醒操作 4200")]:
            ttk.Checkbutton(cf, text=text, variable=V[key], style="Card.TCheckbutton").pack(side="left", padx=(0, 12))
        ttk.Label(g, text="默认不读取芯片回包；核对与结束查询仅在硬件支持读回时开启。",
                  style="Sub.TLabel", wraplength=600).grid(row=10, column=0, columnspan=8, sticky="w", pady=(4, 0))

        preview = ttk.Frame(p, style="Card.TFrame")
        preview.pack(fill="x", pady=(12, 0))
        ttk.Label(preview, text="运行预览", style="Sec.TLabel").pack(side="left")
        ttk.Checkbutton(preview, text="详细参数", variable=self.show_details, command=self.update,
                        style="Card.TCheckbutton").pack(side="right")
        self.lbl = info_box(p, self.ctx.fonts, wrap=600)
        self.lbl.bind("<Configure>", lambda e: self.lbl.configure(wraplength=max(100, e.width - 24)))

    # ---------------------------------------------------------------- 逻辑
    def _select_scene(self, _event=None):
        self.scene.set(W.scene_key(self.scene_display.get()))
        self.apply_scene()

    def apply_scene(self) -> None:
        spec = W.scene(self.scene.get())
        keep_repeat = W.scene_key(self.scene.get()) in W.VARIABLE_REPEAT_SCENES
        for k, v in spec.to_dict().items():
            if k == "repeat" and keep_repeat:
                continue
            if k in self.vars:
                self.vars[k].set(v)

    def spec(self) -> W.WriteTestSpec:
        d = {}
        for f in fields(W.WriteTestSpec):
            if f.name not in self.vars:
                continue
            raw = self.vars[f.name].get()
            try:
                d[f.name] = raw if f.type in ("str", str) else (bool(raw) if f.type in ("bool", bool) else
                                                                (float(raw) if f.type in ("float", float) else int(raw)))
            except (ValueError, TypeError):
                raise W.SpecError("“{}”需要填数字".format(LABELS.get(f.name, f.name)))
        d["poll_after"] = LEGACY_AFTER.get(self.after.get(), self.after.get()) == AFTER[0]
        return W.WriteTestSpec(**d)

    def plan(self) -> W.Plan:
        return W.plan(self.spec())

    def update(self) -> None:
        if not hasattr(self, "lbl"):
            return
        if self.after.get() in LEGACY_AFTER:
            self.after.set(LEGACY_AFTER[self.after.get()])
        if self.scene.get() == "单器件持续选通 8 s（配合 4200 测量）":
            self.scene.set(next(iter(W.SCENES)))
        try:
            key = W.scene_key(self.scene.get())
        except ValueError:
            key = next(iter(W.SCENES))
        self.scene_display.set(W.SCENE_LABELS[key])
        self.scene_description.set(W.SCENE_DESCRIPTIONS[key])
        self.op_display.set(OP_LABELS.get(self.vars["op"].get(), self.vars["op"].get()))
        try:
            plan = self.plan()
            spec = self.spec()
            self.total_time_text.set(duration_text(plan.nominal_selection_s))
            self.time_description.set(
                "单次 {} · 每器件 {} · {} 个器件 · 时钟 {:g} MHz\n"
                "按配置脉宽累计，不计验证重试、指令间隙及通信时间。".format(
                    duration_text(plan.wwv.cycles / CHIP_CLK_HZ), duration_text(plan.per_cell_selection_s),
                    plan.cells, CHIP_CLK_HZ / 1e6))
            text = plan.summary if self.show_details.get() else (
                "{} · PE{} / 阵列{}（{}）· {} 个器件\n"
                "基时间 {} × 时间倍数 {} · 每个重复 {} 次\n"
                "reg[8] = {:08X} · {} 条指令 + 停止".format(self.op_display.get(), spec.pe, spec.array,
                    RRAM_ARRAY.label, plan.cells, plan.wwv.base, plan.wwv.times, spec.repeat, plan.wwv.word, plan.instructions))
            self.lbl.config(text=text, fg=C["text"])
        except (W.SpecError, ValueError) as e:
            self.total_time_text.set("—")
            self.time_description.set("参数不完整或超出范围，请检查下方提示。")
            self.lbl.config(text=str(e), fg=C["err"])

    def _plan_or_warn(self):
        try:
            return self.plan()
        except (W.SpecError, ValueError) as e:
            messagebox.showerror("填写有误", str(e))
            return None

    def run(self) -> None:
        p = self._plan_or_warn()
        if not p:
            return
        if not self.ctx.is_connected():
            messagebox.showwarning("未连接", "请先点右上角“连接”")
            return
        if messagebox.askyesno("一键运行", "目标核 {}\n\n{}\n\n运行后芯片会执行这些指令，可能真正改变器件状态。"
                                         "请确认电压接法和 forming 状态。继续？".format(self.ctx.route().core, p.summary)):
            self.ctx.run(p.items, confirm=False)

    def to_sequence(self) -> None:
        p = self._plan_or_warn()
        if p:
            self.ctx.sequence_set(p.items)
            self.ctx.log("info", "提示", "已生成 {} 条序列条目，可以在下方检查、修改或导出".format(len(p.items)))

    def path_check(self) -> None:
        try:
            wwv = self.plan().wwv
        except (W.SpecError, ValueError):
            wwv = WwvConfig()
        self.ctx.run(W.path_check(wwv), confirm=False)
