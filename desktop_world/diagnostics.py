"""Local Windows compatibility report; optional read-only capture and hidden HWND check."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import statistics
import sys
import time


def capture_screen(layer, output: Path, stage: str) -> bool:
    """Opt-in real composition evidence; screenshots never become game assets."""
    if not layer.desktop_active():
        return False
    import ctypes
    from PIL import ImageGrab
    ctypes.windll.dwmapi.DwmFlush()
    time.sleep(.06)
    if not layer.desktop_active():
        return False
    output.mkdir(parents=True, exist_ok=True)
    ImageGrab.grab(all_screens=True).save(output / f"desktop-{stage}.png")
    return True


def save_capture_index(output: Path, captured: list[str]) -> None:
    output.mkdir(parents=True, exist_ok=True)
    (output / "composite-capture.json").write_text(json.dumps({
        "kind": "real composed desktop pixels; not transparent render frames", "captured": captured,
    }, indent=2), encoding="utf-8")


def collect(*, desktop: bool = False, window_check: bool = False) -> dict:
    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    from .dpi import enable_physical_coordinates
    dpi = enable_physical_coordinates()
    import win32api
    import win32gui
    from .timing import FramePacer
    from .winlayer import _desktop_host

    ver = sys.getwindowsversion()
    family = "Windows Server" if ver.product_type != 1 else ("Windows 11" if ver.build >= 22000 else "Windows 10")
    packages = {}
    for name in ("pygame", "Pillow", "pywin32", "numpy", "PyInstaller"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = "not recorded in this distribution"
    host = _desktop_host()
    report = {"recorded_utc": datetime.now(timezone.utc).isoformat(),
              "os_family": family, "os_build": ver.build, "os_version": platform.version(),
              "architecture": platform.machine(), "python": platform.python_version(),
              "frozen": bool(getattr(sys, "frozen", False)), "dpi": dpi, "packages": packages,
              "desktop_host": {"hwnd": host, "class": win32gui.GetClassName(host) if host else None},
              "monitors": [win32api.GetMonitorInfo(monitor) for monitor, _, _ in win32api.EnumDisplayMonitors()],
              "limitations": ["Only this recorded OS was tested; another Windows release is not implied.",
                              "No desktop visibility changes are made by this report."]}
    pacer = FramePacer()
    try:
        start = time.perf_counter()
        overshoot = []
        for i in range(30):
            deadline = start + (i + 1) / 60
            pacer.wait_until(deadline)
            overshoot.append(max(0.0, time.perf_counter() - deadline) * 1000)
        report["timer"] = {"backend": pacer.backend,
                           "median_overshoot_ms": round(statistics.median(overshoot), 3),
                           "max_overshoot_ms": round(max(overshoot), 3)}
    finally:
        pacer.close()
    if window_check:
        import pygame
        from .winlayer import LayeredWindow
        with LayeredWindow((-16000, -16000, -15984, -15984), "Desktop Killer hidden diagnostic") as window:
            surface = pygame.Surface((16, 16), pygame.SRCALPHA, 32)
            surface.fill((0, 0, 0, 0))
            surface.set_at((4, 4), (0, 0, 0, 255))
            surface.set_at((5, 4), (100, 200, 50, 128))
            window.present(surface)
            report["hidden_window"] = {"upload_ok": True,
                                       "visible": bool(win32gui.IsWindowVisible(window.hwnd))}
            if report["hidden_window"]["visible"]:
                raise RuntimeError("Diagnostic window unexpectedly became visible")
    if desktop:
        from .shell import capture_desktop
        snapshot = capture_desktop()
        report["desktop_capture"] = {"bounds": snapshot.bounds, "work_area": snapshot.work_area,
                                     "icon_count": len(snapshot.icons), "source_windows": snapshot.source_windows,
                                     "diagnostics": {k: v for k, v in snapshot.diagnostics.items() if k != "items"}}
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--desktop", action="store_true", help="Read real icon assets; never hide the desktop")
    parser.add_argument("--window-check", action="store_true", help="Upload to an invisible, owned 16x16 HWND")
    parser.add_argument("--output", type=Path, default=Path(os.environ.get("LOCALAPPDATA", ".")) /
                        "DesktopKiller" / "artifacts" / "windows-diagnostics.json")
    args = parser.parse_args(argv)
    try:
        report = collect(desktop=args.desktop, window_check=args.window_check)
        result = 0
    except Exception as exc:
        report = {"error": f"{type(exc).__name__}: {exc}", "desktop_changed": False}
        result = 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if sys.stdout is not None:
        print(json.dumps({"output": str(args.output), "result": result, **report}, ensure_ascii=False, indent=2))
    return result
