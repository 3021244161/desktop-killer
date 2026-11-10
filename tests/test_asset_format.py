"""One-time asset conversion preserves every alpha level and needs no display."""
import os
from types import SimpleNamespace

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

from PIL import Image
import pygame

from desktop_world.prototype import DesktopScene, _native_alpha_surface


def test_native_conversion_preserves_all_alpha_levels_and_black_pixels():
    pixels = bytearray()
    for alpha in range(256):
        pixels.extend((alpha * 13 % 256, alpha * 71 % 256, alpha * 193 % 256, alpha))
        pixels.extend((0, 0, 0, alpha))
        pixels.extend((255, 255, 255, alpha))
    source = pygame.image.frombytes(bytes(pixels), (3, 256), "RGBA")
    reference = pygame.Surface((3, 256), pygame.SRCALPHA)
    converted = _native_alpha_surface(source, reference)
    assert converted.get_masks() == reference.get_masks()
    assert converted.get_flags() & pygame.SRCALPHA
    assert pygame.image.tobytes(converted, "RGBA") == bytes(pixels)
    assert _native_alpha_surface(converted, reference) is converted


def test_scene_builds_native_image_and_label_without_pixel_changes():
    rgba = bytes([0, 0, 0, 255, 200, 50, 100, 128, 255, 255, 255, 0, 80, 90, 10, 1])
    icon = SimpleNamespace(key="native", name="native", x=20, y=30, width=4, height=1,
        label_rect=(20, 33, 24, 34), image=Image.frombytes("RGBA", (4, 1), rgba),
        label_image=Image.frombytes("RGBA", (4, 1), rgba))
    snapshot = SimpleNamespace(bounds=(0, 0, 400, 300), work_area=(0, 0, 400, 300),
        font_name="arial", font_size=12, icons=[icon])
    scene = DesktopScene(snapshot, auto_wake=False)
    actor = scene.actors[0]
    for surface in (actor.image, actor.label):
        assert surface.get_masks() == scene.frame.get_masks()
        assert pygame.image.tobytes(surface, "RGBA") == rgba
