"""顶部两行：标题与连接、路由与发送选项。"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Dict

from ...engine.runner import RunOptions
from ...protocol import fpga
from ...protocol.pkg import NODES, Route
from ..theme import C


class ConnectionBar:
    def __init__(self, parent, fonts, on_toggle: Callable[[], None]):
        top = ttk.Frame(parent, padding=(16, 12, 16, 4))
        top.pack(fill="x")
        ttk.Label(top, text="I1003 调试台", style="App.TLabel").pack(side="left")
        self.lbl_status = tk.Label(top, text="", bg=C["bg"], fg=C["warn"], font=fonts.bold)
        self.lbl_status.pack(side="left", padx=20)
        self.lbl_state = tk.Label(top, text="●  未连接", bg=C["bg"], fg=C["sub"], font=fonts.ui)
        self.lbl_state.pack(side="right")
        self.btn = ttk.Button(top, text="连接", style="Accent.TButton", command=on_toggle)
        self.btn.pack(side="right", padx=(8, 12))
        self.vars: Dict[str, tk.StringVar] = dict(
            lip=tk.StringVar(value=fpga.PC_IP), lport=tk.StringVar(value=str(fpga.PORT)),
            rip=tk.StringVar(value=fpga.BOARD_IP), rport=tk.StringVar(value=str(fpga.PORT)))
        for key, w, lbl in [("rport", 6, ":"), ("rip", 13, "板卡"), ("lport", 6, ":"), ("lip", 13, "本机")]:
            ttk.Entry(top, textvariable=self.vars[key], width=w).pack(side="right")
            ttk.Label(top, text=lbl, style="Bar.TLabel").pack(side="right", padx=(10, 4))

    def endpoints(self):
        v = {k: x.get().strip() for k, x in self.vars.items()}
        return v["lip"], int(v["lport"]), v["rip"], int(v["rport"])

    def set_connected(self, on: bool) -> None:
        self.btn.config(text="断开" if on else "连接")
        self.lbl_state.config(text="●  已连接" if on else "●  未连接", fg=C["ok"] if on else C["sub"])

    def set_status(self, text: str) -> None:
        self.lbl_status.config(text=text)


class RouteBar:
    def __init__(self, parent, on_route_changed: Callable[[], None]):
        bar = ttk.Frame(parent, padding=(16, 2, 16, 8))
        bar.pack(fill="x")
        self.vars: Dict[str, tk.Variable] = dict(
            core=tk.StringVar(value="00"), src=tk.StringVar(value="30"), rgn=tk.StringVar(value="0"),
            gap=tk.StringVar(value="20"), ready=tk.BooleanVar(value=True), quiet=tk.BooleanVar(value=True),
            fast=tk.BooleanVar(value=False))

        def lab(t):
            ttk.Label(bar, text=t, style="Bar.TLabel").pack(side="left", padx=(0, 4))

        for key, label, values, w in [("core", "目标核", NODES, 4), ("src", "源节点", NODES, 4),
                                      ("rgn", "RGN", ["0", "1", "2", "3"], 3)]:
            lab(label)
            cb = ttk.Combobox(bar, textvariable=self.vars[key], values=values, width=w, state="readonly")
            cb.pack(side="left", padx=(0, 14))
            cb.bind("<<ComboboxSelected>>", lambda e: on_route_changed())
        lab("间隔 ms")
        ttk.Entry(bar, textvariable=self.vars["gap"], width=5).pack(side="left", padx=(0, 14))
        for key, text in [("ready", "发送前查 Ready"), ("quiet", "日志隐藏 Ready 查询"), ("fast", "批量快速发送（每包 100 帧）")]:
            ttk.Checkbutton(bar, text=text, variable=self.vars[key], style="Bar.TCheckbutton").pack(side="left", padx=(0, 10))
        ttk.Label(bar, text="源节点 30 是推断（片外口 3）", style="Bar.TLabel").pack(side="right")

    def route(self) -> Route:
        return Route.from_names(self.vars["core"].get(), self.vars["src"].get(), int(self.vars["rgn"].get()))

    def options(self) -> RunOptions:
        try:
            gap = float(self.vars["gap"].get() or 0) / 1000.0
        except ValueError:
            gap = 0.02
        return RunOptions(route=self.route(), check_ready=self.vars["ready"].get(), gap_s=gap,
                          fast=self.vars["fast"].get())

    @property
    def quiet(self) -> bool:
        return bool(self.vars["quiet"].get())
