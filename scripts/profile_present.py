"""Profile owned HWND upload stages; never show a full-screen diagnostic window."""
from pathlib import Path
import sys
import os
import ctypes
import json
import statistics
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from desktop_world.dpi import enable_physical_coordinates
enable_physical_coordinates()
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import pygame
import win32gui
from desktop_world import winlayer as w


def profile(size, *, show=False, carrier=False, repeats=60):
    width, height = size
    bounds = (0, 0, width, height)
    source = pygame.Surface(size, pygame.SRCALPHA, 32)
    source.fill((0, 0, 0, 0))
    if size == (1920, 1080):
        fixture = ROOT / "artifacts" / "game-live" / "scene-10.png"
        if fixture.is_file():
            source.blit(pygame.image.load(str(fixture)), (0, 0))
    measurements = {name: [] for name in ("premultiply", "carrier_fill", "prepare_bgra", "memmove", "UpdateLayeredWindow", "total")}
    foreground = win32gui.GetForegroundWindow()
    with w.LayeredWindow(bounds, "Desktop Killer owned upload benchmark",
                         input_bounds=bounds if carrier else None) as layer:
        if show:
            assert width <= 32 and height <= 32, "Never show a large benchmark window"
            layer.present(source)
            layer.show()  # Desktop z-order: always below ordinary applications.
        target, dimensions, origin, blend = w._POINT(0, 0), w._SIZE(width, height), w._POINT(0, 0), w._BLEND(0, 0, 255, 1)
        for i in range(repeats + 5):
            points = [time.perf_counter()]
            premul = source.premul_alpha()
            points.append(time.perf_counter())
            if carrier:
                w._apply_input_carrier(premul, layer._input_rect)
            points.append(time.perf_counter())
            if w._is_contiguous_bgra(premul):
                proxy = premul.get_buffer()
                exported = ctypes.c_ubyte.from_buffer(proxy)
                source_address = ctypes.addressof(exported)
            else:
                source_address = pygame.image.tobytes(premul, "BGRA")
            points.append(time.perf_counter())
            ctypes.memmove(layer._bits, source_address, layer._byte_count)
            points.append(time.perf_counter())
            if not w._user.UpdateLayeredWindow(layer.hwnd, None, ctypes.byref(target), ctypes.byref(dimensions),
                    layer._dc, ctypes.byref(origin), 0, ctypes.byref(blend), 2):
                raise ctypes.WinError(ctypes.get_last_error())
            points.append(time.perf_counter())
            if i >= 5:
                for index, name in enumerate(list(measurements)[:-1]):
                    measurements[name].append((points[index + 1] - points[index]) * 1000)
                measurements["total"].append((points[-1] - points[0]) * 1000)
        result = {"size": size, "shown": show, "carrier": carrier,
                  "visible_style": bool(win32gui.IsWindowVisible(layer.hwnd)),
                  "foreground_unchanged": win32gui.GetForegroundWindow() == foreground,
                  "note": "Shown 32px window remains at desktop z-order and may be occluded by ordinary apps.",
                  "timings_ms": {name: {"mean": round(statistics.mean(values), 4),
                                         "median": round(statistics.median(values), 4),
                                         "p95": round(sorted(values)[int(len(values) * .95)], 4)}
                                  for name, values in measurements.items()}}
    return result


results = [profile((1920, 1080), carrier=False), profile((1920, 1080), carrier=True),
           profile((32, 32), carrier=True), profile((32, 32), show=True, carrier=True)]
output = ROOT / "artifacts" / "present-stage-profile-after.json"
output.write_text(json.dumps(results, indent=2), encoding="utf-8")
print(json.dumps(results, indent=2))
