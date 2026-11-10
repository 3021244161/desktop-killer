"""Deterministic combat simulation in physical screen-center coordinates."""
from __future__ import annotations

from dataclasses import dataclass, field
import math
import random

from .content import CHAPTERS, ENEMIES, STAGE_REWARDS, UPGRADES, classify_role


def _clamp(value, low, high):
    return max(low, min(high, value))


def _unit(dx, dy):
    distance = math.hypot(dx, dy)
    return (dx / distance, dy / distance) if distance > 1e-8 else (1.0, 0.0)


def _distance(a, b):
    return math.hypot(a.x - b.x, a.y - b.y)


@dataclass
class Player:
    x: float
    y: float
    radius: float
    hp: float = 100.0
    max_hp: float = 100.0
    shield: float = 20.0
    max_shield: float = 20.0
    invulnerable: float = 0.0
    dash_left: float = 0.0
    dash_cd: float = 0.0
    pulse_cd: float = 0.0
    level: int = 1
    xp: float = 0.0
    xp_next: float = 58.0
    kills: int = 0
    damage: float = 12.0
    fire_rate: float = 3.2
    projectiles: int = 1
    chain_level: int = 0
    blade_level: int = 0
    pierce: int = 0
    speed: float = 330.0
    fire_cd: float = 0.0
    hurt_age: float = 99.0
    dash_direction: tuple[float, float] = (1.0, 0.0)

    @property
    def pos(self):
        return self.x, self.y


@dataclass
class Enemy:
    key: str
    name: str
    home: tuple[float, float]
    size: tuple[float, float]
    x: float
    y: float
    kind: str
    radius: float
    state: str = "home"
    hp: float = 0.0
    max_hp: float = 0.0
    generation: int = 0
    state_time: float = 0.0
    reboot_left: float = 0.0
    seal_progress: float = 0.0
    is_boss: bool = False
    attack_phase: str = "move"
    attack_style: str = ""
    telegraph_left: float = 0.0
    aim: tuple[float, float] = (0.0, 0.0)
    flash: float = 0.0
    stun: float = 0.0
    death_count: int = 0
    sealed_once: bool = False
    attack_cd: float = 0.0
    action_left: float = 0.0
    vx: float = 0.0
    vy: float = 0.0
    phase: float = 0.0
    attack_number: int = 0
    wake_duration: float = .75
    blade_hit_at: float = -99.0

    @property
    def pos(self):
        return self.x, self.y


@dataclass
class Projectile:
    x: float
    y: float
    vx: float
    vy: float
    radius: float
    damage: float
    enemy: bool = False
    kind: str = "bullet"
    ttl: float = 3.0
    pierce: int = 0
    hit: set[str] = field(default_factory=set)

    @property
    def pos(self):
        return self.x, self.y


@dataclass
class Shard:
    x: float
    y: float
    value: float
    age: float = 0.0

    @property
    def pos(self):
        return self.x, self.y


