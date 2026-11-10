"""Failed result saves remain visible and retry without settling a run twice."""
import copy
import json
import os

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

from PIL import Image, ImageDraw
import pytest

from desktop_world.game_view import GameView
from desktop_world.profile import _default_profile, _validated
from desktop_world.progression import settle_run
from desktop_world.shell import DesktopIcon, DesktopSnapshot


def snapshot(bounds):
    left, top, _, _ = bounds
    image = Image.new("RGBA", (32, 32))
    ImageDraw.Draw(image).ellipse((3, 3, 28, 28), fill=(80, 220, 170, 255))
    icon = DesktopIcon("one", "Icon", left + 50, top + 60, 32, 32, image,
                       (left + 40, top + 95, left + 100, top + 115))
    return DesktopSnapshot(0, 0, bounds, bounds, [icon], "arial", 12)


def failed_result(outcomes, bounds=(0, 0, 640, 360), *, with_callback=True):
    profile = _default_profile()
    state = {"settlements": 0, "snapshots": [], "messages": [], "outcomes": list(outcomes)}

    def persist():
        # Serialize through the same validator as a disk save, with no filesystem
        # or real desktop access. The UI's receipt metadata must stay separate.
        state["snapshots"].append(json.loads(json.dumps(_validated(profile))))
        return state["outcomes"].pop(0)

    def on_result(summary):
        state["settlements"] += 1
        receipt = settle_run(profile, summary)
        receipt["saved"] = persist()
        return receipt

    game = GameView(snapshot(bounds), profile=profile,
                    on_result=on_result if with_callback else None,
                    on_profile_change=persist, start_mode="campaign", seed=3)
    original_text = game._text

    def collect_text(text, *args, **kwargs):
        state["messages"].append(str(text))
        return original_text(text, *args, **kwargs)

    game._text = collect_text
    game.session.total_time = 30.0
    game.session.player.kills = 2
    game.session.score = 160
    game.session.retire()
    game.update(.05, game.session.player.pos)
    game.render()
    assert game.reward["saved"] is False
    assert any("未保存" in text or "保存失败" in text for text in state["messages"])
    return game, state


def click_retry(game):
    game.render()
    rect = next(rect for rect, action in game.buttons if action == "retry_save")
    assert game.work.contains(rect), "the recovery control must be reachable on a small desktop"
    assert game.frame.get_at(rect.center).a > 0
    point = (rect.centerx + game.offset.x, rect.centery + game.offset.y)
    game.handle_click(*point, 1)


@pytest.mark.parametrize("bounds", [(0, 0, 640, 360), (-640, -360, 0, 0)])
def test_retry_saves_the_existing_reward_without_duplicate_settlement(bounds):
    game, state = failed_result([False, True], bounds)
    settled = copy.deepcopy(game.profile)
    assert settled["progression"]["crystals"] > 80
    click_retry(game)
    assert game.reward["saved"] is True
    for _ in range(8):
        game.update(.1, game.session.player.pos)
        game.render()
    assert state["settlements"] == 1
    assert len(state["snapshots"]) == 2
    assert state["snapshots"][0] == state["snapshots"][1] == settled
    assert game.profile == settled
    assert "retry_save" not in [action for _, action in game.buttons]
    assert "saved" not in game.profile["progression"]["last_reward"]
    assert all("saved" not in receipt for receipt in game.profile["progression"]["run_receipts"].values())


def test_repeated_failed_retries_preserve_warning_and_do_not_credit_again():
    game, state = failed_result([False, False, False])
    settled = copy.deepcopy(game.profile)
    for _ in range(2):
        state["messages"].clear()
        click_retry(game)
        game.render()
        assert game.reward["saved"] is False
        assert "retry_save" in [action for _, action in game.buttons]
        assert any("未保存" in text or "保存失败" in text for text in state["messages"])
        assert game.profile == settled
    assert state["settlements"] == 1 and len(state["snapshots"]) == 3


def test_fallback_without_result_callback_still_exposes_save_failure_and_retry():
    game, state = failed_result([False, True], with_callback=False)
    settled = copy.deepcopy(game.profile)
    click_retry(game)
    assert game.reward["saved"] is True
    assert game.profile == settled
    assert game.profile["runs"] == 1
    assert len(state["snapshots"]) == 2
