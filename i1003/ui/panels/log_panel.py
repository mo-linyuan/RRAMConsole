"""日志区。"""

from __future__ import annotations

import datetime
import tkinter as tk
from tkinter import filedialog, ttk

from ..theme import C, LOG_COLORS, card

MAX_LINES = 8000


class LogPanel:
    def __init__(self, parent, fonts):
        self.fonts = fonts
        self.outer, inner = card(parent, "日志", header=self._header)
        self.text = tk.Text(inner, font=fonts.mono, wrap="none", bd=0, highlightthickness=0, bg="white",
                            fg=C["text"], height=10, padx=6, pady=4)
        sb = ttk.Scrollbar(inner, command=self.text.yview)
        self.text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.text.pack(fill="both", expand=True)
        for tag, color in LOG_COLORS.items():
            self.text.tag_config(tag, foreground=color)

    def _header(self, head):
        ttk.Button(head, text="保存", command=self.save).pack(side="right")
        ttk.Button(head, text="清空", command=self.clear).pack(side="right", padx=6)
        for txt, color in [("芯片回包", C["warn"]), ("接收/核对", C["ok"]), ("发送", C["accent"])]:
            tk.Label(head, text="● " + txt, bg=C["card"], fg=color, font=self.fonts.small).pack(side="right", padx=6)

    def append(self, tag: str, head: str, text: str) -> None:
        ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self.text.insert("end", ts + "  ", "ts")
        self.text.insert("end", "{}  {}\n".format(head, text), tag if tag in LOG_COLORS else "info")
        if int(self.text.index("end-1c").split(".")[0]) > MAX_LINES:
            self.text.delete("1.0", "2000.0")
        self.text.see("end")

    def clear(self) -> None:
        self.text.delete("1.0", "end")

    def save(self) -> None:
        path = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("文本", "*.txt")])
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.text.get("1.0", "end"))
