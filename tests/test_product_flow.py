"""Player flows through actual views, using synthetic icons and memory-only saves."""
import copy
import math
import os
from types import SimpleNamespace

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

from PIL import Image, ImageDraw
import pytest

from desktop_world.game_view import GameView, MODES
from desktop_world.profile import _default_profile
from desktop_world.progression import purchase_talent, talent_bonuses, talent_catalog
from desktop_world.scene import DrawingSession, GameSession
from desktop_world.wardrobe import outfit_catalog


def snapshot(bounds=(0, 0, 1000, 700), count=8):
    left, top, right, bottom = bounds
    image = Image.new("RGBA", (24, 24))
    ImageDraw.Draw(image).ellipse((2, 2, 21, 21), fill=(0, 0, 0, 255))
    icons = []
    for index in range(count):
        x = left + 30 + (index % 4) * min(70, (right-left-80)//4)
        y = top + 35 + (index // 4) * 65
        icons.append(SimpleNamespace(key=str(index), name=f"Icon {index}", x=x, y=y,
            width=24, height=24, image=image.copy(), label_rect=(x-8,y+27,x+32,y+43)))
    return SimpleNamespace(bounds=bounds, work_area=bounds, icons=icons, font_name="arial", font_size=12)


def view(bounds=(0, 0, 1000, 700), *, funds=0, persist=None, mode=None):
    profile = _default_profile()
    profile["progression"]["crystals"] = funds
    return GameView(snapshot(bounds), profile=profile, on_profile_change=persist,
                    start_mode=mode, seed=11)


def click(game, action):
    game.render()
    rect = next(rect for rect, item in reversed(game.buttons) if item == action)
    assert game.work.contains(rect), f"control outside work area: {action}: {rect}"
    assert game.frame.get_at(rect.center).a > 0
    point = (rect.centerx + game.offset.x, rect.centery + game.offset.y)
    return game.handle_click(*point, 1)


def draw_line(game, points, *, keys=(0x11,)):
    game.render()
    for point in points:
        game.update(1/60, point, keys=keys, buttons=(1,))
    game.update(1/60, points[-1], keys=keys, buttons=())


@pytest.mark.parametrize("bounds", [(0,0,1000,700), (-1000,-700,0,0), (0,0,640,360)])
def test_ctrl_left_multiframe_release_commits_one_even_formation(bounds):
    saves = []
    game = view(bounds, mode="drawing", persist=lambda: saves.append(True) or True)
    left, top, _, _ = bounds
    points = [(left+x,top+230) for x in range(40, 301, 20)]
    draw_line(game, points)
    session = game.session
    assert isinstance(session, DrawingSession)
    assert len(session.strokes) == 1 and not session.preview and not session.drawing
    assert len(session.target_points) == len(session.actors)
    xs = sorted(x for x,y in session.target_points)
    gaps = [b-a for a,b in zip(xs,xs[1:])]
    assert gaps == pytest.approx([260/len(xs)]*len(gaps))
    assert all(y == top+230 for x,y in session.target_points)
    assert len(saves) == 1
    assert game.profile["progression"]["totals"]["draw_strokes"] == 1


def test_plain_left_drag_and_ui_origin_chord_never_draw():
    game = view(mode="drawing")
    draw_line(game, [(40,230),(100,230),(300,230)], keys=())
    assert not game.session.strokes
    game.render()
    point = tuple(game._drawing_ui_rect.center)
    game.update(1/60, point, keys=(0x11,), buttons=(1,))
    game.update(1/60, (100,230), keys=(0x11,), buttons=(1,))
    game.update(1/60, (300,230), keys=(0x11,), buttons=(1,))
    game.update(1/60, (300,230), keys=(0x11,), buttons=())
    assert not game.session.strokes and not game.session.preview


def test_fast_stroke_includes_the_release_position():
    game = view(mode="drawing")
    game.render()
    game.update(1/60, (40, 230), keys=(0x11,), buttons=(1,))
    game.update(1/60, (300, 230), keys=(0x11,), buttons=())
    assert game.session.strokes == [[(40.0, 230.0), (300.0, 230.0)]]


def test_focus_loss_cancels_preview_and_freezes_until_explicit_resume():
    game = view(mode="drawing")
    game.render()
    for point in ((40,230),(100,230),(180,230)):
        game.update(1/60, point, keys=(0x11,), buttons=(1,))
    assert game.session.preview
    game.focus_changed(False)
    before = (game.session.total_time, [a.pos for a in game.session.actors])
    for active in (False, True, True):
        game.focus_changed(active)
        game.update(.1, (300,230))
    assert game.drawing_paused
    assert not game.session.preview and not game.session.strokes
    assert (game.session.total_time, [a.pos for a in game.session.actors]) == before
    game.handle_key(ord("P"), (300,230))
    game.update(1/60, (300,230))
    assert not game.drawing_paused and game.session.total_time > before[0]
    assert not game.session.strokes


def test_resume_with_old_chord_held_requires_a_new_press_before_drawing():
    game = view(mode="drawing")
    game.render()
    game.update(1/60,(40,230),keys=(0x11,),buttons=(1,))
    game.update(1/60,(140,230),keys=(0x11,),buttons=(1,))
    game.focus_changed(False)
    game.focus_changed(True)
    game.handle_key(ord("P"),(140,230))
    game.update(1/60,(150,230),keys=(0x11,),buttons=(1,))
    game.update(1/60,(300,230),keys=(0x11,),buttons=(1,))
    game.update(1/60,(300,230),keys=(0x11,),buttons=())
    assert not game.session.strokes
    draw_line(game, [(40,230),(150,230),(300,230)])
    assert len(game.session.strokes) == 1


def test_drawing_toolbar_preset_undo_reset_and_guides_use_real_clicks():
    game = view(mode="drawing")
    click(game, "preset:heart")
    assert game.session.stroke_count == 1
    draw_line(game, [(40,500),(120,500),(300,500)])
    assert game.session.stroke_count == 2
    click(game, "draw:undo")
    assert game.session.stroke_count == 1
    guides = game.profile["settings"]["drawing_guides"]
    game.handle_key(0x20,(0,0))
    assert game.profile["settings"]["drawing_guides"] is not guides
    click(game, "draw:reset")
    assert game.session.stroke_count == 0
    assert all(a.target == a.home for a in game.session.actors)


@pytest.mark.parametrize("bounds", [(0,0,1000,700), (-640,-360,0,0), (0,0,640,360)])
def test_four_menu_entrances_and_every_product_page_have_hittable_controls(bounds):
    for mode in MODES:
        game = view(bounds)
        click(game, mode)
        assert game.mode == mode and game.session is not None
    game = view(bounds)
    for page in ("wardrobe", "career", "achievements", "settings", "guide"):
        click(game, "page:"+page)
        assert game.page == page and game.session is None
        game.render()
        assert game.buttons
        for rect, action in game.buttons:
            assert game.work.contains(rect), f"{page}/{action}: {rect} outside {game.work}"
        click(game, "page:home")
        assert game.page == "home"


@pytest.mark.parametrize("action", ["outfit:courier", "talent:damage"])
def test_failed_save_rolls_back_purchase_equip_and_wallet(action):
    attempts = []
    game = view(funds=1000, persist=lambda: attempts.append(True) or False)
    game.page = "wardrobe" if action.startswith("outfit") else "career"
    original = copy.deepcopy(game.profile)
    identity = id(game.profile)
    click(game, action)
    assert attempts == [True]
    assert game.profile == original and id(game.profile) == identity
    assert "保存失败" in game.toast


def test_successful_purchase_equips_and_training_affects_next_game():
    game = view(funds=1000, persist=lambda: True)
    game.page = "wardrobe"
    price = next(o["price"] for o in outfit_catalog(game.profile) if o["id"] == "courier")
    click(game, "outfit:courier")
    assert game.profile["progression"]["equipped"] == "courier"
    assert game.profile["progression"]["crystals"] == 1000-price
    game.page = "career"
    click(game,"talent:damage")
    game.start("campaign")
    assert game.session.player.damage == pytest.approx(12*1.05)


def test_settings_toggle_is_persisted_and_failed_toggle_is_rolled_back():
    game = view(persist=lambda: False)
    game.page = "settings"
    original = copy.deepcopy(game.profile)
    click(game,"setting:show_hints")
    assert game.profile == original
    game.on_profile_change = lambda: True
    click(game,"setting:show_hints")
    assert game.profile["settings"]["show_hints"] is False


def test_all_talents_are_bounded_and_survive_upgrade_and_stage_transition():
    profile = _default_profile()
    profile["progression"]["crystals"] = 10000
    for item in talent_catalog(profile):
        for _ in range(item["max_level"]):
            assert purchase_talent(profile,item["id"])["ok"]
        before = copy.deepcopy(profile)
        assert not purchase_talent(profile,item["id"])["ok"]
        assert profile == before
    bonuses = talent_bonuses(profile)
    assert all(.8 <= value <= 1.2 for value in bonuses.values())
    icons = [dict(key="one",name="one",home=(50,50),size=(24,24))]
    session = GameSession(icons,(0,0,1000,700),bonuses=bonuses)
    assert session.player.hp == session.player.max_hp == 120
    assert session.player.shield == session.player.max_shield == 24
    assert session.player.damage == pytest.approx(14.4)
    assert session.player.speed == pytest.approx(330*session.scale*1.2)
    assert session.seal_duration == pytest.approx(.8)
    assert session.pulse() and session.player.pulse_cd == pytest.approx(6*.8)
    assert session.dash((800,500)) and session.player.dash_cd == pytest.approx(2.6*.8)
    session._add_xp(session.player.xp_next)
    session.update(1/60,session.player.pos)
    assert session.state == "upgrade"
    assert session.choose_upgrade(0)
    stacks = session.upgrade_stacks
    assert session.player.damage == pytest.approx(12*(1+.2*stacks.get("damage",0))*1.2)
    session._complete_stage()
    assert session.choose_stage(1)
    assert session.player.damage == pytest.approx(12*(1+.2*stacks.get("damage",0)+.15)*1.2)
    assert session.player.max_hp >= 120 and session.player.max_shield >= 24
    assert session.bonuses == bonuses


def test_untrusted_talent_values_are_clamped_before_they_touch_combat():
    session = GameSession([dict(key="a",name="a",home=(50,50),size=(24,24))],(0,0,1000,700),
                          bonuses={"damage_mult":1000,"max_hp_mult":1000,"speed_mult":1000,
                                   "shield_mult":1000,"cooldown_mult":-100,"seal_duration_mult":-100})
    assert session.player.damage == pytest.approx(14.4)
    assert session.player.max_hp == 120 and session.player.max_shield == 24
    assert session.bonuses["cooldown_mult"] == session.bonuses["seal_duration_mult"] == .8


def test_talents_change_actual_projectiles_movement_damage_and_sealing():
    icons = [dict(key="a",name="a",home=(50,50),size=(24,24))]
    baseline = GameSession(icons,(0,0,1000,700))
    trained = GameSession(icons,(0,0,1000,700),bonuses={
        "damage_mult":1.2,"max_hp_mult":1.2,"speed_mult":1.2,
        "shield_mult":1.2,"seal_duration_mult":.8})
    for session in (baseline, trained):
        session._fire(session.actors[0])
    assert trained.bullets[0].damage == pytest.approx(baseline.bullets[0].damage*1.2)
    start = baseline.player.x
    for _ in range(30):
        for session in (baseline, trained):
            session.update(1/60,session.player.pos,movement=(1,0))
    assert trained.player.x-start == pytest.approx((baseline.player.x-start)*1.2)
    for session in (baseline, trained):
        session.player.invulnerable = 0
        assert session._hurt_player(25)
    assert baseline.player.hp == 95 and trained.player.hp == 119
    for session in (baseline, trained):
        actor = session.actors[0]
        session._wake(actor)
        session._damage_enemy(actor,999)
        session.player.x,session.player.y = actor.home
        for _ in range(54):
            session.update(1/60,actor.home)
    assert baseline.sealed_count == 0
    assert trained.sealed_count == 1
