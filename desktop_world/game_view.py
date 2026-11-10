"""Transparent game presentation: desktop objects, combat feedback and local panels."""
from __future__ import annotations

import math
import random
import uuid

import pygame

from .prototype import DesktopScene as AssetScene
from .scene import GameSession
from .product_view import ProductViews
from .feedback import ScreenFeedback


MODES = {
    "campaign": ("重启行动", "三章闯关 · 断链、成长、击破主控", "01"),
    "blitz": ("极速清理", "三分钟挑战 · 更快成长，更密集的复活", "02"),
    "endless": ("无限循环", "持续升级的危机 · 挑战最高分", "03"),
    "drawing": ("画画模式", "画下线条 · 让图标走成你的形状", "04"),
}
INK = (23, 30, 35)
WHITE = (239, 244, 241)
DIM = (158, 176, 176)
MINT = (117, 236, 189)
GOLD = (255, 192, 102)
RED = (255, 111, 111)
BLUE = (124, 192, 249)


class GameView(ProductViews):
    """Render GameSession while keeping the actual desktop beneath transparent."""

    def __init__(self, snapshot, profile=None, audio=None, on_result=None,
                 *, start_mode=None, seed=None, on_profile_change=None):
        self.assets = AssetScene(snapshot, auto_wake=False)
        self.snapshot = snapshot
        self.frame = self.assets.frame
        self.offset = self.assets.offset
        self.work = self.assets.work
        self.scale = max(.48, min(1.7, self.work.h / 1042))
        self.feedback = ScreenFeedback(scale=self.scale)
        self._foreground = True
        self.profile = profile if profile is not None else {}
        self._profile_cache = {}
        self.audio = audio
        self.on_result = on_result
        self.on_profile_change = on_profile_change
        self.page = "home"
        self.toast = ""
        self.toast_left = 0.0
        self.reward = {}
        self.run_id = ""
        self.drawing_paused = False
        self._drawing_started = self._drawing_chord = False
        self._drawing_wait_release = False
        self._drawing_demo_done = False
        self._drawing_ui_rect = pygame.Rect(0, 0, 0, 0)
        self.seed = seed
        self.session = None
        self.mode = start_mode or "campaign"
        self.clock = 0.0
        self.hover = (0, 0)
        self.buttons = []
        self.result_written = False
        self.new_record = False
        self.paused_by_focus = False
        self.quit_requested = False
        self.notice = ""
        self.notice_left = 0.0
        self.particles = []
        self.control_mode = "mouse"
        self._last_cursor = None
        self._movement = (0, 0)
        self._demo_wait = 0.0
        self._random = random.Random(104)
        self._image_cache = {}
        self._visual = {actor.key: actor for actor in self.assets.actors}
        self.fonts = {size: pygame.font.SysFont("microsoftyaheiui,microsoftyahei,segoeui", max(8, round(size * self.scale)))
                      for size in (11, 12, 13, 14, 16, 18, 22, 28, 36)}
        self.icons = [dict(key=icon.key, name=icon.name,
                           home=(icon.x + icon.width / 2, icon.y + icon.height / 2),
                           size=(icon.width, icon.height)) for icon in snapshot.icons]
        # Off-primary-screen originals are still drawn, but do not become combat targets.
        l, t, r, b = snapshot.work_area
        self.play_icons = [icon for icon in self.icons if l <= icon["home"][0] < r and t <= icon["home"][1] < b]
        if not self.play_icons:
            raise RuntimeError("主屏没有可参与战斗的图标，请把至少一个图标放到主屏。")
        if start_mode:
            self.start(start_mode)

    @property
    def actors(self):
        return self.session.actors if self.session else self.assets.actors

    @property
    def time(self):
        return getattr(self.session, "total_time", 0.0)

    @property
    def hits(self):
        return getattr(getattr(self.session, "player", None), "kills", 0)

    def start(self, mode):
        from .progression import talent_bonuses
        from .scene import DrawingSession
        self.mode = mode
        self.feedback.clear()
        self.run_id = uuid.uuid4().hex
        self.reward = {}
        self.session = (DrawingSession(self.play_icons, self.snapshot.work_area) if mode == "drawing" else
                        GameSession(self.play_icons, self.snapshot.work_area, mode=mode,
                                    seed=self.seed, bonuses=talent_bonuses(self.profile)))
        self._drawing_started = self._drawing_chord = False
        self._drawing_wait_release = False
        self._drawing_demo_done = self.drawing_paused = False
        self.result_written = False
        self.new_record = False
        self.paused_by_focus = False
        self.particles.clear()
        self.control_mode = "mouse"
        self._last_cursor = None
        self._demo_wait = 0.0
        self.buttons.clear()
        self.notice = "击碎图标后，靠近原位光环完成断链"
        self.notice_left = 8.0
        if self.profile.get("settings", {}).get("show_hints", True) is False:
            self.notice_left = 0.0

    def _point(self, pos):
        return round(pos[0] - self.offset.x), round(pos[1] - self.offset.y)

    def _camera_point(self, pos):
        # Only moving game objects use this projection. Input, home positions
        # and interface controls remain in unshifted physical screen space.
        x, y = self._point(pos)
        dx, dy = self.feedback.offset()
        return x + dx, y + dy

    def update_audio(self, dt, *, foreground=True):
        if not self.audio or not hasattr(self.audio, "update_music"):
            return
        settings = self.profile.get("settings", {})
        context, paused, suspended = "menu", not foreground, not foreground
        if self.session:
            if self.mode == "drawing":
                context, paused = "drawing", paused or self.drawing_paused
                suspended = suspended or self.drawing_paused
            else:
                context = "boss" if self.session.boss_spawned and not self.session.boss_defeated else "battle"
                paused = paused or self.session.state != "playing"
                suspended = suspended or self.session.state == "paused"
        self.audio.update_music(context, dt, paused=paused,
                                suspended=suspended,
                                enabled=settings.get("music_enabled", True),
                                volume=settings.get("music_volume", .35))

    def _update_feedback(self, dt):
        settings = self.profile.get("settings", {})
        active = (self._foreground and self.session is not None and self.mode != "drawing"
                  and self.session.state == "playing")
        hp_ratio = self.session.player.hp / max(1, self.session.player.max_hp) if active else 1
        self.feedback.update(dt, hp_ratio, active=active,
                             reduced_motion=settings.get("reduced_motion", False),
                             flashes=settings.get("screen_flash", True),
                             shake=settings.get("screen_shake", True),
                             low_health=settings.get("low_health_vignette", True))

    def _text(self, text, pos, color=WHITE, size=14, *, center=False, right=False, surface=None):
        surface = surface or self.frame
        font = self.fonts[size]
        image = font.render(str(text), True, color)
        rect = image.get_rect()
        if center:
            rect.center = pos
        elif right:
            rect.topright = pos
        else:
            rect.topleft = pos
        surface.blit(image, rect)
        return rect

    def _wrap(self, text, x, y, width, color=DIM, size=13, line_limit=3):
        font = self.fonts[size]
        line = ""
        lines = []
        for ch in str(text):
            if ch == "\n" or font.size(line + ch)[0] > width:
                lines.append(line)
                line = "" if ch == "\n" else ch
            else:
                line += ch
        if line:
            lines.append(line)
        for text_line in lines[:line_limit]:
            self._text(text_line, (x, y), color, size)
            y += font.get_linesize() + round(3 * self.scale)
        return y

    def _panel(self, rect, *, accent=MINT):
        shadow = rect.move(0, round(6 * self.scale)).inflate(8, 8)
        pygame.draw.rect(self.frame, (0, 0, 0, 65), shadow, border_radius=round(15 * self.scale))
        pygame.draw.rect(self.frame, (*INK, 247), rect, border_radius=round(12 * self.scale))
        pygame.draw.rect(self.frame, (80, 101, 102, 230), rect, 1, border_radius=round(12 * self.scale))
        pygame.draw.line(self.frame, accent, (rect.x + 20, rect.y), (rect.x + 78, rect.y), 3)

    def _button(self, rect, title, action, *, subtitle="", accent=MINT, number=""):
        if self.scale < .62:
            subtitle = ""
        hover = rect.collidepoint(self.hover)
        pygame.draw.rect(self.frame, (42, 61, 60, 250) if hover else (32, 43, 47, 250), rect, border_radius=7)
        pygame.draw.rect(self.frame, accent if hover else (67, 85, 88), rect, 1, border_radius=7)
        inset = round(14 * self.scale)
        if number:
            self._text(number, (rect.x + inset, rect.y + inset), accent, 13)
            inset += round(35 * self.scale)
        title_y = rect.y + round(10 * self.scale) if subtitle else rect.centery - self.fonts[14].get_height() // 2
        self._text(title, (rect.x + inset, title_y), WHITE, 16 if subtitle else 14)
        if subtitle:
            self._wrap(subtitle, rect.x + inset, rect.y + round(36 * self.scale),
                       rect.w - inset - 10, DIM, 12, 2)
        self.buttons.append((rect, action))

    def _menu_rect(self, height=560, width=430):
        width, height = round(width * self.scale), round(height * self.scale)
        return pygame.Rect(max(self.work.left + 18, self.work.right - width - round(36 * self.scale)),
                           self.work.top + max(20, (self.work.h - height) // 2), width, height)

    def handle_key(self, key, cursor):
        if key == 0x74:
            return "quit"
        if key == 0x70:
            return "help"
        if key == ord("M"):
            self.profile["muted"] = not self.profile.get("muted", False)
            if self.audio:
                self.audio.set_muted(self.profile["muted"])
            return "settings"
        if not self.session:
            if key == 0x1B:
                if self.page != "home":
                    self.page = "home"
                    return None
                return "quit"
            if key == ord("C"):
                self.page = "wardrobe"
            elif key == ord("H"):
                self.page = "career"
            elif self.page == "home" and key in (ord("1"), ord("2"), ord("3"), ord("4")):
                self.start(list(MODES)[key - ord("1")])
            elif key == 0x0D and self.page == "home":
                self.start(self.mode)
            return None
        if self.mode == "drawing":
            if key in (0x1B, ord("P")):
                self.drawing_paused = not self.drawing_paused
                self.session.cancel_stroke()
                self._drawing_started = False
                self._drawing_wait_release = True
            elif key == 0x08:
                self.session.undo()
            elif key == ord("R"):
                self.session.reset()
            elif key == 0x20:
                return self._product_action("setting:drawing_guides")
            return None
        session = self.session
        if key in (0x1B, ord("P")) and session.state not in ("won", "lost"):
            session.toggle_pause()
        elif session.state in ("upgrade", "intermission") and key in (ord("1"), ord("2"), ord("3")):
            self._choose(key - ord("1"))
        elif session.state == "playing":
            if key == 0x20:
                session.pulse()
            elif key == 0x10:
                target = cursor
                if any(self._movement):
                    target = (session.player.x + self._movement[0] * 100,
                              session.player.y + self._movement[1] * 100)
                session.dash(target)
        elif session.state in ("won", "lost"):
            if key in (ord("R"), 0x0D):
                self.start(self.mode)
            elif key == 0x1B:
                self.session = None
        return None

    def _choose(self, index):
        if self.session.state == "upgrade":
            self.session.choose_upgrade(index)
        elif self.session.state == "intermission":
            self.session.choose_stage(index)
        self.buttons.clear()

    def handle_click(self, x, y, button):
        pos = self._point((x, y))
        self.hover = pos
        if button == 1:
            for rect, action in reversed(self.buttons):
                if rect.collidepoint(pos):
                    return self._act(action, (x, y))
        if self.session and self.session.state == "playing":
            if button == 1:
                self.session.pulse()
            elif button == 3:
                self.session.dash((x, y))
        return None

    def _act(self, action, cursor=None):
        if action.startswith(("page:", "outfit:", "talent:", "setting:", "volume:", "preset:", "draw:")) or action in ("help", "open_data", "retry_save"):
            return self._product_action(action)
        if action == "quit":
            return "quit"
        if action in MODES:
            self.start(action)
        elif action == "restart":
            self.start(self.mode)
        elif action == "menu":
            self.session = None
            self.page = "home"
            self.particles.clear()
        elif action == "pause":
            self.session.toggle_pause()
            self.paused_by_focus = False
        elif action == "retire":
            self.session.retire()
        elif action == "pulse":
            self.session.pulse()
        elif action == "dash":
            self.session.dash(cursor or self.session.player.pos)
        elif action.startswith("choice:"):
            self._choose(int(action.split(":")[1]))
        elif action == "mute":
            return self.handle_key(ord("M"), cursor)
        self.buttons.clear()
        return None

    def focus_changed(self, active):
        self._foreground = active
        if not active:
            self.feedback.clear()
        if self.session and self.mode == "drawing":
            if not active:
                self.session.cancel_stroke()
                self._drawing_started = self._drawing_chord = False
                self._drawing_wait_release = True
                self.drawing_paused = True
            return
        if self.session and not active and self.session.state == "playing":
            self.session.toggle_pause()
            self.paused_by_focus = True

    def update(self, dt, cursor, *, keys=(), buttons=(), demo=False):
        self.clock += min(dt, .05)
        self.toast_left = max(0, self.toast_left - dt)
        self.hover = self._point(cursor)
        if not self.session:
            self._update_feedback(dt)
            return
        if self.mode == "drawing":
            self._update_drawing(dt, cursor, keys, buttons, demo)
            self._update_feedback(dt)
            return
        s = self.session
        movement = ((int(0x44 in keys or 0x27 in keys) - int(0x41 in keys or 0x25 in keys)),
                    (int(0x53 in keys or 0x28 in keys) - int(0x57 in keys or 0x26 in keys)))
        self._movement = movement
        if self._last_cursor is None:
            self._last_cursor = tuple(cursor)
        if any(movement):
            self.control_mode = "keyboard"
            self._last_cursor = tuple(cursor)
        elif self.control_mode == "keyboard" and math.dist(cursor, self._last_cursor) > 3:
            # Compare with the last keyboard-position anchor, not the preceding
            # frame: slow 1px mouse movements must eventually reclaim control.
            self.control_mode = "mouse"
        if self.control_mode == "mouse":
            self._last_cursor = tuple(cursor)
        if self.control_mode == "keyboard" and not any(movement):
            cursor = s.player.pos
        if demo:
            cursor = self.demo_cursor()
            if s.state in ("upgrade", "intermission"):
                self._demo_wait += dt
                if self._demo_wait >= 1.2:
                    self._demo_wait = 0.0
                    choices = s.upgrade_choices if s.state == "upgrade" else s.stage_choices
                    priority = {"chain":0,"multishot":1,"blades":2,"overclock":3,"damage":4,"fire_rate":5}
                    if choices:
                        self._choose(min(range(len(choices)), key=lambda i: priority.get(choices[i]["id"], 10)))
            else:
                self._demo_wait = 0.0
        s.update(dt, cursor, movement=movement)
        if s.state == "playing":
            self.notice_left = max(0, self.notice_left - dt)
            for particle in self.particles:
                particle[0] += particle[2] * dt
                particle[1] += particle[3] * dt
                particle[4] -= dt
            self.particles[:] = [p for p in self.particles if p[4] > 0]
        for event in s.drain_events():
            self.feedback.receive(event)
            kind = event.get("kind", "")
            if self.audio:
                sound = "reboot" if kind == "wake" and event.get("generation", 0) > 0 else {
                    "shot": "shoot", "stage": "upgrade", "won": "victory", "lost": "defeat", "pulse": "seal",
                }.get(kind, kind)
                self.audio.play(sound)
            if kind in ("kill", "seal", "hurt", "reboot"):
                color = MINT if kind == "seal" else RED if kind == "hurt" else GOLD
                for _ in range(8 if kind == "kill" else 5):
                    angle = self._random.uniform(0, math.tau)
                    speed = self._random.uniform(25, 105)
                    self.particles.append([event.get("x", s.player.x), event.get("y", s.player.y),
                                           math.cos(angle) * speed, math.sin(angle) * speed, .45, color])
                self.particles[:] = self.particles[-160:]
            if kind == "boss":
                self.notice, self.notice_left = "主控已接管一个图标 · 注意红色预警", 4.0
            elif kind == "surge":
                self.notice, self.notice_left = "入侵回流 · 已断链的图标再次苏醒", 3.0
        self._update_feedback(dt)
        if s.state in ("won", "lost") and not self.result_written:
            self.result_written = True
            summary = dict(s.summary(), run_id=self.run_id)
            if self.on_result:
                result = self.on_result(summary)
                self._profile_cache.clear()
                self.reward = result if isinstance(result, dict) else {}
                self.new_record = bool(self.reward.get("new_record", False) if isinstance(result, dict) else result)
            else:
                from .progression import settle_run
                self.reward = settle_run(self.profile, summary)
                self.new_record = self.reward["new_record"]
                self.reward["saved"] = self._persist()

    def demo_cursor(self):
        """A bounded demo steering policy; it does not grant health or damage cheats."""
        s = self.session
        p = pygame.Vector2(s.player.pos)
        ports = [a for a in s.actors if a.state == "rebooting"]
        if ports:
            return min(ports, key=lambda a: p.distance_squared_to(a.home)).home
        enemies = [a for a in s.actors if a.state == "active"]
        if enemies:
            nearest = min(enemies, key=lambda a: p.distance_squared_to(a.pos))
            delta = p - pygame.Vector2(nearest.pos)
            if delta.length() < 210:
                if delta.length_squared() < 1:
                    delta.update(1, 0)
                point = p + delta.normalize() * 100 + pygame.Vector2(-delta.y, delta.x).normalize() * 65
                return tuple(point)
        l, t, r, b = self.snapshot.work_area
        return ((l + r) / 2 + math.sin(s.total_time * .6) * (r - l) * .22,
                (t + b) / 2 + math.cos(s.total_time * .5) * (b - t) * .24)

    def render(self):
        # Clear transients immediately on modal changes, even without an update.
        self._update_feedback(0)
        self.frame.fill((0, 0, 0, 0))
        self.buttons.clear()
        if not self.session:
            for actor in self.assets.actors:
                self.assets._draw_actor(actor)
            self._draw_product_page()
            self._draw_toast()
            return self.frame
        if self.mode == "drawing":
            self._draw_drawing()
            self._draw_toast()
            return self.frame
        s = self.session
        battle_keys = {a.key for a in s.actors}
        for actor in self.assets.actors:
            if actor.key not in battle_keys:
                self.assets._draw_actor(actor)
        for actor in s.actors:
            if actor.state in ("home", "sealed", "rebooting"):
                self._draw_actor(actor)
        clip = self.frame.get_clip()
        self.frame.set_clip(clip.clip(self.work))
        for actor in s.actors:
            if actor.state not in ("home", "sealed", "rebooting"):
                self._draw_actor(actor)
        for shard in s.shards:
            x, y = self._camera_point(shard.pos)
            pygame.draw.polygon(self.frame, (*MINT, 240), [(x, y-4), (x+4, y), (x, y+4), (x-4, y)])
        self._draw_effects()
        for bullet in s.bullets:
            x, y = self._camera_point(bullet.pos)
            color = RED if bullet.enemy else MINT
            radius = max(2, round(bullet.radius))
            pygame.draw.circle(self.frame, (*color, 55), (x, y), radius + 4)
            pygame.draw.circle(self.frame, (*color, 255), (x, y), radius)
        self._draw_player()
        self._draw_guidance()
        for x, y, vx, vy, life, color in self.particles:
            pygame.draw.circle(self.frame, (*color, round(255 * min(1, life/.25))), self._camera_point((x, y)), 2)
        self.frame.set_clip(clip)
        self.feedback.render_overlay(self.frame, self.work)
        self._draw_hud()
        if s.state in ("upgrade", "intermission"):
            self._draw_choices()
        elif s.state == "paused":
            self._draw_pause()
        elif s.state in ("won", "lost"):
            self._draw_result()
        self._draw_toast()
        return self.frame

    def _draw_actor(self, actor):
        visual = self._visual[actor.key]
        if actor.state == "home":
            self.frame.blit(visual.image, visual.home)
            self.frame.blit(visual.label, visual.home + visual.label_offset)
            return
        home = self._point(actor.home)
        if actor.state == "sealed":
            pygame.draw.circle(self.frame, (*MINT, 95), home, 13, 1)
            pygame.draw.lines(self.frame, (*MINT, 200), False,
                              [(home[0]-5, home[1]), (home[0]-1, home[1]+4), (home[0]+6, home[1]-5)], 2)
            return
        if actor.state == "rebooting":
            radius = 24 + round(math.sin(self.clock * 4) * 2)
            pygame.draw.circle(self.frame, (*GOLD, 55), home, radius+9, 2)
            pygame.draw.circle(self.frame, (*GOLD, 200), home, radius, 2)
            ghost = visual.image.copy()
            ghost.set_alpha(45)
            self.frame.blit(ghost, ghost.get_rect(center=home))
            self._text(f"{actor.reboot_left:.0f}", home, GOLD, 16, center=True)
            if actor.seal_progress > 0:
                rect = pygame.Rect(home[0]-radius-5, home[1]-radius-5, 2*radius+10, 2*radius+10)
                pygame.draw.arc(self.frame, MINT, rect, -math.pi/2,
                                -math.pi/2 + math.tau * actor.seal_progress, 4)
                self._text("断链中", (home[0], home[1]+38), MINT, 11, center=True)
            else:
                self._text("靠近断链", (home[0], home[1]+38), GOLD, 11, center=True)
            return
        x, y = self._camera_point(actor.pos)
        progress = min(1.0, actor.state_time / .7) if actor.state == "waking" else 1.0
        reduced = self.profile.get("settings", {}).get("reduced_motion", False)
        angle = 0 if reduced else math.sin(actor.state_time * (17 if actor.state == "waking" else 8)) * 6 * progress
        lift = 0 if reduced else 5 * progress + (abs(math.sin(actor.state_time * 6)) * 3 if actor.state == "active" else 0)
        factor = 1 + .65 * progress if actor.is_boss else 1.0
        key = (actor.key, round(angle), round(factor, 2), bool(actor.flash > 0))
        image = self._image_cache.get(key)
        if image is None:
            source = visual.image
            if actor.flash > 0:
                source = source.copy()
                source.fill((100, 100, 100, 0), special_flags=pygame.BLEND_RGB_ADD)
            image = pygame.transform.rotozoom(source, round(angle), round(factor, 2))
            if len(self._image_cache) > 1200:
                self._image_cache.clear()
            self._image_cache[key] = image
        shadow = pygame.Rect(0, 0, round(visual.image.get_width() * factor * .8), 8)
        shadow.center = (x, y + visual.image.get_height() / 2)
        pygame.draw.ellipse(self.frame, (0, 0, 0, 75), shadow)
        if actor.is_boss:
            pygame.draw.circle(self.frame, (*RED, 160), (x, y), round(actor.radius + 7), 2)
        if actor.telegraph_left > 0:
            target = self._camera_point(actor.aim)
            pygame.draw.line(self.frame, (*RED, 130), (x, y), target, 2)
            pygame.draw.circle(self.frame, (*RED, 160), target, 13, 1)
        self.frame.blit(image, image.get_rect(center=(x, round(y - lift))))
        if actor.state == "waking":
            label = visual.label.copy()
            label.set_alpha(round(255 * (1 - progress)))
            self.frame.blit(label, visual.home + visual.label_offset)
        if actor.hp < actor.max_hp or actor.is_boss:
            width = max(28, round(visual.image.get_width() * factor))
            rect = pygame.Rect(x-width//2, y-round(image.get_height()/2)-12, width, 4)
            pygame.draw.rect(self.frame, (18, 23, 28, 210), rect, border_radius=2)
            pygame.draw.rect(self.frame, RED if actor.is_boss else GOLD,
                             (rect.x, rect.y, max(0, round(width*actor.hp/max(1,actor.max_hp))), 4), border_radius=2)
        if actor.generation:
            self._text(f"↻{actor.generation}", (x + image.get_width()//2, y), GOLD, 11)

    def _draw_player(self):
        from .wardrobe import draw_character, equipped_outfit
        s, p = self.session, self.session.player
        center = self._camera_point(p.pos)
        draw_character(self.frame, center, outfit=self._cached("equipped", lambda: equipped_outfit(self.profile)), scale=s.scale,
                       clock=0 if self.profile.get("settings", {}).get("reduced_motion") else self.clock,
                       hurt=max(0, .32-p.hurt_age), dashing=p.dash_left>0)
        if p.shield > 0:
            pygame.draw.circle(self.frame, (*BLUE, 110), center, round(p.radius + 9), 1)
        if p.dash_left > 0:
            pygame.draw.circle(self.frame, (*MINT, 180), center, round(p.radius + 14), 2)
        blades = getattr(p, "blade_level", 0)
        for index in range(blades):
            angle = s.total_time * 3.8 + math.tau * index / max(1, blades)
            radius = 64 * getattr(s, "scale", 1)
            tip = (round(center[0]+math.cos(angle)*radius), round(center[1]+math.sin(angle)*radius))
            pygame.draw.circle(self.frame, (*BLUE, 55), center, round(radius), 1)
            pygame.draw.line(self.frame, BLUE, (tip[0]-6, tip[1]+5), (tip[0]+6, tip[1]-5), 3)

    def _draw_effects(self):
        for effect in self.session.effects:
            kind = effect.get("kind")
            project = self._point if kind == "seal" else self._camera_point
            x, y = project((effect.get("x", 0), effect.get("y", 0)))
            ttl = max(0, effect.get("ttl", .2))
            if kind == "chain":
                points = effect.get("points")
                if points and len(points) >= 2:
                    pygame.draw.lines(self.frame, (*BLUE, 220), False, [self._camera_point(pt) for pt in points], 3)
                elif effect.get("target"):
                    pygame.draw.line(self.frame, BLUE, (x,y), self._camera_point(effect["target"]), 3)
            elif kind in ("pulse", "seal", "kill"):
                radius = round(effect.get("radius", 100 if kind == "pulse" else 24) * (1 - min(1,ttl/.5)))
                pygame.draw.circle(self.frame, (*(MINT if kind != "kill" else GOLD), 160), (x,y), max(1,radius), 2)

    def _draw_guidance(self):
        s = self.session
        if s.state != "playing":
            return
        target, title, color = None, "", MINT
        if s.sealed_count < s.seal_goal:
            ports = [a for a in s.actors if a.state == "rebooting"]
            if ports:
                target = min(ports, key=lambda a: math.dist(a.home, s.player.pos)).home
                title = "前往断链"
        elif s.boss_spawned and not s.boss_defeated:
            boss = next((a for a in s.actors if a.is_boss and a.state in ("waking", "active")), None)
            if boss:
                target, title, color = boss.pos, "击破主控", RED
        if target is None:
            return
        delta = pygame.Vector2(target) - pygame.Vector2(s.player.pos)
        if delta.length() < 120 * self.scale:
            return
        direction = delta.normalize()
        center = pygame.Vector2(self._camera_point(s.player.pos)) + direction * 42 * self.scale
        tangent = pygame.Vector2(-direction.y, direction.x)
        points = [center + direction * 8, center - direction * 5 + tangent * 5,
                  center - direction * 5 - tangent * 5]
        pygame.draw.polygon(self.frame, (*color, 220), points)
        self._text(title, (round(center.x), round(center.y - 15*self.scale)), color, 11, center=True)

    def _draw_menu(self):
        self._draw_home()

    def _bar(self, rect, fraction, color):
        pygame.draw.rect(self.frame, (48,60,65,230),rect,border_radius=3)
        fill=rect.copy(); fill.w=max(0,round(rect.w*max(0,min(1,fraction))))
        pygame.draw.rect(self.frame,color,fill,border_radius=3)

    def _draw_hud(self):
        s,p=self.session,self.session.player
        sc=self.scale
        rect=pygame.Rect(self.work.right-round(334*sc),self.work.top+round(18*sc),round(316*sc),round(148*sc))
        pygame.draw.rect(self.frame,(*INK,225),rect,border_radius=9)
        x=rect.x+round(14*sc); y=rect.y+round(10*sc)
        self._text(f"{s.chapter:02d} / {s.stage_title}",(x,y),MINT,14)
        secs=max(0,math.ceil(s.remaining_time))
        self._text(f"{secs//60:02d}:{secs%60:02d}",(rect.right-round(13*sc),y),GOLD if secs<25 else WHITE,16,right=True)
        y+=round(29*sc)
        self._text(f"生命 {math.ceil(p.hp)}/{p.max_hp:.0f}",(x,y),WHITE,12)
        self._text(f"护盾 {p.shield:.0f}",(rect.right-round(13*sc),y),BLUE,12,right=True)
        self._bar(pygame.Rect(x,y+round(22*sc),rect.w-round(28*sc),round(5*sc)),p.hp/max(1,p.max_hp),RED if p.hp<30 else MINT)
        y+=round(37*sc)
        self._text(f"断链 {min(s.sealed_count,s.seal_goal)}/{s.seal_goal}  ·  主控 {'已击破' if s.boss_defeated else '苏醒中' if s.boss_spawned else '未出现'}",(x,y),WHITE,12)
        y+=round(25*sc)
        self._text(f"Lv.{p.level}  {s.weapon_name}",(x,y),DIM,11)
        self._text(f"{s.score:,} 分",(rect.right-round(13*sc),y),WHITE,12,right=True)
        self._bar(pygame.Rect(x,rect.bottom-round(11*sc),rect.w-round(28*sc),3),p.xp/max(1,p.xp_next),BLUE)
        bottom=self.work.bottom-round(42*sc)
        for i,(title,action,cd) in enumerate([(f"脉冲 {p.pulse_cd:.1f}s" if p.pulse_cd else "脉冲 · 空格","pulse",p.pulse_cd),
                                            (f"冲刺 {p.dash_cd:.1f}s" if p.dash_cd else "冲刺 · Shift","dash",p.dash_cd),
                                            ("暂停 · P","pause",0),("退出 · F5","quit",0)]):
            r=pygame.Rect(self.work.right-round((448-112*i)*sc),bottom,round(104*sc),round(28*sc))
            self._button(r,title,action,accent=DIM if cd else MINT)
        if self.notice_left>0 and s.state=="playing":
            self._wrap(self.notice,rect.x+8,rect.bottom+12,rect.w-16,GOLD,13,3)

    def _draw_choices(self):
        s=self.session
        inter=s.state=="intermission"
        choices=s.stage_choices if inter else s.upgrade_choices
        rect=self._menu_rect(height=480,width=470)
        self._panel(rect,accent=GOLD if inter else MINT)
        x=rect.x+round(24*self.scale); y=rect.y+round(26*self.scale)
        self._text("区域清理完成" if inter else "系统升级",(x,y),GOLD if inter else MINT,28)
        self._text("选择一项补给，进入下一区域" if inter else "战斗已暂停 · 选择你的构筑",(x,y+round(45*self.scale)),DIM,13)
        y+=round(86*self.scale)
        for i,choice in enumerate(choices[:3]):
            r=pygame.Rect(x,y,rect.w-round(48*self.scale),round(96*self.scale))
            self._button(r,choice["title"],f"choice:{i}",subtitle=choice["description"],number=str(i+1),accent=GOLD if inter else MINT)
            y+=round(108*self.scale)

    def _draw_pause(self):
        rect=self._menu_rect(height=350,width=400)
        self._panel(rect)
        x=rect.x+round(24*self.scale); y=rect.y+round(25*self.scale)
        self._text("战斗暂停",(x,y),WHITE,28)
        self._text("切回桌面后，点击继续" if self.paused_by_focus else "复活倒计时与敌人行动已冻结",(x,y+round(42*self.scale)),DIM,13)
        y+=round(83*self.scale)
        for title,action in [("继续 · P / Esc","pause"),("重新开始这一局","restart"),("结束本局并结算","retire"),("还原桌面并退出 · F5","quit")]:
            self._button(pygame.Rect(x,y,rect.w-round(48*self.scale),round(44*self.scale)),title,action)
            y+=round(54*self.scale)

    def _draw_result(self):
        s=self.session
        won=s.state=="won"
        rect=self._menu_rect(height=560,width=470)
        self._panel(rect,accent=MINT if won else RED)
        x=rect.x+round(26*self.scale); y=rect.y+round(26*self.scale)
        self._text("重启成功" if won else "本局结束",(x,y),MINT if won else RED,36)
        reason = {"health":"生命耗尽", "timeout":"清理超时", "retired":"主动结束"}.get(s.finish_reason, MODES[self.mode][0])
        self._text("新纪录 · " + reason if self.new_record else reason,(x,y+round(58*self.scale)),GOLD,14)
        y+=round(100*self.scale)
        for label,value in [("得分",f"{s.score:,}"),("击碎图标",str(s.player.kills)),("抵达章节",str(s.chapter)),
                            ("存活时间",f"{int(s.total_time)//60:02d}:{int(s.total_time)%60:02d}")]:
            self._text(label,(x,y),DIM,14)
            self._text(value,(rect.right-round(28*self.scale),y),WHITE,18,right=True)
            y+=round(36*self.scale)
        y+=round(15*self.scale)
        if self.reward:
            self._text(f"+{self.reward.get('xp',0)} 档案经验   +{self.reward.get('crystals',0)} 数据晶片",(x,y),GOLD,14)
            y+=round(27*self.scale)
            if self.reward.get("saved") is False:
                self._text("档案尚未保存 · 自动重试中，也可点击下方重试",(x,y),RED,12)
            elif self.reward.get("unlocked_outfits"):
                from .wardrobe import OUTFITS
                names="、".join(OUTFITS[key]["title"] for key in self.reward["unlocked_outfits"])
                self._text("解锁装扮："+names,(x,y),MINT,12)
            elif self.reward.get("achievements"):
                self._text(f"达成 {len(self.reward['achievements'])} 项新成就 · 主菜单可查看",(x,y),MINT,12)
            elif not self.reward.get("eligible",True):
                self._text("战斗满 10 秒且有击杀后可获得结算奖励",(x,y),DIM,11)
            else:
                self._text(f"档案等级 Lv.{self.reward.get('level',1)} · 换装与天赋已可使用",(x,y),DIM,12)
            y+=round(31*self.scale)
        for title,action in [("再来一局 · R","restart"),("选择其他模式","menu"),("还原桌面并退出","quit")]:
            self._button(pygame.Rect(x,y,rect.w-round(52*self.scale),round(41*self.scale)),title,action)
            y+=round(50*self.scale)
        if self.reward.get("saved") is False:
            self._button(pygame.Rect(x,y,rect.w-round(52*self.scale),round(32*self.scale)),
                         "重试保存档案","retry_save",accent=GOLD)
