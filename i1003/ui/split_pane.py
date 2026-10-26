"""Native Tk splitters; no Python mouse grabs or motion handlers."""
import tkinter as tk

from .theme import C


class SplitPane(tk.PanedWindow):
    """Native non-opaque sash dragging with the existing layout API.

    Tk owns pointer tracking, proxy painting and button release. Keep sashpos()
    and add(weight=...) compatible with the existing layout code.
    """
    def __init__(self, parent, **kwargs):
        vertical = str(kwargs.get("orient", "horizontal")) == "vertical"
        super().__init__(parent, bg=C["bg"], bd=0, relief="flat", opaqueresize=False,
                         sashwidth=8, sashpad=0, sashrelief="flat", showhandle=False,
                         sashcursor="sb_v_double_arrow" if vertical else "sb_h_double_arrow",
                         proxybackground=C["accent"], proxyborderwidth=0, proxyrelief="flat", **kwargs)
        self._vertical = vertical

    def add(self, child, **kwargs):
        weight = kwargs.pop("weight", 1)
        kwargs.setdefault("stretch", "always" if weight else "never")
        kwargs.setdefault("minsize", 80)
        super().add(child, **kwargs)

    def sashpos(self, index, position=None):
        if position is not None:
            if self._vertical:
                self.sash_place(index, 0, int(position))
            else:
                self.sash_place(index, int(position), 0)
        return self.sash_coord(index)[1 if self._vertical else 0]
