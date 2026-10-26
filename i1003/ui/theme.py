"""界面外观：颜色、字体、ttk 样式、卡片容器。"""

from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

from .controls import apply_controls

C = dict(bg="#F4F6F9", card="#FFFFFF", line="#DCE2EB", text="#202A38", sub="#68788D",
         accent="#2563EB", accent_d="#1D4ED8", ok="#15965B", warn="#AD7114", err="#D63D54",
         stripe="#F6F8FB", field="#FFFFFF", hover="#F0F4FA", selected="#E8F0FF", disabled="#97A3B3")

LOG_COLORS = {"send": C["accent"], "recv": C["ok"], "ok": C["ok"], "chip": C["warn"], "err": C["err"],
              "info": C["sub"], "ts": "#8492A5"}


class Fonts:
    def __init__(self):
        fam = set(tkfont.families())
        ui = next((f for f in ("Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC",
                               "WenQuanYi Micro Hei") if f in fam), "TkDefaultFont")
        mono = next((f for f in ("Consolas", "Cascadia Mono", "Menlo", "DejaVu Sans Mono") if f in fam), "TkFixedFont")
        self.ui, self.bold, self.title = (ui, 10), (ui, 10, "bold"), (ui, 13, "bold")
        self.mono, self.small = (mono, 10), (ui, 9)
        tkfont.nametofont("TkFixedFont").configure(family=mono, size=10)
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
    s.configure("Sec.TLabel", background=C["card"], foreground=C["accent"], font=f.bold)
    s.configure("Title.TLabel", background=C["card"], foreground=C["text"], font=f.bold)
    s.configure("Bar.TLabel", background=C["bg"], foreground=C["sub"])
    s.configure("App.TLabel", background=C["bg"], foreground=C["text"], font=f.title)
    s.configure("TButton", background=C["card"], foreground=C["text"], bordercolor=C["line"], lightcolor=C["card"],
                darkcolor=C["card"], padding=(8, 3), relief="flat", borderwidth=1, width=-4)
    s.map("TButton", background=[("active", C["hover"]), ("disabled", C["bg"])], foreground=[("disabled", C["disabled"])])
    s.configure("Accent.TButton", background=C["accent"], foreground="white", bordercolor=C["accent"],
                lightcolor=C["accent"], darkcolor=C["accent"])
    s.map("Accent.TButton", background=[("active", C["accent_d"]), ("disabled", C["selected"])],
          foreground=[("disabled", C["sub"])])
    s.configure("Danger.TButton", foreground=C["err"])
    s.configure("Quiet.TButton", foreground=C["sub"])
    for w in ("TEntry", "TCombobox", "TSpinbox"):
        s.configure(w, fieldbackground=C["field"], background=C["field"], foreground=C["text"],
                    insertcolor=C["text"], selectbackground=C["selected"], selectforeground=C["text"],
                    bordercolor=C["line"], lightcolor=C["field"], darkcolor=C["field"], padding=3, arrowsize=13)
    s.configure("TEntry", font=f.mono)
    s.configure("TSpinbox", font=f.mono)
    s.map("TEntry", bordercolor=[("focus", C["accent"]), ("active", C["sub"])])
    for w, bg in (("Card.TCheckbutton", C["card"]), ("Bar.TCheckbutton", C["bg"])):
        s.configure(w, background=bg)
        s.map(w, background=[("active", bg)])
    line_height = tkfont.Font(font=f.ui).metrics("linespace")
    s.configure("Treeview", background=C["card"], fieldbackground=C["card"], rowheight=max(25, line_height + 6),
                bordercolor=C["card"], lightcolor=C["card"], darkcolor=C["card"], borderwidth=0, font=f.ui)
    s.configure("Treeview.Heading", background=C["stripe"], foreground=C["sub"], font=f.small, relief="flat",
                padding=(6, 4))
    s.map("Treeview", background=[("selected", C["selected"])], foreground=[("selected", C["text"])])
    s.configure("TProgressbar", background=C["accent"], troughcolor=C["line"], bordercolor=C["line"],
                lightcolor=C["accent"], darkcolor=C["accent"], thickness=6)
    s.configure("TPanedwindow", background=C["bg"])
    s.configure("Sash", background=C["bg"], lightcolor=C["bg"], bordercolor=C["bg"], sashthickness=6)
    s.layout("Horizontal.Sash", [("Sash.hsash", {"sticky": "nswe"})])
    s.layout("Vertical.Sash", [("Sash.vsash", {"sticky": "nswe"})])
    s.configure("Card.TNotebook", background=C["card"], borderwidth=0, bordercolor=C["card"],
                lightcolor=C["card"], darkcolor=C["card"])
    s.configure("Card.TNotebook.Tab", background=C["card"], foreground=C["sub"], padding=(12, 5), borderwidth=0,
                font=f.bold)
    s.map("Card.TNotebook.Tab", background=[("selected", C["card"])], foreground=[("selected", C["accent"])])
    apply_controls(s, f.ui, C)
    _style_titlebar(s.master)


