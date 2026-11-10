"""Provider identity/layout tests without touching the actual desktop."""
import struct

import numpy as np
from PIL import Image
import pytest

from desktop_world.desklite import calibrate_grid, decode_layout, parse_tlv, positioned_items, verify_live_item


def _field(tag, value):
    if tag == "S":
        payload = value
    elif tag == "s":
        payload = value.encode("utf-16le")
    else:
        payload = struct.pack("<i", value)
    return tag.encode() + struct.pack("<I", len(payload)) + payload


def test_dtf_preserves_provider_slots_and_paths_without_shell_order_guessing():
    item_values = [20000000, 60000002, 99, r"C:\Desktop\实际图标.lnk", "实际图标", 0, 0, "", 0, 18, -1, 0]
    item = _field("S", b"".join(_field(tag, value) for tag, value in zip("dddssddsdddB", item_values)))
    header = [("d", 60000002), ("s", r"\\.\display1"), ("d", 0), ("d", 1042),
              ("d", 0), ("d", 1920), ("d", 125)]
    tail = b"".join(_field("d", value) for value in [95, 97, 45, 45])
    data = _field("S", b"".join(_field(*f) for f in header) + item + tail)
    group = decode_layout(data)[0]
    assert group["desktop"]
    assert group["layout"] == [95, 97, 45, 45]
    assert group["items"][0]["slot"] == 18
    assert group["items"][0]["path"] == r"C:\Desktop\实际图标.lnk"


@pytest.mark.parametrize("data", [b"S", b"S\xff\xff\xff\x7f", _field("x", 0)])
def test_dtf_corruption_or_unknown_schema_is_refused(data):
    with pytest.raises(ValueError):
        parse_tlv(data)


def _live_grid():
    rng = np.random.default_rng(83)
    images = {}
    reference = np.zeros((200, 160, 3), dtype=np.uint8)
    for slot in (0, 1, 2, 3, 5, 6, 7, 8):
        rgb = rng.integers(40, 255, (16, 16, 3), dtype=np.uint8)
        images[slot] = Image.fromarray(rgb).convert("RGBA")
        col, row = divmod(slot, 5)
        x, y = 12 + col * 40, 5 + row * 40
        reference[y:y + 16, x:x + 16] = rgb
    return reference, images


def test_grid_pitch_is_measured_from_live_assets_not_stored_spacing_guess():
    reference, images = _live_grid()
    result = calibrate_grid(reference, images, 40, 16, 160, 200)
    assert (result["x0"], result["y0"], result["pitch_y"], result["rows"]) == (12, 5, 40, 5)
    assert result["anchor_errors"] == [0, 0]
    assert len(result["checks"]) >= 4


def test_stale_layout_or_foreign_render_layer_is_refused():
    reference, images = _live_grid()
    reference[:, 40:] = 0  # The supposed next column is absent from the visible renderer.
    with pytest.raises(RuntimeError, match="enough live icons"):
        calibrate_grid(reference, images, 40, 16, 160, 200)


def test_missing_calibration_slots_refuses_instead_of_using_explorer_coordinates():
    reference, images = _live_grid()
    del images[0]
    with pytest.raises(RuntimeError, match="first two slots"):
        calibrate_grid(reference, images, 40, 16, 160, 200)


def test_every_item_requires_visual_evidence_at_its_own_position():
    reference, images = _live_grid()
    assert verify_live_item(reference, images[8], 52, 125)["pixel_error"] == 0
    reference[125:141, 52:68] = 0
    with pytest.raises(RuntimeError, match="differs from the live"):
        verify_live_item(reference, images[8], 52, 125)


def test_missing_dark_icon_is_not_accepted_as_a_low_absolute_error():
    image = Image.new("RGBA", (16, 16), (40, 40, 40, 255))
    blank = np.zeros((40, 40, 3), dtype=np.uint8)
    # 40/255 is below the absolute threshold but identical to an empty location.
    with pytest.raises(RuntimeError, match="relative empty-background error=1.000"):
        verify_live_item(blank, image, 4, 4)


def test_unpositioned_desktop_ini_and_empty_slots_are_not_visible_icons():
    visible = {"name": "NVIDIA App", "path": r"C:\Desktop\NVIDIA.lnk", "slot": 0}
    group = {"items": [visible,
                       {"name": "", "path": r"C:\Users\TestUser\Desktop\desktop.ini", "slot": -1},
                       {"name": "", "path": r"C:\Users\Public\Desktop\desktop.ini", "slot": -1},
                       {"name": "", "path": "", "slot": 5}]}
    assert positioned_items(group) == [visible]


@pytest.mark.parametrize("item", [
    {"name": "Lost", "path": "", "slot": 4},
    {"name": "", "path": r"C:\Desktop\visible.lnk", "slot": 4},
    {"name": "", "path": r"C:\Desktop\desktop.ini", "slot": 4},
])
def test_incomplete_visible_items_still_refuse(item):
    with pytest.raises(ValueError, match="incomplete positioned item"):
        positioned_items({"items": [item]})
