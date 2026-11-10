"""Account growth is bounded, validated and safe to retry after a failed save."""
import copy

import pytest

from desktop_world.profile import load_profile, record_run
from desktop_world.progression import (ACHIEVEMENTS, TALENTS, account_info, achievement_catalog,
                                      level_from_xp, purchase_talent, record_drawing,
                                      settle_run, talent_bonuses, talent_catalog)


def fresh(tmp_path):
    return load_profile(tmp_path / "profile.json")


def summary(run_id="one", **changes):
    return {"mode": "campaign", "score": 3200, "kills": 20, "time": 90.0,
            "stage": 3, "sealed": 12, "won": True, "run_id": run_id, **changes}


def test_reward_receipt_matches_account_changes_and_bool_contract(tmp_path):
    data = fresh(tmp_path)
    before = account_info(data)
    receipt = settle_run(data, summary())
    after = account_info(data)
    assert receipt["eligible"] and receipt["new_record"] and not receipt["duplicate"]
    assert after["crystals"] - before["crystals"] == receipt["crystals"]
    assert after["xp"] - before["xp"] == receipt["xp"]
    assert receipt["base_crystals"] + receipt["achievement_crystals"] == receipt["crystals"]
    assert after["level"] == receipt["level"]
    assert set(receipt["achievements"]) == {"first_blood", "unlinker", "first_win", "campaign_clear"}
    assert "robot" in receipt["unlocked_outfits"]
    state = copy.deepcopy(data)
    assert record_run(data, summary()) is False
    assert data == state


def test_idempotence_uses_run_identity_even_when_a_caller_changes_summary_fields(tmp_path):
    data = fresh(tmp_path)
    settle_run(data, summary())
    before = copy.deepcopy(data)
    receipt = settle_run(data, summary(score=999999, kills=1000, mode="endless"))
    assert receipt["duplicate"] and not receipt["new_record"]
    assert receipt["xp"] == receipt["crystals"] == 0
    assert data == before
    assert settle_run(data, summary("two"))["duplicate"] is False
    assert data["runs"] == 2


@pytest.mark.parametrize("kills,time", [(0, 0), (0, 120), (1, 2), (10, 9.99)])
def test_empty_or_too_short_retirements_cannot_farm_account_rewards(tmp_path, kills, time):
    data = fresh(tmp_path)
    for index in range(5):
        receipt = settle_run(data, summary(str(index), score=0, won=False, sealed=0, kills=kills, time=time))
        assert not receipt["eligible"]
        assert receipt["xp"] == receipt["crystals"] == 0
        assert receipt["achievements"] == []
    assert account_info(data)["crystals"] == 80
    assert account_info(data)["xp"] == 0


def test_talent_prices_cap_each_bonus_and_failed_purchases_do_not_partially_mutate(tmp_path):
    data = fresh(tmp_path)
    assert set(talent_bonuses(data).values()) == {1.0}
    assert purchase_talent(data, "damage")["ok"]
    assert account_info(data)["crystals"] == 35
    before = copy.deepcopy(data)
    failed = purchase_talent(data, "damage")
    assert not failed["ok"] and failed["reason"] == "insufficient_crystals"
    assert data == before
    with pytest.raises(ValueError):
        purchase_talent(data, "unlimited_damage")
    assert data == before
    data["progression"]["crystals"] = 10000
    for key in TALENTS:
        while not next(row for row in talent_catalog(data) if row["id"] == key)["maxed"]:
            assert purchase_talent(data, key)["ok"]
        before = copy.deepcopy(data)
        assert purchase_talent(data, key)["reason"] == "max_level"
        assert data == before
    bonuses = talent_bonuses(data)
    assert bonuses == {"damage_mult": 1.2, "max_hp_mult": 1.2, "speed_mult": 1.2,
                       "shield_mult": 1.2, "cooldown_mult": .8, "seal_duration_mult": .8}


def test_invalid_progression_or_summary_never_partially_updates_stats(tmp_path):
    data = fresh(tmp_path)
    before = copy.deepcopy(data)
    for changes in ({"run_id": []}, {"sealed": -1}, {"draw_distance": float("nan")},
                    {"draw_strokes": True}):
        with pytest.raises(ValueError):
            settle_run(data, summary(**changes))
        assert data == before
    data["progression"]["talents"]["damage"] = 5
    before = copy.deepcopy(data)
    with pytest.raises(ValueError):
        purchase_talent(data, "vitality")
    assert data == before


def test_drawings_require_length_are_idempotent_and_award_only_finite_achievements(tmp_path):
    data = fresh(tmp_path)
    for index in range(10):
        assert not record_drawing(data, distance=0, event_id=f"click-{index}")["eligible"]
    assert data["progression"]["totals"]["draw_strokes"] == 0
    earned = []
    for index in range(30):
        receipt = record_drawing(data, distance=200, event_id=f"stroke-{index}")
        earned.extend(receipt["achievements"])
        before = copy.deepcopy(data)
        retry = record_drawing(data, distance=200, event_id=f"stroke-{index}")
        assert retry["duplicate"] and retry["crystals"] == 0
        assert data == before
    assert earned == ["sketchbook", "desktop_artist"]
    assert "wizard" in data["progression"]["outfits"]
    assert account_info(data)["xp"] == 0
    balance = account_info(data)["crystals"]
    for index in range(30, 40):
        assert record_drawing(data, distance=200, event_id=f"stroke-{index}")["crystals"] == 0
    assert account_info(data)["crystals"] == balance


def test_all_achievements_unlock_once_and_catalog_reports_completed_progress(tmp_path):
    data = fresh(tmp_path)
    unlocked = []
    for index in range(3):
        unlocked.extend(settle_run(data, summary(str(index), kills=40))["achievements"])
    unlocked.extend(record_drawing(data, strokes=30, distance=6000, event_id="drawing-batch")["achievements"])
    assert set(unlocked) == set(ACHIEVEMENTS)
    assert len(unlocked) == len(set(unlocked))
    assert all(row["unlocked"] and row["progress_ratio"] == 1 for row in achievement_catalog(data))


@pytest.mark.parametrize("xp,level", [(0, 1), (119, 1), (120, 2), (359, 2),
                                     (360, 3), (719, 3), (720, 4), (1200, 5)])
def test_level_thresholds_have_no_off_by_one(xp, level):
    assert level_from_xp(xp) == level
