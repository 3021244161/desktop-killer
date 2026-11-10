"""Visual lifecycle invariants that the original screenshot implementation missed."""
import os
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

from types import SimpleNamespace

from PIL import Image, ImageDraw
import pygame

from desktop_world.scene import DesktopScene


def snapshot(bounds=(0, 0, 800, 600)):
    image = Image.new("RGBA", (32, 32))
    ImageDraw.Draw(image).ellipse((4, 4, 27, 27), fill=(0, 0, 0, 255))
    icon = SimpleNamespace(key="one", name="", x=bounds[0] + 50, y=bounds[1] + 60,
                           width=32, height=32, image=image,
                           label_rect=(bounds[0] + 40, bounds[1] + 95, bounds[0] + 100, bounds[1] + 115))
    return SimpleNamespace(bounds=bounds, work_area=bounds, icons=[icon], font_name="arial", font_size=12)


def test_idle_preserves_origin_size_and_black_pixels():
    scene = DesktopScene(snapshot(), auto_wake=False)
    frame = scene.render()
    assert frame.get_at((65, 75)) == (0, 0, 0, 255)
    assert frame.get_at((50, 60)).a == 0
    assert frame.get_at((200, 200)).a == 0
    assert scene.actors[0].image.get_size() == (32, 32)


def test_departure_leaves_no_copy_at_origin():
    scene = DesktopScene(snapshot(), auto_wake=False)
    assert scene.wake_next()
    for _ in range(100):
        scene.update(.05, (600, 400))
    assert scene.actors[0].state == "chasing"
    assert scene.render().get_at((65, 75)).a == 0
    assert len(scene.actors) == 1
    assert not scene.wake_next()


def test_waking_starts_on_same_object_without_teleport():
    scene = DesktopScene(snapshot(), auto_wake=False)
    before = scene.actors[0].pos.copy()
    scene.wake_next()
    scene.update(.1, (500, 300))
    assert scene.actors[0].pos == before
    assert scene.actors[0].state == "waking"


def test_reset_restores_exact_origins():
    scene = DesktopScene(snapshot())
    for _ in range(120):
        scene.update(.05, (500, 300))
    scene.reset()
    assert scene.actors[0].pos == scene.actors[0].home
    assert scene.actors[0].state == "idle"
    assert scene.render().get_at((65, 75)).a == 255


def test_negative_virtual_screen_origin_is_normalized_once():
    scene = DesktopScene(snapshot((-800, -100, 0, 500)), auto_wake=False)
    assert scene.actors[0].home == pygame.Vector2(50, 60)
    assert scene.render().get_at((65, 75)).a == 255
    assert scene.action_at(-800 + scene.close_rect.centerx, -100 + scene.close_rect.centery) == "quit"
