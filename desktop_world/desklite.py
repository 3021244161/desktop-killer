"""Read the visible 360 DesktopLite layout and verify it against its renderer.

The DTF layout is an observed, versioned compatibility adapter, not a public
360 API. Window pixels are used solely to verify/calibrate coordinates. Every
game sprite remains an independently extracted Shell image.
"""
from __future__ import annotations

from dataclasses import dataclass
import ctypes as C
from ctypes import wintypes as W
import hashlib
import ntpath
import os
from pathlib import Path
import struct
import time

import numpy as np
from PIL import Image


@dataclass
class Node:
    tag: str
    offset: int
    size: int
    value: object


def parse_tlv(data: bytes, start=0, end=None, depth=0) -> list[Node]:
    end = len(data) if end is None else end
    if depth > 16:
        raise ValueError("Excessive DTF nesting")
    nodes = []
    cursor = start
    while cursor < end:
        if end - cursor < 5:
            raise ValueError(f"Truncated DTF header at {cursor}")
        tag = chr(data[cursor])
        size = struct.unpack_from("<I", data, cursor + 1)[0]
        payload, limit = cursor + 5, cursor + 5 + size
        if limit > end:
            raise ValueError(f"Truncated DTF payload at {cursor}")
        if tag == "S":
            value = parse_tlv(data, payload, limit, depth + 1)
        elif tag == "s":
            value = data[payload:limit].decode("utf-16le", errors="strict")
        elif tag in ("d", "B") and size == 4:
            value = struct.unpack_from("<i", data, payload)[0]
        else:
            raise ValueError(f"Unknown DTF field {tag!r}/{size}")
        nodes.append(Node(tag, cursor, size, value))
        cursor = limit
    return nodes


def decode_layout(data: bytes) -> list[dict]:
    if len(data) > 8 * 1024 * 1024:
        raise ValueError("Unexpectedly large DTF layout")
    groups = []
    for node in parse_tlv(data):
        if node.tag != "S":
            raise ValueError("Expected DTF group")
        fields = node.value
        scalars = [f.value for f in fields if f.tag != "S"]
        if len(scalars) < 7:
            raise ValueError("Incomplete DTF group")
        items = []
        for child in fields:
            if child.tag != "S":
                continue
            if "".join(f.tag for f in child.value) != "dddssddsdddB":
                raise ValueError("Unsupported DTF item schema")
            values = [f.value for f in child.value]
            items.append({"id": values[0], "path": values[3], "name": values[4], "slot": values[9]})
        groups.append({"name": scalars[1], "tblr": scalars[2:6], "scale": scalars[6],
                       "layout": scalars[-4:], "items": items,
                       "desktop": isinstance(scalars[1], str) and scalars[1].lower().startswith("\\\\.\\display")})
    return groups


def positioned_items(group: dict) -> list[dict]:
    """Distinguish visible icons from empty slots and hidden desktop metadata."""
    result = []
    for item in group["items"]:
        name, path, slot = item["name"], item["path"], item["slot"]
        if not name and not path:
            continue  # Empty provider slot; there is no visible object to reproduce.
        if not name and slot < 0 and ntpath.basename(path).lower() == "desktop.ini":
            continue  # Observed per-user/Public Desktop metadata, not a displayed icon.
        if not name or not path or slot < 0:
            raise ValueError(f"360 desktop contains an incomplete positioned item: {name or path!r}")
        result.append(item)
    return result


def find_surfaces() -> list[int]:
    """Find the actual visible provider, including its WorkerW child surface."""
    import win32gui
    import win32process
    from . import shell_native as n
    query = n._bind(n.kernel32, "QueryFullProcessImageNameW", W.BOOL,
                    [W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD)])
    found = set()

    def inspect(hwnd, _):
        if (win32gui.GetClassName(hwnd) != "360DirectUICls"
                or win32gui.GetWindowText(hwnd) != "360DTFenceLite"
                or not win32gui.IsWindowVisible(hwnd)):
            return
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        handle = n.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            raise RuntimeError("Cannot verify the visible 360 DesktopLite process")
        try:
            size = W.DWORD(32768)
            path = C.create_unicode_buffer(size.value)
            if not query(handle, 0, path, C.byref(size)):
                raise RuntimeError("Cannot read 360 DesktopLite process identity")
            if Path(path.value).name.lower() not in ("360desktoplite.exe", "360desktoplite32.exe", "360desktoplite64.exe"):
                raise RuntimeError("Unexpected process owns the 360 desktop window")
            found.add(hwnd)
        finally:
            n.kernel32.CloseHandle(handle)

    def top(hwnd, _):
        inspect(hwnd, None)
        win32gui.EnumChildWindows(hwnd, inspect, None)

    win32gui.EnumWindows(top, None)
    return sorted(found)


