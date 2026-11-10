"""Per-pixel-alpha Win32 desktop overlay; pygame is only an offscreen renderer."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
import sys
import time

import numpy as np
import pygame
import win32api
import win32con
import win32gui
import win32process


class _POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class _SIZE(ctypes.Structure):
    _fields_ = [("cx", wintypes.LONG), ("cy", wintypes.LONG)]


class _BLEND(ctypes.Structure):
    _fields_ = [("op", ctypes.c_ubyte), ("flags", ctypes.c_ubyte),
                ("alpha", ctypes.c_ubyte), ("format", ctypes.c_ubyte)]


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("width", wintypes.LONG),
                ("height", wintypes.LONG), ("planes", wintypes.WORD),
                ("bits", wintypes.WORD), ("compression", wintypes.DWORD),
                ("image_size", wintypes.DWORD), ("xppm", wintypes.LONG),
                ("yppm", wintypes.LONG), ("used", wintypes.DWORD),
                ("important", wintypes.DWORD)]


_user = ctypes.WinDLL("user32", use_last_error=True)
_gdi = ctypes.WinDLL("gdi32", use_last_error=True)
_gdi.CreateCompatibleDC.argtypes = [wintypes.HDC]
_gdi.CreateCompatibleDC.restype = wintypes.HDC
_gdi.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.POINTER(_BITMAPINFOHEADER),
                                wintypes.UINT, ctypes.POINTER(ctypes.c_void_p),
                                wintypes.HANDLE, wintypes.DWORD]
_gdi.CreateDIBSection.restype = wintypes.HBITMAP
_gdi.SelectObject.argtypes = [wintypes.HDC, wintypes.HANDLE]
_gdi.SelectObject.restype = wintypes.HANDLE
_gdi.DeleteObject.argtypes = [wintypes.HANDLE]
_gdi.DeleteObject.restype = wintypes.BOOL
_gdi.DeleteDC.argtypes = [wintypes.HDC]
_gdi.DeleteDC.restype = wintypes.BOOL
_user.UpdateLayeredWindow.argtypes = [wintypes.HWND, wintypes.HDC,
    ctypes.POINTER(_POINT), ctypes.POINTER(_SIZE), wintypes.HDC,
    ctypes.POINTER(_POINT), wintypes.COLORREF, ctypes.POINTER(_BLEND), wintypes.DWORD]
_user.UpdateLayeredWindow.restype = wintypes.BOOL
_dwm = ctypes.WinDLL("dwmapi")
_dwm.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
_dwm.DwmGetWindowAttribute.restype = ctypes.c_long


def _is_contiguous_bgra(surface: pygame.Surface) -> bool:
    """Only use raw memory when SDL's actual format and row pitch match the DIB."""
    return (sys.byteorder == "little" and surface.get_bytesize() == 4
            and surface.get_masks() == (0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000)
            and surface.get_pitch() == surface.get_width() * 4)


def _apply_input_carrier(surface: pygame.Surface, rect: pygame.Rect) -> None:
    """Clamp only alpha; four-channel SDL MAX blending is costly at desktop size."""
    alpha = pygame.surfarray.pixels_alpha(surface)
    try:
        region = alpha[rect.left:rect.right, rect.top:rect.bottom]
        np.maximum(region, np.uint8(1), out=region)
        del region
    finally:
        del alpha  # Release the surface lock before uploading it.


def _desktop_host() -> int:
    """Find the existing Explorer icon host without creating WorkerW windows."""
    found: list[int] = []

    def visit(hwnd, _):
        if win32gui.GetClassName(hwnd) in ("Progman", "WorkerW"):
            # Shell's private nesting can change between Windows builds. Locate
            # the actual view anywhere below a desktop root, never a folder window.
            descendants = []
            win32gui.EnumChildWindows(hwnd, lambda child, _: descendants.append(child), None)
            if any(win32gui.GetClassName(child) == "SHELLDLL_DefView" for child in descendants):
                found.append(hwnd)

    win32gui.EnumWindows(visit, None)
    return found[0] if found else 0


def _identity(hwnd: int) -> tuple[int, str] | None:
    try:
        if not win32gui.IsWindow(hwnd):
            return None
        return win32process.GetWindowThreadProcessId(hwnd)[1], win32gui.GetClassName(hwnd)
    except win32gui.error:
        return None


