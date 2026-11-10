"""Establish and verify physical-pixel DPI coordinates before any GUI import."""
from __future__ import annotations

import ctypes
import os


def _configure(user32) -> dict:
    """Prefer PMv2; verify already configured processes instead of ignoring FALSE."""
    current = user32.GetThreadDpiAwarenessContext
    equal = user32.AreDpiAwarenessContextsEqual
    per_monitor_v2 = ctypes.c_void_p(-4)
    if equal(current(), per_monitor_v2):
        return {"awareness": "per-monitor-v2", "method": "already-configured"}
    success = user32.SetProcessDpiAwarenessContext(per_monitor_v2)
    process_error = ctypes.get_last_error() if not success else 0
    if equal(current(), per_monitor_v2):
        return {"awareness": "per-monitor-v2", "method": "process"}
    # A launcher/manifest can have locked the process default. Setting this
    # not-yet-GUI thread's context is documented and keeps all geometry physical.
    previous = user32.SetThreadDpiAwarenessContext(per_monitor_v2)
    if previous and equal(current(), per_monitor_v2):
        return {"awareness": "per-monitor-v2", "method": "thread", "process_error": process_error}
    raise RuntimeError(f"Cannot establish per-monitor DPI awareness (process error={process_error}, "
                       f"thread error={ctypes.get_last_error()}); no desktop changes were made")


def enable_physical_coordinates() -> dict:
    """Require Win10 1809+/Win11 PMv2 support and prove the calling context."""
    if os.name != "nt":
        return {"awareness": "not-windows", "method": "not-applicable"}
    user = ctypes.WinDLL("user32", use_last_error=True)
    for name in ("SetProcessDpiAwarenessContext", "AreDpiAwarenessContextsEqual"):
        fn = getattr(user, name)
        fn.restype = ctypes.c_int
        fn.argtypes = [ctypes.c_void_p] * (2 if name.startswith("Are") else 1)
    user.GetThreadDpiAwarenessContext.argtypes = []
    user.GetThreadDpiAwarenessContext.restype = ctypes.c_void_p
    user.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
    user.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
    return _configure(user)
