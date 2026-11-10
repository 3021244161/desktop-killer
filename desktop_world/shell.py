"""Read the real Explorer desktop view and independent transparent Shell assets."""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import time

from PIL import Image


@dataclass
class DesktopIcon:
    key: str
    name: str
    x: float
    y: float
    width: int
    height: int
    image: Image.Image
    label_rect: tuple[int, int, int, int]
    label_image: Image.Image | None = None


@dataclass
class DesktopSnapshot:
    listview_hwnd: int
    host_hwnd: int
    bounds: tuple[int, int, int, int]
    work_area: tuple[int, int, int, int]
    icons: list[DesktopIcon]
    font_name: str
    font_size: int
    diagnostics: dict = field(default_factory=dict)
    source_windows: list[int] = field(default_factory=list)


class DesktopReadError(RuntimeError):
    """A precise desktop read failed; callers must not hide Explorer afterward."""


def _screen_rect(rect, origin):
    ox, oy = origin
    l, t, r, b = rect
    return l + ox, t + oy, r + ox, b + oy


def _image_bounds(layout_rect, logical_size: int, dpi: int):
    """Center the DPI-scaled image inside Explorer's padded icon layout slot."""
    size = (logical_size * dpi + 48) // 96
    l, t, r, b = layout_rect
    if size <= 0 or size > min(r - l, b - t):
        raise DesktopReadError(f"Icon size {size}px does not fit Explorer rectangle {layout_rect}")
    x = l + (r - l - size) // 2
    y = t + (b - t - size) // 2
    return x, y, x + size, y + size


def _find_listview(view_hwnd: int) -> int:
    import win32gui
    result = win32gui.FindWindowEx(view_hwnd, 0, "SysListView32", None)
    if result:
        return result
    children = []
    win32gui.EnumChildWindows(view_hwnd, lambda hwnd, _: children.append(hwnd), None)
    return next((h for h in children if win32gui.GetClassName(h) == "SysListView32"), 0)


def _extract_image(item: bytes, size: tuple[int, int], path: str) -> tuple[Image.Image, str]:
    from . import shell_native as native

    width, height = size
    # Existing thumbnails are independent Shell assets, never desktop pixels.
    if not path.lower().endswith((".lnk", ".url")):
        try:
            return native.thumbnail_from_pidl(item, width, height), "thumbnail"
        except OSError:
            pass  # No thumbnail is normal; request this item's real icon below.
    hicon, source_size = native.large_shell_icon(item, max(size))
    try:
        image = native.icon_to_rgba(hicon, width, height)
    finally:
        native.user32.DestroyIcon(hicon)
    if image.getchannel("A").getextrema()[1] == 0:
        raise DesktopReadError(f"Shell icon is fully transparent for {path!r}")
    return image, f"shell-icon-with-overlays-{source_size[0]}px"


def capture_desktop() -> DesktopSnapshot:
    """Route to the visible icon provider, never an obscured Explorer layout."""
    from . import desklite
    try:
        surfaces = desklite.find_surfaces()
        return desklite.capture(surfaces) if surfaces else _capture_explorer()
    except DesktopReadError:
        raise
    except Exception as exc:
        raise DesktopReadError(f"Cannot read the visible desktop provider: {exc}") from exc


