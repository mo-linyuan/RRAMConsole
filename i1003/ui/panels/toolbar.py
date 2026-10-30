"""顶部两行：标题与连接、路由与发送选项。"""

from __future__ import annotations

import tkinter as tk
import math
from tkinter import ttk
from typing import Callable, Dict

from ...engine.runner import RunOptions
from ...protocol import fpga
from ...protocol.pkg import NODES, Route
from ...transport.simulator import PROFILES
from ..theme import C


class ConnectionBar:
    def __init__(self, parent, fonts, on_toggle: Callable[[], None]):
        self._connected = False
        self.mode = tk.StringVar(value="真实板卡")
        self.profile = tk.StringVar(value=next(iter(PROFILES)))
        mode_row = ttk.Frame(parent)
        mode_row.pack(fill="x", pady=(0, 4))
        ttk.Label(mode_row, text="连接模式", style="Bar.TLabel").pack(side="left", padx=(0, 6))
        self.mode_combo = ttk.Combobox(mode_row, textvariable=self.mode, values=("真实板卡", "离线模拟"),
                                       width=9, state="readonly")
        self.mode_combo.pack(side="left")
        self.mode_combo.bind("<<ComboboxSelected>>", lambda event: self._refresh_mode())
        self.profile_combo = ttk.Combobox(mode_row, textvariable=self.profile, values=tuple(PROFILES),
                                          width=23, state="readonly")
        self.mode_hint = tk.Label(mode_row, text="仅本机模拟 · 不连接实物", bg=C["bg"], fg=C["warn"], font=fonts.ui)
        top = ttk.Frame(parent)
        top.pack(fill="x")
        self.lbl_status = tk.Label(top, text="", bg=C["bg"], fg=C["warn"], font=fonts.bold)
        self.lbl_state = tk.Label(top, text="●  未连接", bg=C["bg"], fg=C["sub"], font=fonts.ui)
        self.lbl_state.pack(side="right")
        self.btn = ttk.Button(top, text="连接", style="Toolbar.Accent.TButton", command=on_toggle)
        self.btn.pack(side="right", padx=(8, 12))
        self.vars: Dict[str, tk.StringVar] = dict(
            lip=tk.StringVar(value=fpga.PC_IP), lport=tk.StringVar(value=str(fpga.PORT)),
            rip=tk.StringVar(value=fpga.BOARD_IP), rport=tk.StringVar(value=str(fpga.PORT)))
        self.entries = []
        for key, w, lbl in [("rport", 6, ":"), ("rip", 13, "板卡"), ("lport", 6, ":"), ("lip", 13, "本机")]:
            entry = ttk.Entry(top, textvariable=self.vars[key], width=w)
            entry.pack(side="right")
            self.entries.append(entry)
            ttk.Label(top, text=lbl, style="Bar.TLabel").pack(side="right", padx=(10, 4))

    def endpoints(self):
        v = {k: x.get().strip() for k, x in self.vars.items()}
        return v["lip"], int(v["lport"]), v["rip"], int(v["rport"])

    def is_simulation(self):
        return self.mode.get() == "离线模拟"

    def _refresh_mode(self):
        simulated = self.is_simulation()
        if simulated:
            self.profile_combo.pack(side="left", padx=(8, 0))
            self.mode_hint.pack(side="left", padx=(8, 0))
        else:
            self.profile_combo.pack_forget()
            self.mode_hint.pack_forget()
        for entry in self.entries:
            entry.configure(state="disabled" if self._connected or simulated else "normal")
        self.btn.configure(text="断开" if self._connected else "启动模拟" if simulated else "连接")
        self.lbl_state.configure(text=("●  离线模拟" if simulated else "●  UDP 已打开") if self._connected
                                 else "●  模拟未启动" if simulated else "●  未连接",
                                 fg=C["warn"] if simulated else C["ok"] if self._connected else C["sub"])

    def set_connected(self, on: bool) -> None:
        self._connected = on
        self.mode_combo.configure(state="disabled" if on else "readonly")
        self.profile_combo.configure(state="disabled" if on else "readonly")
        self._refresh_mode()

    def set_status(self, text: str) -> None:
        self.lbl_status.config(text=text)
        if text:
            self.lbl_status.pack(side="left", padx=(0, 10))
        else:
            self.lbl_status.pack_forget()

    def set_link_state(self, ok: bool, detail: str = "") -> None:
        """The LED reflects a real probe answer, not just a successful local bind."""
        if ok:
            text = "●  UDP 已打开" + ("（{}）".format(detail) if detail else "")
            self.lbl_state.configure(text=text, fg=C["warn"] if detail else C["ok"])
        else:
            self.lbl_state.configure(text="●  未连通（{}）".format(detail) if detail else "●  未连通",
                                     fg=C["err"])


