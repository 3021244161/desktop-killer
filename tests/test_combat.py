"""Combat invariants, deterministic transitions, and tiny-desktop completion."""
import copy
import math

import pytest

from desktop_world.scene import GameSession, Projectile, Shard
from desktop_world.content import UPGRADES
from desktop_world.content import classify_role


def game(count=8, mode="campaign", seed=17, bounds=(0, 0, 1920, 1042)):
    left, top, right, bottom = bounds
    icons = [{"key": str(i), "name": f"icon {i}",
              "home": (left + (right-left) * (.15 + .13*(i % 5)),
                       top + (bottom-top) * (.2 + .16*(i // 5))), "size": (32, 32)}
             for i in range(count)]
    return GameSession(icons, bounds, mode, seed)


def frames(session, seconds, cursor=None, choose=True):
    for _ in range(round(seconds * 60)):
        if session.state == "upgrade" and choose:
            session.choose_upgrade(0)
        session.update(1/60, cursor or session.player.pos)


def kill(session, actor):
    if actor.state in ("home", "sealed", "rebooting"):
        session._wake(actor)
    session._damage_enemy(actor, actor.max_hp + 1)


def seal_at_home(session, actor):
    session.player.x, session.player.y = actor.home
    session.player.fire_cd = 999
    frames(session, 1.2, actor.home)


def clear_stage(session):
    for actor in session._eligible[:session.seal_goal]:
        kill(session, actor)
        seal_at_home(session, actor)
    assert session.sealed_count == session.seal_goal
    assert session.boss_spawned
    boss = session._by_key[session.boss_key]
    session._damage_enemy(boss, boss.max_hp + 1)
    if boss.state == "rebooting":
        seal_at_home(session, boss)
    frames(session, .05)


def test_original_actor_identity_and_geometry_survive_death_revival_and_stage():
    session = game()
    original = [(id(a), a.key, a.home, a.size) for a in session.actors]
    actor = session.actors[0]
    kill(session, actor)
    assert actor.state == "rebooting" and actor.pos == actor.home
    old_hp = actor.max_hp
    session.player.x, session.player.y = (1800, 950)
    session.player.fire_cd = 999
    frames(session, 8.1)
    assert actor.generation == 1 and actor.max_hp > old_hp
    assert [(id(a), a.key, a.home, a.size) for a in session.actors] == original


@pytest.mark.parametrize("count", [1, 2, 3])
def test_tiny_desktop_finishes_all_three_campaign_chapters_without_clones(count):
    session = game(count)
    identities = [id(a) for a in session.actors]
    for chapter in (1, 2, 3):
        clear_stage(session)
        assert [id(a) for a in session.actors] == identities
        assert session.chapter == chapter
        if chapter < 3:
            assert session.state == "intermission"
            assert session.choose_stage(0)
        else:
            assert session.state == "won"
    assert session.summary()["bosses"] == 3
    assert session.summary()["won"] is True


def test_sealing_requires_staying_at_port_and_restores_health():
    session = game(2)
    actor = session.actors[0]
    kill(session, actor)
    session.player.hp = 40
    frames(session, .8)
    assert session.sealed_count == 0
    session.player.x, session.player.y = actor.home
    frames(session, .5, actor.home)
    assert 0 < actor.seal_progress < 1
    assert actor.state == "rebooting"
    frames(session, .55, actor.home)
    assert actor.state == "sealed" and session.sealed_count == 1
    assert session.player.hp == 48


def test_seal_goal_alone_does_not_clear_and_boss_hijack_preserves_progress():
    session = game(1)
    actor = session.actors[0]
    kill(session, actor)
    seal_at_home(session, actor)
    assert session.sealed_count == 1
    assert actor.is_boss and actor.state in ("waking", "active")
    assert actor.hp == actor.max_hp == 250
    assert actor.sealed_once and not session.boss_defeated
    assert session.state == "playing"


def test_boss_death_alone_does_not_clear_stage():
    session = game(8)
    session._spawn_boss()
    boss = session._by_key[session.boss_key]
    session._damage_enemy(boss, 9999)
    frames(session, .1)
    assert session.boss_defeated
    assert session.sealed_count < session.seal_goal
    assert session.state not in ("won", "intermission")


@pytest.mark.parametrize("state", ["paused", "upgrade", "intermission", "won", "lost"])
def test_nonplaying_states_freeze_entire_combat_clock(state):
    session = game()
    frames(session, 2)
    session.state = state
    before = (session.total_time, session.stage_time, copy.deepcopy(session.player),
              copy.deepcopy(session.actors), copy.deepcopy(session.bullets), copy.deepcopy(session.effects))
    session.update(5, (0, 0), dash=True)
    assert not session.pulse() and not session.dash((0, 0))
    after = (session.total_time, session.stage_time, session.player, session.actors,
             session.bullets, session.effects)
    assert after == before


def test_same_seed_and_fixed_steps_are_deterministic_across_frame_partition():
    first, second = game(seed=31), game(seed=31)
    for _ in range(240):
        first.update(1/60, (1700, 900))
    for _ in range(120):
        second.update(1/30, (1700, 900))
    assert first.player == second.player
    assert first.actors == second.actors
    assert first.bullets == second.bullets
    assert first.summary() == second.summary()


@pytest.mark.parametrize("kind,style", [("chaser", "charge"), ("charger", "charge"),
                                       ("ranger", "shot"), ("orbiter", "spread")])
def test_each_enemy_has_locked_telegraph_before_attack(kind, style):
    session = game(1)
    actor = session.actors[0]
    actor.kind, actor.state, actor.attack_cd = kind, "active", 0
    actor.x, actor.y = session.player.x + 50 * session.scale, session.player.y
    session._enemy_step(actor, 1/60)
    assert actor.attack_phase == "telegraph"
    assert actor.telegraph_left > 0 and actor.attack_style == style
    target = actor.aim
    session.player.x += 100
    session._enemy_step(actor, .1)
    assert actor.aim == target
    assert not session.bullets


def test_boss_salvo_count_is_not_squared():
    session = game(1)
    session._spawn_boss()
    boss = session.actors[0]
    boss.attack_style, boss.aim = "fan", session.player.pos
    session._enemy_fire(boss)
    assert len(session.bullets) == 5


def test_dash_protects_and_pulse_intercepts_with_real_cooldowns():
    session = game(2)
    p = session.player
    p.invulnerable = 0
    assert session.dash((p.x + 100, p.y))
    assert not session._hurt_player(50)
    assert not session.dash((0, 0))
    session.bullets.append(Projectile(p.x + 40, p.y, 0, 0, 5, 10, True))
    assert session.pulse()
    assert not any(b.enemy for b in session.bullets)
    assert not session.pulse()


def test_shards_auto_collect_at_timeout_and_stage_clear_does_not_discard_xp():
    session = game(2)
    session.shards.append(Shard(0, 0, 10, age=4.49))
    before = session.player.xp
    session._move_shards(.02)
    assert session.player.xp == before + 10 and not session.shards
    session.shards.append(Shard(0, 0, 5))
    session._complete_stage()
    assert session.player.xp == before + 15 and not session.shards


def test_three_weapon_routes_change_actual_attacks_and_upgrade_pool_is_bounded():
    session = game(3)
    for key in ("multishot", "chain", "blades"):
        session.state = "upgrade"
        session.upgrade_choices = [{"id": key}]
        assert session.choose_upgrade(0)
    assert session.player.projectiles == 2 and session.player.chain_level == session.player.blade_level == 1
    session._fire(session.actors[0])
    assert len(session.bullets) == 2
    assert len(session.blade_positions()) == 1
    for key, value in UPGRADES.items():
        session.upgrade_stacks[key] = value[2]
    session._pending_upgrades = 10
    session._open_upgrade()
    assert session.state == "playing" and session._pending_upgrades == 0


def test_stage_reward_is_not_repeatable_and_endless_continues():
    session = game(1, "endless")
    for _ in range(4):
        clear_stage(session)
        assert session.state == "intermission"
        assert session.choose_stage(1)
        damage = session.player.damage
        assert not session.choose_stage(1)
        assert session.player.damage == damage
    assert session.chapter == 5 and session.state == "playing"
    assert session.retire()
    result = session.summary()
    assert result["reason"] == "retired" and result["stage"] == 5 and not result["won"]


def test_blitz_has_real_deadline_and_two_victory_conditions():
    session = game(1, "blitz")
    assert session.stage_limit == 180
    actor = session.actors[0]
    kill(session, actor)
    seal_at_home(session, actor)
    assert session.sealed_count == 1 and not session.boss_spawned
    assert session.state == "playing"
    session.stage_time = 145.0
    frames(session, .05)
    assert session.boss_spawned
    session._damage_enemy(actor, actor.max_hp + 1)
    frames(session, .05)
    assert session.state == "won"
    other = game(1, "blitz")
    other.stage_time = 180 - 1/120
    other.update(1/60, other.player.pos)
    assert other.state == "lost" and other.summary()["reason"] == "timeout"


def test_blitz_surges_reuse_sealed_entity_with_warning_and_keep_unique_goal():
    session = game(1, "blitz")
    actor = session.actors[0]
    identity = id(actor)
    kill(session, actor)
    seal_at_home(session, actor)
    session._surge_timer = 0
    frames(session, 1/60)
    assert id(session.actors[0]) == identity and len(session.actors) == 1
    assert actor.state == "waking" and actor.generation == 1
    assert actor.telegraph_left > 1
    assert session.sealed_count == 1
    assert any(e["kind"] == "surge" and e["count"] == 1 and e["phase"] == 1 for e in session.events)
    session.stage_time = 105
    session._blitz_pressure(1/60)
    assert session.blitz_phase == 3


@pytest.mark.parametrize("name,role", [("Google Chrome", "ranger"), ("Microsoft Edge", "ranger"),
    ("火狐浏览器", "ranger"), ("Steam", "charger"), ("Epic Games Launcher", "charger"),
    ("工作记录.pdf", "orbiter"), ("照片.png", "orbiter")])
def test_familiar_icon_names_have_recognizable_roles(name, role):
    assert classify_role(name) == role


@pytest.mark.parametrize("bounds", [(0, 0, 1280, 695), (0, 0, 3840, 2084), (-1920, 0, 0, 1042)])
def test_speed_skills_scale_with_screen_but_native_icons_do_not(bounds):
    session = game(1, bounds=bounds)
    assert session.player.speed == pytest.approx(330 * session.scale)
    assert session.pulse_radius == pytest.approx(170 * session.scale)
    assert session.actors[0].size == (32, 32)
    clear_stage(session)
    assert session.state == "intermission"
