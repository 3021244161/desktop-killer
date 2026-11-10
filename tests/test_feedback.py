"""Transparent, bounded, deterministic feedback with no native desktop access."""
import math
import os

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
import pygame
import pytest

from desktop_world.feedback import ScreenFeedback


def canvas(size=(800, 600)):
    return pygame.Surface(size, pygame.SRCALPHA)


def test_healthy_and_empty_feedback_has_zero_pixels_and_allocates_no_masks():
    feedback = ScreenFeedback()
    surface = canvas()
    feedback.update(1/60, 1.0)
    assert not feedback.render_overlay(surface, (0,0,800,600))
    assert not feedback._edge_cache
    assert surface.get_bounding_rect().size == (0,0)
    assert feedback.offset() == (0,0)


def test_hurt_camera_is_deterministic_bounded_and_decays_to_zero():
    first, second = ScreenFeedback(), ScreenFeedback()
    for feedback in (first,second):
        feedback.receive({"kind":"hurt","damage":50})
    sequence = []
    for _ in range(60):
        first.update(1/120,1)
        second.update(1/120,1)
        assert first.offset() == second.camera_offset
        assert math.hypot(*first.offset()) <= 6
        sequence.append(first.offset())
    assert any(point != (0,0) for point in sequence)
    assert first.offset() == (0,0) and first.flash_alpha == 0


@pytest.mark.parametrize("event", [{"kind":"pulse"},{"kind":"boss"},{"kind":"kill","boss":True},
                                   {"kind":"heavy_hit"},{"kind":"hurt","damage":12,"shield":12}])
def test_supported_flashes_are_mild_colored_edges_not_fullscreen_white(event):
    feedback = ScreenFeedback()
    feedback.receive(event)
    feedback.update(0,1)
    surface = canvas()
    assert feedback.render_overlay(surface,(30,20,730,540))
    assert 0 < surface.get_at((30,20)).a <= 40
    assert surface.get_at((395,290)).a == 0
    assert surface.get_at((0,0)).a == 0
    rgb = surface.get_at((30,20))[:3]
    assert rgb != (255,255,255)


def test_health_vignette_fades_in_breathes_and_clears_after_healing():
    feedback = ScreenFeedback()
    values=[]
    for _ in range(30):
        feedback.update(1/60,.12)
        values.append(feedback.low_health_alpha)
    assert 0 < values[0] < values[-1] <= 80
    surface=canvas()
    feedback.render_overlay(surface,(0,0,800,600))
    assert surface.get_at((0,0)).a > 0
    assert surface.get_at((400,300)).a == 0
    before=feedback.low_health_alpha
    feedback.update(1/60,1)
    assert 0 < feedback.low_health_alpha <= before
    for _ in range(240):
        feedback.update(1/60,1)
    assert feedback.low_health_alpha == 0
    surface.fill((0,0,0,0))
    assert not feedback.render_overlay(surface,(0,0,800,600))


def test_reduced_motion_cancels_transients_and_preserves_static_low_health():
    feedback=ScreenFeedback()
    feedback.receive({"kind":"kill","boss":True})
    feedback.update(1,.1,reduced_motion=True)
    assert feedback.offset() == (0,0) and feedback.flash_alpha == 0
    assert feedback.low_health_alpha > 0
    for _ in range(180):
        feedback.update(1/60,.1,reduced_motion=True)
    values=[]
    for _ in range(180):
        feedback.update(1/60,.1,reduced_motion=True)
        values.append(feedback.low_health_alpha)
    assert len(set(values)) == 1
    feedback.update(1/60,.1,reduced_motion=True,low_health=False)
    assert feedback.low_health_alpha == 0


@pytest.mark.parametrize("active", [False])
def test_inactive_scene_immediately_cancels_pending_and_existing_feedback(active):
    feedback=ScreenFeedback()
    feedback.receive({"kind":"hurt","damage":20})
    feedback.update(.05,.1)
    feedback.receive({"kind":"boss"})
    feedback.update(1/60,.1,active=active)
    assert feedback.offset() == (0,0)
    assert feedback.flash_alpha == feedback.low_health_alpha == 0
    assert not feedback.render_overlay(canvas(),(0,0,800,600))
    feedback.update(0,1,active=True)
    assert feedback.offset() == (0,0) and feedback.flash_alpha == 0


