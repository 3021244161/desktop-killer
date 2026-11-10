"""Transparent desktop scene; each icon has exactly one continuous visual life."""
from __future__ import annotations

import math
from dataclasses import dataclass

import pygame


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _native_alpha_surface(source: pygame.Surface, reference: pygame.Surface) -> pygame.Surface:
    """Match the offscreen frame's channel masks once, preserving straight RGBA.

    Shell/Pillow assets arrive in RGBA byte order, whereas the native frame uses
    BGRA bytes. Converting during every blit is expensive. A transparent target
    performs this one-time conversion without needing a pygame display window.
    """
    if source.get_bitsize() == reference.get_bitsize() and source.get_masks() == reference.get_masks():
        return source
    native = pygame.Surface(source.get_size(), pygame.SRCALPHA,
                            reference.get_bitsize(), reference.get_masks())
    native.blit(source, (0, 0))
    return native


@dataclass
class Actor:
    key: str
    name: str
    image: pygame.Surface
    label: pygame.Surface
    label_offset: tuple[float, float]
    home: pygame.Vector2
    pos: pygame.Vector2
    state: str = "idle"
    age: float = 0.0
    attack_cooldown: float = 0.0
    velocity: pygame.Vector2 | None = None


class DesktopScene:
    """The background is always transparent. Coordinates are desktop physical pixels."""

    def __init__(self, snapshot, *, auto_wake: bool = True) -> None:
        pygame.font.init()
        self.snapshot = snapshot
        self.bounds = snapshot.bounds
        self.offset = pygame.Vector2(*self.bounds[:2])
        self.size = (self.bounds[2] - self.bounds[0], self.bounds[3] - self.bounds[1])
        self.frame = pygame.Surface(self.size, pygame.SRCALPHA)
        self.font = pygame.font.SysFont(snapshot.font_name, max(10, snapshot.font_size))
        self.ui_font = pygame.font.SysFont("microsoftyaheiui,microsoftyahei,segoeui", 14)
        self.auto_wake = auto_wake
        self.actors: list[Actor] = []
        for icon in snapshot.icons:
            pil = icon.image.convert("RGBA")
            image = pygame.image.frombytes(pil.tobytes(), pil.size, "RGBA")
            if image.get_size() != (icon.width, icon.height):
                image = pygame.transform.smoothscale(image, (icon.width, icon.height))
            native_label = getattr(icon, "label_image", None)
            if native_label is not None:
                native_label = native_label.convert("RGBA")
                label = pygame.image.frombytes(native_label.tobytes(), native_label.size, "RGBA")
            else:
                label = self._label(icon.name, icon.label_rect)
            image = _native_alpha_surface(image, self.frame)
            label = _native_alpha_surface(label, self.frame)
            home = pygame.Vector2(icon.x, icon.y) - self.offset
            self.actors.append(Actor(
                icon.key, icon.name, image, label,
                (icon.label_rect[0] - icon.x, icon.label_rect[1] - icon.y),
                home, home.copy(), velocity=pygame.Vector2(),
            ))
        work = snapshot.work_area
        self.work = pygame.Rect(work[0] - self.bounds[0], work[1] - self.bounds[1],
                                work[2] - work[0], work[3] - work[1])
        self.player = pygame.Vector2(self.work.x + self.work.w * .57,
                                     self.work.y + self.work.h * .57)
        self.player_home = self.player.copy()
        self.time = 0.0
        self.next_wake = 2.4
        self.hurt = 0.0
        self.hits = 0
        self.pulse_age = 99.0
        self.pulse_center = self.player.copy()
        # Tiny, local controls; the rest of the desktop is untouched transparency.
        self.close_rect = pygame.Rect(self.work.right - 104, self.work.bottom - 42, 88, 28)
        self.wake_rect = pygame.Rect(self.close_rect.x - 102, self.close_rect.y, 94, 28)
        self.reset_rect = pygame.Rect(self.wake_rect.x - 72, self.close_rect.y, 64, 28)
        candidates = [a for a in self.actors if self.work.colliderect(
            pygame.Rect(a.home.x, a.home.y, *a.image.get_size()))]
        # A spatial order keeps the first awakening easy to locate on the primary screen.
        self.wake_order = sorted(candidates, key=lambda a: (
            (a.home - self.player).length_squared(), a.key))

    def _label(self, name: str, rect: tuple[int, int, int, int]) -> pygame.Surface:
        width, height = max(1, rect[2] - rect[0]), max(1, rect[3] - rect[1])
        label = pygame.Surface((width + 4, height + 4), pygame.SRCALPHA)
        line_height = self.font.get_linesize()
        max_lines = max(1, min(3, height // max(1, self.font.get_height())))
        remaining = name.replace("\n", " ")
        lines = []
        for index in range(max_lines):
            line = ""
            while remaining and self.font.size(line + remaining[0])[0] <= width:
                line += remaining[0]
                remaining = remaining[1:]
            if index == max_lines - 1 and remaining:
                while line and self.font.size(line + "...")[0] > width:
                    line = line[:-1]
                line += "..."
            lines.append(line)
            if not remaining:
                break
        for i, line in enumerate(lines):
            fg = self.font.render(line, True, (255, 255, 255))
            shadow = self.font.render(line, True, (0, 0, 0))
            x, y = (width - fg.get_width()) // 2, i * line_height
            for dx, dy, alpha in [(1, 1, 180), (-1, 1, 90), (0, 2, 80)]:
                shadow.set_alpha(alpha)
                label.blit(shadow, (x + dx, y + dy))
            label.blit(fg, (x, y))
        return label

    def wake_next(self) -> bool:
        """Wake an existing desktop object; never spawn a second copy."""
        for actor in self.wake_order:
            if actor.state == "idle":
                actor.state, actor.age = "waking", 0.0
                return True
        return False

    def reset(self) -> None:
        for actor in self.actors:
            actor.pos.update(actor.home)
            actor.state, actor.age, actor.attack_cooldown = "idle", 0.0, 0.0
            actor.velocity.update(0, 0)
        self.player.update(self.player_home)
        self.time, self.next_wake, self.hits, self.hurt = 0.0, 2.4, 0, 0.0
        self.pulse_age = 99.0

    def action_at(self, screen_x: int, screen_y: int) -> str | None:
        pos = (screen_x - self.bounds[0], screen_y - self.bounds[1])
        for rect, action in [(self.close_rect, "quit"), (self.wake_rect, "wake"),
                             (self.reset_rect, "reset")]:
            if rect.collidepoint(pos):
                return action
        return "pulse"

    def pulse(self) -> None:
        if self.pulse_age < .8:
            return
        self.pulse_age = 0.0
        self.pulse_center.update(self.player)
        for actor in self.actors:
            if actor.state != "chasing":
                continue
            delta = actor.pos + pygame.Vector2(actor.image.get_size()) / 2 - self.player
            if 0 < delta.length() < 165:
                actor.velocity += delta.normalize() * 420

    def update(self, dt: float, cursor: tuple[float, float], *, demo: bool = False) -> None:
        dt = clamp(dt, 0, .05)
        self.time += dt
        self.hurt = max(0, self.hurt - dt)
        self.pulse_age += dt
        if self.auto_wake and self.time >= self.next_wake:
            if sum(a.state != "idle" for a in self.actors) < 6:
                self.wake_next()
            self.next_wake += 4.0
        target = pygame.Vector2(cursor) - self.offset
        if demo:
            target = self.player_home + pygame.Vector2(
                math.sin(self.time * .48) * 100, math.cos(self.time * .37) * 70)
        target.x = clamp(target.x, self.work.left + 22, self.work.right - 22)
        target.y = clamp(target.y, self.work.top + 22, self.work.bottom - 55)
        delta = target - self.player
        if self.time > 1.2 and delta.length() > 8:
            self.player += delta.normalize() * min(delta.length() - 8, 260 * dt)
        for actor in self.actors:
            if actor.state == "idle":
                continue
            actor.age += dt
            actor.attack_cooldown = max(0, actor.attack_cooldown - dt)
            if actor.state == "waking":
                if actor.age >= .85:
                    actor.state, actor.age = "chasing", 0.0
                continue
            center = actor.pos + pygame.Vector2(actor.image.get_size()) / 2
            delta = self.player - center
            distance = delta.length()
            if distance > 0:
                direction = delta / distance
                speed = 78 + min(42, actor.age * 4)
                if distance < 120 and actor.attack_cooldown <= 0:
                    speed = 210
                actor.pos += direction * min(distance, speed * dt)
                if distance < max(actor.image.get_width() * .35, 16) + 10:
                    if actor.attack_cooldown <= 0:
                        self.hits += 1
                        self.hurt = .32
                        actor.attack_cooldown = 1.3
                        actor.velocity -= direction * 240
            actor.pos += actor.velocity * dt
            actor.velocity *= max(0, 1 - dt * 5)
            actor.pos.x = clamp(actor.pos.x, self.work.left, self.work.right - actor.image.get_width())
            actor.pos.y = clamp(actor.pos.y, self.work.top, self.work.bottom - actor.image.get_height())

    def render(self) -> pygame.Surface:
        self.frame.fill((0, 0, 0, 0))
        for actor in self.actors:
            self._draw_actor(actor)
        if self.time > 1.1:
            self._draw_player()
            self._draw_controls()
        if self.pulse_age < .5:
            radius = int(20 + self.pulse_age * 300)
            pygame.draw.circle(self.frame, (170, 255, 228, int(190 * (1 - self.pulse_age / .5))),
                               self.pulse_center, radius, 2)
        return self.frame

    def _draw_actor(self, actor: Actor) -> None:
        if actor.state == "idle":
            self.frame.blit(actor.image, actor.home)
            self.frame.blit(actor.label, actor.home + actor.label_offset)
            return
        image = actor.image
        if actor.state == "waking":
            progress = clamp(actor.age / .85, 0, 1)
            angle = math.sin(progress * math.pi * 5) * 8 * progress
            lift = math.sin(progress * math.pi / 2) * 7
            label_alpha = int(255 * (1 - progress * .8))
        else:
            angle = math.sin(actor.age * 9) * 7
            lift = 7 + abs(math.sin(actor.age * 5)) * 4
            label_alpha = max(0, int(50 * (1 - actor.age / .5)))
        center = actor.pos + pygame.Vector2(image.get_size()) / 2
        shadow_alpha = int(65 * min(1, actor.age * 3))
        shadow_rect = pygame.Rect(0, 0, int(image.get_width() * .85), 8)
        shadow_rect.midtop = (int(center.x), int(actor.pos.y + image.get_height() - 2))
        pygame.draw.ellipse(self.frame, (0, 0, 0, shadow_alpha), shadow_rect)
        turned = pygame.transform.rotozoom(image, angle, 1.0)
        self.frame.blit(turned, turned.get_rect(center=(round(center.x), round(center.y - lift))))
        if label_alpha:
            label = actor.label.copy()
            label.set_alpha(label_alpha)
            self.frame.blit(label, actor.pos + actor.label_offset)

    def _draw_player(self) -> None:
        x, y = round(self.player.x), round(self.player.y)
        alpha = int(255 * clamp((self.time - 1.1) / .6, 0, 1))
        pygame.draw.ellipse(self.frame, (0, 0, 0, alpha // 4), (x - 10, y + 13, 22, 7))
        bob = round(math.sin(self.time * 8) * 1.5)
        color = (255, 126, 113, alpha) if self.hurt else (244, 247, 239, alpha)
        outline = (42, 59, 60, alpha)
        body = [(x - 8, y - 11 + bob), (x + 5, y - 11 + bob),
                (x + 11, y - 5 + bob), (x + 8, y + 10 + bob),
                (x + 3, y + 7 + bob), (x - 1, y + 13 + bob),
                (x - 7, y + 9 + bob), (x - 10, y - 3 + bob)]
        pygame.draw.polygon(self.frame, outline, body)
        inner = [(x + (px - x) * .8, y + (py - y) * .8) for px, py in body]
        pygame.draw.polygon(self.frame, color, inner)
        pygame.draw.line(self.frame, (30, 64, 62, alpha), (x - 3, y - 2 + bob), (x - 3, y + 1 + bob), 2)
        pygame.draw.line(self.frame, (30, 64, 62, alpha), (x + 4, y - 2 + bob), (x + 4, y + 1 + bob), 2)
        if self.hurt:
            pygame.draw.circle(self.frame, (255, 150, 130, int(alpha * self.hurt / .32)), (x, y), 23, 2)

    def _draw_controls(self) -> None:
        for rect, title in [(self.reset_rect, "重演"), (self.wake_rect, "唤醒图标"),
                            (self.close_rect, "退出 · Esc")]:
            pygame.draw.rect(self.frame, (23, 30, 34, 210), rect, border_radius=7)
            pygame.draw.rect(self.frame, (206, 230, 220, 75), rect, 1, border_radius=7)
            text = self.ui_font.render(title, True, (230, 240, 235))
            self.frame.blit(text, text.get_rect(center=rect.center))
        if self.time < 12:
            text = self.ui_font.render("鼠标引导小人  ·  空格唤醒  ·  F5 还原桌面", True, (245, 250, 247))
            rect = text.get_rect(bottomright=(self.close_rect.right, self.close_rect.top - 9))
            pygame.draw.rect(self.frame, (20, 28, 32, 195), rect.inflate(14, 10), border_radius=5)
            self.frame.blit(text, rect)
