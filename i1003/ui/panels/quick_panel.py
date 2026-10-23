"""一键测试：选场景、改几个数，生成并运行整套 RRAM 写测试。表单和 WriteTestSpec 一一对应。"""

from __future__ import annotations

import tkinter as tk
from dataclasses import fields
from tkinter import messagebox, ttk
from typing import Dict

from ...protocol.isa import CellEncoding
from ...recipes import write_test as W
from ..context import AppContext
from ..theme import C, info_box

AFTER = ["等预计时间后读 reg[0] 确认结束", "只等预计时间"]
LABELS = dict(pe="PE", array="阵列", row_from="行", row_to="行", col_from="列", col_to="列", repeat="每个器件重复", hold_s="选通时间",
              pulse_ms="脉宽", verify_times="验证次数")


class QuickPanel:
    def __init__(self, parent, ctx: AppContext):
        self.ctx = ctx
        first = next(iter(W.SCENES))
        d = W.scene(first)
        self.scene = tk.StringVar(value=first)
        # 每个 spec 字段对应一个界面变量
        self.vars: Dict[str, tk.Variable] = {}
        for f in fields(W.WriteTestSpec):
            v = getattr(d, f.name)
            self.vars[f.name] = tk.BooleanVar(value=v) if isinstance(v, bool) else tk.StringVar(value=str(v))
        self.after = tk.StringVar(value=AFTER[0])
        self._build(parent)
        for v in list(self.vars.values()) + [self.after]:
            v.trace_add("write", lambda *a: self.update())
        self.update()

    def settings_vars(self) -> Dict[str, tk.Variable]:
        return dict(self.vars, scene=self.scene, after=self.after)

    # ---------------------------------------------------------------- 界面
    def _build(self, p):
        row = ttk.Frame(p, style="Card.TFrame")
        row.pack(fill="x")
        ttk.Label(row, text="场景", style="Card.TLabel").pack(side="left", padx=(0, 8))
        cb = ttk.Combobox(row, textvariable=self.scene, values=list(W.SCENES), state="readonly", width=36)
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>", lambda e: self.apply_scene())
        ttk.Label(row, text="选场景会自动填好下面各项", style="Sub.TLabel").pack(side="left", padx=10)

        g = ttk.Frame(p, style="Card.TFrame", padding=(0, 6, 0, 0))
        g.pack(fill="x")
        V = self.vars

        def sec(r, text):
            ttk.Label(g, text=text, style="Sec.TLabel").grid(row=r, column=0, columnspan=8, sticky="w", pady=(6, 0))

        def lab(r, c, text):
            ttk.Label(g, text=text, style="Card.TLabel").grid(row=r, column=c, sticky="w", padx=(0, 6), pady=2)

        def spin(r, c, key, lo, hi, w=4):
            ttk.Spinbox(g, textvariable=V[key], from_=lo, to=hi, width=w).grid(row=r, column=c, sticky="w", pady=2, padx=(0, 12))

        def combo(r, c, var, values, w, span=1):
            ttk.Combobox(g, textvariable=var, values=values, state="readonly", width=w).grid(
                row=r, column=c, columnspan=span, sticky="w", pady=2, padx=(0, 12))

        def entry(r, c, key, w=7):
            ttk.Entry(g, textvariable=V[key], width=w).grid(row=r, column=c, sticky="w", pady=2, padx=(0, 12))

        sec(0, "目标器件（目标核在顶部选）")
        lab(1, 0, "操作"); combo(1, 1, V["op"], W.OPS, 22, 3)
        lab(1, 4, "地址编码"); combo(1, 5, V["encoding"], CellEncoding.ALL, 18, 3)
        lab(2, 0, "PE"); spin(2, 1, "pe", 0, 7)
        lab(2, 2, "阵列"); spin(2, 3, "array", 0, 7)
        lab(3, 0, "行"); spin(3, 1, "row_from", 0, 127)
        lab(3, 2, "到"); spin(3, 3, "row_to", 0, 127)
        lab(3, 4, "列"); spin(3, 5, "col_from", 0, 127)
        lab(3, 6, "到"); spin(3, 7, "col_to", 0, 127)
        sec(4, "脉冲与运行")
        lab(5, 0, "脉宽 ms"); entry(5, 1, "pulse_ms")
        lab(5, 2, "验证次数"); spin(5, 3, "verify_times", 0, 255)
        lab(5, 4, "每个器件重复"); entry(5, 5, "repeat")
        lab(6, 0, "或选通 s"); entry(6, 1, "hold_s")
        ttk.Label(g, text="填大于 0 的秒数就按选通时间自动算重复次数；填 0 按上面的次数",
                  style="Sub.TLabel").grid(row=6, column=2, columnspan=6, sticky="w")
        lab(7, 0, "启动后"); combo(7, 1, self.after, AFTER, 30, 5)
        cf = ttk.Frame(g, style="Card.TFrame")
        cf.grid(row=8, column=0, columnspan=8, sticky="w", pady=(2, 0))
        for key, text in [("check_reg8", "核对 reg[8]"), ("check_inst", "核对第一条指令"),
                          ("remind_4200", "启动后提醒去 4200 点 run")]:
            ttk.Checkbutton(cf, text=text, variable=V[key], style="Card.TCheckbutton").pack(side="left", padx=(0, 12))

        self.lbl = info_box(p, self.ctx.fonts, wrap=600)
        btns = ttk.Frame(p, style="Card.TFrame")
        btns.pack(anchor="w")
        ttk.Button(btns, text="一键运行", style="Accent.TButton", command=self.run).pack(side="left")
        ttk.Button(btns, text="生成到序列", command=self.to_sequence).pack(side="left", padx=8)
        ttk.Button(btns, text="只检查通路（写读 reg[8]）", command=self.path_check).pack(side="left")

    # ---------------------------------------------------------------- 逻辑
    def apply_scene(self) -> None:
        spec = W.scene(self.scene.get())
        for k, v in spec.to_dict().items():
            self.vars[k].set(v)

    def spec(self) -> W.WriteTestSpec:
        d = {}
        for f in fields(W.WriteTestSpec):
            raw = self.vars[f.name].get()
            try:
                d[f.name] = raw if f.type in ("str", str) else (bool(raw) if f.type in ("bool", bool) else
                                                                (float(raw) if f.type in ("float", float) else int(raw)))
            except (ValueError, TypeError):
                raise W.SpecError("“{}”需要填数字".format(LABELS.get(f.name, f.name)))
        d["poll_after"] = self.after.get() == AFTER[0]
        return W.WriteTestSpec(**d)

    def plan(self) -> W.Plan:
        return W.plan(self.spec())

    def update(self) -> None:
        if not hasattr(self, "lbl"):
            return
        try:
            self.lbl.config(text=self.plan().summary, fg=C["text"])
        except (W.SpecError, ValueError) as e:
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
            self.ctx.log("info", "提示", "已生成 {} 条序列条目，可以在右边检查、修改或导出".format(len(p.items)))

    def path_check(self) -> None:
        try:
            wwv = self.plan().wwv
        except (W.SpecError, ValueError):
            from ...protocol.isa import WwvConfig
            wwv = WwvConfig.from_pulse_ms(1.0)
        self.ctx.run(W.path_check(wwv), confirm=False)
