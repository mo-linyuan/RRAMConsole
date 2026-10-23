"""主窗口：创建通信、执行器和各面板，并实现 AppContext 把它们连起来。

线程模型：UDP 接收线程和执行线程都不直接碰 Tk 控件，事件先进队列，由主线程每 50 ms 取出处理。
"""

from __future__ import annotations

import os
import queue
import tkinter as tk
from tkinter import messagebox, ttk
from typing import List, Optional, Sequence

from ..engine.runner import RunEvents, Runner
from ..model.items import Item, hexs, total_frames
from ..protocol.pkg import NODES, Pkg
from ..transport.udp_link import UdpLink
from .context import AppContext
from .panels.log_panel import LogPanel
from .panels.quick_panel import QuickPanel
from .panels.sequence_panel import SequencePanel
from .panels.template_panel import TemplatePanel
from .panels.toolbar import ConnectionBar, RouteBar
from .settings import Settings
from .theme import C, Fonts, apply_style, card

SETTINGS_FILE = os.path.join(os.path.expanduser("~"), ".i1003_console", "settings.json")


class _QueueEvents(RunEvents):
    """把执行器的回调转成队列消息。"""

    def __init__(self, q: "queue.Queue"):
        self.q = q

    def log(self, tag, head, text): self.q.put(("log", tag, head, text))
    def progress(self, done, total): self.q.put(("progress", done, total))
    def status(self, text): self.q.put(("status", text))
    def notify(self, text): self.q.put(("notify", text))
    def item_state(self, row, state): self.q.put(("state", row, state))
    def finished(self, ok): self.q.put(("finished", ok))


