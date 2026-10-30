"""主窗口：创建通信、执行器和各面板，并实现 AppContext 把它们连起来。

线程模型：UDP 接收线程和执行线程都不直接碰 Tk 控件，事件先进队列，由主线程每 50 ms 取出处理。
"""

from __future__ import annotations

import os
import queue
import threading
import time
from dataclasses import asdict, replace
from datetime import datetime
import tkinter as tk
from tkinter import messagebox, ttk
from typing import List, Optional, Sequence

from rram_console import APP_NAME
from rram_console.chips import DEFAULT_FAMILY, families, get_family
from rram_console.run_record import RunRecord
from .context import AppContext
from .display import work_area, window_size
from .icon import set_app_icon, set_app_identity
from .panels.log_panel import LogPanel, MAX_PREVIEW_CHARS
from .panels.toolbar import ChipSelector
from .settings import Settings
from .resize_surface import ResizeSurface
from .split_pane import SplitPane
from .theme import C, Fonts, apply_style, card

SETTINGS_FILE = os.path.join(os.path.expanduser("~"), ".i1003_console", "settings.json")


class _QueueEvents:
    """把执行器的回调转成队列消息。"""

    def __init__(self, q: "queue.Queue", record=None, simulated=None, control=None):
        self.q = q
        self.record = record or (lambda *args, **kwargs: None)
        self.simulated = simulated or (lambda: False)
        self.control = control if control is not None else q

    def log(self, tag, head, text):
        if self.simulated():
            head = "模拟·" + head
        self.record("log", tag=tag, head=head, text=text)
        self.q.put(("log", tag, head, text, datetime.now().strftime("%H:%M:%S.%f")[:-3]))
    def progress(self, done, total): self.control.put(("progress", done, total))
    def status(self, text): self.control.put(("status", text))
    def notify(self, text): self.control.put(("notify", ("[离线模拟] " if self.simulated() else "") + text))
    def item_state(self, row, state):
        self.record("step", row=row, state=state)
        self.control.put(("state", row, state))
    def result(self, result):
        if self.simulated():
            result = replace(result, summary="[离线模拟] " + result.summary + "；不代表实物结果")
        self.record("result", **asdict(result))
        self.control.put(("result", result))
    def finished(self, ok):
        self.record("finished", ok=ok)
        self.control.put(("finished", ok))


