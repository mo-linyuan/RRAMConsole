"""Instrument-style ttk controls, preserving native keyboard and mouse behavior."""

from __future__ import annotations

import math
import struct
import tkinter as tk
import zlib
from tkinter import ttk


def _photo(master, width, height, color, inside):
    """Small antialiased RGBA assets without a third-party imaging dependency."""
    rgb = bytes.fromhex(color.lstrip("#"))
    rows = bytearray()
    for y in range(height):
        rows.append(0)
        for x in range(width):
            coverage = sum(inside(x + (sx + .5) / 3, y + (sy + .5) / 3)
                           for sy in range(3) for sx in range(3))
            rows.extend(rgb + bytes([round(255 * coverage / 9)]))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(bytes(rows))) + chunk(b"IEND", b""))
    return tk.PhotoImage(master=master, data=png)


def apply_controls(style: ttk.Style, font, colors) -> None:
    root = style.master
    scale = float(root.tk.call("tk", "scaling")) / (96 / 72)
    blue, line = colors["accent"], colors["line"]
    field, panel = colors["field"], colors["card"]
    hover, selected, muted = colors["hover"], colors["selected"], colors["disabled"]
    for name in ("TCombobox", "TSpinbox"):
        style.configure(name, fieldbackground=field, background=field, foreground=colors["text"],
                        bordercolor=line, lightcolor=field, darkcolor=field, borderwidth=1,
                        relief="flat", padding=(5, 3), arrowcolor=colors["sub"])
        style.map(name, fieldbackground=[("disabled", panel), ("readonly", field)],
                  background=[("disabled", panel), ("active", hover), ("!disabled", field)],
                  bordercolor=[("focus", blue), ("active", colors["sub"])],
                  foreground=[("disabled", muted), ("!disabled", colors["text"])],
                  selectbackground=[("!focus", field)], selectforeground=[("!focus", colors["text"])])

    if not hasattr(root, "_console_control_images"):
        images = []
        arrow_width, arrow_height = round(23 * scale), round(16 * scale)

        def chevron(x, y):
            x, y = x / scale, y / scale
            # Distance to the two segments of a small, rounded V.
            for ax, ay, bx, by in ((7.5, 6, 11.5, 10), (11.5, 10, 15.5, 6)):
                dx, dy = bx - ax, by - ay
                t = min(1, max(0, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy)))
                if math.hypot(x - ax - t * dx, y - ay - t * dy) <= .85:
                    return True
            return False

        arrows = [_photo(root, arrow_width, arrow_height, c, chevron)
                  for c in (colors["sub"], blue, muted)]
        images.extend(arrows)
        style.element_create("Console.Combobox.downarrow", "image", arrows[0],
                             ("disabled", arrows[2]), ("active", arrows[1]), ("focus", arrows[1]),
                             sticky="e")

        # Nine-slice image elements stretch the center while retaining rounded caps.
        for orientation in ("Vertical", "Horizontal"):
            thickness, length = max(10, round(11 * scale)), round(32 * scale)
            width, height = (thickness, length) if orientation == "Vertical" else (length, thickness)

            def capsule(x, y, w=width, h=height, vertical=orientation == "Vertical"):
                cross, along = (x, y) if vertical else (y, x)
                cross_size, along_size = (w, h) if vertical else (h, w)
                radius = (cross_size - 4 * scale) / 2
                center = cross_size / 2
                cap = min(along_size - 2 * scale - radius, max(2 * scale + radius, along))
                return math.hypot(cross - center, along - cap) <= radius

            thumbs = [_photo(root, width, height, color, capsule)
                      for color in ("#C4CFDE", "#97ACC9", blue, "#E7ECF3")]
            images.extend(thumbs)
            cap = round(thickness / 2)
            border = (0, cap, 0, cap) if orientation == "Vertical" else (cap, 0, cap, 0)
            style.element_create("Console.{}.thumb".format(orientation), "image", thumbs[0],
                                 ("disabled", thumbs[3]), ("pressed", thumbs[2]), ("active", thumbs[1]),
                                 border=border, sticky="nswe")
        root._console_control_images = images

    if not hasattr(root, "_console_surface_images"):
        images = []
        w, h = round(44 * scale), round(28 * scale)
        radius = 2 * scale

        def rounded(x, y, inset=0):
            cx = min(w - radius, max(radius, x))
            cy = min(h - radius, max(radius, y))
            return (inset <= x <= w-inset and inset <= y <= h-inset
                    and math.hypot(x-cx, y-cy) <= radius-inset)

        def surface(border, fill):
            image = _photo(root, w, h, border, rounded)
            inner = _photo(root, w, h, fill, lambda x, y: rounded(x, y, max(1, scale * .7)))
            image.tk.call(str(image), "copy", str(inner), "-compositingrule", "overlay")
            images.append(image)
            return image

        for name, palette in (
            ("Button", ((line, panel), ("#9EB4D3", hover), (blue, selected),
                        ("#E7ECF3", panel), (blue, panel))),
            ("Primary", (("#2563EB", "#2563EB"), ("#3478F6", "#3478F6"), ("#1D4ED8", "#1D4ED8"),
                         (line, selected), ("#A5C8FF", "#2563EB"))),
        ):
            normal, hover_image, pressed, disabled, focus = [surface(*pair) for pair in palette]
            style.element_create("Console.{}.surface".format(name), "image", normal,
                                 ("disabled", disabled), ("pressed", pressed), ("active", hover_image), ("focus", focus),
                                 border=round(8*scale), sticky="nswe")
        inactive = surface(panel, panel)
        selected_tab = surface(blue, selected)
        style.element_create("Console.Tab.surface", "image", inactive, ("selected", selected_tab),
                             border=round(8*scale), sticky="nswe")
        root._console_surface_images = images

    for name, element in (("TButton", "Button"), ("Accent.TButton", "Primary")):
        style.layout(name, [("Console.{}.surface".format(element), {"sticky": "nswe", "children": [
            ("Button.padding", {"sticky": "nswe", "children": [
                ("Button.label", {"sticky": "nswe"})]})]})])
    # Image corners must reveal the surface behind the button, not a solid blue widget rectangle.
    style.configure("Accent.TButton", background=colors["card"])
    style.map("Accent.TButton", background=[("!disabled", colors["card"]), ("disabled", colors["card"])])
    style.configure("Toolbar.Accent.TButton", background=colors["bg"])
    style.map("Toolbar.Accent.TButton", background=[("!disabled", colors["bg"]), ("disabled", colors["bg"])])
    style.layout("Card.TNotebook.Tab", [("Console.Tab.surface", {"sticky": "nswe", "children": [
        ("Notebook.padding", {"sticky": "nswe", "children": [
            ("Notebook.label", {"sticky": "nswe"})]})]})])

    if not hasattr(root, "_console_check_images"):
        size = max(16, round(16 * scale))

        def box(x, y):
            # A slightly rounded square, with a transparent one-pixel outer margin.
            x, y = x / scale, y / scale
            cx, cy = min(12, max(4, x)), min(12, max(4, y))
            return math.hypot(x - cx, y - cy) <= 3

        def mark(x, y):
            x, y = x / scale, y / scale
            for ax, ay, bx, by in ((4.2, 8, 6.8, 10.6), (6.8, 10.6, 11.8, 5.4)):
                dx, dy = bx - ax, by - ay
                t = min(1, max(0, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy)))
                if math.hypot(x - ax - t * dx, y - ay - t * dy) <= .95:
                    return True
            return False

        def check_image(border, fill, tick=False):
            image = _photo(root, size, size, border, box)
            inner = _photo(root, size, size, fill, lambda x, y: box(
                (x / scale - 8) * 1.2 * scale + 8 * scale,
                (y / scale - 8) * 1.2 * scale + 8 * scale))
            image.tk.call(str(image), "copy", str(inner), "-compositingrule", "overlay")
            if tick:
                overlay = _photo(root, size, size, "#FFFFFF", mark)
                image.tk.call(str(image), "copy", str(overlay), "-compositingrule", "overlay")
            return image

        checks = [check_image("#ACBACD", field), check_image("#16A34A", "#16A34A", True),
                  check_image(blue, hover), check_image("#15803D", "#15803D", True),
                  check_image(line, panel), check_image("#ACCBB7", "#ACCBB7", True)]
        style.element_create("Console.Checkbutton.indicator", "image", checks[0],
                             ("disabled", "selected", checks[5]), ("disabled", checks[4]),
                             ("selected", "active", checks[3]), ("selected", checks[1]), ("active", checks[2]),
                             sticky="w", padding=(0, 0, round(6 * scale), 0))
        root._console_check_images = checks

    for name in ("TCheckbutton", "Card.TCheckbutton", "Bar.TCheckbutton"):
        style.layout(name, [("Checkbutton.padding", {"sticky": "nswe", "children": [
            ("Console.Checkbutton.indicator", {"side": "left", "sticky": "w"}),
            ("Checkbutton.focus", {"side": "left", "sticky": "nswe", "children": [
                ("Checkbutton.label", {"sticky": "nswe"})]})]})])

    style.layout("TCombobox", [("Combobox.field", {"sticky": "nswe", "children": [
        ("Console.Combobox.downarrow", {"side": "right", "sticky": "ns"}),
        ("Combobox.padding", {"expand": "1", "sticky": "nswe", "children": [
            ("Combobox.textarea", {"sticky": "nswe"})]})]})])
    style.configure("TMenubutton", background=panel, foreground=colors["text"],
                    bordercolor=line, lightcolor=panel, darkcolor=panel, borderwidth=1,
                    relief="flat", padding=(8, 4))
    style.map("TMenubutton", background=[("active", hover)],
              bordercolor=[("active", blue)])
    style.layout("TMenubutton", [("Menubutton.border", {"sticky": "nswe", "children": [
        ("Console.Combobox.downarrow", {"side": "right", "sticky": "ns"}),
        ("Menubutton.padding", {"sticky": "we", "children": [
            ("Menubutton.label", {"side": "left", "sticky": "w"})]})]})])
    style.configure("ComboboxPopdownFrame", background=field, bordercolor=line,
                    lightcolor=line, darkcolor=line, borderwidth=1, relief="solid")

    for orientation, sticky in (("Vertical", "ns"), ("Horizontal", "we")):
        name = orientation + ".TScrollbar"
        style.configure(name, background=panel, troughcolor=panel, borderwidth=0,
                        bordercolor=panel, lightcolor=panel, darkcolor=panel, relief="flat")
        style.layout(name, [(orientation + ".Scrollbar.trough", {"sticky": sticky, "children": [
            ("Console.{}.thumb".format(orientation), {"expand": "1", "sticky": "nswe"})]})])

    # ttk's native popup contains a classic Listbox, styled through the option DB.
    for option, value in {"background": field, "foreground": colors["text"],
                          "selectBackground": selected, "selectForeground": colors["text"],
                          "font": font, "relief": "flat", "borderWidth": 0,
                          "highlightThickness": 1, "highlightBackground": line,
                          "selectBorderWidth": 0, "activeStyle": "none"}.items():
        root.option_add("*TCombobox*Listbox." + option, value)