class RouteBar:
    def __init__(self, parent, on_route_changed: Callable[[], None]):
        self.on_options_changed = on_route_changed
        bar = ttk.Frame(parent, padding=(10, 1, 10, 4))
        self.frame = bar
        bar.pack(fill="x")
        self.vars: Dict[str, tk.Variable] = dict(
            core=tk.StringVar(value="00"), src=tk.StringVar(value="30"), rgn=tk.StringVar(value="0"),
            gap=tk.StringVar(value="20"), download_gap=tk.StringVar(value="0"), ready=tk.BooleanVar(value=True))

        def lab(t):
            ttk.Label(bar, text=t, style="Bar.TLabel").pack(side="left", padx=(0, 4))

        for key, label, values, w in [("core", "目标核", NODES, 4), ("src", "源节点", NODES, 4),
                                      ("rgn", "RGN", ["0", "1", "2", "3"], 3)]:
            lab(label)
            cb = ttk.Combobox(bar, textvariable=self.vars[key], values=values, width=w, state="readonly")
            cb.pack(side="left", padx=(0, 14))
            cb.bind("<<ComboboxSelected>>", lambda e: on_route_changed())
        lab("控制间隔 / ms")
        ttk.Entry(bar, textvariable=self.vars["gap"], width=5).pack(side="left", padx=(0, 14))
        ttk.Checkbutton(bar, text="发送前查 Ready", variable=self.vars["ready"],
                        style="Bar.TCheckbutton").pack(side="left", padx=(0, 18))
        self.vars["gap"].trace_add("write", lambda *args: self.on_options_changed())
        self.download_row = ttk.Frame(parent, padding=(10, 0, 10, 4))
        self.download_row.pack(fill="x")
        ttk.Label(self.download_row, text="指令写入间隔 / ms", style="Bar.TLabel").pack(side="left", padx=(0, 4))
        ttk.Entry(self.download_row, textvariable=self.vars["download_gap"], width=5).pack(side="left")
        ttk.Label(self.download_row, text="0 = 不额外等待",
                  style="Bar.TLabel").pack(side="left", padx=(10, 0))
        self.vars["download_gap"].trace_add("write", lambda *args: self.on_options_changed())
        self._download_inline = None
        self._parent = parent
        bar.bind("<Configure>", self._fit_download)

    def set_options_changed_callback(self, callback):
        self.on_options_changed = callback

    def _fit_download(self, event):
        # Measure contents independently of the chosen row, avoiding resize
        # feedback when the row itself changes padding/geometry master.
        required = (sum(w.winfo_reqwidth() for w in self.frame.winfo_children()) + 90
                    + sum(w.winfo_reqwidth() for w in self.download_row.winfo_children()) + 42)
        inline = event.width >= required
        if inline == self._download_inline:
            return
        self._download_inline = inline
        self.download_row.pack_forget()
        if inline:
            self.download_row.configure(padding=(8, 0, 0, 0))
            self.download_row.pack(in_=self.frame, side="left")
        else:
            self.download_row.configure(padding=(10, 0, 10, 4))
            self.download_row.pack(in_=self._parent, after=self.frame, fill="x")

    def route(self) -> Route:
        return Route.from_names(self.vars["core"].get(), self.vars["src"].get(), int(self.vars["rgn"].get()))

    def set_locked(self, locked):
        for widget in self.frame.winfo_children() + self.download_row.winfo_children():
            if isinstance(widget, (ttk.Entry, ttk.Checkbutton)):
                widget.configure(state="disabled" if locked else "readonly" if isinstance(widget, ttk.Combobox) else "normal")

    def options(self) -> RunOptions:
        try:
            gap = float(self.vars["gap"].get() or 0) / 1000.0
            download_gap = float(self.vars["download_gap"].get() or 0) / 1000.0
        except ValueError:
            raise ValueError("发送间隔需要填写数字，单位为 ms")
        if not math.isfinite(gap) or gap < 0:
            raise ValueError("发送间隔必须为非负有限数，单位为 ms")
        if not math.isfinite(download_gap) or download_gap < 0:
            raise ValueError("写入间隔必须为非负有限数，单位为 ms")
        return RunOptions(route=self.route(), check_ready=self.vars["ready"].get(), gap_s=gap,
                          download_gap_s=download_gap)


class ChipSelector:
    """Only registered chip implementations can be selected."""

    def __init__(self, parent, available, current, on_changed, compact=False):
        row = ttk.Frame(parent, padding=0 if compact else (16, 4, 16, 8))
        row.pack(fill="x")
        self._families = {family.name: family for family in available}
        self.selected = tk.StringVar(value=current.name)
        ttk.Label(row, text="芯片系列", style="Bar.TLabel").pack(side="left", padx=(0, 8))
        self.combo = ttk.Combobox(row, textvariable=self.selected, values=list(self._families),
                                  state="readonly", width=18)
        self.combo.pack(side="left")
        self.combo.bind("<<ComboboxSelected>>", lambda e: on_changed(self._families[self.selected.get()].id))
        if not compact:
            ttk.Label(row, text="操作指令随芯片系列加载", style="Bar.TLabel").pack(side="left", padx=14)

    def set_locked(self, locked):
        self.combo.configure(state="disabled" if locked else "readonly")
