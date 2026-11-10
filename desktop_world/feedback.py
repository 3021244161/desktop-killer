"""Bounded battle feedback on transparent pygame surfaces; no desktop operations."""
from __future__ import annotations

import math

import pygame


def _finite(value, default=0.0):
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return result if math.isfinite(result) else default


class ScreenFeedback:
    """Transient camera offsets and cached perimeter overlays for one work area.

    The caller applies ``offset()`` ONLY to moving battle entities. Home icons,
    labels, ports, HUD and the operating-system desktop must retain their origin.
    ``render_overlay`` accepts a work rectangle in the target surface's LOCAL
    coordinates and preserves that surface's existing clip.
    """

    LOW_COLOR = (171, 31, 45)
    COLORS = {"hurt": (229, 72, 79), "shield": (118, 189, 237),
              "pulse": (117, 223, 193), "boss": (193, 142, 224),
              "boss_kill": (240, 187, 111), "heavy_hit": (233, 179, 111)}
    # Amplitude at 1080p, shake lifetime, edge-flash alpha, flash lifetime.
    RESPONSES = {"hurt": (3.4, .22, 30, .20), "shield": (1.3, .14, 16, .16),
                 "pulse": (1.6, .16, 20, .20), "boss": (3.1, .26, 30, .28),
                 "boss_kill": (6.0, .34, 40, .32), "heavy_hit": (2.5, .18, 24, .20)}

    def __init__(self, scale=1.0):
        scale = _finite(scale, -1)
        if scale <= 0:
            raise ValueError("feedback scale must be a positive finite number")
        self.scale = min(3.0, max(.25, scale))
        self.max_offset = max(1, math.floor(6 * self.scale))
        self._edge_cache = {}
        self._active = True
        self._clock = 0.0
        self._breath_phase = 0.0
        self._last_flash_at = self._last_shake_at = -math.inf
        self.clear()

    def clear(self):
        """Remove every visible effect while retaining reusable edge masks."""
        self._pending = []
        self._shake_age = self._shake_duration = self._shake_peak = 0.0
        self._flash_age = self._flash_duration = self._flash_peak = 0.0
        self._flash_kind = "hurt"
        self._low_alpha = 0.0
        self.low_health_alpha = self.flash_alpha = 0
        self._offset = (0, 0)
        self._last_flash_at = self._last_shake_at = -math.inf

    def receive(self, event):
        """Queue a supported gameplay event; ordinary shots and hits stay quiet."""
        if not isinstance(event, dict):
            return False
        kind = event.get("kind")
        if kind == "kill":
            if not event.get("boss"):
                return False
            kind = "boss_kill"
        if kind not in self.RESPONSES:
            return False
        damage = max(0.0, _finite(event.get("damage"), 12.0))
        if kind == "hurt" and damage > 0 and _finite(event.get("shield")) >= damage:
            kind = "shield"
        response = list(self.RESPONSES[kind])
        if kind == "hurt":
            response[0] = min(4.6, max(2.0, 2.0 + damage * .075))
        self._pending.append((kind, tuple(response)))
        if len(self._pending) > 8:
            # A same-frame burst cannot grow an unbounded queue or amplify energy.
            self._pending = sorted(self._pending, key=lambda item: item[1][0], reverse=True)[:8]
        return True

    def update(self, dt, hp_ratio, active=True, reduced_motion=False, flashes=True,
               shake=True, low_health=True):
        """Advance bounded effects. Inactive scenes immediately clear all feedback."""
        elapsed = max(0.0, _finite(dt))
        # Huge clock jumps still expire effects, without unbounded phase values.
        self._clock += min(elapsed, 10.0)
        self._breath_phase = (self._breath_phase + (elapsed % 10.0) * math.tau * .6) % math.tau
        self._active = bool(active)
        if not self._active:
            self.clear()
            return
        allow_shake = bool(shake) and not reduced_motion
        allow_flash = bool(flashes) and not reduced_motion
        if self._pending:
            if allow_shake and self._clock - self._last_shake_at >= .10:
                _, response = max(self._pending, key=lambda item: item[1][0])
                self._shake_peak = min(float(self.max_offset), response[0] * self.scale)
                self._shake_duration, self._shake_age = response[1], 0.0
                self._last_shake_at = self._clock
            # At most three mild edge accents a second, even for an event flood.
            if allow_flash and self._clock - self._last_flash_at >= .35:
                kind, response = max(self._pending, key=lambda item: item[1][2])
                self._flash_kind = kind
                self._flash_peak, self._flash_duration, self._flash_age = response[2], response[3], 0.0
                self._last_flash_at = self._clock
        self._pending.clear()
        self._shake_age += elapsed
        self._flash_age += elapsed
        if not allow_shake or self._shake_age >= self._shake_duration:
            self._offset = (0, 0)
            self._shake_peak = 0.0
        else:
            decay = (1.0 - self._shake_age / self._shake_duration) ** 2
            amplitude = self._shake_peak * decay
            x = math.sin(self._shake_age * 67 + .9)
            y = math.sin(self._shake_age * 49 + 2.1) * .65
            length = max(1.0, math.hypot(x, y))
            ix, iy = round(x / length * amplitude), round(y / length * amplitude)
            while math.hypot(ix, iy) > self.max_offset:
                if abs(ix) >= abs(iy):
                    ix -= 1 if ix > 0 else -1
                else:
                    iy -= 1 if iy > 0 else -1
            self._offset = (ix, iy)
        if not allow_flash or self._flash_age >= self._flash_duration:
            self.flash_alpha = 0
            self._flash_peak = 0.0
        else:
            self.flash_alpha = round(self._flash_peak * (1 - self._flash_age / self._flash_duration) ** 2)

        ratio = min(1.0, max(0.0, _finite(hp_ratio, 1.0)))
        if not low_health:
            self._low_alpha = 0.0
            self.low_health_alpha = 0
            return
        target = 0.0
        if ratio <= .30:
            severity = (0.30 - ratio) / .30
            target = 16.0 + 64.0 * severity ** .7
        duration = .25 if target > self._low_alpha else .45
        self._low_alpha += (target - self._low_alpha) * (1 - math.exp(-elapsed / duration))
        if target == 0 and self._low_alpha < .35:
            self._low_alpha = 0.0
        # Reduced motion removes breathing as well as all transient camera/flash effects.
        breathing = 1.0 if reduced_motion else .94 + .06 * math.sin(self._breath_phase)
        self.low_health_alpha = round(self._low_alpha * breathing)

    def offset(self):
        """Return a deterministic integer camera offset, bounded in vector length."""
        return self._offset

    @property
    def camera_offset(self):
        return self._offset

    def _edges(self, width, height, color):
        thickness = max(1, min(round(90 * self.scale), max(1, min(width, height) // 8)))
        key = (width, height, thickness, color)
        cached = self._edge_cache.get(key)
        if cached is not None:
            return cached
        top = pygame.Surface((width, thickness), pygame.SRCALPHA)
        side = pygame.Surface((thickness, max(1, height - thickness * 2)), pygame.SRCALPHA)
        for depth in range(thickness):
            alpha = round(255 * (1 - depth / thickness) ** 2.2)
            rgba = (*color, alpha)
            pygame.draw.line(top, rgba, (0, depth), (width - 1, depth))
            pygame.draw.line(side, rgba, (depth, 0), (depth, side.get_height() - 1))
        # Corners follow the nearer edge, preventing gaps between the four strips.
        for depth in range(thickness):
            rgba = (*color, round(255 * (1 - depth / thickness) ** 2.2))
            pygame.draw.line(top, rgba, (depth, depth), (depth, thickness - 1))
            pygame.draw.line(top, rgba, (width - depth - 1, depth), (width - depth - 1, thickness - 1))
        cached = ((top, (0, 0)), (pygame.transform.flip(top, False, True), (0, height - thickness)),
                  (side, (0, thickness)), (pygame.transform.flip(side, True, False), (width - thickness, thickness)))
        if len(self._edge_cache) >= 12:
            self._edge_cache.pop(next(iter(self._edge_cache)))
        self._edge_cache[key] = cached
        return cached

    def render_overlay(self, surface, workrect):
        """Blend only cached perimeter strips; the center and other screens stay untouched."""
        if not self._active or not (self.low_health_alpha or self.flash_alpha):
            return False
        rect = pygame.Rect(workrect)
        if rect.width <= 0 or rect.height <= 0:
            return False
        original_clip = surface.get_clip()
        clip = rect.clip(surface.get_rect()).clip(original_clip)
        if not clip.width or not clip.height:
            return False
        surface.set_clip(clip)
        try:
            layers = []
            if self.low_health_alpha:
                layers.append((self.LOW_COLOR, self.low_health_alpha))
            if self.flash_alpha:
                layers.append((self.COLORS[self._flash_kind], self.flash_alpha))
            for color, alpha in layers:
                for strip, position in self._edges(rect.width, rect.height, color):
                    strip.set_alpha(alpha)
                    surface.blit(strip, (rect.x + position[0], rect.y + position[1]))
        finally:
            surface.set_clip(original_clip)
        return True