def _reference_pixels(hwnd: int) -> np.ndarray:
    """Read-only live reference; deliberately never returned as a game asset."""
    import win32gui
    from . import shell_native as n
    _, _, width, height = win32gui.GetClientRect(hwnd)
    if width <= 0 or height <= 0 or width * height > 40_000_000:
        raise RuntimeError("Unsupported 360 desktop surface dimensions")
    dc = n._require(n.gdi32.CreateCompatibleDC(None), "CreateCompatibleDC layout verification")
    bitmap = previous = None
    try:
        pixels = W.LPVOID()
        bitmap = n._require(n.gdi32.CreateDIBSection(dc, C.byref(n._bmi(width, height)), 0,
                                                    C.byref(pixels), None, 0), "CreateDIBSection layout verification")
        previous = n.gdi32.SelectObject(dc, bitmap)
        fn = n._bind(n.user32, "PrintWindow", W.BOOL, [W.HWND, W.HDC, W.UINT])
        n._require(fn(hwnd, dc, 2), "PrintWindow for live 360 layout verification")
        raw = np.frombuffer(C.string_at(pixels, width * height * 4), dtype=np.uint8).reshape(height, width, 4)
        return raw[..., [2, 1, 0]].copy()
    finally:
        if previous:
            n.gdi32.SelectObject(dc, previous)
        if bitmap:
            n.gdi32.DeleteObject(bitmap)
        n.gdi32.DeleteDC(dc)


def _matching_pixels(image: Image.Image):
    rgba = np.array(image.convert("RGBA"))
    mask = rgba[..., 3] >= 240
    if mask.sum() < 80:
        raise RuntimeError("Insufficient opaque image detail to verify 360 layout")
    return rgba[..., :3].astype(np.int16), mask


def _find_anchor_y(reference: np.ndarray, image: Image.Image, x: int, y_limit=None) -> tuple[int, float]:
    target, mask = _matching_pixels(image)
    width, height = image.size
    if x < 0 or x + width > reference.shape[1]:
        raise RuntimeError("360 calibration anchor lies outside its surface")
    strip = reference[:, x:x + width]
    if y_limit is not None:
        strip = strip[:y_limit + height]
    windows = np.lib.stride_tricks.sliding_window_view(strip, height, axis=0).transpose(0, 3, 1, 2)
    distance = np.abs(windows[:, mask].astype(np.int16) - target[mask]).mean(axis=(1, 2)) / 255.0
    y = int(distance.argmin())
    return y, float(distance[y])


def _verify_at(reference: np.ndarray, image: Image.Image, x: int, y: int) -> float:
    target, mask = _matching_pixels(image)
    width, height = image.size
    crop = reference[y:y + height, x:x + width]
    if crop.shape != target.shape:
        raise RuntimeError("360 item lies outside its visible surface")
    return float(np.abs(crop.astype(np.int16)[mask] - target[mask]).mean() / 255)


def verify_live_item(reference: np.ndarray, image: Image.Image, x: int, y: int) -> dict:
    """Require visible evidence for every configured item, including dark icons.

    Absolute error allows Shell/360 image-list scaling differences. Relative
    error compares the match with an empty black PrintWindow background so a
    dark sprite cannot pass simply because its old location is now empty.
    """
    target, mask = _matching_pixels(image)
    empty_error = float(target[mask].mean() / 255)
    error = _verify_at(reference, image, x, y)
    if empty_error < 0.03:
        raise RuntimeError("Icon has insufficient contrast for reliable live layout verification")
    relative_error = error / empty_error
    if error > 0.32 or relative_error > 0.65:
        raise RuntimeError(f"Stored icon position differs from the live 360 desktop "
                           f"(pixel error={error:.3f}, relative empty-background error={relative_error:.3f})")
    return {"pixel_error": round(error, 4), "relative_empty_error": round(relative_error, 4)}


