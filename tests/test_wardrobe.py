"""Cosmetic transactions and geometry render without touching a real desktop."""
import copy
import os

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame
import pytest

from desktop_world.profile import load_profile
from desktop_world.wardrobe import (OUTFITS, draw_character, equip_outfit, equipped_outfit,
                                    outfit_catalog, purchase_outfit, unlock_outfit)


def test_starter_currency_can_buy_a_cosmetic_without_auto_equipping_or_double_charging(tmp_path):
    data = load_profile(tmp_path / "profile.json")
    assert equipped_outfit(data) == "ghost"
    before = copy.deepcopy(data)
    assert equip_outfit(data, "wizard")["reason"] == "locked"
    assert data == before
    receipt = purchase_outfit(data, "courier")
    assert receipt["ok"] and receipt["cost"] == 70 and receipt["balance"] == 10
    assert equipped_outfit(data) == "ghost"
    before = copy.deepcopy(data)
    assert purchase_outfit(data, "courier")["reason"] == "already_owned"
    assert data == before
    assert equip_outfit(data, "courier")["ok"]
    assert equipped_outfit(data) == "courier"
    before = copy.deepcopy(data)
    assert purchase_outfit(data, "wizard")["reason"] == "insufficient_crystals"
    assert data == before


def test_achievement_unlock_is_idempotent_and_retains_the_equipped_outfit(tmp_path):
    data = load_profile(tmp_path / "profile.json")
    assert unlock_outfit(data, "wizard")["changed"]
    assert not unlock_outfit(data, "wizard")["changed"]
    assert equipped_outfit(data) == "ghost"
    row = next(row for row in outfit_catalog(data) if row["id"] == "wizard")
    assert row["owned"] and not row["affordable"] and not row["equipped"]
    assert data["progression"]["crystals"] == 80


def test_six_outfits_have_distinct_transparent_silhouettes_and_visible_accessories():
    masks = []
    for outfit in OUTFITS:
        canvas = pygame.Surface((160, 160), pygame.SRCALPHA)
        draw_character(canvas, (80, 80), outfit=outfit, scale=2, clock=.2)
        mask = pygame.mask.from_surface(canvas, 128)
        assert mask.count() > 150
        assert canvas.get_at((0, 0)).a == canvas.get_at((159, 159)).a == 0
        masks.append(pygame.image.tobytes(mask.to_surface(setcolor="white", unsetcolor="black"), "RGB"))
    assert len(masks) >= 6 and len(set(masks)) == len(masks)


@pytest.mark.parametrize("outfit", list(OUTFITS))
def test_rendering_supports_animation_hurt_dash_alpha_and_clipped_positions(outfit):
    untouched = pygame.Surface((64, 64), pygame.SRCALPHA)
    untouched.fill((20, 40, 60, 255))
    before = pygame.image.tobytes(untouched, "RGBA")
    draw_character(untouched, (32, 32), outfit, alpha=0)
    assert pygame.image.tobytes(untouched, "RGBA") == before
    canvas = pygame.Surface((64, 64), pygame.SRCALPHA)
    draw_character(canvas, (-1, 8), outfit, scale=.75, clock=1.2, hurt=.2,
                   dashing=True, facing=(-1, 0), alpha=128)
    assert pygame.mask.from_surface(canvas, 1).count() > 0
    assert max(pygame.image.tobytes(canvas, "RGBA")[3::4]) <= 128
