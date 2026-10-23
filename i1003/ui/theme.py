"""界面外观：颜色、字体、ttk 样式、卡片容器。"""

from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

C = dict(bg="#F3F4F7", card="#FFFFFF", line="#E3E6EC", text="#1F2328", sub="#6B7280",
         accent="#2563EB", accent_d="#1D4ED8", ok="#16A34A", warn="#D97706", err="#DC2626", stripe="#F8FAFC")

LOG_COLORS = {"send": C["accent"], "recv": C["ok"], "ok": C["ok"], "chip": C["warn"], "err": C["err"],
              "info": C["sub"], "ts": "#9CA3AF"}


class Fonts:
    def __init__(self):
        fam = set(tkfont.families())
        ui = next((f for f in ("Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC",
                               "WenQuanYi Micro Hei") if f in fam), "TkDefaultFont")
        mono = next((f for f in ("Consolas", "Cascadia Mono", "Menlo", "DejaVu Sans Mono") if f in fam), "TkFixedFont")
        self.ui, self.bold, self.title = (ui, 10), (ui, 10, "bold"), (ui, 13, "bold")
        self.mono, self.small = (mono, 10), (ui, 9)
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
            try:
                tkfont.nametofont(name).configure(family=ui, size=10)
            except tk.TclError:
                pass


def apply_style(f: Fonts) -> None:
    s = ttk.Style()
    s.theme_use("clam")
    s.configure(".", background=C["bg"], foreground=C["text"], font=f.ui, borderwidth=0)
    s.configure("Card.TFrame", background=C["card"])
    s.configure("Card.TLabel", background=C["card"], foreground=C["text"])
    s.configure("Sub.TLabel", background=C["card"], foreground=C["sub"], font=f.small)
    s.configure("Sec.TLabel", background=C["card"], foreground=C["accent"], font=f.small)
    s.configure("Title.TLabel", background=C["card"], foreground=C["text"], font=f.bold)
    s.configure("Bar.TLabel", background=C["bg"], foreground=C["sub"])
    s.configure("App.TLabel", background=C["bg"], foreground=C["text"], font=f.title)
    s.configure("TButton", background=C["card"], foreground=C["text"], bordercolor=C["line"], lightcolor=C["card"],
                darkcolor=C["card"], padding=(10, 4), relief="flat", borderwidth=1, width=-4)
    s.map("TButton", background=[("active", "#EEF2F7"), ("disabled", C["bg"])], foreground=[("disabled", "#A0A7B4")])
    s.configure("Accent.TButton", background=C["accent"], foreground="white", bordercolor=C["accent"],
                lightcolor=C["accent"], darkcolor=C["accent"])
    s.map("Accent.TButton", background=[("active", C["accent_d"]), ("disabled", "#93B4F5")],
          foreground=[("disabled", "white")])
    s.configure("Danger.TButton", foreground=C["err"])
    for w in ("TEntry", "TCombobox", "TSpinbox"):
        s.configure(w, fieldbackground="white", bordercolor=C["line"], lightcolor=C["line"], darkcolor=C["line"],
                    padding=3, arrowsize=13)
    for w, bg in (("Card.TCheckbutton", C["card"]), ("Bar.TCheckbutton", C["bg"])):
        s.configure(w, background=bg)
        s.map(w, background=[("active", bg)])
    s.configure("Treeview", background="white", fieldbackground="white", rowheight=28, bordercolor=C["line"], font=f.ui)
    s.configure("Treeview.Heading", background=C["stripe"], foreground=C["sub"], font=f.small, relief="flat",
                padding=(6, 5))
    s.map("Treeview", background=[("selected", "#DBEAFE")], foreground=[("selected", C["text"])])
    s.configure("TProgressbar", background=C["accent"], troughcolor=C["line"], bordercolor=C["line"],
                lightcolor=C["accent"], darkcolor=C["accent"], thickness=6)
    s.configure("TPanedwindow", background=C["bg"])
    s.configure("Card.TNotebook", background=C["card"], borderwidth=0)
    s.configure("Card.TNotebook.Tab", background=C["card"], foreground=C["sub"], padding=(14, 6), borderwidth=0,
                font=f.bold)
    s.map("Card.TNotebook.Tab", background=[("selected", C["card"])], foreground=[("selected", C["accent"])])


def card(parent, title: str = "", header=None):
    """白底卡片。返回 (外框, 内容区)；header(frame) 可在标题行右侧放按钮。"""
    outer = tk.Frame(parent, bg=C["line"], bd=0)
    inner = ttk.Frame(outer, style="Card.TFrame", padding=(14, 10))
    inner.pack(fill="both", expand=True, padx=1, pady=1)
    if title:
        head = ttk.Frame(inner, style="Card.TFrame")
        head.pack(fill="x", pady=(0, 8))
        ttk.Label(head, text=title, style="Title.TLabel").pack(side="left")
        if header:
            header(head)
    return outer, inner


def info_box(parent, fonts: Fonts, mono: bool = False, wrap: int = 600) -> tk.Label:
    box = tk.Frame(parent, bg=C["stripe"], highlightthickness=1, highlightbackground=C["line"])
    box.pack(fill="x", pady=(8, 8))
    lbl = tk.Label(box, text="", bg=C["stripe"], fg=C["text"], font=fonts.mono if mono else fonts.ui, anchor="w",
                   justify="left", padx=10, pady=7, wraplength=wrap)
    lbl.pack(fill="x")
    return lbl