class App(AppContext):
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title(APP_NAME)
        set_app_icon(root)
        scale = root.winfo_fpixels("1i") / 96
        _, _, work_width, work_height = work_area(root)
        width, height, minimum_width, minimum_height = window_size(work_width, work_height, scale)
        root.geometry("{}x{}".format(width, height))
        root.minsize(minimum_width, minimum_height)
        self._display_scale = scale
        self._log_override = None
        root.configure(bg=C["bg"])
        self.fonts = Fonts()
        apply_style(self.fonts)
        self.surface = ResizeSurface(root, width, height)

        self.q: "queue.Queue" = queue.Queue()
        self.control_q = queue.Queue()
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
        self.runner = self.backend.create_runner(self.link, _QueueEvents(
            self.q, self._record_event, lambda: getattr(self.link, "is_simulation", False), self.control_q))

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
        previous_resize = getattr(self, "_resize_job", None)
        if previous_resize is not None:
            self.root.after_cancel(previous_resize)
        header = ttk.Frame(self.surface, padding=(10, 5, 10, 4))
        header.pack(fill="x")
        family_area = ttk.Frame(header)
        family_area.pack(side="left")
        connection_area = ttk.Frame(header)
        connection_area.pack(side="right")
        selector_area = ttk.Frame(family_area)
        selector_area.pack(side="left")
        self.chip_selector = ChipSelector(selector_area, families(), self.family, self._switch_family, compact=True)
        self.log_toggle = ttk.Button(family_area, text="收起日志", command=self._toggle_log)
        self.log_toggle.pack(side="left", padx=(8, 0))
        self.conn = self.backend.create_connection_bar(connection_area, self.fonts, self._toggle_connection)
        self.header, self.family_area, self.connection_area = header, family_area, connection_area
        self._header_stacked = None
        header.bind("<Configure>", self._fit_header)
        self.route_bar = self.backend.create_route_bar(self.surface, self.on_route_changed)
        getattr(self.route_bar, "set_options_changed_callback", lambda callback: None)(self.on_options_changed)

        body = SplitPane(self.surface, orient="vertical")
        body.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        main = SplitPane(body, orient="horizontal")
        body.add(main, weight=4)

        lo, li = card(main)
        main.add(lo, weight=3, minsize=round(300 * self._display_scale))
        nb = ttk.Notebook(li, style="Card.TNotebook")
        nb.pack(fill="both", expand=True)
        t1 = ttk.Frame(nb, style="Card.TFrame", padding=(0, 4, 0, 0))
        t2 = ttk.Frame(nb, style="Card.TFrame", padding=(0, 4, 0, 0))
        nb.add(t1, text="器件配置")
        nb.add(t2, text="报文模板")
        self.nb, self.tab_templates = nb, t2

        self.seq = self.backend.create_sequence_panel(main, self)
        main.add(self.seq.outer, weight=2)
        self.quick = self.backend.create_quick_panel(t1, self)
        self.templates = self.backend.create_template_panel(t2, self)
        generate = getattr(self.quick, "to_sequence", None)
        if callable(generate):
            # Use the unused right side of the native tab strip; no extra row.
            button = ttk.Button(nb, text="生成序列", style="Accent.TButton", command=generate)
            self.quick.generate_button = button
            def fit_tab_action(event=None):
                if nb.select() == str(t1):
                    button.place(relx=1, x=-2, y=0, anchor="ne")
                    button.lift()
                else:
                    button.place_forget()
            nb.bind("<<NotebookTabChanged>>", fit_tab_action)
            fit_tab_action()

        self.logp = LogPanel(body, self.fonts)
        body.add(self.logp.outer, weight=1)
        self.workspace, self.main_split = body, main
        self._log_visible = True
        self._resize_job = None
        previous_layout = getattr(self, "_layout_job", None)
        if previous_layout is not None:
            self.root.after_cancel(previous_layout)
        def initialize_layout():
            self._layout_job = None
            if not body.winfo_exists():
                return
            if body.winfo_height() < 100:
                self._layout_job = self.root.after(50, initialize_layout)
                return
            # Set initial proportions once. Native panes handle later resizes;
            # never move a sash back while the user is dragging it.
            main.sashpos(0, round(main.winfo_width() * .55))
            log_height = min(body.winfo_height() * .30, 200 * self._display_scale)
            body.sashpos(0, round(body.winfo_height() - log_height))
        self._layout_job = self.root.after_idle(initialize_layout)

    def _fit_header(self, event=None):
        required = self.family_area.winfo_reqwidth() + self.connection_area.winfo_reqwidth() + 48
        stacked = self.header.winfo_width() < required + (16 if self._header_stacked else 0)
        if stacked == self._header_stacked:
            return
        self._header_stacked = stacked
        self.family_area.pack_forget()
        self.connection_area.pack_forget()
        if stacked:
            self.family_area.pack(side="top", fill="x", pady=(0, 4))
            self.connection_area.pack(side="top", anchor="w", fill="x")
        else:
            self.family_area.pack(side="left")
            self.connection_area.pack(side="right")

    def _adapt_layout(self):
        self.surface.flush()
        # Bottom logs stay visible on laptops as well as large screens.
        self._set_log_visible(self._log_override if self._log_override is not None else True)

    def _set_log_visible(self, visible):
        if visible != self._log_visible:
            if visible:
                self.workspace.add(self.logp.outer, weight=1)
                height = self.workspace.winfo_height()
                self.workspace.sashpos(0, round(height - min(height * .30, 200 * self._display_scale)))
            else:
                self.workspace.forget(self.logp.outer)
            self._log_visible = visible
            self.log_toggle.configure(text="收起日志" if visible else "显示日志")

    def _toggle_log(self):
        self._log_override = not self._log_visible
        self._set_log_visible(self._log_override)

    # ---------------------------------------------------------------- AppContext
    def chip_family_id(self):
        return self.family.id

    def route(self):
        return self.route_bar.route()

    def is_connected(self) -> bool:
        return self.link.is_open

    def is_busy(self) -> bool:
        return self.runner.busy or self._task_active

    def run(self, items: Sequence, rows: Optional[Sequence[Optional[int]]] = None, confirm: bool = False) -> bool:
        # Keep the old keyword compatible with panel/plugin callers. Routine
        # actions execute directly; parameter validation remains in Runner.
        if not self.link.is_open:
            self.log("err", "未连接", "请先点右上角“连接”")
            return False
        if self.is_busy():
            self.log("info", "提示", "上一个任务还在运行")
            return False
        if getattr(self.seq, "rendering", False):
            self.log("info", "提示", "序列正在分批显示，完成后可运行")
            return False
        try:
            options = self.route_bar.options()
        except (OSError, ValueError, TypeError) as exc:
            messagebox.showerror("任务未启动", "参数无效：{}".format(exc))
            return False
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
        if not self.is_busy():
            self.log("info", "停止", "当前没有发送或等待任务；已发出的报文不能撤回")
            return
        self.runner.stop()
        self.seq.result_text.set("正在停止发送和软件等待…")
        self.conn.set_status("正在停止…")

    def log(self, tag, head, text) -> None:
        self.q.put(("log", tag, head, text))

    def sequence_add(self, item):
        self.seq.add(item)

    def sequence_replace_selected(self, item) -> bool:
        return self.seq.replace_selected(item)

    def sequence_set(self, items: List):
        if self.is_busy():
            return
        self.seq.set_items(items)

    def edit_item(self, item):
        self.nb.select(self.tab_templates)
        self.templates.load(item)

    def on_route_changed(self):
        self.seq.refresh()
        self.templates.update_preview()
        self.quick.update()

    def on_options_changed(self):
        # Pacing changes don't change a packet's bytes. Don't rebuild the
        # sequence or template preview on every keystroke in the interval box.
        self.quick.update()

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
            self.log("info", "切换芯片系列", "请先结束任务并断开连接，再切换芯片系列。")
            return
        try:
            family = get_family(family_id)
            backend = family.create_backend()
            link = backend.create_link(self._on_send, self._on_receive)
            runner = backend.create_runner(link, _QueueEvents(
                self.q, self._record_event, lambda: getattr(self.link, "is_simulation", False), self.control_q))
        except Exception as exc:
            self.chip_selector.selected.set(self.family.name)
            messagebox.showerror("芯片系列加载失败", str(exc))
            return
        self._save_settings()
        self.link.close()
        self.family, self.backend, self.link, self.runner = family, backend, link, runner
        self.settings = Settings(SETTINGS_FILE)
        self.settings.load()
        for child in self.surface.winfo_children():
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
        if quiet and not note:
            return
        hex_text = " ".join("{:02X}".format(value) for value in data[:120])
        self.q.put(("log", "send", "模拟发送" if getattr(self.link, "is_simulation", False) else "发送", "{}    {}".format(hex_text + (" ..." if len(data) > 120 else ""), note),
                    datetime.now().strftime("%H:%M:%S.%f")[:-3]))

    def _on_receive(self, kind: str, data: bytes):
        self._record_event("rx", kind=kind, hex=data.hex(" "))
        tag, head, text = self.backend.describe_receive(kind, data)
        if getattr(getattr(self, "link", None), "is_simulation", False):
            head = "模拟·" + head
        self.q.put(("log", tag, head, text)
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

    # ---------------------------------------------------------------- 主线程消息泵
    def _pump(self):
        self._pump_job = None
        deadline = time.monotonic() + .012
        pending_logs = []
        pending_progress = None
        preview_chars = 0
        processed = 0
        def flush_logs():
            if pending_logs:
                self.logp.append_many(pending_logs)
                pending_logs.clear()
        def flush_progress():
            nonlocal pending_progress
            if pending_progress is not None:
                self.seq.set_progress(*pending_progress)
                pending_progress = None
        try:
            while time.monotonic() < deadline and processed < 200:
                try:
                    m = self.control_q.get_nowait()
                except queue.Empty:
                    m = self.q.get_nowait()
                processed += 1
                k = m[0]
                if k == "log":
                    pending_logs.append(m[1:])
                    preview_chars += min(len(m[3]), MAX_PREVIEW_CHARS) + 64
                    if preview_chars >= 24_000:
                        break
                    continue
                flush_logs()
                if k == "progress":
                    pending_progress = (m[1], m[2])
                elif k == "status":
                    self.conn.set_status(m[1])
                elif k == "notify":
                    self.conn.set_status(m[1])
                elif k == "state":
                    self.seq.set_state(m[1], m[2])
                elif k == "result":
                    flush_progress()
                    self.seq.set_result(m[1])
                elif k == "finished":
                    flush_progress()
                    self._task_active = False
                    self.seq.set_busy(False)
                    getattr(self.route_bar, "set_locked", lambda locked: None)(False)
                    self.chip_selector.set_locked(self.is_connected())
        except queue.Empty:
            pass
        flush_logs()
        flush_progress()
        self._pump_job = self.root.after(16 if not self.q.empty() or not self.control_q.empty() else 50, self._pump)

    def _cancel_ui_jobs(self, event):
        if event.widget != self.root:
            return
        for name in ("_pump_job", "_layout_job", "_resize_job"):
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
            self.root.title(APP_NAME)
            self.chip_selector.set_locked(self.is_busy())
            self.log("info", "提示", "已断开")
            return
        if self.is_busy():
            self.log("info", "任务正在结束", "请等待当前任务停止后再连接。")
            return
        try:
            description = self.backend.open_link(self.link, self.conn)
        except (OSError, ValueError) as e:
            messagebox.showerror("连接失败", "{}\n\n{}".format(e, getattr(self.backend, "connection_hint", "")))
            return
        self.conn.set_connected(True)
        self.root.title(APP_NAME + (" · 离线模拟" if getattr(self.link, "is_simulation", False) else ""))
        probe = getattr(self.backend, "probe_link", None)
        if probe is not None and not getattr(self.link, "is_simulation", False):
            ok, detail = probe(self.link)
            self.conn.set_link_state(ok, detail)
            if not ok:
                self.log("err", "连接探测", detail)
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
