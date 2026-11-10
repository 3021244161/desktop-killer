"""Feedback/audio/settings wiring with synthetic assets and no audio or HWND access."""
import copy
import os
from types import SimpleNamespace

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

from PIL import Image, ImageDraw
import pygame
import pytest

from desktop_world.game_view import GameView
from desktop_world.profile import SETTINGS, _default_profile, _validated, set_setting


class FakeAudio:
    def __init__(self):
        self.music = []
        self.sounds = []
        self.muted = False

    def update_music(self, context, dt, **kwargs):
        self.music.append(dict(context=context, dt=dt, **kwargs))

    def play(self, name):
        self.sounds.append(name)

    def set_muted(self, value):
        self.muted = value


def snapshot(bounds=(0,0,1000,700), work_area=None):
    left,top,right,bottom = work_area or bounds
    icons = []
    image = Image.new("RGBA",(24,24))
    ImageDraw.Draw(image).rectangle((3,3,20,20),fill=(0,0,0,255))
    ImageDraw.Draw(image).rectangle((8,8,15,15),fill=(130,220,170,255))
    for i in range(6):
        x,y = left+35+(i%3)*70,top+60+(i//3)*90
        icons.append(SimpleNamespace(key=str(i),name=f"Synthetic {i}",x=x,y=y,width=24,height=24,
            image=image.copy(),label_rect=(x-8,y+27,x+42,y+43)))
    return SimpleNamespace(bounds=bounds,work_area=work_area or bounds,icons=icons,font_name="arial",font_size=12)


def view(bounds=(0,0,1000,700), *, mode=None, persist=None, work_area=None):
    return GameView(snapshot(bounds,work_area),_default_profile(),FakeAudio(),
                    start_mode=mode,seed=11,on_profile_change=persist)


def click(game, action):
    game.render()
    rect = next(rect for rect,value in reversed(game.buttons) if value == action)
    assert game.work.contains(rect)
    return game.handle_click(rect.centerx+game.offset.x,rect.centery+game.offset.y,1)


@pytest.mark.parametrize("version", [1,2])
def test_old_settings_get_new_defaults_without_losing_existing_preferences(version):
    profile = _default_profile()
    profile["version"] = version
    profile["muted"] = True
    profile["settings"] = {"show_hints":False,"reduced_motion":True,"drawing_guides":False}
    migrated = _validated(profile)
    assert migrated["muted"] is True
    assert migrated["settings"]["show_hints"] is False
    assert migrated["settings"]["reduced_motion"] is True
    assert migrated["settings"]["drawing_guides"] is False
    for key in ("music_enabled","music_volume","screen_flash","screen_shake","low_health_vignette"):
        assert migrated["settings"][key] == SETTINGS[key]


@pytest.mark.parametrize("volume", [-.1,1.01,float("nan"),float("inf"),-float("inf"),True,"0.5",None])
def test_invalid_volume_changes_are_rejected_atomically(volume):
    profile = _default_profile()
    before = copy.deepcopy(profile)
    with pytest.raises(ValueError):
        set_setting(profile,"music_volume",volume)
    assert profile == before


@pytest.mark.parametrize("volume", [0,.2,.35,.7,1])
def test_valid_volume_endpoints_and_fraction_survive_validation(volume):
    profile = _default_profile()
    set_setting(profile,"music_volume",volume)
    assert _validated(profile)["settings"]["music_volume"] == float(volume)


@pytest.mark.parametrize("bounds", [(0,0,640,360),(-640,-360,0,0),(-1920,100,-640,820)])
def test_settings_controls_fit_do_not_overlap_and_operate_at_negative_origins(bounds):
    game = view(bounds)
    game.page = "settings"
    game.render()
    controls = list(game.buttons)
    for index,(rect,action) in enumerate(controls):
        assert game.work.contains(rect), action
        for other,other_action in controls[index+1:]:
            assert not rect.colliderect(other), f"{action} overlaps {other_action}"
    assert {action for rect,action in controls} >= {
        "volume:next","setting:music_enabled","setting:screen_flash","setting:screen_shake",
        "setting:low_health_vignette","setting:reduced_motion","page:home"}
    for key in ("music_enabled","screen_flash","screen_shake","low_health_vignette","reduced_motion"):
        old = game.profile["settings"][key]
        click(game,"setting:"+key)
        assert game.profile["settings"][key] is not old
    old_volume = game.profile["settings"]["music_volume"]
    click(game,"volume:next")
    assert 0 <= game.profile["settings"]["music_volume"] <= 1
    assert game.profile["settings"]["music_volume"] != old_volume


def test_failed_volume_save_rolls_back_and_audio_receives_old_volume():
    game = view(persist=lambda: False)
    game.page = "settings"
    before = copy.deepcopy(game.profile)
    click(game,"volume:next")
    assert game.profile == before
    assert "保存失败" in game.toast
    game.update_audio(.1)
    assert game.audio.music[-1]["volume"] == before["settings"]["music_volume"]


def test_audio_context_routes_menu_drawing_battle_and_boss_without_mutating_combat():
    game = view()
    game.update_audio(.1)
    assert game.audio.music[-1]["context"] == "menu"
    game.start("drawing")
    game.update_audio(.1)
    assert game.audio.music[-1]["context"] == "drawing"
    game.start("campaign")
    before = copy.deepcopy((game.session.player,game.session.actors,game.session.total_time))
    game.update_audio(.1)
    assert game.audio.music[-1]["context"] == "battle"
    assert (game.session.player,game.session.actors,game.session.total_time) == before
    game.session._spawn_boss()
    game.update_audio(.1)
    assert game.audio.music[-1]["context"] == "boss"
    game.session.boss_defeated = True
    game.update_audio(.1)
    assert game.audio.music[-1]["context"] == "battle"


@pytest.mark.parametrize("state", ["upgrade","intermission","won","lost"])
def test_modal_music_pauses_but_result_and_upgrade_sfx_remain_unsuspended(state):
    game = view(mode="campaign")
    game.session.state = state
    game.update_audio(.1,foreground=True)
    call = game.audio.music[-1]
    assert call["paused"] is True
    assert call["suspended"] is False


def test_explicit_pause_focus_and_drawing_pause_suspend_all_audio():
    game = view(mode="campaign")
    game.handle_key(ord("P"),game.session.player.pos)
    game.update_audio(.1)
    assert game.audio.music[-1]["paused"] and game.audio.music[-1]["suspended"]
    game.handle_key(ord("P"),game.session.player.pos)
    game.update_audio(0,foreground=True)
    assert not game.audio.music[-1]["paused"] and not game.audio.music[-1]["suspended"]
    game.focus_changed(False)
    game.update_audio(.1,foreground=False)
    assert game.audio.music[-1]["suspended"]
    game.start("drawing")
    game.drawing_paused = True
    game.update_audio(.1,foreground=True)
    assert game.audio.music[-1]["context"] == "drawing"
    assert game.audio.music[-1]["paused"] and game.audio.music[-1]["suspended"]
    game._act("menu")
    game.update_audio(.1,foreground=False)
    assert game.audio.music[-1]["context"] == "menu"
    assert game.audio.music[-1]["suspended"]


def test_music_enable_volume_and_master_mute_routes_are_independent():
    game = view()
    game.page = "settings"
    click(game,"setting:music_enabled")
    click(game,"volume:next")
    game.update_audio(.2)
    call = game.audio.music[-1]
    assert call["enabled"] is False
    assert call["volume"] == .5
    game.handle_key(ord("M"),(0,0))
    assert game.profile["muted"] and game.audio.muted
    assert game.profile["settings"]["music_enabled"] is False


def test_camera_moves_dynamic_pixels_without_changing_world_input_homes_or_hud():
    game = view((-1000,-700,0,0),mode="campaign")
    settings = game.profile["settings"]
    settings.update(screen_flash=False,low_health_vignette=False)
    moving = game.session.actors[1]
    moving.state = "active"
    moving.x,moving.y = -500,-350
    moving.state_time = .2
    port = game.session.actors[2]
    port.state,port.reboot_left = "rebooting",5.0
    world = copy.deepcopy((game.session.player,game.session.actors,game.session.bullets))
    input_point = (-345,-234)
    projected = game._point(input_point)
    baseline = game.render().copy()
    buttons = [(r.copy(),a) for r,a in game.buttons]
    game.feedback.receive({"kind":"kill","boss":True})
    shaken = game.render().copy()
    assert game.feedback.offset() != (0,0)
    assert game._point(input_point) == projected
    assert (game.session.player,game.session.actors,game.session.bullets) == world
    assert game.buttons == buttons
    icon = game.snapshot.icons[0]
    home_rect = pygame.Rect(icon.x-game.offset.x-5,icon.y-game.offset.y-5,65,55)
    assert pygame.image.tobytes(baseline.subsurface(home_rect),"RGBA") == pygame.image.tobytes(shaken.subsurface(home_rect),"RGBA")
    port_point = game._point(port.home)
    port_rect = pygame.Rect(port_point[0]-40,port_point[1]-40,80,90)
    assert pygame.image.tobytes(baseline.subsurface(port_rect),"RGBA") == pygame.image.tobytes(shaken.subsurface(port_rect),"RGBA")
    sc = game.scale
    hud = pygame.Rect(game.work.right-round(334*sc)+6,game.work.top+round(18*sc)+6,
                      round(316*sc)-12,round(148*sc)-12)
    assert pygame.image.tobytes(baseline.subsurface(hud),"RGBA") == pygame.image.tobytes(shaken.subsurface(hud),"RGBA")
    moving_rect = pygame.Rect(450,280,100,110)
    assert pygame.image.tobytes(baseline.subsurface(moving_rect),"RGBA") != pygame.image.tobytes(shaken.subsurface(moving_rect),"RGBA")


@pytest.mark.parametrize("destination", ["menu","drawing","paused","upgrade","intermission"])
def test_render_immediately_clears_feedback_on_noncombat_destination(destination):
    game = view(mode="campaign")
    game.session.player.hp = 10
    game.feedback.receive({"kind":"hurt","damage":20})
    game._update_feedback(.05)
    assert game.feedback.offset() != (0,0) or game.feedback.flash_alpha
    if destination == "menu":
        game._act("menu")
    elif destination == "drawing":
        game.start("drawing")
    else:
        game.session.state = destination
    game.render()
    assert game.feedback.offset() == (0,0)
    assert game.feedback.flash_alpha == game.feedback.low_health_alpha == 0


def test_reduced_mode_keeps_only_static_workarea_red_edge():
    game = view(mode="campaign")
    game.profile["settings"]["reduced_motion"] = True
    game.session.player.hp = 10
    game.feedback.receive({"kind":"kill","boss":True})
    game._update_feedback(3)
    assert game.feedback.offset() == (0,0) and game.feedback.flash_alpha == 0
    assert game.feedback.low_health_alpha > 0
    alphas=[]
    for _ in range(120):
        game._update_feedback(1/60)
        alphas.append(game.feedback.low_health_alpha)
    assert len(set(alphas)) == 1
    frame = pygame.Surface(game.frame.get_size(),pygame.SRCALPHA)
    game.feedback.render_overlay(frame,game.work)
    assert frame.get_at(game.work.center).a == 0
    assert frame.get_at(game.work.topleft).a > 0
    game.profile["settings"]["low_health_vignette"] = False
    game.render()
    assert game.feedback.low_health_alpha == 0