class GameSession:
    """One icon record remains one Enemy object throughout every chapter.

    Input homes and all positions are CENTER points in global physical pixels.
    Native sprite sizes never change. Rendering, desktop access, audio and disk
    access belong to the caller. Time freezes in every non-playing state.
    """

    STEP = 1.0 / 60.0

    def __init__(self, icons: list[dict], bounds: tuple[int, int, int, int],
                 mode: str = "campaign", seed: int = 1, *, bonuses: dict | None = None) -> None:
        if mode not in ("campaign", "blitz", "endless"):
            raise ValueError("unknown game mode")
        if not icons or len({str(i["key"]) for i in icons}) != len(icons):
            raise ValueError("a game needs uniquely identified desktop icons")
        self.bounds = tuple(float(value) for value in bounds)
        left, top, right, bottom = self.bounds
        if right <= left or bottom <= top:
            raise ValueError("empty game bounds")
        self.scale = math.hypot(right - left, bottom - top) / math.hypot(1920, 1042)
        self.rng = random.Random(seed)
        self.mode, self.seed = mode, seed
        self.bonuses = {}
        for name in ("damage_mult", "max_hp_mult", "speed_mult", "shield_mult",
                     "cooldown_mult", "seal_duration_mult"):
            value = (bonuses or {}).get(name, 1.0)
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError("career bonuses must be finite numbers")
            low, high = (.8, 1.0) if name in ("cooldown_mult", "seal_duration_mult") else (1.0, 1.2)
            self.bonuses[name] = _clamp(float(value), low, high)
        self.state = self.paused_from = "playing"
        self.chapter = 1
        self.stage_time = self.total_time = 0.0
        self.score = self.total_sealed = self.total_revivals = self.boss_kills = 0
        self.player = Player(left + (right - left) * .57, top + (bottom - top) * .57,
                             13.0 * self.scale, speed=330.0 * self.scale)
        self.player.hp = self.player.max_hp = 100 * self.bonuses["max_hp_mult"]
        self.player.shield = self.player.max_shield = 20 * self.bonuses["shield_mult"]
        self.actors: list[Enemy] = []
        for index, icon in enumerate(icons):
            home = tuple(float(value) for value in icon["home"])
            raw_size = icon.get("size", (32, 32))
            size = (float(raw_size), float(raw_size)) if isinstance(raw_size, (int, float)) else tuple(raw_size)
            if len(home) != 2 or len(size) != 2 or min(size) <= 0:
                raise ValueError("icon home and size must contain valid coordinates")
            kind = icon.get("kind", classify_role(str(icon.get("name", "")), index))
            if kind not in ENEMIES:
                kind = "chaser"
            radius = max(10.0 * self.scale, min(40.0 * self.scale, max(size) * .38))
            self.actors.append(Enemy(str(icon["key"]), str(icon.get("name", "")), home, size,
                                     *home, kind, radius, phase=self.rng.random() * math.tau))
        self._by_key = {actor.key: actor for actor in self.actors}
        self._eligible = [a for a in self.actors if left <= a.home[0] <= right and top <= a.home[1] <= bottom]
        if not self._eligible:
            raise ValueError("no desktop icon is inside the playable work area")
        self.bullets: list[Projectile] = []
        self.shards: list[Shard] = []
        self.effects: list[dict] = []
        self.events: list[dict] = []
        self.upgrade_stacks: dict[str, int] = {}
        self.upgrade_choices: list[dict] = []
        self.stage_choices: list[dict] = []
        self._pending_upgrades = 0
        self._accumulator = 0.0
        self._damage_bonus = self._rate_bonus = self._speed_bonus = 0.0
        self._cooldown_bonus = self.bonuses["cooldown_mult"]
        self._sealed_keys: set[str] = set()
        self._wake_order: list[Enemy] = []
        self._wake_timer = .9
        self.blitz_phase = 1
        self.surge_number = 0
        self._surge_timer = 18.0
        self.boss_key: str | None = None
        self.boss_spawned = self.boss_defeated = False
        self.seal_goal, self.stage_limit, self.stage_title = 0, 0.0, ""
        self.finish_reason = ""
        self._refresh_player_stats()
        self._begin_stage()

    @property
    def sealed_count(self):
        return len(self._sealed_keys)

    @property
    def remaining_time(self):
        return max(0.0, self.stage_limit - self.stage_time)

    @property
    def weapon_name(self):
        routes = [name for level, name in ((self.player.projectiles > 1, "多重弹"),
                  (self.player.chain_level, "连锁电"), (self.player.blade_level, "环绕刃")) if level]
        return " · ".join(routes) or "自动脉冲枪"

    @property
    def seal_duration(self):
        return max(.55, 1.0 - .15 * self.upgrade_stacks.get("seal", 0)) * self.bonuses["seal_duration_mult"]

    @property
    def pulse_radius(self):
        return 170.0 * self.scale * (1.0 + .2 * self.upgrade_stacks.get("pulse", 0))

    def drain_events(self):
        result, self.events = self.events, []
        return result

    def _emit(self, kind, x, y, ttl=.35, **values):
        event = {"kind": kind, "x": x, "y": y, **values}
        self.events.append(event)
        if len(self.events) > 256:
            del self.events[:-256]
        if ttl > 0:
            self.effects.append({**event, "ttl": ttl, "max_ttl": ttl})

    def _begin_stage(self):
        content = CHAPTERS[(self.chapter - 1) % 3]
        self.stage_title = "三分钟 · 极速清理" if self.mode == "blitz" else content["title"]
        if self.mode == "endless":
            self.stage_title = f"无限循环 {self.chapter} · " + content["title"].split(" · ")[-1]
        self.stage_limit = 180.0 if self.mode == "blitz" else content["limit"]
        self.seal_goal = min(len(self._eligible), 12 if self.mode == "blitz" else content["seals"])
        self.stage_time = 0.0
        self._sealed_keys.clear()
        self.boss_spawned = self.boss_defeated = False
        self.boss_key = None
        self.bullets.clear()
        self.shards.clear()
        self._wake_timer = .9
        self.blitz_phase, self.surge_number, self._surge_timer = 1, 0, 18.0
        self._wake_order = sorted(self._eligible, key=lambda actor: (
            math.hypot(actor.home[0] - self.player.x, actor.home[1] - self.player.y), actor.key))
        for actor in self.actors:
            actor.x, actor.y = actor.home
            actor.state, actor.state_time = "home", 0.0
            actor.generation = 0
            actor.is_boss = actor.sealed_once = False
            actor.seal_progress = actor.reboot_left = 0.0
            actor.attack_phase, actor.attack_style = "move", ""
            actor.telegraph_left = actor.action_left = actor.stun = 0.0
            actor.vx = actor.vy = 0.0
            actor.attack_cd = 1.0
            self._set_normal_stats(actor)
        self.player.invulnerable = max(self.player.invulnerable, 1.5)
        self.player.fire_cd = 0.0
        self.state = "playing"
        self._emit("stage", *self.player.pos, ttl=1.6, chapter=self.chapter, title=self.stage_title)

    def _set_normal_stats(self, actor):
        actor.max_hp = ENEMIES[actor.kind]["hp"] * (1 + .16 * (self.chapter - 1)) * (1 + .24 * actor.generation)
        actor.hp = actor.max_hp

    def _wake(self, actor, *, revival=False):
        if revival:
            actor.generation += 1
            self.total_revivals += 1
        self._set_normal_stats(actor)
        actor.x, actor.y = actor.home
        actor.state, actor.state_time = "waking", 0.0
        actor.wake_duration = .75
        actor.attack_phase = "move"
        actor.attack_cd = self.rng.uniform(.8, 1.8)
        actor.seal_progress = 0.0
        self._emit("wake", *actor.pos, ttl=.75, key=actor.key, generation=actor.generation)

    def _spawn_boss(self):
        if self.boss_spawned:
            return
        # Small desktops reuse a sealed icon. Objective progress survives the
        # hijack; no clone or additional actor is introduced.
        candidates = [a for a in self._eligible if not a.sealed_once] or self._eligible
        actor = max(candidates, key=lambda a: (math.hypot(a.x - self.player.x, a.y - self.player.y), a.key))
        self.boss_key, self.boss_spawned = actor.key, True
        actor.is_boss = True
        actor.state, actor.state_time = "waking", 0.0
        actor.wake_duration = 1.2
        actor.max_hp = (250.0 + 110.0 * (self.chapter - 1)) * (1.15 if self.mode == "blitz" else 1.0)
        actor.hp = actor.max_hp
        actor.stun = actor.reboot_left = actor.seal_progress = 0.0
        actor.attack_phase, actor.attack_style = "move", ""
        actor.telegraph_left = actor.action_left = actor.vx = actor.vy = 0.0
        actor.attack_cd, actor.attack_number = 1.0, 0
        self._emit("boss", *actor.pos, ttl=1.2, key=actor.key)

    def _blitz_pressure(self, dt):
        """Timed incursion waves reuse sealed actors; objective history persists."""
        self.blitz_phase = 1 if self.stage_time < 50 else (2 if self.stage_time < 100 else 3)
        interval = (18.0, 14.0, 10.0)[self.blitz_phase - 1]
        self._surge_timer = min(interval, self._surge_timer - dt)
        if self._surge_timer > 0:
            return
        self._surge_timer = interval
        candidates = sorted((a for a in self._eligible if a.state == "sealed" and not a.is_boss),
                            key=lambda a: (-a.state_time, a.key))
        selected = candidates[:self.blitz_phase]
        for actor in selected:
            actor.sealed_once = False
            self._wake(actor, revival=True)
            actor.wake_duration = 1.2
            actor.attack_style, actor.aim = "surge", actor.home
            actor.telegraph_left = actor.wake_duration
        if selected:
            self.surge_number += 1
            self._emit("surge", *self.player.pos, ttl=1.2,
                       phase=self.blitz_phase, count=len(selected), wave=self.surge_number)

    def update(self, dt: float, cursor: tuple[float, float],
               movement: tuple[float, float] = (0.0, 0.0), dash: bool = False):
        if self.state != "playing" or dt <= 0:
            return
        if dash:
            self.dash(cursor)
        self._accumulator += min(float(dt), .25)
        while self._accumulator + 1e-10 >= self.STEP and self.state == "playing":
            self._accumulator -= self.STEP
            self._step(self.STEP, cursor, movement)
        if self.state != "playing":
            self._accumulator = 0.0

    def _step(self, dt, cursor, movement):
        self.stage_time += dt
        self.total_time += dt
        for effect in self.effects:
            effect["ttl"] -= dt
        self.effects[:] = [e for e in self.effects if e["ttl"] > 0]
        p = self.player
        p.invulnerable = max(0.0, p.invulnerable - dt)
        p.dash_cd, p.pulse_cd = max(0.0, p.dash_cd - dt), max(0.0, p.pulse_cd - dt)
        p.hurt_age += dt
        if self.upgrade_stacks.get("shield", 0) and p.hurt_age > 4.0:
            p.shield = min(p.max_shield, p.shield + dt * (3 + self.upgrade_stacks["shield"]))
        before = p.pos
        if p.dash_left > 0:
            p.dash_left = max(0.0, p.dash_left - dt)
            p.x += p.dash_direction[0] * 1000 * self.scale * dt
            p.y += p.dash_direction[1] * 1000 * self.scale * dt
        elif math.hypot(*movement) > .1:
            ux, uy = _unit(*movement)
            p.x += ux * p.speed * dt
            p.y += uy * p.speed * dt
        else:
            dx, dy = cursor[0] - p.x, cursor[1] - p.y
            distance = math.hypot(dx, dy)
            if distance > 5 * self.scale:
                amount = min(p.speed * dt, distance)
                p.x += dx / distance * amount
                p.y += dy / distance * amount
        left, top, right, bottom = self.bounds
        p.x = _clamp(p.x, left + p.radius, right - p.radius)
        p.y = _clamp(p.y, top + p.radius, bottom - p.radius)
        moving_speed = math.hypot(p.x - before[0], p.y - before[1]) / dt
        if self.mode == "blitz" and self.stage_time < 145:
            self._blitz_pressure(dt)
        self._wake_timer -= dt
        active_count = sum(a.state in ("active", "waking") for a in self._eligible)
        cap = min(len(self._eligible), 5 + self.chapter * 2 + int(self.stage_time / 18))
        if self.mode == "blitz":
            cap = min(len(self._eligible), 5 + self.blitz_phase * 3 + int(self.stage_time / 22))
        if self._wake_timer <= 0 and active_count < cap:
            home = next((a for a in self._wake_order if a.state == "home"), None)
            if home:
                self._wake(home)
            self._wake_timer = ((1.4, 1.05, .75)[self.blitz_phase - 1] if self.mode == "blitz"
                                else 2.1 / (1 + .04 * (self.chapter - 1)))
        for actor in self._eligible:
            actor.flash, actor.stun = max(0.0, actor.flash - dt), max(0.0, actor.stun - dt)
            actor.state_time += dt
            if actor.state == "waking":
                if actor.attack_style == "surge":
                    actor.telegraph_left = max(0.0, actor.wake_duration - actor.state_time)
                if actor.state_time >= actor.wake_duration:
                    actor.state, actor.state_time = "active", 0.0
                    actor.telegraph_left = 0.0
                    if actor.attack_style == "surge":
                        actor.attack_style = ""
            elif actor.state == "rebooting":
                close = math.hypot(p.x - actor.home[0], p.y - actor.home[1]) <= 58 * self.scale + p.radius
                if close and moving_speed < 55 * self.scale and p.dash_left <= 0:
                    actor.seal_progress = min(1.0, actor.seal_progress + dt / self.seal_duration)
                    if actor.seal_progress >= 1 - 1e-8:
                        self._seal(actor)
                        continue
                else:
                    actor.seal_progress = max(0.0, actor.seal_progress - dt * 1.5)
                actor.reboot_left -= dt
                if actor.reboot_left <= 0:
                    self._wake(actor, revival=True)
            elif actor.state == "active" and actor.stun <= 0:
                self._enemy_step(actor, dt)
        boss_ready = (self.stage_time >= 145.0 if self.mode == "blitz"
                      else self.stage_time >= 35.0 or self.sealed_count >= self.seal_goal)
        if not self.boss_spawned and boss_ready:
            self._spawn_boss()
        p.fire_cd -= dt
        targets = [a for a in self._eligible if a.state == "active"]
        if targets and p.fire_cd <= 0:
            self._fire(min(targets, key=lambda a: (_distance(a, p), a.key)))
            p.fire_cd = 1.0 / p.fire_rate
        self._move_projectiles(dt)
        self._orbit_blades()
        for actor in self._eligible:
            radius = actor.radius * (1.55 if actor.is_boss else 1.0)
            if actor.state == "active" and _distance(actor, p) < radius + p.radius:
                if self._hurt_player(20.0 if actor.is_boss else ENEMIES[actor.kind]["contact"]):
                    ux, uy = _unit(actor.x - p.x, actor.y - p.y)
                    actor.x += ux * 38 * self.scale
                    actor.y += uy * 38 * self.scale
        self._move_shards(dt)
        if p.hp <= 0:
            self._finish(False, "health")
        elif self.boss_defeated and self.sealed_count >= self.seal_goal:
            self._complete_stage()
        elif self.stage_time >= self.stage_limit:
            self._finish(False, "timeout")
        elif self._pending_upgrades:
            self._open_upgrade()

    def _telegraph(self, actor, duration, style):
        actor.attack_phase, actor.attack_style = "telegraph", style
        actor.telegraph_left, actor.aim = duration, self.player.pos
        self._emit("telegraph", *actor.pos, ttl=duration, key=actor.key, target=actor.aim, style=style)

    def _enemy_step(self, actor, dt):
        p = self.player
        actor.attack_cd -= dt
        dx, dy = p.x - actor.x, p.y - actor.y
        distance = math.hypot(dx, dy)
        ux, uy = _unit(dx, dy)
        if actor.attack_phase == "telegraph":
            actor.telegraph_left = max(0.0, actor.telegraph_left - dt)
            if actor.telegraph_left <= 0:
                if actor.attack_style == "charge":
                    ux, uy = _unit(actor.aim[0] - actor.x, actor.aim[1] - actor.y)
                    speed = (360 if actor.is_boss else 470) * self.scale
                    actor.vx, actor.vy = ux * speed, uy * speed
                    actor.action_left = .42 if actor.is_boss else .30
                    actor.attack_phase = "charge"
                else:
                    self._enemy_fire(actor)
                    actor.attack_phase, actor.action_left = "recover", .32
            return
        if actor.attack_phase == "charge":
            actor.x += actor.vx * dt
            actor.y += actor.vy * dt
            actor.action_left -= dt
            if actor.action_left <= 0:
                actor.attack_phase, actor.action_left = "recover", .45
            self._clamp_actor(actor)
            return
        if actor.attack_phase == "recover":
            actor.action_left -= dt
            if actor.action_left <= 0:
                actor.attack_phase = "move"
            return
        if actor.is_boss:
            actor.x += ux * 43 * self.scale * dt
            actor.y += uy * 43 * self.scale * dt
            if actor.attack_cd <= 0:
                actor.attack_number += 1
                style = "charge" if actor.attack_number % 3 == 0 else ("radial" if actor.attack_number % 4 == 0 else "fan")
                self._telegraph(actor, .9, style)
                actor.attack_cd = 2.8
            return
        speed = ENEMIES[actor.kind]["speed"] * self.scale * (1 + min(.8, .08 * actor.generation))
        if actor.kind == "ranger":
            direction = 1 if distance > 260 * self.scale else (-.7 if distance < 190 * self.scale else 0)
            actor.x += ux * speed * direction * dt
            actor.y += uy * speed * direction * dt
            if actor.attack_cd <= 0:
                self._telegraph(actor, .65, "shot")
                actor.attack_cd = 2.65
        elif actor.kind == "orbiter":
            approach = _clamp((distance - 170 * self.scale) / (120 * self.scale), -.55, 1)
            sign = 1 if actor.phase < math.pi else -1
            actor.x += (ux * approach - uy * .8 * sign) * speed * dt
            actor.y += (uy * approach + ux * .8 * sign) * speed * dt
            if actor.attack_cd <= 0:
                self._telegraph(actor, .65, "spread")
                actor.attack_cd = 3.4
        else:
            actor.x += ux * speed * dt
            actor.y += uy * speed * dt
            if actor.attack_cd <= 0 and distance < (390 if actor.kind == "charger" else 110) * self.scale:
                self._telegraph(actor, .75 if actor.kind == "charger" else .48, "charge")
                actor.attack_cd = 3.8 if actor.kind == "charger" else 3.0
        self._clamp_actor(actor)

    def _clamp_actor(self, actor):
        left, top, right, bottom = self.bounds
        actor.x = _clamp(actor.x, left + actor.radius, right - actor.radius)
        actor.y = _clamp(actor.y, top + actor.radius, bottom - actor.radius)

    def _enemy_fire(self, actor):
        base = math.atan2(actor.aim[1] - actor.y, actor.aim[0] - actor.x)
        style = actor.attack_style
        count = 10 if style == "radial" else (5 + min(4, self.chapter - 1) if style == "fan" else (3 if style == "spread" else 1))
        angles = ([base + i * math.tau / count for i in range(count)] if style == "radial"
                  else [base + (i - (count - 1) / 2) * math.radians(14 if actor.is_boss else 22) for i in range(count)])
        for angle in angles:
            speed = (190 if actor.is_boss else 220) * self.scale
            self.bullets.append(Projectile(actor.x, actor.y, math.cos(angle) * speed,
                math.sin(angle) * speed, (6 if actor.is_boss else 5) * self.scale,
                12 if actor.is_boss else 9, True, "boss" if actor.is_boss else "enemy", 6.0))
        self._emit("enemy_shot", *actor.pos, ttl=.12, key=actor.key)

    def _fire(self, target):
        p = self.player
        angle = math.atan2(target.y - p.y, target.x - p.x)
        for index in range(p.projectiles):
            direction = angle + (index - (p.projectiles - 1) / 2) * math.radians(8)
            self.bullets.append(Projectile(p.x, p.y, math.cos(direction) * 740 * self.scale,
                math.sin(direction) * 740 * self.scale, 3.8 * self.scale, p.damage, pierce=p.pierce))
        self._emit("shot", *p.pos, ttl=.07, target=target.pos)

    @staticmethod
    def _segment_distance(x, y, ax, ay, bx, by):
        dx, dy = bx - ax, by - ay
        length = dx * dx + dy * dy
        fraction = _clamp(((x - ax) * dx + (y - ay) * dy) / length, 0, 1) if length else 0
        return math.hypot(x - (ax + dx * fraction), y - (ay + dy * fraction))

    def _move_projectiles(self, dt):
        keep = []
        left, top, right, bottom = self.bounds
        for bullet in self.bullets:
            oldx, oldy = bullet.x, bullet.y
            bullet.x += bullet.vx * dt
            bullet.y += bullet.vy * dt
            bullet.ttl -= dt
            if bullet.ttl <= 0 or not (left - 60 <= bullet.x <= right + 60 and top - 60 <= bullet.y <= bottom + 60):
                continue
            if bullet.enemy:
                p = self.player
                if self._segment_distance(p.x, p.y, oldx, oldy, bullet.x, bullet.y) <= p.radius + bullet.radius:
                    self._hurt_player(bullet.damage)
                    continue
            else:
                for actor in self._eligible:
                    if actor.state != "active" or actor.key in bullet.hit:
                        continue
                    radius = actor.radius * (1.55 if actor.is_boss else 1.0)
                    if self._segment_distance(actor.x, actor.y, oldx, oldy, bullet.x, bullet.y) <= radius + bullet.radius:
                        bullet.hit.add(actor.key)
                        impact = actor.pos
                        self._damage_enemy(actor, bullet.damage)
                        if self.player.chain_level:
                            self._chain(actor, impact)
                        if bullet.pierce <= 0:
                            bullet.ttl = 0
                            break
                        bullet.pierce -= 1
            if bullet.ttl > 0:
                keep.append(bullet)
        self.bullets[:] = keep

    def _chain(self, first, origin=None):
        previous, seen, points = origin or first.pos, {first.key}, [origin or first.pos]
        for _ in range(self.player.chain_level + 1):
            choices = [a for a in self._eligible if a.state == "active" and a.key not in seen
                       and math.hypot(a.x - previous[0], a.y - previous[1]) <= 180 * self.scale]
            if not choices:
                break
            target = min(choices, key=lambda a: (math.hypot(a.x - previous[0], a.y - previous[1]), a.key))
            seen.add(target.key)
            points.append(target.pos)
            previous = target.pos
            self._damage_enemy(target, self.player.damage * (.35 + .15 * self.player.chain_level))
        if len(points) > 1:
            self._emit("chain", *points[0], ttl=.18, points=points)

    def blade_positions(self):
        count = self.player.blade_level
        return [(self.player.x + math.cos(self.total_time * 3.8 + i * math.tau / count) * 64 * self.scale,
                 self.player.y + math.sin(self.total_time * 3.8 + i * math.tau / count) * 64 * self.scale)
                for i in range(count)]

    def _orbit_blades(self):
        for x, y in self.blade_positions():
            for actor in self._eligible:
                if actor.state != "active" or self.total_time - actor.blade_hit_at < .42:
                    continue
                if math.hypot(actor.x - x, actor.y - y) <= actor.radius + 15 * self.scale:
                    actor.blade_hit_at = self.total_time
                    self._damage_enemy(actor, self.player.damage * 1.35)

    def _damage_enemy(self, actor, damage):
        if actor.state not in ("active", "waking"):
            return
        actor.hp -= damage
        actor.flash = .10
        self._emit("hit", *actor.pos, ttl=.14, key=actor.key, damage=damage)
        if actor.hp <= 0:
            self._kill(actor)

    def _kill(self, actor):
        was_boss, death_pos = actor.is_boss, actor.pos
        self.player.kills += 1
        actor.death_count += 1
        self.score += int((400 if was_boss else 80 + actor.generation * 25) * (1 + .12 * (self.chapter - 1)))
        xp = 90.0 if was_boss else ENEMIES[actor.kind]["xp"] + 3 * actor.generation
        xp *= (1.6 if self.mode == "blitz" else 1.0) * (1 + .2 * self.upgrade_stacks.get("magnet", 0))
        self._add_xp(xp * .7)
        self.shards.append(Shard(*death_pos, xp * .3))
        actor.is_boss, actor.hp = False, 0.0
        actor.x, actor.y = actor.home
        actor.state = "sealed" if actor.sealed_once else "rebooting"
        actor.state_time = actor.seal_progress = 0.0
        actor.reboot_left = max(4.0, 8.0 - .35 * actor.generation)
        actor.attack_phase, actor.attack_style = "move", ""
        actor.telegraph_left = actor.action_left = actor.vx = actor.vy = 0.0
        self._emit("kill", *death_pos, ttl=.65, key=actor.key, boss=was_boss, home=actor.home)
        if was_boss:
            self.boss_defeated = True
            self.boss_kills += 1
            self.player.hp = min(self.player.max_hp, self.player.hp + 15)
            self._pending_upgrades += 1

    def _seal(self, actor):
        actor.state, actor.state_time = "sealed", 0.0
        actor.seal_progress, actor.reboot_left = 1.0, 0.0
        actor.x, actor.y = actor.home
        if not actor.sealed_once:
            actor.sealed_once = True
            self._sealed_keys.add(actor.key)
            self.total_sealed += 1
            self.score += 180
            self.player.hp = min(self.player.max_hp, self.player.hp + 8 + 4 * self.upgrade_stacks.get("seal", 0))
            self.player.shield = min(self.player.max_shield, self.player.shield + 4)
        self._emit("seal", *actor.home, ttl=.8, key=actor.key)

    def _hurt_player(self, damage):
        p = self.player
        if p.invulnerable > 0 or p.hp <= 0:
            return False
        absorbed = min(p.shield, damage)
        p.shield -= absorbed
        p.hp = max(0.0, p.hp - (damage - absorbed))
        p.invulnerable, p.hurt_age = .65, 0.0
        self._emit("hurt", *p.pos, ttl=.3, damage=damage, shield=absorbed)
        return True

    def _move_shards(self, dt):
        keep = []
        for shard in self.shards:
            shard.age += dt
            distance = _distance(shard, self.player)
            if distance <= (120 + 35 * self.upgrade_stacks.get("magnet", 0)) * self.scale:
                ux, uy = _unit(self.player.x - shard.x, self.player.y - shard.y)
                step = min(distance, 430 * self.scale * dt)
                shard.x += ux * step
                shard.y += uy * step
            if _distance(shard, self.player) <= 20 * self.scale or shard.age >= 4.5:
                self._add_xp(shard.value)
            else:
                keep.append(shard)
        self.shards[:] = keep

    def _add_xp(self, amount):
        p = self.player
        p.xp += amount
        while p.xp >= p.xp_next:
            p.xp -= p.xp_next
            p.level += 1
            p.xp_next = float(math.ceil(36 + p.level * 18 + p.level ** 1.3 * 4))
            self._pending_upgrades += 1

    def pulse(self):
        p = self.player
        if self.state != "playing" or p.pulse_cd > 0:
            return False
        stacks = self.upgrade_stacks.get("pulse", 0)
        p.pulse_cd = max(3.0, 6.0 - .7 * stacks) * self._cooldown_bonus
        radius = self.pulse_radius
        for actor in self._eligible:
            if actor.state in ("active", "waking") and _distance(actor, p) <= radius + actor.radius:
                ux, uy = _unit(actor.x - p.x, actor.y - p.y)
                actor.x += ux * 75 * self.scale
                actor.y += uy * 75 * self.scale
                self._clamp_actor(actor)
                actor.stun = .8 if not actor.is_boss else .3
                self._damage_enemy(actor, 24 * (1 + .4 * stacks))
        self.bullets[:] = [b for b in self.bullets if not b.enemy or _distance(b, p) > radius]
        self._emit("pulse", *p.pos, ttl=.55, radius=radius)
        return True

    def dash(self, cursor):
        p = self.player
        if self.state != "playing" or p.dash_cd > 0:
            return False
        p.dash_direction = _unit(cursor[0] - p.x, cursor[1] - p.y)
        p.dash_left = .18
        p.invulnerable = max(p.invulnerable, .3)
        p.dash_cd = max(1.4, 2.6 - .22 * self.upgrade_stacks.get("speed", 0)) * self._cooldown_bonus
        self._emit("dash", *p.pos, ttl=.25, direction=p.dash_direction)
        return True

    def _open_upgrade(self):
        available = [key for key, value in UPGRADES.items() if self.upgrade_stacks.get(key, 0) < value[2]]
        if not available:
            self._pending_upgrades = 0
            return
        self._pending_upgrades -= 1
        ids = self.rng.sample(available, min(3, len(available)))
        self.upgrade_choices = [{"id": key, "title": UPGRADES[key][0],
            "description": UPGRADES[key][1], "level": self.upgrade_stacks.get(key, 0) + 1} for key in ids]
        self.state = "upgrade"
        self._emit("upgrade", *self.player.pos, ttl=.7, level=self.player.level)

    def choose_upgrade(self, index):
        if self.state != "upgrade" or not 0 <= index < len(self.upgrade_choices):
            return False
        key = self.upgrade_choices[index]["id"]
        self.upgrade_stacks[key] = self.upgrade_stacks.get(key, 0) + 1
        p = self.player
        if key == "vitality":
            p.max_hp += 20
            p.hp = min(p.max_hp, p.hp + 40)
        elif key == "shield":
            p.max_shield += 15
            p.shield = p.max_shield
        self._refresh_player_stats()
        self.upgrade_choices = []
        self.state = "playing"
        if self._pending_upgrades:
            self._open_upgrade()
        return True

    def _refresh_player_stats(self):
        p, stacks = self.player, self.upgrade_stacks
        p.damage = 12 * (1 + .2 * stacks.get("damage", 0) + self._damage_bonus) * self.bonuses["damage_mult"]
        p.fire_rate = 3.2 * (1 + .18 * stacks.get("fire_rate", 0) + self._rate_bonus)
        p.projectiles = 1 + stacks.get("multishot", 0)
        p.chain_level, p.blade_level = stacks.get("chain", 0), stacks.get("blades", 0)
        p.pierce = stacks.get("pierce", 0)
        p.speed = 330 * self.scale * (1 + .12 * stacks.get("speed", 0) + self._speed_bonus) * self.bonuses["speed_mult"]

    def _complete_stage(self):
        self.score += 350 + int(self.remaining_time) * 5
        self.bullets.clear()
        # Stage transitions must not discard the delayed portion of kill XP.
        self._add_xp(sum(shard.value for shard in self.shards))
        self.shards.clear()
        if self.mode == "blitz" or (self.mode == "campaign" and self.chapter >= 3):
            self._finish(True, "complete")
        else:
            self.state = "intermission"
            self.stage_choices = [dict(choice) for choice in STAGE_REWARDS]
            self._emit("stage_clear", *self.player.pos, ttl=1.0, chapter=self.chapter)

    def choose_stage(self, index):
        if self.state != "intermission" or not 0 <= index < len(self.stage_choices):
            return False
        key = self.stage_choices[index]["id"]
        p = self.player
        if key == "repair":
            p.hp = p.max_hp
            p.max_shield += 15
            p.shield = p.max_shield
        else:
            p.hp = min(p.max_hp, p.hp + 25)
            if key == "overclock":
                self._damage_bonus += .15
                self._rate_bonus += .1
            else:
                self._speed_bonus += .1
                self._cooldown_bonus *= .85
        self._refresh_player_stats()
        self.chapter += 1
        self.stage_choices = []
        self._begin_stage()
        return True

    def toggle_pause(self):
        if self.state == "playing":
            self.paused_from, self.state = "playing", "paused"
            return True
        if self.state == "paused":
            self.state = self.paused_from
            return True
        return False

    def _finish(self, won, reason):
        self.state = "won" if won else "lost"
        self.finish_reason = reason
        self._emit(self.state, *self.player.pos, ttl=1.0, reason=reason)

    def retire(self):
        """End voluntarily while preserving the current score for local records."""
        if self.state in ("won", "lost"):
            return False
        self._finish(False, "retired")
        return True

    def summary(self):
        return {"mode": self.mode, "state": self.state, "chapter": self.chapter, "stage": self.chapter,
                "won": self.state == "won", "score": self.score, "kills": self.player.kills,
                "sealed": self.total_sealed, "revivals": self.total_revivals, "bosses": self.boss_kills,
                "time": round(self.total_time, 2), "level": self.player.level,
                "reason": self.finish_reason, "upgrades": dict(self.upgrade_stacks)}


