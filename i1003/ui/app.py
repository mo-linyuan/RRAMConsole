"""主窗口：创建通信、执行器和各面板，并实现 AppContext 把它们连起来。

线程模型：UDP 接收线程和执行线程都不直接碰 Tk 控件，事件先进队列，由主线程每 50 ms 取出处理。
"""

from __future__ import annotations

import os
import queue
import threading
import time
from dataclasses import asdict
from datetime import datetime
import tkinter as tk
from tkinter import messagebox, ttk
from typing import List, Optional, Sequence

from rram_console import APP_NAME
from rram_console.chips import DEFAULT_FAMILY, families, get_family
from rram_console.run_record import RunRecord, RUNS_DIR
from .context import AppContext
from .icon import set_app_icon, set_app_identity
from .panels.log_panel import LogPanel
from .panels.toolbar import ChipSelector
from .settings import Settings
from .theme import C, Fonts, apply_style, card

SETTINGS_FILE = os.path.join(os.path.expanduser("~"), ".i1003_console", "settings.json")


class _QueueEvents:
    """把执行器的回调转成队列消息。"""

    def __init__(self, q: "queue.Queue", record=None):
        self.q = q
        self.record = record or (lambda *args, **kwargs: None)

    def log(self, tag, head, text):
        self.record("log", tag=tag, head=head, text=text)
        self.q.put(("log", tag, head, text, datetime.now().strftime("%H:%M:%S.%f")[:-3]))
    def progress(self, done, total): self.q.put(("progress", done, total))
    def status(self, text): self.q.put(("status", text))
    def notify(self, text): self.q.put(("notify", text))
    def item_state(self, row, state):
        self.record("step", row=row, state=state)
        self.q.put(("state", row, state))
    def result(self, result):
        self.record("result", **asdict(result))
        self.q.put(("result", result))
    def finished(self, ok):
        self.record("finished", ok=ok)
        self.q.put(("finished", ok))


