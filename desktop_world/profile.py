"""Small, validated local profile with atomic writes and recoverable bad saves."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import uuid

SETTINGS = {"show_hints": True, "reduced_motion": False,
            "drawing_guides": True, "tutorial_seen": False,
            "music_enabled": True, "music_volume": .35,
            "screen_flash": True, "screen_shake": True, "low_health_vignette": True}


def _setting(key, value):
    if key not in SETTINGS:
        raise ValueError("unknown setting")
    if key == "music_volume":
        if type(value) not in (int, float) or not 0 <= value <= 1:
            raise ValueError("music_volume must be a number from 0 to 1")
        return float(value)
    if type(value) is not bool:
        raise ValueError(f"setting {key} must be boolean")
    return value


def _default_profile() -> dict:
    from .progression import new_progression
    return {"version": 2, "muted": False, "runs": 0, "wins": 0,
            "highest_stage": 0, "modes": {}, "settings": dict(SETTINGS),
            "progression": new_progression()}


def _integer(value, field: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{field} must be a nonnegative integer")
    return value


def _seconds(value) -> float:
    try:
        valid = type(value) in (int, float) and math.isfinite(value) and value >= 0
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError("time must be a finite nonnegative number of seconds")
    return float(value)


def _mode_name(value) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 64:
        raise ValueError("mode must be a nonempty name of at most 64 characters")
    return value.strip()


def _summary(value: dict) -> dict:
    if not isinstance(value, dict) or type(value.get("won")) is not bool:
        raise ValueError("a run needs a summary and boolean won flag")
    result = {"mode": _mode_name(value.get("mode")),
            "score": _integer(value.get("score"), "score"),
            "kills": _integer(value.get("kills"), "kills"),
            "time": _seconds(value.get("time")),
            "stage": _integer(value.get("stage"), "stage"), "won": value["won"]}
    if "run_id" in value:
        from .progression import _event_id
        result["run_id"] = _event_id(value["run_id"])
    for field in ("sealed", "draw_strokes"):
        if field in value:
            result[field] = _integer(value[field], field)
    if "draw_distance" in value:
        result["draw_distance"] = _seconds(value["draw_distance"])
    return result


def _mode_record(value: dict, name: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError("mode records must be objects")
    record = {field: _integer(value.get(field, 0), field)
              for field in ("runs", "wins", "best_score", "best_kills", "highest_stage")}
    record["best_time"] = _seconds(value.get("best_time", 0))
    if record["wins"] > record["runs"]:
        raise ValueError("mode wins cannot exceed runs")
    for field in ("best_run", "last_run"):
        saved = value.get(field)
        record[field] = None if saved is None else _summary(saved)
        if record[field] is not None and record[field]["mode"] != name:
            raise ValueError("saved run belongs to a different mode")
    return record


def _validated(data: dict) -> dict:
    from .progression import normalize_progression
    if (not isinstance(data, dict) or type(data.get("version", 1)) is not int
            or data.get("version", 1) not in (1, 2)):
        raise ValueError("unsupported profile format")
    result = _default_profile()
    if type(data.get("muted", False)) is not bool:
        raise ValueError("muted must be a boolean")
    result["muted"] = data.get("muted", False)
    settings = data.get("settings", {})
    if not isinstance(settings, dict):
        raise ValueError("settings must be an object")
    for key, default in SETTINGS.items():
        result["settings"][key] = _setting(key, settings.get(key, default))
    for field in ("runs", "wins", "highest_stage"):
        result[field] = _integer(data.get(field, 0), field)
    if result["wins"] > result["runs"]:
        raise ValueError("profile wins cannot exceed runs")
    modes = data.get("modes", {})
    if not isinstance(modes, dict):
        raise ValueError("modes must be an object")
    for name, record in modes.items():
        normalized = _mode_name(name)
        if normalized in result["modes"]:
            raise ValueError("duplicate mode names")
        result["modes"][normalized] = _mode_record(record, normalized)
    result["progression"] = normalize_progression(
        data.get("progression") if data.get("version", 1) == 2 else None, legacy=result)
    return result


def load_profile(path: Path) -> dict:
    """Load a profile; preserve malformed bytes before returning fresh defaults.

    Filesystem permission errors propagate so a caller cannot accidentally
    replace an existing save that could not be read or backed up.
    """
    path = Path(path)
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return _default_profile()
    try:
        return _validated(json.loads(raw.decode("utf-8")))
    except (ValueError, TypeError, UnicodeError):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        backup = path.with_name(f"{path.stem}.corrupt-{stamp}-{uuid.uuid4().hex[:8]}{path.suffix}")
        path.rename(backup)
        return _default_profile()


def save_profile(path: Path, data: dict) -> None:
    """Flush a sibling temporary file, then atomically replace the profile."""
    contents = json.dumps(_validated(data), ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _record_run_receipt(data: dict, summary: dict) -> dict:
    from .progression import _apply_run_rewards, _empty_receipt
    run = _summary(summary)
    updated = _validated(data)
    state = updated["progression"]
    if run.get("run_id") is not None and run["run_id"] in state["run_receipts"]:
        return _empty_receipt(state, run["run_id"], duplicate=True)
    mode = updated["modes"].setdefault(run["mode"], _mode_record({}, run["mode"]))
    new_record = mode["runs"] == 0 or run["score"] > mode["best_score"]
    mode["runs"] += 1
    mode["wins"] += int(run["won"])
    mode["best_score"] = max(mode["best_score"], run["score"])
    mode["best_kills"] = max(mode["best_kills"], run["kills"])
    mode["best_time"] = max(mode["best_time"], run["time"])
    mode["highest_stage"] = max(mode["highest_stage"], run["stage"])
    mode["last_run"] = run.copy()
    if new_record:
        mode["best_run"] = run.copy()
    updated["runs"] += 1
    updated["wins"] += int(run["won"])
    updated["highest_stage"] = max(updated["highest_stage"], run["stage"])
    receipt = _apply_run_rewards(updated, run, new_record)
    checked = _validated(updated)
    data.clear()
    data.update(checked)
    return receipt


def record_run(data: dict, summary: dict) -> bool:
    """Record one completed run in-place; return whether its mode's score improved.

    Pass a stable summary['run_id'] to make retries idempotent. Legacy summaries
    without an ID retain the original once-per-call contract. Account rewards
    are also settled; use progression.settle_run when the UI needs the receipt.
    """
    return bool(_record_run_receipt(data, summary)["new_record"])


def set_setting(data: dict, key: str, value: bool | float) -> bool:
    """Change a known setting after validating the entire new profile."""
    value = _setting(key, value)
    from .progression import _transact
    def change(updated):
        changed = updated["settings"][key] != value
        updated["settings"][key] = value
        return changed
    return _transact(data, change)
