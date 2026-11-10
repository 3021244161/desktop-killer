"""Small, explicitly typed Win32 readers; no desktop state is changed here."""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
import struct
import uuid

import numpy as np
from PIL import Image


user32 = C.WinDLL("user32", use_last_error=True)
kernel32 = C.WinDLL("kernel32", use_last_error=True)
gdi32 = C.WinDLL("gdi32", use_last_error=True)
shell32 = C.WinDLL("shell32", use_last_error=True)


def _bind(dll, name, result, args):
    fn = getattr(dll, name)
    fn.restype, fn.argtypes = result, args
    return fn


_bind(kernel32, "OpenProcess", W.HANDLE, [W.DWORD, W.BOOL, W.DWORD])
_bind(kernel32, "CloseHandle", W.BOOL, [W.HANDLE])
_bind(kernel32, "VirtualAllocEx", W.LPVOID, [W.HANDLE, W.LPVOID, C.c_size_t, W.DWORD, W.DWORD])
_bind(kernel32, "VirtualFreeEx", W.BOOL, [W.HANDLE, W.LPVOID, C.c_size_t, W.DWORD])
for _name in ("ReadProcessMemory", "WriteProcessMemory"):
    _bind(kernel32, _name, W.BOOL, [W.HANDLE, W.LPCVOID, W.LPVOID, C.c_size_t, C.POINTER(C.c_size_t)])
_bind(user32, "SendMessageTimeoutW", C.c_ssize_t,
      [W.HWND, W.UINT, C.c_size_t, C.c_ssize_t, W.UINT, W.UINT, C.POINTER(C.c_size_t)])
_bind(user32, "GetWindowThreadProcessId", W.DWORD, [W.HWND, C.POINTER(W.DWORD)])
_bind(user32, "GetDC", W.HDC, [W.HWND])
_bind(user32, "ReleaseDC", C.c_int, [W.HWND, W.HDC])
_bind(user32, "DrawIconEx", W.BOOL, [W.HDC, C.c_int, C.c_int, W.HICON, C.c_int, C.c_int, W.UINT, W.HBRUSH, W.UINT])
_bind(user32, "DestroyIcon", W.BOOL, [W.HICON])
_bind(user32, "SystemParametersInfoW", W.BOOL, [W.UINT, W.UINT, W.LPVOID, W.UINT])
_bind(user32, "GetDpiForWindow", W.UINT, [W.HWND])
_bind(gdi32, "CreateCompatibleDC", W.HDC, [W.HDC])
_bind(gdi32, "DeleteDC", W.BOOL, [W.HDC])
_bind(gdi32, "DeleteObject", W.BOOL, [W.HGDIOBJ])
_bind(gdi32, "SelectObject", W.HGDIOBJ, [W.HDC, W.HGDIOBJ])
_bind(gdi32, "GetObjectW", C.c_int, [W.HGDIOBJ, C.c_int, W.LPVOID])


class BITMAPINFOHEADER(C.Structure):
    _fields_ = [("size", W.DWORD), ("width", W.LONG), ("height", W.LONG),
                ("planes", W.WORD), ("bits", W.WORD), ("compression", W.DWORD),
                ("image_size", W.DWORD), ("xppm", W.LONG), ("yppm", W.LONG),
                ("colors_used", W.DWORD), ("colors_important", W.DWORD)]


class BITMAPINFO(C.Structure):
    _fields_ = [("header", BITMAPINFOHEADER), ("colors", W.DWORD * 3)]


class BITMAP(C.Structure):
    _fields_ = [("type", W.LONG), ("width", W.LONG), ("height", W.LONG),
                ("stride", W.LONG), ("planes", W.WORD), ("bits", W.WORD),
                ("data", W.LPVOID)]


class LOGFONT(C.Structure):
    _fields_ = [("height", W.LONG), ("width", W.LONG), ("escapement", W.LONG),
                ("orientation", W.LONG), ("weight", W.LONG), ("italic", W.BYTE),
                ("underline", W.BYTE), ("strikeout", W.BYTE), ("charset", W.BYTE),
                ("out_precision", W.BYTE), ("clip_precision", W.BYTE),
                ("quality", W.BYTE), ("pitch_family", W.BYTE), ("face", W.WCHAR * 32)]


_bind(gdi32, "CreateDIBSection", W.HBITMAP,
      [W.HDC, C.POINTER(BITMAPINFO), W.UINT, C.POINTER(W.LPVOID), W.HANDLE, W.DWORD])