def test_separate_toggles_and_black_center_are_preserved():
    feedback=ScreenFeedback()
    feedback.receive({"kind":"hurt","damage":20})
    feedback.update(0,.1,flashes=False,shake=True,low_health=False)
    assert feedback.offset() != (0,0) and feedback.flash_alpha == 0
    feedback.receive({"kind":"pulse"})
    feedback.update(.4,.1,shake=False)
    assert feedback.offset() == (0,0)
    surface=canvas()
    pygame.draw.rect(surface,(0,0,0,255),(300,200,200,200))
    feedback.render_overlay(surface,(0,0,800,600))
    assert tuple(surface.get_at((400,300))) == (0,0,0,255)


def test_overlay_respects_primary_work_rect_and_callers_clip():
    feedback=ScreenFeedback()
    feedback.update(1,.1)
    surface=canvas((1200,700))
    work=pygame.Rect(100,50,800,600)
    original=pygame.Rect(0,0,850,700)
    surface.set_clip(original)
    feedback.render_overlay(surface,work)
    assert surface.get_clip() == original
    assert surface.get_at((100,50)).a > 0
    for point in ((99,50),(900,50),(100,650),(100,699),(1150,300),(875,300),(500,350)):
        assert surface.get_at(point).a == 0


def test_edge_masks_are_reused_and_small_or_clipped_workareas_are_safe():
    feedback=ScreenFeedback()
    feedback.update(1,.1)
    surface=canvas()
    feedback.render_overlay(surface,(0,0,800,600))
    cached=[id(strip) for value in feedback._edge_cache.values() for strip,point in value]
    feedback.render_overlay(surface,(0,0,800,600))
    assert cached == [id(strip) for value in feedback._edge_cache.values() for strip,point in value]
    for rect in ((-10,-10,40,40),(100,100,1,1),(0,0,0,20),(900,900,20,20)):
        feedback.render_overlay(surface,rect)


@pytest.mark.parametrize("dt", [-1,0,float("nan"),float("inf"),1e100])
def test_extreme_dt_and_invalid_health_never_create_unbounded_effects(dt):
    feedback=ScreenFeedback()
    feedback.receive({"kind":"kill","boss":True})
    feedback.update(dt,float("nan"))
    assert math.hypot(*feedback.offset()) <= 6
    assert 0 <= feedback.flash_alpha <= 40
    assert feedback.low_health_alpha == 0
    feedback.update(1000,1)
    assert feedback.offset() == (0,0) and feedback.flash_alpha == 0


def test_event_burst_is_bounded_and_normal_shots_never_flash():
    feedback=ScreenFeedback()
    for kind in ("shot","hit","kill","upgrade","stage"):
        assert not feedback.receive({"kind":kind})
    for _ in range(10000):
        feedback.receive({"kind":"hurt","damage":10000})
    assert len(feedback._pending) <= 8
    feedback.update(0,1)
    first=feedback.flash_alpha
    feedback.receive({"kind":"kill","boss":True})
    feedback.update(.1,1)
    assert feedback.flash_alpha < first  # No immediate strong re-flash during cooldown.
    assert math.hypot(*feedback.offset()) <= 6


@pytest.mark.parametrize("hp,expected", [(.31,0),(.30,16),(0,80)])
def test_health_threshold_is_visible_but_keeps_a_transparent_center(hp,expected):
    feedback=ScreenFeedback()
    feedback.update(3,hp,reduced_motion=True)
    assert feedback.low_health_alpha == expected
    surface=canvas((1920,1042))
    feedback.render_overlay(surface,surface.get_rect())
    assert surface.get_at((960,0)).a == expected
    assert surface.get_at((960,90)).a == 0
    assert surface.get_at((960,521)).a == 0
    if expected:
        assert surface.get_at((960,60)).a > 0


@pytest.mark.parametrize("size,scale", [((640,360),1),((1920,1042),1),((3840,2084),2)])
def test_red_edge_is_limited_to_scaled_perimeter(size,scale):
    feedback=ScreenFeedback(scale=scale)
    feedback.update(3,0,reduced_motion=True)
    surface=canvas(size)
    feedback.render_overlay(surface,surface.get_rect())
    limit=min(round(90*scale),min(size)//8)
    assert surface.get_at((size[0]//2,limit)).a == 0
    assert surface.get_at((size[0]//2,max(1,limit//2))).a > 0
    assert surface.get_at((size[0]//2,size[1]//2)).a == 0
