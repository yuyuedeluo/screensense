"""Windows 小工具：前景視窗標題、是不是全螢幕。其他系統一律回傳 None／False。"""
from __future__ import annotations

import ctypes
import sys


def foreground_title() -> str | None:
    if sys.platform != "win32":
        return None
    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    n = user32.GetWindowTextLengthW(hwnd)
    if n <= 0:
        return None
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value or None


def is_fullscreen() -> bool:
    """前景視窗是否蓋滿整個螢幕（遊戲、全螢幕影片）。"""
    if sys.platform != "win32":
        return False
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    if not hwnd or hwnd in (user32.GetDesktopWindow(), user32.GetShellWindow()):
        return False
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

    mon = user32.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(MONITORINFO)
    user32.GetMonitorInfoW(mon, ctypes.byref(info))
    m = info.rcMonitor
    return (rect.left <= m.left and rect.top <= m.top and rect.right >= m.right and rect.bottom >= m.bottom)


def title_blocker(words: list[str], own: list[str] | None = None):
    """做一個 allow_fn：標題含黑名單字（銀行、密碼…）或是自己的視窗就不收。"""
    words = [w.lower() for w in words]
    own = [w.lower() for w in (own or [])]

    def allow(title: str | None) -> bool:
        t = (title or "").lower()
        return not any(w in t for w in words + own)

    return allow
