"""Read-only desktop provider inventory. Does not show/hide/change any window."""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
import json
from pathlib import Path
import sys

C.windll.user32.SetProcessDpiAwarenessContext(C.c_void_p(-4))
import win32gui
import win32process

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from desktop_world.shell_native import send_read

kernel = C.WinDLL("kernel32", use_last_error=True)
kernel.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
kernel.OpenProcess.restype = W.HANDLE
kernel.CloseHandle.argtypes = [W.HANDLE]
kernel.QueryFullProcessImageNameW.argtypes = [W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD)]
kernel.QueryFullProcessImageNameW.restype = W.BOOL

processes = {}
def process_path(pid):
    if pid in processes:
        return processes[pid]
    handle = kernel.OpenProcess(0x1000, False, pid)
    path = ""
    if handle:
        try:
            size = W.DWORD(32768)
            buffer = C.create_unicode_buffer(size.value)
            if kernel.QueryFullProcessImageNameW(handle, 0, buffer, C.byref(size)):
                path = buffer.value
        finally:
            kernel.CloseHandle(handle)
    processes[pid] = path
    return path

records = {}
def record(hwnd, top):
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        cls = win32gui.GetClassName(hwnd)
        entry = {"hwnd": hwnd, "top": top, "parent": win32gui.GetParent(hwnd),
                 "owner": win32gui.GetWindow(hwnd, 4), "class": cls,
                 "text": win32gui.GetWindowText(hwnd), "pid": pid,
                 "process": process_path(pid), "visible": bool(win32gui.IsWindowVisible(hwnd)),
                 "rect": win32gui.GetWindowRect(hwnd),
                 "style": win32gui.GetWindowLong(hwnd, -16), "exstyle": win32gui.GetWindowLong(hwnd, -20)}
        if cls == "SysListView32":
            try:
                entry["item_count"] = send_read(hwnd, 0x1004)
            except Exception as exc:
                entry["read_error"] = str(exc)
        records[hwnd] = entry
    except Exception as exc:
        records[hwnd] = {"hwnd": hwnd, "error": str(exc)}

tops = []
win32gui.EnumWindows(lambda hwnd, _: tops.append(hwnd), None)
for hwnd in tops:
    record(hwnd, hwnd)
    win32gui.EnumChildWindows(hwnd, lambda child, top: record(child, top), hwnd)

terms = ("desk", "wallpaper", "fence", "explorer")
selected = [r for r in records.values() if r.get("class") in ("SysListView32", "SHELLDLL_DefView", "Progman", "WorkerW")
            or any(s in r.get("process", "").lower() for s in terms)]
report = {"all_windows": list(records.values()), "desktop_candidates": selected}
out = ROOT / "artifacts" / "icon-sources.json"
out.parent.mkdir(exist_ok=True)
out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
compact = [r for r in selected if r.get("class") in ("SysListView32", "SHELLDLL_DefView", "Progman")
           or (r.get("visible") and "desktoplite" in r.get("process", "").lower())]
print(json.dumps({"total_windows": len(records), "report": str(out), "candidates": compact},
                 ensure_ascii=False, indent=2))
