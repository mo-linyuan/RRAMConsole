"""报文模板：左边模板树，右边自动生成的表单和报文预览。"""

from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from tkinter import messagebox, ttk
from typing import Dict, Optional

from ...model.items import Item, hexs
from .. import templates as T
from ..context import AppContext
from ..theme import C, FormViewport, info_box, bind_wrap
from ..split_pane import SplitPane


class TemplatePanel:
    def __init__(self, parent, ctx: AppContext):
        self.ctx = ctx
        self.cur: Optional[T.Template] = None
        self.vars: Dict[str, tk.StringVar] = {}
        self._build(parent)
        self.select("写验证脉宽 reg[8]")

    def _build(self, p):
        wrap = SplitPane(p, orient="horizontal")
        wrap.pack(fill="both", expand=True)
        self.split = wrap
        navigation = ttk.Frame(wrap, style="Card.TFrame")
        navigation.rowconfigure(0, weight=1)
        navigation.columnconfigure(0, weight=1)
        wrap.add(navigation, weight=0)
        scale = p.winfo_fpixels("1i") / 96
        self._scale = scale
        indent = round(14 * scale)
        ttk.Style(p).configure("Template.Treeview", indent=indent)
        self.tree = ttk.Treeview(navigation, show="tree", selectmode="browse", height=14,
                                 style="Template.Treeview")
        font = tkfont.Font(root=p, font=self.ctx.fonts.ui)
        tree_width = max(font.measure(t.name) for t in T.TEMPLATES) + 2 * indent + round(24 * scale)
        self.tree.column("#0", width=tree_width, stretch=False)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(navigation, orient="vertical", command=self.tree.yview)
        horizontal = ttk.Scrollbar(navigation, orient="horizontal", command=self.tree.xview)
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        for g, ts in T.groups():
            gid = self.tree.insert("", "end", text=g, open=True)
            for t in ts:
                self.tree.insert(gid, "end", iid="tpl::" + t.name, text=t.name)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        right = ttk.Frame(wrap, style="Card.TFrame", padding=(10, 0, 0, 0))
        wrap.add(right, weight=1)
        initialized = False

        def initialize_width(event):
            nonlocal initialized
            if not initialized and event.width > 100:
                initialized = True
                wrap.sashpos(0, min(tree_width + vertical.winfo_reqwidth(), event.width // 2))

        wrap.bind("<Configure>", initialize_width)
        btns = ttk.Frame(right, style="Card.TFrame", padding=(0, 6, 0, 0))
        btns.pack(side="bottom", fill="x")
        self.actions = []
        for text, command, style, pad in [("直接发送", self._send, "Accent.TButton", 0),
                                          ("加入序列", self._add, "TButton", 0),
                                          ("替换选中", self._replace, "TButton", 0)]:
            button = ttk.Button(btns, text=text, style=style, command=command)
            button.pack(side="left", padx=pad)
            self.actions.append(button)
        self.details_viewport = FormViewport(right, min_width=round(320 * scale))
        self.details_viewport.pack(fill="both", expand=True)
        content = self.details_viewport.content
        self.lbl_name = ttk.Label(content, text="", style="Title.TLabel")
        self.lbl_name.pack(anchor="w")
        self.form = ttk.Frame(content, style="Card.TFrame", padding=(0, 4))
        self.form.pack(fill="x")
        self.form.columnconfigure(1, weight=1)
        self.lbl_hint = ttk.Label(content, text="", style="Sub.TLabel", wraplength=360, justify="left")
        self.lbl_hint.pack(anchor="w")
        self.lbl_prev = info_box(content, self.ctx.fonts, mono=True, wrap=380)
        bind_wrap(self.lbl_name, right, round(24 * scale))
        bind_wrap(self.lbl_hint, right, round(24 * scale))
        bind_wrap(self.lbl_prev, right, round(24 * scale) + 20)

    def _on_select(self, _e=None):
        sel = self.tree.selection()
        if sel and sel[0].startswith("tpl::"):
            self.select(sel[0][5:], select_tree=False)

    def select(self, name: str, values: Optional[Dict[str, str]] = None, select_tree: bool = True) -> None:
        t = T.BY_NAME[name]
        if t.name == "写 WRITEB 指令":
            values = t.values(values)
            values.update(start=values.pop("at"), count="1", stop="否")
            t = T.BY_NAME["写入 WRITEB 指令"]
        name = t.name
        self.cur = t
        for button in self.actions:
            button.configure(state="normal")
        if select_tree:
            self.tree.selection_set("tpl::" + name)
            self.tree.see("tpl::" + name)
        self.lbl_name.config(text=name)
        for w in self.form.winfo_children():
            w.destroy()
        self.vars = {}
        vals = t.values(values)
        for r, f in enumerate(t.fields):
            ttk.Label(self.form, text=f.label, style="Card.TLabel", wraplength=round(150 * self._scale),
                      justify="left").grid(row=r, column=0, sticky="w", pady=2, padx=(0, 8))
            var = tk.StringVar(value=vals[f.key])
            if f.kind == "choice":
                w = ttk.Combobox(self.form, textvariable=var, values=f.options, state="readonly", width=20)
            elif f.kind == "int":
                w = ttk.Spinbox(self.form, textvariable=var, from_=f.options[0], to=f.options[1], width=10,
                                command=self.update_preview)
            else:
                w = ttk.Entry(self.form, textvariable=var, width=40 if f.key == "hex" else 22)
            w.grid(row=r, column=1, sticky="ew", pady=2)
            var.trace_add("write", lambda *a: self.update_preview())
            self.vars[f.key] = var
        if not t.fields:
            ttk.Label(self.form, text="不需要填写，直接发送或加入序列。", style="Sub.TLabel").grid(row=0, column=0, sticky="w")
        self.update_preview()
        self.details_viewport._bind_children()
        self.details_viewport.canvas.yview_moveto(0)

    def load(self, it: Item) -> None:
        """序列里双击时载入：模板生成的条目回到原模板；其他条目以原始 HEX 打开。"""
        tpl = it.meta.get("tpl") if it.meta else None
        if tpl in T.BY_NAME:
            self.select(tpl, it.meta.get("vals"))
            return
        if it.kind not in ("pkg", "fpga", "raw"):
            # A diagnostic or multi-command item must never become only its
            # first raw frame, which would discard checks or later commands.
            self.cur = None
            for child in self.form.winfo_children():
                child.destroy()
            self.vars = {}
            self.lbl_name.configure(text="组合步骤 · 只读预览")
            self.lbl_hint.configure(text="写入范围和次数请在左侧配置；诊断步骤请在右侧诊断菜单载入。")
            self.lbl_prev.configure(text=it.summary(self.ctx.route()))
            for button in self.actions:
                button.configure(state="disabled")
            return
        frames = it.frames(self.ctx.route(), 1)
        if frames:
            self.select("原始 HEX", {"hex": hexs(frames[0][0])})

    def _values(self) -> Dict[str, str]:
        return {k: v.get() for k, v in self.vars.items()}

    def build(self) -> Item:
        if self.cur is None:
            raise ValueError("请选择一个可编辑的报文模板")
        return self.cur.make(self._values())

    def update_preview(self) -> None:
        if not self.cur or not hasattr(self, "lbl_prev"):
            return
        try:
            it = self.build()
            self.lbl_hint.config(text=self.cur.describe(self._values()))
            self.lbl_prev.config(text=it.summary(self.ctx.route()), fg=C["text"])
        except (ValueError, KeyError, IndexError) as exc:
            self.lbl_prev.config(text=str(exc) or "填写内容格式不对", fg=C["err"])

    def _item_or_warn(self) -> Optional[Item]:
        try:
            return self.build()
        except (ValueError, KeyError, IndexError) as e:
            messagebox.showerror("参数有误", str(e))
            return None

    def _add(self):
        it = self._item_or_warn()
        if it:
            self.ctx.sequence_add(it)

    def _send(self):
        it = self._item_or_warn()
        if it:
            # No sequence row belongs to this standalone template operation.
            self.ctx.run([it], [None])

    def _replace(self):
        it = self._item_or_warn()
        if it and not self.ctx.sequence_replace_selected(it):
            self.ctx.log("info", "提示", "先在序列里选中一条")
