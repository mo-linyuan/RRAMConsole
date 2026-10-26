"""日志区。"""

from __future__ import annotations

import datetime
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ..theme import C, LOG_COLORS, card

MAX_LINES = 8000
MAX_PREVIEW_CHARS = 2048


class LogPanel:
    def __init__(self, parent, fonts, open_records=None):
        self.fonts = fonts
        self.open_records = open_records
        self.follow = tk.BooleanVar(value=True)
        self.outer, inner = card(parent, "日志", header=self._header)
        viewport = ttk.Frame(inner, style="Card.TFrame")
        viewport.pack(fill="both", expand=True)
        viewport.rowconfigure(0, weight=1)
        viewport.columnconfigure(0, weight=1)
        self.text = tk.Text(viewport, font=fonts.mono, wrap="none", bd=0, highlightthickness=0, bg=C["stripe"],
                            fg=C["text"], insertbackground=C["text"], selectbackground=C["selected"],
                            selectforeground=C["text"], height=10, padx=8, pady=6, spacing1=2, spacing3=2)
        vertical = ttk.Scrollbar(viewport, orient="vertical", command=self.text.yview)
        horizontal = ttk.Scrollbar(viewport, orient="horizontal", command=self.text.xview)
        self.text.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.text.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        for tag, color in LOG_COLORS.items():
            self.text.tag_config(tag, foreground=color)

    def _header(self, head):
        if self.open_records:
            ttk.Button(head, text="运行记录", command=self.open_records).pack(side="right", padx=(6, 0))
        ttk.Button(head, text="保存", command=self.save).pack(side="right")
        ttk.Button(head, text="清空", command=self.clear).pack(side="right", padx=6)
        ttk.Checkbutton(head, text="跟随最新", variable=self.follow, style="Card.TCheckbutton").pack(side="right", padx=6)
        for text, color in [("发送", C["accent"]), ("接收/核对", C["ok"]), ("芯片回包", C["warn"])]:
            tk.Label(head, text="● " + text, bg=C["card"], fg=color, font=self.fonts.small).pack(side="left", padx=(8, 0))

    def append(self, tag: str, head: str, text: str, timestamp=None) -> None:
        self.append_many([(tag, head, text, timestamp)])

    def append_many(self, entries) -> None:
        if not entries:
            return
        follow = self.follow.get() and self.text.yview()[1] >= .999999
        segments = []
        for entry in entries:
            tag, head, text = entry[:3]
            if len(text) > MAX_PREVIEW_CHARS:
                text = text[:MAX_PREVIEW_CHARS] + " …（长报文仅显示预览）"
            ts = entry[3] if len(entry) > 3 else None
            ts = ts or datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
            segments.extend((ts + "  ", ("ts",), "{}  {}\n".format(head, text),
                             (tag if tag in LOG_COLORS else "info",)))
        # One Tcl call and at most one scroll operation per batch.
        self.text.insert("end", *segments)
        lines = int(self.text.index("end-1c").split(".")[0])
        if lines > MAX_LINES:
            removed = max(2000, lines - MAX_LINES)
            self.text.delete("1.0", "{}.0".format(removed + 1))
        if follow:
            self.text.see("end")

    def clear(self) -> None:
        self.text.delete("1.0", "end")

    def save(self) -> None:
        path = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("文本", "*.txt")])
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(self.text.get("1.0", "end"))
            except OSError as exc:
                messagebox.showerror("保存失败", str(exc))