# Preserve the verified desktop-fusion demonstration and its diagnostic API.
from .prototype import DesktopScene  # noqa: E402,F401


def _drawing_segment_distance(point, start, end):
    dx, dy = end[0] - start[0], end[1] - start[1]
    length_sq = dx * dx + dy * dy
    amount = (_clamp(((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length_sq, 0, 1)
              if length_sq > 1e-12 else 0.0)
    return math.hypot(point[0] - start[0] - dx * amount, point[1] - start[1] - dy * amount)


def simplify_stroke(points, tolerance=1.5, max_points=512):
    """Bound an individual stroke without introducing connections to other strokes."""
    if max_points < 2:
        raise ValueError("max_points must be at least two")
    cleaned = []
    for point in points:
        p = (float(point[0]), float(point[1]))
        if not all(math.isfinite(value) for value in p):
            continue
        if not cleaned or math.dist(cleaned[-1], p) > 1e-8:
            cleaned.append(p)
    if len(cleaned) < 3:
        return cleaned

    def reduce(epsilon):
        retained = {0, len(cleaned) - 1}
        pending = [(0, len(cleaned) - 1)]
        while pending:
            first, last = pending.pop()
            greatest, pivot = epsilon, -1
            for index in range(first + 1, last):
                distance = _drawing_segment_distance(cleaned[index], cleaned[first], cleaned[last])
                if distance > greatest:
                    greatest, pivot = distance, index
            if pivot >= 0:
                retained.add(pivot)
                pending.extend(((first, pivot), (pivot, last)))
        return [cleaned[index] for index in sorted(retained)]

    epsilon = max(.05, float(tolerance))
    result = reduce(epsilon)
    # A hard point limit also bounds repeatedly scribbled previews and saved paths.
    for _ in range(12):
        if len(result) <= max_points:
            return result
        epsilon *= 1.7
        result = reduce(epsilon)
    if len(result) > max_points:
        result = [result[round(index * (len(result) - 1) / (max_points - 1))]
                  for index in range(max_points)]
    return result


def sample_strokes(strokes, count):
    """Sample the combined arc length, excluding every gap between separate pens."""
    if count <= 0:
        return []
    segments = []
    total = 0.0
    for stroke in strokes:
        for start, end in zip(stroke, stroke[1:]):
            length = math.dist(start, end)
            if length > 1e-8:
                segments.append((tuple(start), tuple(end), length))
                total += length
    if not segments:
        return []
    result, segment_index, consumed = [], 0, 0.0
    # Bin centers avoid duplicating the coincident first/last point of a circle.
    for index in range(count):
        offset = total * (index + .5) / count
        while segment_index + 1 < len(segments) and consumed + segments[segment_index][2] < offset:
            consumed += segments[segment_index][2]
            segment_index += 1
        start, end, length = segments[segment_index]
        fraction = _clamp((offset - consumed) / length, 0.0, 1.0)
        result.append((start[0] + (end[0] - start[0]) * fraction,
                       start[1] + (end[1] - start[1]) * fraction))
    return result


def assign_targets(origins, targets):
    """Return a bijection minimizing travel, with bounded work for large desktops.

    Up to 128 icons use exact Hungarian matching on Euclidean distance. Larger
    desktops use spatial greedy matching followed by two improving pair-swap
    passes, O(n²), to avoid cubic UI stalls and remove unnecessary crossings.
    """
    count = len(origins)
    if count != len(targets):
        raise ValueError("each icon requires exactly one target")
    if not count:
        return []
    if count > 128:
        free = set(range(count))
        result = [-1] * count
        for index in sorted(range(count), key=lambda i: (origins[i][0], origins[i][1], i)):
            target = min(free, key=lambda j: (math.dist(origins[index], targets[j]), j))
            result[index] = target
            free.remove(target)
        for _ in range(2):
            changed = False
            for first in range(count):
                for second in range(first + 1, count):
                    a, b = result[first], result[second]
                    old = math.dist(origins[first], targets[a]) + math.dist(origins[second], targets[b])
                    new = math.dist(origins[first], targets[b]) + math.dist(origins[second], targets[a])
                    if new + 1e-8 < old:
                        result[first], result[second] = b, a
                        changed = True
            if not changed:
                break
        return result
    costs = [[math.dist(origin, target) for target in targets] for origin in origins]
    row_potential, col_potential = [0.0] * (count + 1), [0.0] * (count + 1)
    matched_row, previous = [0] * (count + 1), [0] * (count + 1)
    for row in range(1, count + 1):
        matched_row[0] = row
        minimum = [math.inf] * (count + 1)
        used = [False] * (count + 1)
        col = 0
        while True:
            used[col] = True
            current_row = matched_row[col]
            delta, next_col = math.inf, 0
            for candidate in range(1, count + 1):
                if used[candidate]:
                    continue
                reduced = costs[current_row - 1][candidate - 1] - row_potential[current_row] - col_potential[candidate]
                if reduced < minimum[candidate]:
                    minimum[candidate], previous[candidate] = reduced, col
                if minimum[candidate] < delta:
                    delta, next_col = minimum[candidate], candidate
            for candidate in range(count + 1):
                if used[candidate]:
                    row_potential[matched_row[candidate]] += delta
                    col_potential[candidate] -= delta
                else:
                    minimum[candidate] -= delta
            col = next_col
            if matched_row[col] == 0:
                break
        while col:
            prior = previous[col]
            matched_row[col] = matched_row[prior]
            col = prior
    result = [-1] * count
    for col in range(1, count + 1):
        result[matched_row[col] - 1] = col - 1
    return result


@dataclass
class DrawingActor:
    key: str
    name: str
    home: tuple[float, float]
    size: tuple[float, float]
    x: float
    y: float
    target: tuple[float, float]
    state: str = "home"
    velocity: tuple[float, float] = (0.0, 0.0)
    speed: float = 0.0

    @property
    def pos(self):
        return self.x, self.y


class DrawingSession:
    """Arrange the same desktop actors along freely drawn, disconnected strokes.

    No operating-system layout, combat resources, player stats, or save files are
    touched. Positions and paths are physical global center coordinates.
    """

    MAX_STROKES = 16
    MAX_POINTS = 512
    state = "drawing"
    mode = "drawing"

    def __init__(self, icons: list[dict], bounds: tuple[int, int, int, int]):
        self.bounds = tuple(float(value) for value in bounds)
        left, top, right, bottom = self.bounds
        if not all(math.isfinite(value) for value in self.bounds) or right <= left or bottom <= top:
            raise ValueError("drawing bounds must be a finite, nonempty LTRB rectangle")
        if len({str(icon["key"]) for icon in icons}) != len(icons):
            raise ValueError("desktop icons must have unique identities")
        self.scale = math.hypot(right - left, bottom - top) / math.hypot(1920, 1042)
        self.actors = []
        for icon in icons:
            home = tuple(float(value) for value in icon["home"])
            raw_size = icon.get("size", (32, 32))
            size = ((float(raw_size), float(raw_size)) if isinstance(raw_size, (int, float))
                    else tuple(float(value) for value in raw_size))
            if len(home) != 2 or len(size) != 2 or min(size) <= 0 or not all(math.isfinite(v) for v in home + size):
                raise ValueError("drawing icon coordinates and sizes must be finite")
            self.actors.append(DrawingActor(str(icon["key"]), str(icon.get("name", "")),
                                            home, size, *home, home))
        self.strokes: list[list[tuple[float, float]]] = []
        self.preview: list[tuple[float, float]] = []
        self.target_points: list[tuple[float, float]] = []
        self.drawing = False
        self._append = True
        self.total_time = 0.0
        self._accumulator = 0.0
        self.last_error = ""

    @property
    def current(self):
        return self.preview

    @property
    def stroke_count(self):
        return len(self.strokes)

    def _point(self, point):
        x, y = float(point[0]), float(point[1])
        if not math.isfinite(x) or not math.isfinite(y):
            return None
        left, top, right, bottom = self.bounds
        return _clamp(x, left, right), _clamp(y, top, bottom)

    def begin_stroke(self, point, append=True):
        self.cancel_stroke()
        start = self._point(point)
        if start is None:
            return False
        self.drawing, self._append = True, bool(append)
        self.preview = [start]
        self.last_error = ""
        return True

    def add_point(self, point):
        if not self.drawing:
            return False
        p = self._point(point)
        if p is None or math.dist(self.preview[-1], p) < max(.5, 1.5 * self.scale):
            return False
        self.preview.append(p)
        if len(self.preview) > self.MAX_POINTS * 2:
            self.preview = simplify_stroke(self.preview, max(.5, 1.5 * self.scale), self.MAX_POINTS)
        return True

    def end_stroke(self):
        if not self.drawing:
            return False
        stroke = simplify_stroke(self.preview, max(.3, .9 * self.scale), self.MAX_POINTS)
        append = self._append
        self.cancel_stroke()
        length = sum(math.dist(a, b) for a, b in zip(stroke, stroke[1:]))
        if length < max(3.0, 8.0 * self.scale):
            self.last_error = "笔划太短，请画一条更长的线。"
            return False
        if append and len(self.strokes) >= self.MAX_STROKES:
            self.last_error = "最多保留 16 笔；可撤销或清空后继续。"
            return False
        self.strokes = [*self.strokes, stroke] if append else [stroke]
        self.last_error = ""
        self._arrange()
        return True

    def cancel_stroke(self):
        self.preview = []
        self.drawing = False

    def undo(self):
        self.cancel_stroke()
        if not self.strokes:
            return False
        self.strokes.pop()
        self._arrange()
        self.last_error = ""
        return True

    def reset(self):
        self.cancel_stroke()
        self.strokes.clear()
        self.target_points.clear()
        self.last_error = ""
        for actor in self.actors:
            actor.target = actor.home
            actor.state = "home" if math.dist(actor.pos, actor.home) < .01 else "moving"

    def _arrange(self):
        self.target_points = sample_strokes(self.strokes, len(self.actors))
        if not self.target_points:
            for actor in self.actors:
                actor.target = actor.home
                actor.state = "home" if math.dist(actor.pos, actor.home) < .01 else "moving"
            return
        assignment = assign_targets([actor.pos for actor in self.actors], self.target_points)
        for index, actor in enumerate(self.actors):
            actor.target = self.target_points[assignment[index]]
            actor.state = "arranged" if math.dist(actor.pos, actor.target) < .01 else "moving"

    def preset(self, name):
        if name not in ("heart", "star", "circle"):
            return False
        left, top, right, bottom = self.bounds
        cx, cy = (left + right) / 2, (top + bottom) / 2
        radius = min(right - left, bottom - top) * .33
        if name == "circle":
            points = [(cx + math.cos(i * math.tau / 160) * radius,
                       cy + math.sin(i * math.tau / 160) * radius) for i in range(161)]
        elif name == "star":
            points = [(cx + math.cos(-math.pi/2 + i * math.pi/5) * radius * (1 if i % 2 == 0 else .43),
                       cy + math.sin(-math.pi/2 + i * math.pi/5) * radius * (1 if i % 2 == 0 else .43))
                      for i in range(11)]
        else:
            raw = [(16 * math.sin(i * math.tau / 200) ** 3,
                    -(13 * math.cos(i * math.tau / 200) - 5 * math.cos(2*i*math.tau/200)
                      - 2 * math.cos(3*i*math.tau/200) - math.cos(4*i*math.tau/200)))
                   for i in range(201)]
            min_y, max_y = min(p[1] for p in raw), max(p[1] for p in raw)
            points = [(cx + x * radius / 16, cy + (y - (min_y + max_y)/2) * radius / 16) for x, y in raw]
        self.cancel_stroke()
        self.strokes = [simplify_stroke(points, max(.3, .65 * self.scale), self.MAX_POINTS)]
        self.last_error = ""
        self._arrange()
        return True

    def update(self, dt):
        if dt <= 0 or not math.isfinite(dt):
            return
        self._accumulator += min(float(dt), .25)
        step = 1.0 / 60.0
        while self._accumulator + 1e-10 >= step:
            self._accumulator -= step
            self.total_time += step
            acceleration, top_speed = 1700.0 * self.scale, 640.0 * self.scale
            for actor in self.actors:
                dx, dy = actor.target[0] - actor.x, actor.target[1] - actor.y
                distance = math.hypot(dx, dy)
                if distance < max(.05, .15 * self.scale):
                    actor.x, actor.y = actor.target
                    actor.speed, actor.velocity = 0.0, (0.0, 0.0)
                    actor.state = "home" if not self.strokes else "arranged"
                    continue
                desired = min(top_speed, math.sqrt(2 * acceleration * distance), distance * 5)
                actor.speed += _clamp(desired - actor.speed, -acceleration * step, acceleration * step)
                amount = min(distance, actor.speed * step)
                actor.x += dx / distance * amount
                actor.y += dy / distance * amount
                actor.velocity = (dx / distance * actor.speed, dy / distance * actor.speed)
                actor.state = "moving"