def _capture_explorer() -> DesktopSnapshot:
    """Read every displayed desktop item or raise, without changing the desktop.

    Call after enabling per-monitor DPI awareness, before creating any window.
    All coordinates are physical screen pixels, including negative monitor X/Y.
    """
    import pythoncom
    import win32api
    import win32com.client
    import win32gui
    from win32com.shell import shell, shellcon
    from . import shell_native as native

    started = time.perf_counter()
    pythoncom.CoInitialize()
    try:
        try:
            # Documented desktop IFolderView route, no FindWindowSW mutations.
            windows = win32com.client.Dispatch("Shell.Application").Windows()
            desktop = windows.FindWindowSW(0, 0, 8, 0, 1)
            provider = desktop._oleobj_.QueryInterface(pythoncom.IID_IServiceProvider)
            browser = provider.QueryService(shell.SID_STopLevelBrowser, shell.IID_IShellBrowser)
            view = browser.QueryActiveShellView()
            folder_view = view.QueryInterface(shell.IID_IFolderView)
            folder = folder_view.GetFolder(shell.IID_IShellFolder)
            host = int(view.GetWindow())
            listview = _find_listview(host)
            if not listview:
                raise DesktopReadError("The desktop Shell view has no SysListView32; this desktop is not supported yet")
            if not win32gui.IsWindowVisible(listview):
                raise DesktopReadError("Desktop icons are currently hidden; enable Show desktop icons first")
        except DesktopReadError:
            raise
        except Exception as exc:
            raise DesktopReadError(f"Cannot access Explorer IFolderView: {exc}") from exc

        count = folder_view.ItemCount(shellcon.SVGIO_ALLVIEW)
        visible_count = native.send_read(listview, 0x1004)
        if count != visible_count:
            raise DesktopReadError(f"Desktop changed during capture: Shell={count}, ListView={visible_count}")
        if not count:
            raise DesktopReadError("This desktop has no icons to animate")
        origin = win32gui.ClientToScreen(listview, (0, 0))
        vx, vy = win32api.GetSystemMetrics(76), win32api.GetSystemMetrics(77)
        bounds = (vx, vy, vx + win32api.GetSystemMetrics(78), vy + win32api.GetSystemMetrics(79))
        monitor = win32api.MonitorFromPoint((0, 0), 1)
        work_area = tuple(win32api.GetMonitorInfo(monitor)["Work"])
        label_font = native.desktop_logfont(listview)
        font_name, font_size = label_font.face, abs(label_font.height)
        view_mode, logical_icon_size = native.view_icon_size(folder_view)
        dpi = native.user32.GetDpiForWindow(listview)
        if view_mode != 1:
            raise DesktopReadError(f"Desktop view mode {view_mode} is unsupported; use desktop Icons view")
        icons = []
        records = []
        try:
            with native.ListViewGeometry(listview) as geometry:
                for index in range(count):
                    item = folder_view.Item(index)
                    if not isinstance(item, bytes):
                        raise DesktopReadError(f"Shell returned no PIDL for item {index}")
                    name = folder.GetDisplayNameOf([item], shellcon.SHGDN_NORMAL)
                    path = folder.GetDisplayNameOf([item], shellcon.SHGDN_FORPARSING)
                    position = folder_view.GetItemPosition(item)
                    if tuple(position) != geometry.position(index):
                        raise DesktopReadError(f"Shell/ListView order changed at {name!r}; retry capture")
                    layout_rect = _screen_rect(geometry.rect(index, 1), origin)
                    icon_rect = _image_bounds(layout_rect, logical_icon_size, dpi)
                    label_rect = _screen_rect(geometry.rect(index, 2), origin)
                    l, t, r, b = icon_rect
                    width, height = r - l, b - t
                    if not (0 < width <= 1024 and 0 < height <= 1024):
                        raise DesktopReadError(f"Invalid icon rectangle {icon_rect} for {name!r}")
                    image, source = _extract_image(item, (width, height), path)
                    label_image = native.label_to_rgba(name, label_rect[2] - label_rect[0],
                                                      label_rect[3] - label_rect[1], label_font)
                    key = hashlib.sha256(item).hexdigest()[:24]
                    icons.append(DesktopIcon(key, name, l, t, width, height, image, label_rect, label_image))
                    records.append({"key": key, "name": name, "position": position,
                                    "icon_rect": icon_rect, "layout_rect": layout_rect, "label_rect": label_rect,
                                    "source": source})
        except DesktopReadError:
            raise
        except Exception as exc:
            raise DesktopReadError(f"Desktop capture failed at item {len(icons)}/{count}: {exc}") from exc

        if folder_view.ItemCount(shellcon.SVGIO_ALLVIEW) != count or native.send_read(listview, 0x1004) != count:
            raise DesktopReadError("Desktop items changed during capture; retry before taking control")
        for index, record in enumerate(records):
            current_item = folder_view.Item(index)
            if (hashlib.sha256(current_item).hexdigest()[:24] != record["key"]
                    or tuple(folder_view.GetItemPosition(current_item)) != tuple(record["position"])):
                raise DesktopReadError("Desktop order or positions changed during capture; retry before taking control")
        if len({icon.key for icon in icons}) != count:
            raise DesktopReadError("Desktop enumeration returned duplicate item identities")
        diagnostics = {"method": "IFolderView + LVM_GETITEMRECT + Shell assets", "icon_count": count,
                       "source_kind": "explorer",
                       "logical_icon_size": logical_icon_size, "view_dpi": dpi, "view_mode": view_mode,
                       "capture_seconds": round(time.perf_counter() - started, 3), "items": records,
                       "label_font": {field: getattr(label_font, field) for field, _ in label_font._fields_},
                       "label_fidelity": "native DrawTextW + actual LOGFONT; grayscale antialiasing and 1px shadow"}
        return DesktopSnapshot(listview, host, bounds, work_area, icons, font_name, font_size,
                               diagnostics, source_windows=[listview])
    finally:
        pythoncom.CoUninitialize()