class LayeredWindow:
    """A nonactivating overlay above Explorer and below ordinary application windows.

    The prototype leaves alpha-zero pixels hit-test transparent. A game can opt
    into a 1/255-alpha input carrier confined to its work area, so a skill click
    cannot also open Explorer's context menu. Input is polled only on the desktop;
    no hook or hotkey is registered.
    """

    _KEYS = (win32con.VK_ESCAPE, win32con.VK_F5, win32con.VK_SPACE,
             win32con.VK_RETURN, win32con.VK_SHIFT, win32con.VK_CONTROL,
             win32con.VK_BACK, win32con.VK_F1, win32con.VK_LEFT,
             win32con.VK_RIGHT, win32con.VK_UP, win32con.VK_DOWN,
             ord("R"), ord("1"), ord("2"), ord("3"), ord("4"), ord("W"), ord("A"),
             ord("S"), ord("D"), ord("P"), ord("M"), ord("C"), ord("H"))
    _BUTTONS = ((win32con.VK_LBUTTON, 1), (win32con.VK_RBUTTON, 3))

    def __init__(self, bounds: tuple[int, int, int, int],
                 title: str = "Desktop Killer — 桌面叛乱",
                 input_bounds: tuple[int, int, int, int] | None = None) -> None:
        self.bounds = tuple(int(v) for v in bounds)
        left, top, right, bottom = self.bounds
        self.width, self.height = right - left, bottom - top
        if self.width <= 0 or self.height <= 0:
            raise ValueError("bounds must be a nonempty LTRB rectangle")
        self._input_rect: pygame.Rect | None = None
        self.set_input_bounds(input_bounds)
        self.hwnd = 0
        self._events: list[tuple[str, object]] = []
        self._dc = self._bitmap = self._old_bitmap = None
        self._closed = False
        self._shown = False
        self._last_order = 0.0
        self._desktop_lost = False
        self._host = _desktop_host()
        self._host_identity = _identity(self._host)
        self._keys = {key: False for key in self._KEYS}
        self._buttons = {vk: False for vk, _ in self._BUTTONS}
        self._held_keys: set[int] = set()
        self._held_buttons: set[int] = set()
        self._allowed_buttons: set[int] = set()
        self._activation_button: int | None = None
        self._input_active = False
        self._class_name = f"DesktopKillerLayer_{os.getpid()}_{id(self):x}"
        wc = win32gui.WNDCLASS()
        wc.hInstance = win32api.GetModuleHandle(None)
        wc.lpszClassName = self._class_name
        wc.lpfnWndProc = self._wndproc
        wc.hCursor = win32gui.LoadCursor(0, win32con.IDC_ARROW)
        self._instance = wc.hInstance
        win32gui.RegisterClass(wc)
        try:
            self.hwnd = win32gui.CreateWindowEx(
                win32con.WS_EX_LAYERED | win32con.WS_EX_TOOLWINDOW | win32con.WS_EX_NOACTIVATE,
                self._class_name, title, win32con.WS_POPUP,
                left, top, self.width, self.height, 0, 0, self._instance, None)
            self._allocate_bitmap()
        except BaseException:
            self.close()
            raise

    def _allocate_bitmap(self) -> None:
        self._dc = _gdi.CreateCompatibleDC(None)
        if not self._dc:
            raise ctypes.WinError(ctypes.get_last_error())
        info = _BITMAPINFOHEADER()
        info.size = ctypes.sizeof(info)
        info.width, info.height = self.width, -self.height
        info.planes, info.bits = 1, 32
        bits = ctypes.c_void_p()
        self._bitmap = _gdi.CreateDIBSection(self._dc, ctypes.byref(info), 0,
                                           ctypes.byref(bits), None, 0)
        if not self._bitmap or not bits.value:
            raise ctypes.WinError(ctypes.get_last_error())
        self._old_bitmap = _gdi.SelectObject(self._dc, self._bitmap)
        self._bits = bits.value
        self._byte_count = self.width * self.height * 4
        ctypes.memset(self._bits, 0, self._byte_count)

    def _wndproc(self, hwnd, message, wparam, lparam):
        if message == win32con.WM_CLOSE:
            self._events.append(("quit", None))
            return 0
        if message == win32con.WM_DESTROY:
            if not self._closed:
                self._events.append(("quit", None))
            return 0
        if message == win32con.WM_MOUSEACTIVATE:
            if self._input_rect is not None and self._point_in_input(win32gui.GetCursorPos()):
                # Activation follows an explicit user click on our input surface,
                # never automatic startup. NOACTIVATE otherwise keeps the previous
                # app foreground, preventing the desktop-scoped input from starting.
                try:
                    win32gui.SetForegroundWindow(hwnd)
                    self._place_above_desktop()
                    trigger = (int(lparam) >> 16) & 0xFFFF
                    self._activation_button = {
                        win32con.WM_LBUTTONDOWN: 1, win32con.WM_RBUTTONDOWN: 3,
                    }.get(trigger)
                except win32gui.error:
                    pass
            return win32con.MA_NOACTIVATE
        if message == win32con.WM_CONTEXTMENU and self._input_rect is not None:
            return 0
        if message == win32con.WM_ERASEBKGND:
            return 1
        if message == win32con.WM_DISPLAYCHANGE or message == 0x02E0:  # WM_DPICHANGED
            self._events.append(("display_changed", None))
            return 0
        if message == win32con.WM_SETTINGCHANGE and wparam == 0x002F:  # SPI_SETWORKAREA
            self._events.append(("display_changed", None))
        if message in (win32con.WM_KEYDOWN, win32con.WM_KEYUP):
            # The desktop-scoped poll below is the single input source.
            return 0
        if message in (win32con.WM_LBUTTONDOWN, win32con.WM_LBUTTONUP,
                       win32con.WM_RBUTTONDOWN, win32con.WM_RBUTTONUP,
                       win32con.WM_MBUTTONDOWN, win32con.WM_MBUTTONUP):
            # Preserve the explicit click that activated this owned input surface.
            # All other mouse edges come from polling. A focus return alone never
            # arms this path, so held clicks from another app are not replayed.
            logical = {win32con.WM_LBUTTONDOWN: 1, win32con.WM_RBUTTONDOWN: 3}.get(message)
            if logical is not None and logical == getattr(self, "_activation_button", None):
                self._activation_button = None
                point = win32gui.GetCursorPos()
                if self.desktop_active() and self._cursor_on_desktop(point):
                    physical = self._physical_button(logical)
                    self._buttons[physical] = True
                    self._allowed_buttons.add(physical)
                    self._events.append(("click", (*point, logical)))
            return 0
        return win32gui.DefWindowProc(hwnd, message, wparam, lparam)

    def _place_above_desktop(self) -> None:
        if not self._host_identity or _identity(self._host) != self._host_identity:
            if not self._desktop_lost:
                self._events.append(("desktop_lost", None))
                self._desktop_lost = True
            return
        # Insert after the window immediately ABOVE Explorer, not after Explorer
        # itself (which would put the overlay underneath its opaque wallpaper).
        above = win32gui.GetWindow(self._host, win32con.GW_HWNDPREV)
        if above == self.hwnd:
            return
        if above and win32gui.GetWindowLong(above, win32con.GWL_EXSTYLE) & win32con.WS_EX_TOPMOST:
            # HWND_NOTOPMOST is a no-op for an already non-topmost window;
            # HWND_TOP actually raises within the ordinary (non-topmost) band.
            above = win32con.HWND_TOP
        win32gui.SetWindowPos(self.hwnd, above or win32con.HWND_TOP, 0, 0, 0, 0,
            win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE |
            win32con.SWP_NOOWNERZORDER)

    def present(self, surface: pygame.Surface) -> None:
        """Upload straight RGBA as a premultiplied, top-down BGRA DIB."""
        if self._closed:
            raise RuntimeError("window is closed")
        if surface.get_size() != (self.width, self.height):
            raise ValueError("surface dimensions must match the overlay bounds")
        premultiplied = surface.premul_alpha()
        if getattr(self, "_input_rect", None) is not None:
            # Windows hit-tests alpha-zero layered pixels through to Explorer.
            # A 1/255 black coverage carrier prevents native desktop clicks/menus
            # while the real live wallpaper remains visible underneath. This is
            # confined to the game work area and does not alter the scene surface.
            _apply_input_carrier(premultiplied, self._input_rect)
        self._copy_pixels(premultiplied)
        destination = _POINT(self.bounds[0], self.bounds[1])
        size = _SIZE(self.width, self.height)
        origin = _POINT(0, 0)
        blend = _BLEND(0, 0, 255, 1)  # AC_SRC_OVER, AC_SRC_ALPHA
        if not _user.UpdateLayeredWindow(self.hwnd, None, ctypes.byref(destination),
                ctypes.byref(size), self._dc, ctypes.byref(origin), 0,
                ctypes.byref(blend), 2):  # ULW_ALPHA; never SetLayeredWindowAttributes
            raise ctypes.WinError(ctypes.get_last_error())

    def _copy_pixels(self, premultiplied: pygame.Surface) -> None:
        if _is_contiguous_bgra(premultiplied):
            # Keep both BufferProxy and the exported ctypes object alive through
            # memmove. No raw/.tobytes copy and no per-pixel channel conversion.
            proxy = premultiplied.get_buffer()
            exported = ctypes.c_ubyte.from_buffer(proxy)
            ctypes.memmove(self._bits, ctypes.addressof(exported), self._byte_count)
        else:
            # Nonstandard masks and subsurface pitches still produce correct BGRA.
            bgra = pygame.image.tobytes(premultiplied, "BGRA")
            ctypes.memmove(self._bits, bgra, self._byte_count)

    def set_input_bounds(self, bounds: tuple[int, int, int, int] | None) -> None:
        """Enable the minimal-alpha input carrier only for this screen rectangle.

        None retains exact alpha-zero transparency for the fusion prototype.
        A carrier is mathematically nonzero (at most 1/255 darkening in empty
        pixels), required for native hit-testing without global input hooks.
        """
        if bounds is None:
            self._input_rect = None
            return
        left, top, right, bottom = (int(v) for v in bounds)
        outer_l, outer_t, outer_r, outer_b = self.bounds
        if not (outer_l <= left < right <= outer_r and outer_t <= top < bottom <= outer_b):
            raise ValueError("input bounds must be a nonempty rectangle inside the overlay")
        self._input_rect = pygame.Rect(left - outer_l, top - outer_t, right - left, bottom - top)

    def _point_in_input(self, point: tuple[int, int]) -> bool:
        rect = getattr(self, "_input_rect", None)
        return rect is None or rect.collidepoint(point[0] - self.bounds[0], point[1] - self.bounds[1])

    def show(self) -> None:
        """Show without stealing focus or lifting above normal applications."""
        if self._closed:
            raise RuntimeError("window is closed")
        self._place_above_desktop()
        win32gui.ShowWindow(self.hwnd, win32con.SW_SHOWNOACTIVATE)
        self._place_above_desktop()
        self._shown = True

    def hide(self) -> None:
        """Stop automatic visibility maintenance before releasing the desktop lease."""
        self._shown = False
        if self.hwnd and win32gui.IsWindow(self.hwnd):
            win32gui.ShowWindow(self.hwnd, win32con.SW_HIDE)

    def desktop_active(self) -> bool:
        """Whether foreground focus belongs to this overlay or the actual desktop."""
        if self._shown and self._cloaked():
            return False
        foreground = win32gui.GetForegroundWindow()
        if foreground == self.hwnd:
            return True
        if not foreground or not self._host_identity:
            return False
        try:
            if _identity(self._host) != self._host_identity:
                return False
            root = win32gui.GetAncestor(foreground, win32con.GA_ROOT)
            identity = _identity(root)
            return root == self._host or bool(identity and
                identity[0] == self._host_identity[0] and identity[1] in ("Progman", "WorkerW"))
        except win32gui.error:
            return False

    def _cloaked(self) -> bool:
        """A Shell-cloaked overlay must not leave global desktop icons hidden."""
        value = wintypes.DWORD()
        return bool(_dwm.DwmGetWindowAttribute(self.hwnd, 14, ctypes.byref(value), ctypes.sizeof(value)) == 0
                    and value.value)

    def pump(self) -> list[tuple[str, object]]:
        """Dispatch local messages and desktop-scoped keyboard edge events."""
        if self._closed:
            return []
        win32gui.PumpWaitingMessages()
        if self._shown and self._cloaked() and not self._desktop_lost:
            # Windows virtual-desktop changes can cloak a window without changing
            # WS_VISIBLE. Relinquish the lease instead of drawing on another workspace.
            self._desktop_lost = True
            self._events.append(("desktop_lost", None))
        active = self.desktop_active()
        self._poll_input(active)
        now = time.monotonic()
        if now - self._last_order > 0.5:
            self._last_order = now
            if self._shown and not self._desktop_lost:
                # Win+D can hide/minimize tool windows together with applications.
                # The caller must validate its lease heartbeat BEFORE pumping.
                if active and (win32gui.IsIconic(self.hwnd) or not win32gui.IsWindowVisible(self.hwnd)):
                    win32gui.ShowWindow(self.hwnd, win32con.SW_SHOWNOACTIVATE)
                self._place_above_desktop()
        events, self._events = self._events, []
        return events

    def _cursor_on_desktop(self, point: tuple[int, int]) -> bool:
        """Do not interpret a click on a nonforeground app or taskbar as a skill."""
        if not self._point_in_input(point):
            return False
        try:
            hit = win32gui.WindowFromPoint(point)
            root = win32gui.GetAncestor(hit, win32con.GA_ROOT)
            if root in (self.hwnd, self._host):
                return True
            identity = _identity(root)
            return bool(identity and self._host_identity and identity[0] == self._host_identity[0]
                        and identity[1] in ("Progman", "WorkerW"))
        except win32gui.error:
            return False

    def _poll_input(self, active: bool) -> None:
        if not active:
            self._held_keys.clear()
            self._held_buttons.clear()
            self._allowed_buttons.clear()
            self._activation_button = None
            self._input_active = False
            return  # Never query keys/buttons while an ordinary application is active.
        previously_active = self._input_active
        self._held_keys = set()
        for key in self._KEYS:
            down = bool(win32api.GetAsyncKeyState(key) & 0x8000)
            if down:
                self._held_keys.add(key)
            if previously_active and down and not self._keys[key]:
                self._events.append(("key", key))
            self._keys[key] = down
        self._held_buttons = set()
        point = win32gui.GetCursorPos()
        on_desktop = self._cursor_on_desktop(point)
        for vk, button in self._BUTTONS:
            down = bool(win32api.GetAsyncKeyState(vk) & 0x8000)
            if previously_active and down and not self._buttons[vk]:
                if on_desktop:
                    self._allowed_buttons.add(vk)
                    self._events.append(("click", (*point, self._logical_button(button))))
            if not down:
                self._allowed_buttons.discard(vk)
            elif on_desktop and vk in self._allowed_buttons:
                self._held_buttons.add(self._logical_button(button))
            self._buttons[vk] = down
        self._activation_button = None
        self._input_active = True

    @staticmethod
    def _logical_button(button: int) -> int:
        return 4 - button if win32api.GetSystemMetrics(win32con.SM_SWAPBUTTON) else button

    @classmethod
    def _physical_button(cls, logical: int) -> int:
        # WM button messages are logical; GetAsyncKeyState uses physical buttons.
        physical = cls._logical_button(logical)
        return win32con.VK_LBUTTON if physical == 1 else win32con.VK_RBUTTON

    def keys(self) -> set[int]:
        """Return held VKs from the latest pump, only while the desktop is active."""
        return set(self._held_keys) if not self._closed and self.desktop_active() else set()

    def buttons(self) -> set[int]:
        """Logical held buttons started here, only over the active game work area."""
        if self._closed or not self.desktop_active():
            return set()
        return set(self._held_buttons) if self._cursor_on_desktop(win32gui.GetCursorPos()) else set()

    def cursor(self) -> tuple[int, int]:
        """Get the cursor in physical screen coordinates (caller enables DPI awareness)."""
        return win32gui.GetCursorPos()

    def close(self) -> None:
        """Hide and destroy only our own HWND and release all GDI resources."""
        if self._closed:
            return
        self._closed = True
        if self.hwnd and win32gui.IsWindow(self.hwnd):
            win32gui.ShowWindow(self.hwnd, win32con.SW_HIDE)
            win32gui.DestroyWindow(self.hwnd)
        if self._dc and self._old_bitmap:
            _gdi.SelectObject(self._dc, self._old_bitmap)
        if self._bitmap:
            _gdi.DeleteObject(self._bitmap)
        if self._dc:
            _gdi.DeleteDC(self._dc)
        try:
            win32gui.UnregisterClass(self._class_name, self._instance)
        except win32gui.error:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
