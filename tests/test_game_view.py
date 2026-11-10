"""Game-facing input, modal, persistence and screen-coordinate regressions.

All assets are synthetic transparent icons. These tests create no native window,
audio device, desktop lease or real profile file.
"""
import copy
import os

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

from PIL import Image, ImageDraw
import pytest

from desktop_world.game_view import GameView
from desktop_world.profile import record_run
from desktop_world.shell import DesktopIcon, DesktopSnapshot


def snapshot(bounds=(0, 0, 800, 600), work_area=None):
    work_area = work_area or bounds
    left, top, right, bottom = work_area
    image = Image.new("RGBA", (32, 32))
    ImageDraw.Draw(image).ellipse((3, 3, 28, 28), fill=(35, 210, 130, 255))
    icons = []
    for index, (fx, fy) in enumerate(((.2, .2), (.2, .65), (.65, .2), (.8, .7))):
        x, y = int(left + (right - left) * fx), int(top + (bottom - top) * fy)
        icons.append(DesktopIcon(str(index), f"Icon {index}", x, y, 32, 32,
                                 image.copy(), (x - 15, y + 35, x + 47, y + 53)))
    return DesktopSnapshot(0, 0, bounds, work_area, icons, "arial", 12)


def profile():
    return {"version": 1, "muted": False, "modes": {}}


def view(**kwargs):
    return GameView(snapshot(), profile(), seed=11, start_mode="campaign", **kwargs)


def click_button(game, action):
    """Click the visible topmost matching control using physical screen pixels."""
    game.render()
    rect = next(rect for rect, candidate in reversed(game.buttons) if candidate == action)
    assert game.work.contains(rect), f"{action} is outside the playable work area"
    assert game.frame.get_at(rect.center).a > 0, f"{action} is not drawn"
    x = rect.centerx + game.snapshot.bounds[0]
    y = rect.centery + game.snapshot.bounds[1]
    return game.handle_click(x, y, 1)


def frozen_combat(session):
    return copy.deepcopy((session.total_time, session.stage_time, session.player,
                          session.actors, session.bullets, session.shards, session.effects,
                          session.score, session.sealed_count, session._pending_upgrades))


@pytest.mark.parametrize("key,axis,direction", [(ord("D"), 0, 1), (0x25, 0, -1),
                                               (ord("W"), 1, -1), (0x28, 1, 1)])
def test_releasing_movement_stops_until_the_mouse_actually_moves(key, axis, direction):
    game = view()
    old_pointer = (20, 20)
    start = game.session.player.pos
    for _ in range(4):
        game.update(.05, old_pointer, keys=(key,))
    stopped = game.session.player.pos
    assert (stopped[axis] - start[axis]) * direction > 0
    for _ in range(6):
        game.update(.05, old_pointer)
    assert game.session.player.pos == pytest.approx(stopped)
    # A fresh mouse gesture deliberately switches back to pointer movement.
    game.update(.05, (35, 20))
    assert game.session.player.pos[0] < stopped[0]


def test_losing_focus_pauses_without_resuming_on_repeated_notifications():
    game = view()
    game.update(.05, game.session.player.pos)
    game.focus_changed(False)
    before = frozen_combat(game.session)
    for active in (False, False, True, True):
        game.focus_changed(active)
        game.update(.2, (0, 0), keys=(ord("D"),))
        game.render()
    assert game.session.state == "paused"
    assert frozen_combat(game.session) == before
    game.handle_key(ord("P"), game.session.player.pos)
    game.update(.05, game.session.player.pos)
    assert game.session.state == "playing"
    assert game.session.total_time > before[0]


def test_slow_mouse_motion_eventually_takes_control_after_keyboard_movement():
    game = view()
    for _ in range(4):
        game.update(.05, (20, 20), keys=(ord("D"),))
    stopped_x = game.session.player.x
    game.update(.05, (20, 20))
    # Intentional pointer motion can be slow: its cumulative distance, rather
    # than the speed of any single frame, must hand control back to the mouse.
    for x in range(21, 33):
        game.update(1 / 60, (x, 20))
    assert game.session.player.x < stopped_x


