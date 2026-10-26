"""Initial window sizing from the current monitor's usable work area."""
import sys


def work_area(root):
    fallback = (0, 0, root.winfo_screenwidth(), root.winfo_screenheight())
    if sys.platform != "win32":
        return fallback
    try:
        import ctypes
        from ctypes import wintypes
        class MonitorInfo(ctypes.Structure):
            _fields_ = [("size", wintypes.DWORD), ("monitor", wintypes.RECT),
                        ("work", wintypes.RECT), ("flags", wintypes.DWORD)]
        user = ctypes.windll.user32
        user.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        user.MonitorFromWindow.restype = wintypes.HANDLE
        user.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]
        user.GetMonitorInfoW.restype = wintypes.BOOL
        monitor = user.MonitorFromWindow(root.winfo_id(), 2)
        info = MonitorInfo()
        info.size = ctypes.sizeof(info)
        if user.GetMonitorInfoW(monitor, ctypes.byref(info)):
            rect = info.work
            return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top
    except (AttributeError, OSError):
        pass
    return fallback


def window_size(work_width, work_height, scale):
    width = min(round(1380 * scale), max(1, work_width - round(24 * scale)))
    height = min(round(900 * scale), max(1, work_height - round(64 * scale)))
    return width, height, min(round(800 * scale), width), min(round(480 * scale), height)