class App(AppContext):
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title(APP_NAME)
        set_app_icon(root)
        scale = root.winfo_fpixels("1i") / 96
        width = min(round(1380 * scale), round(root.winfo_screenwidth() * .94))
        height = min(round(900 * scale), round(root.winfo_screenheight() * .90))
        root.geometry("{}x{}".format(width, height))
        root.minsize(min(round(1150 * scale), width), min(round(720 * scale), height))
        root.configure(bg=C["bg"])
        self.fonts = Fonts()
        apply_style(self.fonts)

        self.q: "queue.Queue" = queue.Queue()
        self._record = None
        self._record_lock = threading.Lock()
        self._task_active = False
        self.settings = Settings(SETTINGS_FILE)
        self.settings.load()
        saved_family = self.settings.get_extra("chip_family", DEFAULT_FAMILY)
        try:
            self.family = get_family(saved_family)
        except ValueError:
            self.family = get_family(DEFAULT_FAMILY)
            self.log("info", "提示", "已保存的芯片系列 {} 尚未安装，使用 {}".format(saved_family, self.family.name))
        self.backend = self.family.create_backend()
        self.link = self.backend.create_link(self._on_send, self._on_receive)
        self.runner = self.backend.create_runner(self.link, _QueueEvents(self.q, self._record_event))

        self._build()
        self._register_settings()
        self.settings.load()
        getattr(self.backend, "migrate_settings", lambda settings, quick: None)(self.settings, self.quick)
        self.quick.update()
        self._pump_job = root.after(50, self._pump)
        root.bind("<Destroy>", self._cancel_ui_jobs, add="+")
        root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------------------------------------------------------------- 布局
    def _build(self):
        header = ttk.Frame(self.root, padding=(16, 8, 16, 6))
        header.pack(fill="x")
        family_area = ttk.Frame(header)
        family_area.pack(side="left")
        connection_area = ttk.Frame(header)
        connection_area.pack(side="right")
        self.chip_selector = ChipSelector(family_area, families(), self.family, self._switch_family, compact=True)
        self.conn = self.backend.create_connection_bar(connection_area, self.fonts, self._toggle_connection)
        self.route_bar = self.backend.create_route_bar(self.root, self.on_route_changed)

        body = ttk.PanedWindow(self.root, orient="horizontal")
        body.pack(fill="both", expand=True, padx=16, pady=(0, 14))
        left = ttk.PanedWindow(body, orient="vertical")
        body.add(left, weight=3)

        lo, li = card(left)
        left.add(lo, weight=3)
        nb = ttk.Notebook(li, style="Card.TNotebook")
        nb.pack(fill="both", expand=True)
        t1 = ttk.Frame(nb, style="Card.TFrame", padding=(2, 10, 2, 2))
        t2 = ttk.Frame(nb, style="Card.TFrame", padding=(2, 10, 2, 2))
        nb.add(t1, text="一键测试")
        nb.add(t2, text="报文模板")
        self.nb, self.tab_templates = nb, t2

        self.seq = self.backend.create_sequence_panel(left, self)
        left.add(self.seq.outer, weight=2)
        self.quick = self.backend.create_quick_panel(t1, self)
        self.templates = self.backend.create_template_panel(t2, self)

        self.logp = LogPanel(body, self.fonts, open_records=self._open_records)
        body.add(self.logp.outer, weight=2)
        self.workspace, self.left_stack = body, left
        previous_layout = getattr(self, "_layout_job", None)
        if previous_layout is not None:
            self.root.after_cancel(previous_layout)
        def initialize_layout():
            self._layout_job = None
            if not body.winfo_exists():
                return
            self.root.update_idletasks()
            if body.winfo_height() < 100:
                self._layout_job = self.root.after(50, initialize_layout)
                return
            body.sashpos(0, round(body.winfo_width() * .57))
            self.root.update_idletasks()
            left.sashpos(0, round(left.winfo_height() * .60))
        self._layout_job = self.root.after(150, initialize_layout)

    # ---------------------------------------------------------------- AppContext
    def chip_family_id(self):
        return self.family.id

    def route(self):
        return self.route_bar.route()

    def is_connected(self) -> bool:
        return self.link.is_open

    def is_busy(self) -> bool:
        return self.runner.busy or self._task_active

    def run(self, items: Sequence, rows: Optional[Sequence[Optional[int]]] = None, confirm: bool = True) -> bool:
        if not self.link.is_open:
            messagebox.showwarning("未连接", "请先点右上角“连接”")
            return False
        if self.is_busy():
            messagebox.showinfo("提示", "上一个任务还在运行")
            return False
        if confirm:
            confirmation = self.backend.start_confirmation(items, self.route())
            if confirmation and not messagebox.askyesno("启动确认", confirmation):
                return False
            n = self.backend.frame_count(list(items))
            if n > 200 and not messagebox.askyesno("确认", "这次一共要发 {} 条报文，继续？".format(n)):
                return False
        try:
            options = self.route_bar.options()
            metadata = getattr(self.backend, "run_metadata", lambda items, options: {})(items, options)
            self._record = RunRecord({"chip_family": self.family.id,
                                      "endpoints": self.conn.endpoints(), "rows": list(rows) if rows is not None else None,
                                      **metadata})
        except (OSError, ValueError, TypeError) as exc:
            messagebox.showerror("任务未启动", "参数或运行记录创建失败：{}".format(exc))
            return False
        self.log("info", "记录", str(self._record.path))
        self._save_settings()
        self.seq.set_busy(True)
        self._task_active = True
        started = self.runner.start(items, options, rows)
        if started:
            self.chip_selector.set_locked(True)
            getattr(self.route_bar, "set_locked", lambda locked: None)(True)
        else:
            self._task_active = False
            self.seq.set_busy(False)
            self._record_event("finished", ok=False)
        return started

    def stop(self) -> None:
        self.runner.stop()

    def log(self, tag, head, text) -> None:
        self.q.put(("log", tag, head, text))

    def sequence_add(self, item):
        self.seq.add(item)

    def sequence_replace_selected(self, item) -> bool:
        return self.seq.replace_selected(item)

    def sequence_set(self, items: List):
        if self.is_busy():
            return
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
        declared_family = header.get("chip_family", DEFAULT_FAMILY)
        if declared_family != self.family.id:
            raise ValueError("序列属于 {}，当前选择的是 {}，请先切换到对应芯片系列".format(
                declared_family, self.family.name))
        self.backend.apply_header(header, self)

    def _register_settings(self):
        prefix = getattr(self.backend, "settings_prefix", self.family.id + ".")
        self.settings.register(prefix + "conn", self.conn.vars)
        self.settings.register(prefix + "route", self.route_bar.vars)
        self.settings.register(prefix + "quick", self.quick.settings_vars())

    def _save_settings(self):
        self.settings.set_extra("chip_family", self.family.id)
        self.settings.save()

    def _switch_family(self, family_id):
        if family_id == self.family.id:
            return
        if self.is_connected() or self.is_busy():
            self.chip_selector.selected.set(self.family.name)
            messagebox.showinfo("切换芯片系列", "请先结束任务并断开连接，再切换芯片系列。")
            return
        if self.seq.items and not messagebox.askyesno("切换芯片系列", "切换后会清空当前序列，请先导出需要保留的内容。继续？"):
            self.chip_selector.selected.set(self.family.name)
            return
        try:
            family = get_family(family_id)
            backend = family.create_backend()
            link = backend.create_link(self._on_send, self._on_receive)
            runner = backend.create_runner(link, _QueueEvents(self.q, self._record_event))
        except Exception as exc:
            self.chip_selector.selected.set(self.family.name)
            messagebox.showerror("芯片系列加载失败", str(exc))
            return
        self._save_settings()
        self.link.close()
        self.family, self.backend, self.link, self.runner = family, backend, link, runner
        self.settings = Settings(SETTINGS_FILE)
        self.settings.load()
        for child in self.root.winfo_children():
            child.destroy()
        self._build()
        self._register_settings()
        self.settings.load()
        getattr(self.backend, "migrate_settings", lambda settings, quick: None)(self.settings, self.quick)
        self.quick.update()
        self._save_settings()
        self.log("info", "提示", "已加载 {} 的操作指令".format(family.name))

    # ---------------------------------------------------------------- 通信回调（在其他线程里调用）
    def _on_send(self, data: bytes, note: str, quiet: bool):
        self._record_event("tx", hex=data.hex(" "), note=note, quiet=quiet)
        hex_text = " ".join("{:02X}".format(value) for value in data[:120])
        self.q.put(("log", "send", "发送", "{}    {}".format(hex_text + (" ..." if len(data) > 120 else ""), note),
                    datetime.now().strftime("%H:%M:%S.%f")[:-3]))

    def _on_receive(self, kind: str, data: bytes):
        self._record_event("rx", kind=kind, hex=data.hex(" "))
        self.q.put(("log",) + self.backend.describe_receive(kind, data)
                   + (datetime.now().strftime("%H:%M:%S.%f")[:-3],))

    def _record_event(self, event, **fields):
        with self._record_lock:
            if self._record is None:
                return
            try:
                self._record.write(event, **fields)
            except (OSError, ValueError, TypeError) as exc:
                self.q.put(("log", "err", "记录失败", str(exc)))
                record = self._record
                self._record = None
                try:
                    record.close()
                except OSError:
                    pass
                return
            if event in ("finished", "window_closed"):
                record = self._record
                self._record = None
                try:
                    record.close()
                except OSError as exc:
                    self.q.put(("log", "err", "记录关闭失败", str(exc)))

    def _open_records(self):
        RUNS_DIR.mkdir(parents=True, exist_ok=True)
        os.startfile(str(RUNS_DIR))

    # ---------------------------------------------------------------- 主线程消息泵
    def _pump(self):
        self._pump_job = None
        deadline = time.monotonic() + .012
        try:
            while time.monotonic() < deadline:
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
                elif k == "result":
                    self.seq.set_result(m[1])
                elif k == "finished":
                    self._task_active = False
                    self.seq.set_busy(False)
                    getattr(self.route_bar, "set_locked", lambda locked: None)(False)
                    self.chip_selector.set_locked(self.is_connected())
        except queue.Empty:
            pass
        self._pump_job = self.root.after(10 if not self.q.empty() else 50, self._pump)

    def _cancel_ui_jobs(self, event):
        if event.widget != self.root:
            return
        for name in ("_pump_job", "_layout_job"):
            job = getattr(self, name, None)
            if job is not None:
                self.root.after_cancel(job)
                setattr(self, name, None)

    # ---------------------------------------------------------------- 连接
    def _toggle_connection(self):
        if self.link.is_open:
            self.runner.stop()
            self.link.close()
            self.conn.set_connected(False)
            self.chip_selector.set_locked(self.is_busy())
            self.log("info", "提示", "已断开")
            return
        if self.is_busy():
            messagebox.showinfo("任务正在结束", "请等待当前任务停止后再连接。")
            return
        try:
            description = self.backend.open_link(self.link, self.conn)
        except (OSError, ValueError) as e:
            messagebox.showerror("连接失败", "{}\n\n{}".format(e, getattr(self.backend, "connection_hint", "")))
            return
        self.conn.set_connected(True)
        self.chip_selector.set_locked(True)
        self.log("info", "提示", description)

    def _on_close(self):
        self._save_settings()
        self.runner.stop()
        self.link.close()
        self._record_event("window_closed", interrupted=self.runner.busy)
        self.root.destroy()


def main():
    set_app_identity()
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)      # Windows 高分屏下字体清晰
    except Exception:  # noqa: BLE001  非 Windows 或旧系统
        pass
    root = tk.Tk()
    App(root)
    root.mainloop()