_bind(gdi32, "GetDIBits", C.c_int,
      [W.HDC, W.HBITMAP, W.UINT, W.UINT, W.LPVOID, C.POINTER(BITMAPINFO), W.UINT])
_bind(gdi32, "CreateFontIndirectW", W.HFONT, [C.POINTER(LOGFONT)])
_bind(gdi32, "SetBkMode", C.c_int, [W.HDC, C.c_int])
_bind(gdi32, "SetTextColor", W.DWORD, [W.HDC, W.DWORD])
_bind(user32, "DrawTextW", C.c_int, [W.HDC, W.LPCWSTR, C.c_int, C.POINTER(W.RECT), W.UINT])


def _bmi(width: int, height: int) -> BITMAPINFO:
    info = BITMAPINFO()
    info.header = BITMAPINFOHEADER(C.sizeof(BITMAPINFOHEADER), width, -height, 1, 32, 0, 0, 0, 0, 0, 0)
    return info


def _require(ok, operation: str):
    if not ok:
        raise OSError(C.get_last_error(), f"{operation} failed")
    return ok


def send_read(hwnd: int, message: int, wparam: int = 0, lparam: int = 0) -> int:
    """Bound every Explorer message so a hung shell cannot freeze startup."""
    result = C.c_size_t()
    _require(user32.SendMessageTimeoutW(hwnd, message, wparam, lparam, 2, 1500, C.byref(result)),
             f"SendMessageTimeoutW(0x{message:x})")
    return result.value


class ListViewGeometry:
    """Read icon/label rectangles using a disposable remote message buffer.

    VM_WRITE is used only to initialize this newly allocated RECT structure.
    No item-setting messages, desktop-file writes, or position writes exist.
    """

    def __init__(self, hwnd: int):
        self.hwnd = hwnd
        self.process = None
        self.remote = None

    def __enter__(self):
        pid = W.DWORD()
        _require(user32.GetWindowThreadProcessId(self.hwnd, C.byref(pid)), "GetWindowThreadProcessId")
        self.process = _require(kernel32.OpenProcess(0x0400 | 0x0010 | 0x0020 | 0x0008, False, pid.value),
                                "OpenProcess for desktop geometry")
        self.remote = kernel32.VirtualAllocEx(self.process, None, 16, 0x3000, 0x04)
        if not self.remote:
            kernel32.CloseHandle(self.process)
            self.process = None
            raise OSError(C.get_last_error(), "VirtualAllocEx for temporary RECT failed")
        return self

    def rect(self, index: int, portion: int) -> tuple[int, int, int, int]:
        data = C.create_string_buffer(struct.pack("<4i", portion, 0, 0, 0))
        transferred = C.c_size_t()
        _require(kernel32.WriteProcessMemory(self.process, self.remote, data, 16, C.byref(transferred)),
                 "WriteProcessMemory for temporary RECT")
        if not send_read(self.hwnd, 0x100E, index, self.remote):
            raise RuntimeError(f"Explorer did not return rectangle for item {index}")
        _require(kernel32.ReadProcessMemory(self.process, self.remote, data, 16, C.byref(transferred)),
                 "ReadProcessMemory for icon rectangle")
        if transferred.value != 16:
            raise RuntimeError("Incomplete desktop rectangle read")
        return struct.unpack("<4i", data.raw[:16])

    def position(self, index: int) -> tuple[int, int]:
        """Cross-check COM enumeration order against the actual ListView index."""
        if not send_read(self.hwnd, 0x1010, index, self.remote):
            raise RuntimeError(f"Explorer did not return position for item {index}")
        data = C.create_string_buffer(8)
        transferred = C.c_size_t()
        _require(kernel32.ReadProcessMemory(self.process, self.remote, data, 8, C.byref(transferred)),
                 "ReadProcessMemory for icon position")
        if transferred.value != 8:
            raise RuntimeError("Incomplete desktop position read")
        return struct.unpack("<2i", data.raw)

    def __exit__(self, *_):
        if self.remote:
            kernel32.VirtualFreeEx(self.process, self.remote, 0, 0x8000)
        if self.process:
            kernel32.CloseHandle(self.process)