def _style_titlebar(root):
    """Use the native light Windows caption when supported."""
    import sys
    if sys.platform != "win32":
        return

    def apply():
        import ctypes
        try:
            hwnd = ctypes.windll.user32.GetAncestor(root.winfo_id(), 2)
            enabled = ctypes.c_int(0)
            for attribute in (20, 19):
                result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attribute, ctypes.byref(enabled), ctypes.sizeof(enabled))
                if result == 0:
                    break
        except (AttributeError, OSError, tk.TclError):
            pass
    job = root.after_idle(apply)
    def dispose(event):
        if event.widget == root:
            root.after_cancel(job)
    root.bind("<Destroy>", dispose, add="+")


class CardFrame(tk.Frame):
    """Native geometry container: no full-panel Canvas redraw on each drag."""

    def __init__(self, parent):
        super().__init__(parent, bg=C["card"], bd=0, highlightthickness=1, highlightbackground=C["line"])
        inset = max(2, round(3 * self.winfo_fpixels("1i") / 96))
        self.content = ttk.Frame(self, style="Card.TFrame", padding=(10, 6))
        self.content.pack(fill="both", expand=True, padx=inset, pady=inset)


def bind_wrap(label, source=None, padding=0):
    """Coalesce width changes; height-only events must not reflow text again."""
    source = source or label
    pending = None
    latest = applied = None

    def apply():
        nonlocal pending, applied
        pending = None
        if latest != applied:
            applied = latest
            label.configure(wraplength=latest)

    def resize(event):
        nonlocal pending, latest
        width = max(100, event.width - padding)
        if width == latest:
            return
        latest = width
        if pending is None:
            pending = source.after(16, apply)

    def destroy(event):
        nonlocal pending
        if event.widget == source and pending is not None:
            source.after_cancel(pending)
            pending = None

    source.bind("<Configure>", resize, add="+")
    source.bind("<Destroy>", destroy, add="+")


class FormViewport(ttk.Frame):
    """Scroll long forms in a short window without displacing their action buttons."""

    def __init__(self, parent, min_width=0):
        super().__init__(parent, style="Card.TFrame")
        self._minimum_width = min_width
        self.canvas = tk.Canvas(self, bg=C["card"], highlightthickness=0, bd=0, width=1, height=1)
        self.bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.horizontal = ttk.Scrollbar(self, orient="horizontal", command=self.canvas.xview)
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.bar.grid(row=0, column=1, sticky="ns")
        self.horizontal.grid(row=1, column=0, sticky="ew")
        self.content = ttk.Frame(self.canvas, style="Card.TFrame")
        self._window = self.canvas.create_window(0, 0, anchor="nw", window=self.content)
        self._content_width = None
        self._region = None
        self.canvas.configure(yscrollcommand=self.bar.set, xscrollcommand=self.horizontal.set)
        self.canvas.bind("<Configure>", self._fit_content)
        self.content.bind("<Configure>", self._update_region)
        self._tag = "FormViewport" + str(id(self))
        self.bind_class(self._tag, "<MouseWheel>", self._wheel)
        self.bind_class(self._tag, "<Button-4>", lambda e: self._wheel(e, -3))
        self.bind_class(self._tag, "<Button-5>", lambda e: self._wheel(e, 3))
        self._bindings_job = self.after_idle(self._bind_children)
        self.bind("<Destroy>", self._destroy_bindings, add="+")

    def _fit_content(self, event=None):
        available = self.canvas.winfo_width()
        # Wrapped text changes its requested width as the viewport resizes.
        # Use an explicit form minimum to avoid a geometry feedback loop.
        needed = self._minimum_width
        target = max(available, needed)
        if target != self._content_width:
            self._content_width = target
            self.canvas.itemconfigure(self._window, width=target)

    def _update_region(self, event=None):
        region = self.canvas.bbox("all")
        if region != self._region:
            self._region = region
            self.canvas.configure(scrollregion=region)

    def _bind_children(self):
        if self._bindings_job is not None:
            self.after_cancel(self._bindings_job)
        self._bindings_job = None
        def visit(widget):
            if self._tag not in widget.bindtags():
                widget.bindtags((self._tag,) + widget.bindtags())
            for child in widget.winfo_children():
                visit(child)
        visit(self.canvas)

    def _destroy_bindings(self, event):
        if event.widget == self:
            if self._bindings_job is not None:
                self.after_cancel(self._bindings_job)
                self._bindings_job = None
            for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                self.unbind_class(self._tag, sequence)

    def _wheel(self, event, units=None):
        first, last = self.canvas.yview()
        if last-first < .999:
            self.canvas.yview_scroll(units if units is not None else (-3 if event.delta > 0 else 3), "units")
        return "break"


def card(parent, title: str = "", header=None):
    """面板容器。返回 (外框, 内容区)；header(frame) 可在标题行右侧放按钮。"""
    outer = CardFrame(parent)
    inner = outer.content
    if title:
        head = ttk.Frame(inner, style="Card.TFrame")
        head.pack(fill="x", pady=(0, 4))
        ttk.Label(head, text=title, style="Title.TLabel").pack(side="left")
        if header:
            header(head)
    return outer, inner


def info_box(parent, fonts: Fonts, mono: bool = False, wrap: int = 600) -> tk.Label:
    box = tk.Frame(parent, bg=C["stripe"], highlightthickness=0)
    box.pack(fill="x", pady=4)
    lbl = tk.Label(box, text="", bg=C["stripe"], fg=C["text"], font=fonts.mono if mono else fonts.ui, anchor="w",
                   justify="left", padx=8, pady=6, wraplength=wrap)
    lbl.pack(fill="x")
    return lbl