@pytest.mark.parametrize("modal", ["paused", "upgrade"])
def test_modal_view_freezes_combat_despite_updates_and_action_inputs(modal):
    game = view()
    # Populate actual combat before opening the modal: timers and moving objects
    # must freeze as well as the player, not merely a blank starting scene.
    for _ in range(45):
        game.update(.05, game.session.player.pos)
    session = game.session
    if modal == "paused":
        game.handle_key(ord("P"), session.player.pos)
    else:
        session._add_xp(session.player.xp_next)
        game.update(.05, session.player.pos)
    assert session.state == modal
    before = frozen_combat(session)
    for _ in range(12):
        game.handle_key(0x20, (0, 0))
        game.handle_key(0x10, (0, 0))
        game.update(.2, (0, 0), keys=(ord("D"),))
        game.render()
    assert frozen_combat(session) == before
    if modal == "paused":
        click_button(game, "pause")
    else:
        click_button(game, "choice:0")
    assert session.state == "playing"
    game.update(.05, session.player.pos)
    assert session.total_time > before[0]


def test_retirement_records_once_and_a_restarted_run_gets_its_own_record():
    saved, results = profile(), []

    def on_result(summary):
        results.append(summary.copy())
        return record_run(saved, summary)

    game = GameView(snapshot(), saved, on_result=on_result, start_mode="endless", seed=5)
    for expected_runs in (1, 2):
        game.update(.05, game.session.player.pos)
        game.handle_key(ord("P"), game.session.player.pos)
        click_button(game, "retire")
        for _ in range(12):
            game.update(.1, (0, 0))
            game.render()
        assert len(results) == saved["runs"] == expected_runs
        assert saved["modes"]["endless"]["runs"] == expected_runs
        assert results[-1]["reason"] == "retired"
        assert not game.session.retire()
        if expected_runs == 1:
            click_button(game, "restart")
            assert game.session.state == "playing"


SCREEN_CASES = [
    ((0, 0, 640, 360), (0, 0, 640, 360)),
    ((-1280, -200, 0, 520), (-640, -180, 0, 180)),
]


@pytest.mark.parametrize("bounds,work_area", SCREEN_CASES)
@pytest.mark.parametrize("panel", ["menu", "paused", "upgrade", "result"])
def test_small_and_negative_coordinate_panels_have_visible_working_controls(bounds, work_area, panel):
    game = GameView(snapshot(bounds, work_area), profile(), seed=7)
    if panel != "menu":
        game.start("campaign")
        if panel == "paused":
            game.handle_key(ord("P"), game.session.player.pos)
        elif panel == "upgrade":
            game.session._add_xp(game.session.player.xp_next)
            game.update(.05, game.session.player.pos)
        else:
            game.session.retire()
            game.update(.05, game.session.player.pos)
    game.render()
    assert game.buttons
    for rect, action in game.buttons:
        assert game.work.contains(rect), f"{panel}/{action} clipped at {work_area}"
        assert game.frame.get_at(rect.center).a > 0
    action = {"menu": "campaign", "paused": "pause", "upgrade": "choice:0", "result": "restart"}[panel]
    click_button(game, action)
    assert game.session is not None and game.session.state == "playing"


@pytest.mark.parametrize("bounds,work_area", SCREEN_CASES)
def test_small_menu_mute_and_exit_are_clickable_in_screen_coordinates(bounds, work_area):
    saved = profile()
    game = GameView(snapshot(bounds, work_area), saved, seed=7)
    click_button(game, "page:settings")
    assert click_button(game, "mute") == "settings"
    assert saved["muted"] is True
    click_button(game, "page:home")
    assert click_button(game, "quit") == "quit"


@pytest.mark.parametrize("mode", ["campaign", "blitz", "endless"])
def test_mode_button_starts_the_selected_ruleset(mode):
    game = GameView(snapshot(), profile(), seed=7)
    click_button(game, mode)
    assert game.session.mode == mode
