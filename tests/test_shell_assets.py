"""Check the properties that prevent square screenshot sprites and DPI jumps."""
import sys

import numpy as np
import pytest

from desktop_world.shell import DesktopReadError, _image_bounds, _screen_rect


def test_physical_image_bounds_use_real_size_not_click_target():
    assert _image_bounds((0, 5, 94, 63), 43, 120) == (20, 7, 74, 61)


def test_secondary_monitor_keeps_negative_coordinates():
    layout = _screen_rect((0, 5, 94, 63), (-1920, -1080))
    assert _image_bounds(layout, 43, 120) == (-1900, -1073, -1846, -1019)


def test_incompatible_layout_refuses_instead_of_distorting_sprite():
    with pytest.raises(DesktopReadError, match="does not fit"):
        _image_bounds((0, 0, 30, 30), 48, 192)


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 rasterization module")
def test_alpha_reconstruction_preserves_black_and_transparency():
    from desktop_world.shell_native import rgba_from_composites
    # BGRA samples: opaque black, transparent, half-transparent red, opaque blue.
    black = np.array([[[0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 128, 0], [255, 0, 0, 0]]], dtype=np.uint8)
    white = np.array([[[0, 0, 0, 0], [255, 255, 255, 0], [127, 127, 255, 0], [255, 0, 0, 0]]], dtype=np.uint8)
    image = rgba_from_composites(black, white)
    assert image.getpixel((0, 0)) == (0, 0, 0, 255)
    assert image.getpixel((1, 0)) == (0, 0, 0, 0)
    assert image.getpixel((2, 0)) == (255, 0, 0, 128)
    assert image.getpixel((3, 0)) == (0, 0, 255, 255)


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 rasterization module")
def test_mask_based_hicon_preserves_opaque_black():
    """Exercise actual DrawIconEx, including classic AND/XOR mask icons."""
    import ctypes
    from ctypes import wintypes
    import win32gui
    from desktop_world.shell_native import icon_to_rgba, user32
    # 16x16 monochrome icon: left half opaque black, right half transparent.
    and_mask = b"\x00\xff" * 16
    xor_mask = b"\x00\x00" * 16
    create = user32.CreateIcon
    create.restype = wintypes.HICON
    create.argtypes = [wintypes.HINSTANCE, ctypes.c_int, ctypes.c_int,
                       wintypes.BYTE, wintypes.BYTE, ctypes.c_void_p, ctypes.c_void_p]
    icon = create(None, 16, 16, 1, 1, and_mask, xor_mask)
    assert icon
    try:
        image = icon_to_rgba(icon, 16, 16)
        assert image.getpixel((2, 8)) == (0, 0, 0, 255)
        assert image.getpixel((12, 8)) == (0, 0, 0, 0)
    finally:
        win32gui.DestroyIcon(icon)


@pytest.mark.skipif(sys.platform != "win32", reason="Native Windows text layout")
def test_native_label_keeps_transparency_shadow_and_grayscale_edges():
    from desktop_world.shell_native import LOGFONT, label_to_rgba
    font = LOGFONT()
    font.face, font.height, font.weight = "Microsoft YaHei UI", -15, 400
    image = label_to_rgba("报告.docx", 74, 22, font)
    pixels = np.array(image)
    assert image.size == (74, 22)
    assert image.getchannel("A").getextrema() == (0, 255)
    assert np.array_equal(pixels[..., 0], pixels[..., 1])
    assert np.array_equal(pixels[..., 1], pixels[..., 2])
    assert ((pixels[..., 0] == 0) & (pixels[..., 3] > 0)).any()  # real transparent black shadow
    assert font.quality == 0  # Rendering doesn't change the captured Explorer font.


@pytest.mark.skipif(sys.platform != "win32", reason="Native Windows text layout")
def test_native_label_wraps_mixed_chinese_english_within_real_rectangle():
    from desktop_world.shell_native import LOGFONT, label_to_rgba
    font = LOGFONT()
    font.face, font.height, font.weight = "Microsoft YaHei UI", -15, 400
    image = label_to_rgba("这是一个很长的 English 文件名称及内容.docx", 94, 42, font)
    alpha = np.array(image.getchannel("A"))
    assert alpha[:20].max() == 255
    assert alpha[22:].max() == 255
    assert image.size == (94, 42)
    # The trailing text is outside the two-line display and must be ellipsized.
    same_visible_prefix = label_to_rgba("这是一个很长的 English 文件名称及完全不同的尾部.pdf", 94, 42, font)
    assert image.tobytes() == same_visible_prefix.tobytes()


@pytest.mark.skipif(sys.platform != "win32", reason="Native Windows text layout")
def test_native_label_ampersand_is_filename_text_not_keyboard_mnemonic():
    from desktop_world.shell_native import LOGFONT, label_to_rgba
    font = LOGFONT()
    font.face, font.height, font.weight = "Microsoft YaHei UI", -15, 400
    literal = label_to_rgba("A&B.txt", 94, 22, font)
    no_ampersand = label_to_rgba("AB.txt", 94, 22, font)
    assert literal.tobytes() != no_ampersand.tobytes()
