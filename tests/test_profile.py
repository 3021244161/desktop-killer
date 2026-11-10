"""Persistence protects previous results and separates different game modes."""
import copy
import json

import pytest

from desktop_world import profile


def run(mode="campaign", score=100, kills=8, time=42.5, stage=2, won=False):
    return dict(mode=mode, score=score, kills=kills, time=time, stage=stage, won=won)


def test_mode_records_and_ties_do_not_overwrite_the_best_run(tmp_path):
    data = profile.load_profile(tmp_path / "profile.json")
    assert profile.record_run(data, run(won=True))
    assert profile.record_run(data, run("endless", score=60, stage=5))
    assert not profile.record_run(data, run(score=100, kills=15, time=55, stage=3))
    assert data["runs"] == 3 and data["wins"] == 1 and data["highest_stage"] == 5
    campaign = data["modes"]["campaign"]
    assert campaign["runs"] == 2 and campaign["wins"] == 1
    assert campaign["best_score"] == 100 and campaign["best_kills"] == 15
    assert campaign["best_time"] == 55 and campaign["highest_stage"] == 3
    assert campaign["best_run"]["won"] and not campaign["last_run"]["won"]
    assert data["modes"]["endless"]["best_score"] == 60


def test_roundtrip_preserves_muted_and_best_run_without_aliasing_summary(tmp_path):
    path = tmp_path / "runtime" / "profile.json"
    data = profile.load_profile(path)
    data["muted"] = True
    summary = run()
    profile.record_run(data, summary)
    summary["score"] = 999
    profile.save_profile(path, data)
    assert profile.load_profile(path) == data
    assert data["modes"]["campaign"]["best_score"] == 100
    assert not list(path.parent.glob("*.tmp"))


@pytest.mark.parametrize("contents", [b'{"version":', b'\xff\xfe\xf0', b'[]',
                                      b'{"runs":true}', b'{"version":999}'])
def test_corrupt_save_is_preserved_before_defaults_are_returned(tmp_path, contents):
    path = tmp_path / "profile.json"
    path.write_bytes(contents)
    data = profile.load_profile(path)
    assert data["runs"] == 0 and data["modes"] == {}
    backups = list(tmp_path.glob("profile.corrupt-*.json"))
    assert len(backups) == 1 and backups[0].read_bytes() == contents
    assert not path.exists()
    profile.save_profile(path, data)
    assert json.loads(path.read_text())["version"] == 2


def test_failed_atomic_replace_leaves_previous_save_readable(tmp_path, monkeypatch):
    path = tmp_path / "profile.json"
    old = profile.load_profile(path)
    profile.save_profile(path, old)
    old_bytes = path.read_bytes()
    profile.record_run(old, run())
    def fail_replace(*_):
        raise PermissionError("simulated locked destination")
    monkeypatch.setattr(profile.os, "replace", fail_replace)
    with pytest.raises(PermissionError):
        profile.save_profile(path, old)
    assert path.read_bytes() == old_bytes
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize("field,value", [("score", -1), ("kills", True),
                                        ("time", float("nan")), ("stage", 1.5), ("won", 1)])
def test_invalid_run_cannot_partially_change_profile(tmp_path, field, value):
    data = profile.load_profile(tmp_path / "profile.json")
    profile.record_run(data, run())
    before = copy.deepcopy(data)
    summary = run()
    summary[field] = value
    with pytest.raises(ValueError):
        profile.record_run(data, summary)
    assert data == before


def test_v1_migration_keeps_every_old_stat_and_does_not_touch_disk_until_saved(tmp_path):
    path = tmp_path / "profile.json"
    old_run = run(won=True)
    old = {"version": 1, "muted": True, "runs": 4, "wins": 3, "highest_stage": 3,
           "modes": {"campaign": {"runs": 4, "wins": 3, "best_score": 100,
                                  "best_kills": 8, "best_time": 42.5, "highest_stage": 3,
                                  "best_run": old_run, "last_run": old_run}}}
    original = json.dumps(old, ensure_ascii=False).encode("utf-8")
    path.write_bytes(original)
    migrated = profile.load_profile(path)
    assert migrated["version"] == 2
    for key in ("muted", "runs", "wins", "highest_stage", "modes"):
        assert migrated[key] == old[key]
    assert migrated["progression"]["crystals"] == 80
    assert migrated["progression"]["xp"] == 0
    assert {"ghost", "knight", "robot"} <= set(migrated["progression"]["outfits"])
    assert migrated["settings"] == profile.SETTINGS
    assert path.read_bytes() == original
    profile.save_profile(path, migrated)
    assert profile.load_profile(path) == migrated
    assert not list(tmp_path.glob("*.corrupt-*"))


def test_settings_change_is_validated_and_atomic(tmp_path):
    data = profile.load_profile(tmp_path / "profile.json")
    assert profile.set_setting(data, "reduced_motion", True)
    assert not profile.set_setting(data, "reduced_motion", True)
    before = copy.deepcopy(data)
    for key, value in (("unknown", True), ("show_hints", 0)):
        with pytest.raises(ValueError):
            profile.set_setting(data, key, value)
        assert data == before


def test_v2_progression_survives_save_and_load_with_idempotent_receipts(tmp_path):
    from desktop_world.progression import settle_run
    path = tmp_path / "profile.json"
    data = profile.load_profile(path)
    summary = {**run(won=True), "run_id": "stable-id", "sealed": 12}
    receipt = settle_run(data, summary)
    assert receipt["crystals"] > 0
    profile.save_profile(path, data)
    restored = profile.load_profile(path)
    before = copy.deepcopy(restored)
    duplicate = settle_run(restored, summary)
    assert duplicate["duplicate"] and duplicate["crystals"] == duplicate["xp"] == 0
    assert restored == before == data
