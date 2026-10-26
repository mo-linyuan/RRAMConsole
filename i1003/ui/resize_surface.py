"""Keep expensive Tk child layout out of a burst of top-level size events."""
import tkinter as tk

from .theme import C


class ResizeSurface(tk.Frame):
    """Resize the content once the outer window has settled for 90 ms.

    Explicit pixel dimensions isolate descendants from every intermediate root
    resize. No OS hooks, mouse grabs, nested update calls or worker-thread Tk.
    """
    def __init__(self, root, width, height, settle_ms=90):
        super().__init__(root, bg=C["bg"], bd=0, highlightthickness=0)
        self._toplevel = root
        self._settle_ms = settle_ms
        self._resize_job = None
        self._target = self._applied = (width, height)
        self.place(x=0, y=0, width=width, height=height)
        self._binding = root.bind("<Configure>", self._queue_resize, add="+")
        self.bind("<Destroy>", self._dispose, add="+")

    def _queue_resize(self, event):
        if event.widget != self._toplevel or event.width <= 1 or event.height <= 1:
            return
        target = (event.width, event.height)
        if target == self._target:
            return
        self._target = target
        if self._resize_job is not None:
            self.after_cancel(self._resize_job)
            self._resize_job = None
        if target != self._applied:
            self._resize_job = self.after(self._settle_ms, self.flush)

    def flush(self):
        if self._resize_job is not None:
            self.after_cancel(self._resize_job)
            self._resize_job = None
        if self._target != self._applied:
            width, height = self._target
            self.place_configure(width=width, height=height)
            self._applied = self._target

    def _dispose(self, event):
        if event.widget != self:
            return
        if self._resize_job is not None:
            self.after_cancel(self._resize_job)
            self._resize_job = None
        self._toplevel.unbind("<Configure>", self._binding)