def desktop_logfont(hwnd: int) -> LOGFONT:
    """Copy Explorer's complete LOGFONT; the owned copy is safe to recreate."""
    font = LOGFONT()
    handle = send_read(hwnd, 0x0031)  # WM_GETFONT
    if not handle or not gdi32.GetObjectW(handle, C.sizeof(font), C.byref(font)):
        _require(user32.SystemParametersInfoW(0x001F, C.sizeof(font), C.byref(font), 0), "SPI_GETICONTITLELOGFONT")
    return font


def desktop_font(hwnd: int) -> tuple[str, int]:
    """Read the actual desktop ListView font face and pixel height."""
    font = desktop_logfont(hwnd)
    return font.face, abs(font.height)


def label_to_rgba(text: str, width: int, height: int, source_font: LOGFONT) -> Image.Image:
    """Draw an independent Windows label with native layout and transparent shadow.

    Explorer's label rectangle includes two horizontal and one vertical padding
    pixels. Copying the full LOGFONT preserves weight/charset instead of asking
    an SDL font matcher to guess a member of the font family. Gray antialiasing
    is intentional: ClearType subpixels assume an opaque background and cause
    colored fringes when a transparent label moves over arbitrary wallpaper.
    """
    if width <= 4 or height <= 2:
        raise ValueError(f"Label rectangle is too small: {width}x{height}")
    if not text:
        return Image.new("RGBA", (width, height))
    font = LOGFONT.from_buffer_copy(source_font)
    font.quality = 4  # ANTIALIASED_QUALITY; preserve all other LOGFONT fields.
    dc = _require(gdi32.CreateCompatibleDC(None), "CreateCompatibleDC label")
    bitmap = owned_font = previous_bitmap = previous_font = None
    try:
        owned_font = _require(gdi32.CreateFontIndirectW(C.byref(font)), "CreateFontIndirectW label")
        previous_font = gdi32.SelectObject(dc, owned_font)
        address = W.LPVOID()
        bitmap = _require(gdi32.CreateDIBSection(dc, C.byref(_bmi(width, height)), 0,
                                               C.byref(address), None, 0), "CreateDIBSection label")
        previous_bitmap = gdi32.SelectObject(dc, bitmap)
        gdi32.SetBkMode(dc, 1)  # TRANSPARENT: untouched pixels retain each test background.
        flags = 0x0001 | 0x0010 | 0x0800 | 0x2000 | 0x8000
        composites = []
        for shade in (0, 255):
            C.memset(address, shade, width * height * 4)
            # One-pixel Windows-style drop shadow, then centered foreground.
            for offset, color in ((1, 0x000000), (0, 0xffffff)):
                gdi32.SetTextColor(dc, color)
                rectangle = W.RECT(2 + offset, 1 + offset, width - 2 + offset, height - 1 + offset)
                _require(user32.DrawTextW(dc, text, -1, C.byref(rectangle), flags), "DrawTextW desktop label")
            composites.append(np.frombuffer(C.string_at(address, width * height * 4), dtype=np.uint8)
                              .reshape(height, width, 4).copy())
        return rgba_from_composites(*composites)
    finally:
        if previous_bitmap:
            gdi32.SelectObject(dc, previous_bitmap)
        if previous_font:
            gdi32.SelectObject(dc, previous_font)
        if bitmap:
            gdi32.DeleteObject(bitmap)
        if owned_font:
            gdi32.DeleteObject(owned_font)
        gdi32.DeleteDC(dc)


def rgba_from_composites(black: np.ndarray, white: np.ndarray) -> Image.Image:
    """Recover alpha from two actual GDI composites, preserving opaque black.

    This is algebraic alpha reconstruction, not a black color key. It also
    handles old mask-based icons whose HICON has no usable alpha channel.
    """
    b = black[..., :3].astype(np.float32)
    w = white[..., :3].astype(np.float32)
    alpha = np.clip(255.0 - np.max(w - b, axis=2), 0, 255)
    rgb = np.zeros_like(b)
    np.divide(b * 255.0, alpha[..., None], out=rgb, where=alpha[..., None] > 0)
    out = np.dstack((np.clip(np.rint(rgb), 0, 255), np.rint(alpha))).astype(np.uint8)
    return Image.fromarray(out[..., [2, 1, 0, 3]], "RGBA")