class App(AppContext):
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("I1003 调试台")
        root.geometry("1380x900")
        root.minsize(1150, 720)
        root.configure(bg=C["bg"])
        self.fonts = Fonts()
        apply_style(self.fonts)

        self.q: "queue.Queue" = queue.Queue()
        self.link = UdpLink(on_send=self._on_send, on_receive=self._on_receive)
        self.runner = Runner(self.link, _QueueEvents(self.q))
        self.settings = Settings(SETTINGS_FILE)

        self._build()
        self.settings.register("conn", self.conn.vars)
        self.settings.register("route", self.route_bar.vars)
        self.settings.register("quick", self.quick.settings_vars())
        self.settings.load()
        self.quick.update()
        root.after(50, self._pump)
        root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------------------------------------------------------------- 布局
    def _build(self):
        self.conn = ConnectionBar(self.root, self.fonts, self._toggle_connection)
        self.route_bar = RouteBar(self.root, self.on_route_changed)

        body = ttk.PanedWindow(self.root, orient="vertical")
        body.pack(fill="both", expand=True, padx=16, pady=(0, 14))
        upper = ttk.PanedWindow(body, orient="horizontal")
        body.add(upper, weight=3)

        lo, li = card(upper)
        upper.add(lo, weight=2)
        nb = ttk.Notebook(li, style="Card.TNotebook")
        nb.pack(fill="both", expand=True)
        t1 = ttk.Frame(nb, style="Card.TFrame", padding=(2, 10, 2, 2))
        t2 = ttk.Frame(nb, style="Card.TFrame", padding=(2, 10, 2, 2))
        nb.add(t1, text="一键测试")
        nb.add(t2, text="报文模板")
        self.nb, self.tab_templates = nb, t2

        self.seq = SequencePanel(upper, self)
        upper.add(self.seq.outer, weight=3)
        self.quick = QuickPanel(t1, self)
        self.templates = TemplatePanel(t2, self)

        self.logp = LogPanel(body, self.fonts)
        body.add(self.logp.outer, weight=2)
        self.root.after(150, lambda: upper.sashpos(0, 680))
        self.root.after(160, lambda: body.sashpos(0, 560))

    # ---------------------------------------------------------------- AppContext
    def route(self):
        return self.route_bar.route()

    def is_connected(self) -> bool:
        return self.link.is_open

    def is_busy(self) -> bool:
        return self.runner.busy

    def run(self, items: Sequence[Item], rows: Optional[Sequence[Optional[int]]] = None, confirm: bool = True) -> bool:
        if not self.link.is_open:
            messagebox.showwarning("未连接", "请先点右上角“连接”")
            return False
        if self.runner.busy:
            messagebox.showinfo("提示", "上一个任务还在运行")
            return False
        if confirm:
            if any(it.is_start() for it in items) and not messagebox.askyesno(
                    "启动确认", "要运行的内容里有“启动核”，核 {} 会开始执行指令区，可能真正写器件。\n\n"
                                "请确认：指令区末尾有停止指令，电压和 forming 已确认。继续？".format(self.route().core)):
                return False
            n = total_frames(list(items))
            if n > 200 and not messagebox.askyesno("确认", "这次一共要发 {} 条报文，继续？".format(n)):
                return False
        self.settings.save()
        self.seq.set_busy(True)
        return self.runner.start(items, self.route_bar.options(), rows)

    def stop(self) -> None:
        self.runner.stop()

    def log(self, tag, head, text) -> None:
        self.q.put(("log", tag, head, text))

    def sequence_add(self, item):
        self.seq.add(item)

    def sequence_replace_selected(self, item) -> bool:
        return self.seq.replace_selected(item)

    def sequence_set(self, items: List[Item]):
        if self.seq.items and not messagebox.askyesno("生成到序列", "替换当前序列？"):
            return
        self.seq.set_items(items)

    def edit_item(self, item):
        self.nb.select(self.tab_templates)
        self.templates.load(item)

    def on_route_changed(self):
        self.seq.refresh()
        self.templates.update_preview()

    def apply_header(self, header: dict):
        v = self.route_bar.vars
        if header.get("core") in NODES:
            v["core"].set(header["core"])
        if header.get("src") in NODES:
            v["src"].set(header["src"])
        if str(header.get("rgn", "")) in ("0", "1", "2", "3"):
            v["rgn"].set(str(header["rgn"]))
        self.on_route_changed()

    # ---------------------------------------------------------------- 通信回调（在其他线程里调用）
    def _on_send(self, data: bytes, note: str, quiet: bool):
        if quiet and self.route_bar.quiet:
            return
        self.q.put(("log", "send", "发送", "{}    {}".format(hexs(data[:120]) + (" ..." if len(data) > 120 else ""), note)))

    def _on_receive(self, kind: str, data: bytes):
        if kind == "bit":
            if not self.route_bar.quiet:
                self.q.put(("log", "recv", "接收", "{}    值={}".format(hexs(data), data[7] & 1)))
        elif kind == "fpga":
            self.q.put(("log", "recv", "接收", "{}    FPGA 存值（不是芯片回包）".format(hexs(data))))
        else:
            note = "可能来自芯片"
            if len(data) == 8:
                note += "  ·  " + Pkg.decode(data).describe()
            self.q.put(("log", "chip", "芯片", "{}    {}".format(hexs(data), note)))

    # ---------------------------------------------------------------- 主线程消息泵
    def _pump(self):
        try:
            while True:
                m = self.q.get_nowait()
                k = m[0]
                if k == "log":
                    self.logp.append(*m[1:])
                elif k == "progress":
                    self.seq.set_progress(m[1], m[2])
                elif k == "status":
                    self.conn.set_status(m[1])
                elif k == "notify":
                    self.root.after(10, lambda t=m[1]: messagebox.showinfo("请操作", t))
                elif k == "state":
                    self.seq.set_state(m[1], m[2])
                elif k == "finished":
                    self.seq.set_busy(False)
        except queue.Empty:
            pass
        self.root.after(50, self._pump)

    # ---------------------------------------------------------------- 连接
    def _toggle_connection(self):
        if self.link.is_open:
            self.runner.stop()
            self.link.close()
            self.conn.set_connected(False)
            self.log("info", "提示", "已断开")
            return
        try:
            lip, lport, rip, rport = self.conn.endpoints()
            self.link.open(lip, lport, rip, rport)
        except (OSError, ValueError) as e:
            messagebox.showerror("连接失败", "{}\n\n常见原因：网络调试助手还开着，占用了本地端口；"
                                         "或者本机 IP 不是这台电脑网卡的地址（FPGA 的回包固定发往 192.168.1.9:8080）。".format(e))
            return
        self.conn.set_connected(True)
        self.log("info", "提示", "UDP 已打开 {}:{} → {}:{}".format(lip, lport, rip, rport))

    def _on_close(self):
        self.settings.save()
        self.runner.stop()
        self.link.close()
        self.root.destroy()


def main():
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)      # Windows 高分屏下字体清晰
    except Exception:  # noqa: BLE001  非 Windows 或旧系统
        pass
    root = tk.Tk()
    App(root)
    root.mainloop()