def calibrate_grid(reference: np.ndarray, images: dict[int, Image.Image], cell_width: int,
                   icon_width: int, work_width: int, work_height: int) -> dict:
    """Calibrate row pitch from live independent-image matches, then cross-check.

    The stored second spacing value is NOT assumed to be physical row pitch.
    This adapter refuses layouts without a verifiable first-column pair.
    """
    if 0 not in images or 1 not in images:
        raise RuntimeError("360 layout needs populated first two slots for reliable live calibration")
    x0 = (cell_width - icon_width) // 2
    y0, error0 = _find_anchor_y(reference, images[0], x0, min(80, work_height // 4))
    y1, error1 = _find_anchor_y(reference, images[1], x0)
    pitch = y1 - y0
    if max(error0, error1) > 0.19 or not (icon_width + 20 <= pitch <= icon_width + 160):
        raise RuntimeError(f"360 live layout calibration failed: errors={error0:.3f}/{error1:.3f}, row pitch={pitch}")
    rows = (work_height - y0 - images[0].height) // pitch + 1
    if rows < 2:
        raise RuntimeError("360 desktop has no reliable column layout")
    candidates = [slot for slot in sorted(images) if slot not in (0, 1)]
    checks = []
    # Verify several independent images spanning at least two columns.
    for slot in candidates:
        if len(checks) >= 6:
            break
        if slot < rows and len(checks) >= 2:
            continue
        col, row = divmod(slot, rows)
        x, y = x0 + col * cell_width, y0 + row * pitch
        error = _verify_at(reference, images[slot], x, y)
        if error > 0.22:
            continue  # Some shell-thumbnail decoration differs; don't use that item as an anchor.
        checks.append({"slot": slot, "x": x, "y": y, "error": round(error, 4)})
    if len(checks) < 4 or not any(c["slot"] >= rows for c in checks):
        raise RuntimeError("360 stored layout did not match enough live icons; refusing potentially stale coordinates")
    return {"x0": x0, "y0": y0, "pitch_x": cell_width, "pitch_y": pitch, "rows": rows,
            "anchor_errors": [round(error0, 4), round(error1, 4)], "checks": checks}


def capture(surfaces: list[int]):
    import pythoncom
    import win32api
    import win32com.client
    import win32gui
    from win32com.shell import shell, shellcon
    from .shell import DesktopIcon, DesktopSnapshot, DesktopReadError, _find_listview, _extract_image
    from . import shell_native as n

    if len(surfaces) != 1:
        raise DesktopReadError("Only one verified 360 desktop surface is supported by this prototype")
    started = time.perf_counter()
    path = Path(os.environ["APPDATA"]) / "360Desktoplite" / "DTFence" / "DTFenceData.dtf"
    data = path.read_bytes()
    groups = decode_layout(data)
    desktops = [g for g in groups if g["desktop"]]
    if len(desktops) != 1:
        raise DesktopReadError("360 multi-monitor stored layouts are not supported yet")
    group = desktops[0]
    top, bottom, left, right = group["tblr"]
    work_area = (left, top, right, bottom)
    if tuple(win32api.GetMonitorInfo(win32api.MonitorFromPoint((0, 0), 1))["Work"]) != work_area:
        raise DesktopReadError("360 stored work area differs from the current display; refresh its layout before playing")
    hwnd = surfaces[0]
    origin = win32gui.ClientToScreen(hwnd, (0, 0))
    if origin != (left, top):
        raise DesktopReadError("Unsupported offset between the 360 desktop surface and its stored layout")
    cell_width, _, icon_width, icon_height = group["layout"]
    if not (16 <= icon_width <= 256 and 16 <= icon_height <= 256 and icon_width < cell_width <= 500):
        raise DesktopReadError("Unsupported 360 icon dimensions")
    try:
        items = positioned_items(group)
    except ValueError as exc:
        raise DesktopReadError(str(exc)) from exc
    if not items or len({i["slot"] for i in items}) != len(items):
        raise DesktopReadError("360 stored desktop contains no unique positioned icons")
    if len({os.path.normcase(i["path"]) for i in items}) != len(items):
        raise DesktopReadError("360 desktop contains duplicate file identities")
    items.sort(key=lambda i: i["slot"])
    pythoncom.CoInitialize()
    try:
        desktop = win32com.client.Dispatch("Shell.Application").Windows().FindWindowSW(0, 0, 8, 0, 1)
        view = desktop._oleobj_.QueryInterface(pythoncom.IID_IServiceProvider).QueryService(
            shell.SID_STopLevelBrowser, shell.IID_IShellBrowser).QueryActiveShellView()
        fv = view.QueryInterface(shell.IID_IFolderView)
        folder = fv.GetFolder(shell.IID_IShellFolder)
        host = int(view.GetWindow())
        listview = _find_listview(host)
        if not listview:
            raise DesktopReadError("Cannot find the underlying Explorer layer for complete desktop restoration")
        by_path = {}
        for i in range(fv.ItemCount(shellcon.SVGIO_ALLVIEW)):
            pidl = fv.Item(i)
            parsing = folder.GetDisplayNameOf([pidl], shellcon.SHGDN_FORPARSING)
            by_path[os.path.normcase(parsing)] = pidl
        images, sources = {}, {}
        for item in items:
            pidl = by_path.get(os.path.normcase(item["path"]))
            if pidl is None:
                raise DesktopReadError(f"Cannot map visible 360 icon to Shell asset: {item['name']} ({item['path']})")
            images[item["slot"]], sources[item["slot"]] = _extract_image(pidl, (icon_width, icon_height), item["path"])
        reference = _reference_pixels(hwnd)
        grid = calibrate_grid(reference, images, cell_width, icon_width, right - left, bottom - top)
        font = n.desktop_logfont(listview)
        icons, records = [], []
        for item in items:
            slot = item["slot"]
            col, row = divmod(slot, grid["rows"])
            x = left + grid["x0"] + col * grid["pitch_x"]
            y = top + grid["y0"] + row * grid["pitch_y"]
            if x + icon_width > right or y + icon_height > bottom:
                raise DesktopReadError(f"360 icon is outside its stored desktop: {item['name']}")
            try:
                visual_match = verify_live_item(reference, images[slot], x - left, y - top)
            except RuntimeError as exc:
                raise DesktopReadError(f"360 icon '{item['name']}' cannot be verified: {exc}") from exc
            label_rect = (left + col * cell_width, y + icon_height + 3,
                          left + (col + 1) * cell_width, y + icon_height + 45)
            label = n.label_to_rgba(item["name"], cell_width, 42, font)
            key = "360-" + str(item["id"])
            icons.append(DesktopIcon(key, item["name"], x, y, icon_width, icon_height,
                                     images[slot], label_rect, label))
            records.append({"key": key, "name": item["name"], "slot": slot,
                            "icon_rect": (x, y, x + icon_width, y + icon_height),
                            "label_rect": label_rect, "source": sources[slot], "visual_match": visual_match})
        if path.read_bytes() != data or not win32gui.IsWindowVisible(hwnd):
            raise DesktopReadError("360 desktop changed during capture; retry before taking control")
        vx, vy = win32api.GetSystemMetrics(76), win32api.GetSystemMetrics(77)
        bounds = (vx, vy, vx + win32api.GetSystemMetrics(78), vy + win32api.GetSystemMetrics(79))
        hidden_panel_items = sum(bool(i["name"]) for g in groups if not g["desktop"] for i in g["items"])
        diagnostics = {"source_kind": "360-desktoplite", "method": "strict DTF layout + live independent-icon calibration",
                       "icon_count": len(icons), "hidden_panel_items": hidden_panel_items,
                       "provider_surface": hwnd, "layout_sha256": hashlib.sha256(data).hexdigest(),
                       "layout_grid": grid, "items": records,
                       "live_verification": {"checked": len(records),
                                             "max_pixel_error": max(r["visual_match"]["pixel_error"] for r in records),
                                             "median_pixel_error": float(np.median([r["visual_match"]["pixel_error"] for r in records])),
                                             "max_relative_empty_error": max(r["visual_match"]["relative_empty_error"] for r in records),
                                             "pixel_error_limit": 0.32, "relative_empty_error_limit": 0.65},
                       "panels": "360 categorized folders, clock and notes temporarily hidden with provider; restored on exit",
                       "label_fidelity": "native GDI labels using desktop font; 360 private text effects may differ",
                       "capture_seconds": round(time.perf_counter() - started, 3)}
        return DesktopSnapshot(listview, host, bounds, work_area, icons, font.face, abs(font.height),
                               diagnostics, source_windows=[listview, hwnd])
    finally:
        pythoncom.CoUninitialize()