def icon_to_rgba(hicon: int, width: int, height: int) -> Image.Image:
    """Rasterize a Shell HICON at its display dimensions without screenshots."""
    dc = _require(gdi32.CreateCompatibleDC(None), "CreateCompatibleDC")
    bitmap = None
    previous = None
    try:
        address = W.LPVOID()
        bitmap = _require(gdi32.CreateDIBSection(dc, C.byref(_bmi(width, height)), 0, C.byref(address), None, 0),
                          "CreateDIBSection")
        previous = gdi32.SelectObject(dc, bitmap)
        composites = []
        for shade in (0, 255):
            C.memset(address, shade, width * height * 4)
            _require(user32.DrawIconEx(dc, 0, 0, hicon, width, height, 0, None, 3), "DrawIconEx")
            composites.append(np.frombuffer(C.string_at(address, width * height * 4), dtype=np.uint8)
                              .reshape(height, width, 4).copy())
        return rgba_from_composites(*composites)
    finally:
        if previous:
            gdi32.SelectObject(dc, previous)
        if bitmap:
            gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(dc)


class GUID(C.Structure):
    _fields_ = [("data", C.c_ubyte * 16)]

    @classmethod
    def parse(cls, value: str):
        result = cls()
        result.data[:] = uuid.UUID(value).bytes_le
        return result


class SIZE(C.Structure):
    _fields_ = [("cx", W.LONG), ("cy", W.LONG)]


def _method(pointer, index, result, *args):
    table = C.cast(pointer, C.POINTER(C.POINTER(W.LPVOID))).contents
    return C.WINFUNCTYPE(result, W.LPVOID, *args)(table[index])


def view_icon_size(folder_view) -> tuple[int, int]:
    """Read IFolderView2's size through COM's official Global Interface Table.

    pywin32 lacks an IFolderView2 wrapper. The GIT safely bridges its supported
    IFolderView object to ctypes without inspecting Python object memory.
    """
    import pythoncom
    import pywintypes
    iid_text = "1af3a467-214f-4298-908e-06b03e0b39f9"
    iid = pywintypes.IID("{" + iid_text + "}")
    bridge = pythoncom.CoCreateInstance(pythoncom.CLSID_StdGlobalInterfaceTable, None, 1,
                                       pythoncom.IID_IGlobalInterfaceTable)
    cookie = bridge.RegisterInterfaceInGlobal(folder_view, iid)
    ole32 = C.WinDLL("ole32")
    create = _bind(ole32, "CoCreateInstance", C.c_long,
                   [C.POINTER(GUID), W.LPVOID, W.DWORD, C.POINTER(GUID), C.POINTER(W.LPVOID)])
    table, interface = W.LPVOID(), W.LPVOID()
    try:
        hr = create(C.byref(GUID.parse(str(pythoncom.CLSID_StdGlobalInterfaceTable))), None, 1,
                    C.byref(GUID.parse(str(pythoncom.IID_IGlobalInterfaceTable))), C.byref(table))
        if hr < 0:
            raise OSError(f"CoCreateInstance GIT HRESULT 0x{hr & 0xffffffff:08x}")
        hr = _method(table, 5, C.c_long, W.DWORD, C.POINTER(GUID), C.POINTER(W.LPVOID))(
            table, cookie, C.byref(GUID.parse(iid_text)), C.byref(interface))
        if hr < 0:
            raise OSError(f"GetInterfaceFromGlobal HRESULT 0x{hr & 0xffffffff:08x}")
        mode, size = C.c_int(), C.c_int()
        hr = _method(interface, 36, C.c_long, C.POINTER(C.c_int), C.POINTER(C.c_int))(
            interface, C.byref(mode), C.byref(size))
        if hr < 0:
            raise OSError(f"GetViewModeAndIconSize HRESULT 0x{hr & 0xffffffff:08x}")
        return mode.value, size.value
    finally:
        if interface:
            _method(interface, 2, W.ULONG)(interface)
        if table:
            _method(table, 2, W.ULONG)(table)
        bridge.RevokeInterfaceFromGlobal(cookie)


_bind(shell32, "SHCreateItemFromIDList", C.c_long, [W.LPCVOID, C.POINTER(GUID), C.POINTER(W.LPVOID)])
_bind(shell32, "SHGetImageList", C.c_long, [C.c_int, C.POINTER(GUID), C.POINTER(W.LPVOID)])


