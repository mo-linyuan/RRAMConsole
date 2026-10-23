"""Application window and taskbar identity."""

from pathlib import Path
import sys
import tkinter as tk


ASSETS = Path(__file__).resolve().parent / "assets"


def set_app_icon(root: tk.Tk) -> None:
    icons = [tk.PhotoImage(master=root, file=str(ASSETS / "app-{}.png".format(size)))
             for size in (16, 32, 48, 128, 256)]
    root.iconphoto(True, *icons)
    root._app_icons = icons
    if sys.platform == "win32":
        # The native multi-size ICO supplies both the caption and taskbar icons.
        # Apply it last so iconphoto does not replace Windows' size selection.
        icon_path = str(ASSETS / "app.ico")
        root.iconbitmap(default=icon_path)
        root.iconbitmap(icon_path)
        _set_windows_icons(root, icon_path)


def _set_windows_icons(root, icon_path):
    """Use the same source file for native small-caption and large-taskbar icons."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
    user32.GetAncestor.restype = wintypes.HWND
    user32.LoadImageW.argtypes = (wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
                                 ctypes.c_int, ctypes.c_int, wintypes.UINT)
    user32.LoadImageW.restype = wintypes.HANDLE
    user32.SendMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    user32.SendMessageW.restype = wintypes.LPARAM
    user32.DestroyIcon.argtypes = (wintypes.HANDLE,)
    handles = []

    def apply():
        hwnd = user32.GetAncestor(root.winfo_id(), 2)
        for kind, metric in ((0, 49), (1, 11)):  # ICON_SMALL / ICON_BIG; SM_CXSMICON / SM_CXICON.
            size = user32.GetSystemMetrics(metric)
            handle = user32.LoadImageW(None, icon_path, 1, size, size, 0x10)
            if handle:
                handles.append(handle)
                user32.SendMessageW(hwnd, 0x80, kind, handle)  # WM_SETICON

    job = root.after_idle(apply)

    def cleanup(event):
        if event.widget == root:
            root.after_cancel(job)
            for handle in handles:
                user32.DestroyIcon(handle)
            handles.clear()

    root.bind("<Destroy>", cleanup, add="+")


def set_app_identity() -> None:
    if sys.platform == "win32":
        import ctypes
        # Give this app its own taskbar group instead of the Python interpreter's.
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("RRAM.ChipConsole")