def large_shell_icon(item: bytes, target_size: int) -> tuple[int, tuple[int, int]]:
    """Get a suitably detailed system icon with its actual Shell overlay index."""
    from win32com.shell import shell
    # ICON is required by OVERLAYINDEX. Destroy its temporary low-resolution copy.
    result, info = shell.SHGetFileInfo([item], 0, 0x8 | 0x100 | 0x4000 | 0x40)
    if not result:
        raise OSError("SHGetFileInfo could not resolve system icon index")
    if info[0]:
        user32.DestroyIcon(info[0])
    image_index = info[1] & 0x00ffffff
    overlay_index = (info[1] >> 24) & 0xff
    iid = GUID.parse("46eb5926-582e-4017-9fdf-e8998daa0950")
    image_list = W.LPVOID()
    hr = shell32.SHGetImageList(2, C.byref(iid), C.byref(image_list))
    if hr < 0:
        raise OSError(f"SHGetImageList HRESULT 0x{hr & 0xffffffff:08x}")
    try:
        width, height = C.c_int(), C.c_int()
        hr = _method(image_list, 16, C.c_long, C.POINTER(C.c_int), C.POINTER(C.c_int))(
            image_list, C.byref(width), C.byref(height))
        if hr < 0:
            raise OSError(f"IImageList.GetIconSize HRESULT 0x{hr & 0xffffffff:08x}")
        if target_size > width.value:
            _method(image_list, 2, W.ULONG)(image_list)
            image_list = W.LPVOID()
            hr = shell32.SHGetImageList(4, C.byref(iid), C.byref(image_list))
            if hr < 0:
                raise OSError(f"SHGetImageList JUMBO HRESULT 0x{hr & 0xffffffff:08x}")
            width.value = height.value = 256
        icon = W.HICON()
        hr = _method(image_list, 10, C.c_long, C.c_int, W.UINT, C.POINTER(W.HICON))(
            image_list, image_index, 1 | (overlay_index << 8), C.byref(icon))
        if hr < 0 or not icon:
            raise OSError(f"IImageList.GetIcon HRESULT 0x{hr & 0xffffffff:08x}")
        return icon.value, (width.value, height.value)
    finally:
        if image_list:
            _method(image_list, 2, W.ULONG)(image_list)


def thumbnail_from_pidl(item: bytes, width: int, height: int) -> Image.Image:
    """Request an independent Shell thumbnail; raises if none exists."""
    pidl = C.create_string_buffer(struct.pack("<H", len(item) + 2) + item + b"\0\0")
    iid = GUID.parse("bcc18b79-ba16-442f-80c4-8a59c30c463b")
    factory = W.LPVOID()
    hr = shell32.SHCreateItemFromIDList(pidl, C.byref(iid), C.byref(factory))
    if hr < 0:
        raise OSError(f"SHCreateItemFromIDList HRESULT 0x{hr & 0xffffffff:08x}")
    bitmap = W.HBITMAP()
    try:
        # THUMBNAILONLY | BIGGERSIZEOK | INCACHEONLY: no thumbnail handler launch.
        hr = _method(factory, 3, C.c_long, SIZE, W.DWORD, C.POINTER(W.HBITMAP))(
            factory, SIZE(width, height), 0x19, C.byref(bitmap))
        if hr < 0:
            raise OSError(f"Shell thumbnail HRESULT 0x{hr & 0xffffffff:08x}")
        desc = BITMAP()
        _require(gdi32.GetObjectW(bitmap, C.sizeof(desc), C.byref(desc)), "GetObjectW thumbnail")
        buffer = C.create_string_buffer(desc.width * desc.height * 4)
        dc = _require(gdi32.CreateCompatibleDC(None), "CreateCompatibleDC thumbnail")
        try:
            _require(gdi32.GetDIBits(dc, bitmap, 0, desc.height, buffer,
                                   C.byref(_bmi(desc.width, desc.height)), 0), "GetDIBits thumbnail")
        finally:
            gdi32.DeleteDC(dc)
        arr = np.frombuffer(buffer, dtype=np.uint8).reshape(desc.height, desc.width, 4).copy()
        alpha = arr[..., 3].astype(np.float32)
        if not alpha.any():
            arr[..., 3] = 255
        else:
            rgb = arr[..., :3].astype(np.float32)
            np.divide(rgb * 255, alpha[..., None], out=rgb, where=alpha[..., None] > 0)
            arr[..., :3] = np.clip(np.rint(rgb), 0, 255).astype(np.uint8)
        image = Image.fromarray(arr[..., [2, 1, 0, 3]], "RGBA")
        image.thumbnail((width, height), Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (width, height))
        canvas.alpha_composite(image, ((width - image.width) // 2, (height - image.height) // 2))
        return canvas
    finally:
        if bitmap:
            gdi32.DeleteObject(bitmap)
        _method(factory, 2, W.ULONG)(factory)
