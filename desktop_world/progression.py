"""Offline account growth, bounded talents and idempotent earned rewards."""
from __future__ import annotations

import copy
import math


TALENTS = {
    "damage": {"title": "稳定输出", "description": "每级基础伤害 +5%，最多 +20%。", "bonus": "damage_mult"},
    "vitality": {"title": "生命缓冲", "description": "每级基础生命上限 +5%，最多 +20%。", "bonus": "max_hp_mult"},
    "speed": {"title": "轻盈步伐", "description": "每级基础移动速度 +5%，最多 +20%。", "bonus": "speed_mult"},
    "shield": {"title": "护盾储备", "description": "每级基础护盾上限 +5%，最多 +20%。", "bonus": "shield_mult"},
    "cooldown": {"title": "快速响应", "description": "每级技能冷却 -5%，最多 -20%。", "bonus": "cooldown_mult"},
    "seal": {"title": "断链熟练", "description": "每级断链所需时间 -5%，最多 -20%。", "bonus": "seal_duration_mult"},
}
TALENT_COSTS = (45, 65, 85, 110)
ACHIEVEMENTS = {
    "first_blood": {"title": "第一道裂缝", "description": "累计击碎 1 个图标。", "stat": "kills", "target": 1, "reward": 10},
    "unlinker": {"title": "断链专员", "description": "累计完成 10 次断链。", "stat": "seals", "target": 10, "reward": 20},
    "century": {"title": "百次唤醒", "description": "累计击碎 100 个图标。", "stat": "kills", "target": 100, "reward": 30},
    "first_win": {"title": "安全重启", "description": "赢得任意模式的第一局。", "stat": "wins", "target": 1, "reward": 20},
    "three_wins": {"title": "桌面守卫", "description": "累计赢得 3 局，解锁骑士装。", "stat": "wins", "target": 3, "reward": 35, "outfit": "knight"},
    "campaign_clear": {"title": "系统修复师", "description": "完成一次三章行动，解锁机器人。", "stat": "campaign_wins", "target": 1, "reward": 25, "outfit": "robot"},
    "sketchbook": {"title": "桌面速写", "description": "画下 5 笔，总长度达到 800 像素。", "stat": "draw_strokes", "target": 5, "distance": 800, "reward": 20},
    "desktop_artist": {"title": "光笔魔法师", "description": "画下 30 笔，总长度达到 5000 像素，解锁巫师装。", "stat": "draw_strokes", "target": 30, "distance": 5000, "reward": 30, "outfit": "wizard"},
}
_TOTALS = ("kills", "seals", "wins", "runs", "campaign_wins", "draw_strokes")


def _nonnegative(value, field):
    if type(value) is not int or value < 0:
        raise ValueError(f"{field} must be a nonnegative integer")
    return value


def _distance(value):
    try:
        valid = type(value) in (int, float) and math.isfinite(value) and value >= 0
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError("drawing distance must be finite and nonnegative")
    return float(value)


def _event_id(value):
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > 128:
        raise ValueError("event ID must contain 1–128 characters")
    return value


def level_from_xp(xp: int) -> int:
    xp = _nonnegative(xp, "xp")
    return (math.isqrt(1 + 8 * xp // 120) - 1) // 2 + 1


def _achievement_met(state, rule):
    return (state["totals"][rule["stat"]] >= rule["target"] and
            state["totals"]["draw_distance"] >= rule.get("distance", 0))


def new_progression(legacy=None):
    legacy = legacy or {}
    modes = legacy.get("modes", {})
    totals = {key: 0 for key in _TOTALS}
    totals.update(runs=legacy.get("runs", 0), wins=legacy.get("wins", 0),
                  kills=sum(mode.get("best_kills", 0) for mode in modes.values()),
                  campaign_wins=modes.get("campaign", {}).get("wins", 0), draw_distance=0.0)
    state = {"xp": 0, "level": 1, "crystals": 80,
             "talents": {key: 0 for key in TALENTS}, "outfits": ["ghost"], "equipped": "ghost",
             "achievements": [], "totals": totals, "run_receipts": {},
             "drawing_events": [], "last_reward": None}
    # Legacy saves cannot reconstruct all historical kills or seals. Preserve
    # the known lower bounds and honor earned cosmetics without inventing XP
    # or paying retrospective run rewards.
    for key, rule in ACHIEVEMENTS.items():
        if _achievement_met(state, rule):
            state["achievements"].append(key)
            if rule.get("outfit") and rule["outfit"] not in state["outfits"]:
                state["outfits"].append(rule["outfit"])
    return state


def _receipt(value):
    from .wardrobe import OUTFITS
    if not isinstance(value, dict):
        raise ValueError("reward receipt must be an object")
    result = {"run_id": _event_id(value.get("run_id"))}
    for field in ("new_record", "duplicate", "eligible"):
        if type(value.get(field)) is not bool:
            raise ValueError(f"{field} must be boolean")
        result[field] = value[field]
    for field in ("xp", "crystals", "base_crystals", "achievement_crystals", "level", "levels_gained", "balance"):
        result[field] = _nonnegative(value.get(field), field)
    if result["level"] < 1:
        raise ValueError("account level starts at one")
    for field, choices in (("achievements", ACHIEVEMENTS), ("unlocked_outfits", OUTFITS)):
        items = value.get(field)
        if not isinstance(items, list) or any(not isinstance(item, str) or item not in choices for item in items):
            raise ValueError(f"invalid {field} in receipt")
        if len(items) != len(set(items)):
            raise ValueError(f"duplicate {field} in receipt")
        result[field] = list(items)
    return result


def normalize_progression(value, legacy=None):
    from .wardrobe import OUTFITS
    if value is None:
        return new_progression(legacy)
    if not isinstance(value, dict):
        raise ValueError("progression must be an object")
    result = new_progression()
    for key in ("xp", "crystals"):
        result[key] = _nonnegative(value.get(key, result[key]), key)
    result["level"] = level_from_xp(result["xp"])
    talents = value.get("talents", {})
    if not isinstance(talents, dict) or set(talents) - TALENTS.keys():
        raise ValueError("unrecognized talent records")
    for key in TALENTS:
        level = _nonnegative(talents.get(key, 0), key)
        if level > len(TALENT_COSTS):
            raise ValueError("talent exceeds its cap")
        result["talents"][key] = level
    for field, choices in (("outfits", OUTFITS), ("achievements", ACHIEVEMENTS)):
        items = value.get(field, result[field])
        if not isinstance(items, list) or any(not isinstance(item, str) or item not in choices for item in items):
            raise ValueError(f"unrecognized {field}")
        if len(items) != len(set(items)):
            raise ValueError(f"duplicate {field}")
        result[field] = list(items)
    if "ghost" not in result["outfits"]:
        result["outfits"].insert(0, "ghost")
    equipped = value.get("equipped", "ghost")
    if equipped not in result["outfits"]:
        raise ValueError("equipped outfit must be owned")
    result["equipped"] = equipped
    totals = value.get("totals", {})
    if not isinstance(totals, dict):
        raise ValueError("totals must be an object")
    result["totals"] = {key: _nonnegative(totals.get(key, 0), key) for key in _TOTALS}
    result["totals"]["draw_distance"] = _distance(totals.get("draw_distance", 0))
    if result["totals"]["wins"] > result["totals"]["runs"]:
        raise ValueError("account wins cannot exceed runs")
    receipts = value.get("run_receipts", {})
    if not isinstance(receipts, dict):
        raise ValueError("run receipts must be an object")
    result["run_receipts"] = {}
    for key, receipt in receipts.items():
        if _event_id(key) is None:
            raise ValueError("stored run IDs must be strings")
        checked = _receipt(receipt)
        if checked["run_id"] != key:
            raise ValueError("receipt ID does not match its run")
        result["run_receipts"][key] = checked
    drawings = value.get("drawing_events", [])
    if not isinstance(drawings, list) or any(_event_id(key) is None for key in drawings):
        raise ValueError("drawing event IDs must be strings")
    if len(drawings) != len(set(drawings)):
        raise ValueError("duplicate drawing event IDs")
    result["drawing_events"] = list(drawings)
    last = value.get("last_reward")
    result["last_reward"] = None if last is None else _receipt(last)
    return result


def _transact(data, mutate):
    from .profile import _validated
    updated = _validated(data)
    result = mutate(updated)
    checked = _validated(updated)
    data.clear()
    data.update(checked)
    return copy.deepcopy(result)


def _read(data):
    from .profile import _validated
    return _validated(data)


def account_info(data):
    profile = _read(data)
    state = profile["progression"]
    level, xp = state["level"], state["xp"]
    return {"level": level, "xp": xp, "xp_into_level": xp - 60 * (level - 1) * level,
            "xp_for_next": 120 * level, "crystals": state["crystals"],
            "equipped": state["equipped"], "achievements_unlocked": len(state["achievements"]),
            "runs": profile["runs"], "wins": profile["wins"], "highest_stage": profile["highest_stage"]}


def talent_catalog(data):
    state = _read(data)["progression"]
    result = []
    for key, rule in TALENTS.items():
        level = state["talents"][key]
        price = TALENT_COSTS[level] if level < len(TALENT_COSTS) else None
        result.append({"id": key, "title": rule["title"], "description": rule["description"],
                       "level": level, "max_level": len(TALENT_COSTS), "price": price,
                       "owned": level > 0, "maxed": price is None,
                       "affordable": price is not None and state["crystals"] >= price})
    return result


def purchase_talent(data, talent_id):
    if talent_id not in TALENTS:
        raise ValueError("unknown talent")
    def purchase(profile):
        state = profile["progression"]
        level = state["talents"][talent_id]
        result = {"ok": False, "id": talent_id, "level": level, "cost": 0, "balance": state["crystals"]}
        if level >= len(TALENT_COSTS):
            return {**result, "reason": "max_level"}
        cost = TALENT_COSTS[level]
        if state["crystals"] < cost:
            return {**result, "reason": "insufficient_crystals", "cost": cost}
        state["crystals"] -= cost
        state["talents"][talent_id] += 1
        return {**result, "ok": True, "reason": "purchased", "cost": cost,
                "level": level + 1, "balance": state["crystals"]}
    return _transact(data, purchase)


def talent_bonuses(data):
    state = _read(data)["progression"]
    return {rule["bonus"]: round(1 + (-.05 if key in ("cooldown", "seal") else .05) * state["talents"][key], 2)
            for key, rule in TALENTS.items()}


def achievement_catalog(data):
    state = _read(data)["progression"]
    result = []
    for key, rule in ACHIEVEMENTS.items():
        progress = min(rule["target"], state["totals"][rule["stat"]])
        ratio = progress / rule["target"]
        if rule.get("distance"):
            ratio = min(ratio, state["totals"]["draw_distance"] / rule["distance"])
        result.append({"id": key, "title": rule["title"], "description": rule["description"],
                       "target": rule["target"], "progress": progress, "progress_ratio": min(1.0, ratio),
                       "unlocked": key in state["achievements"], "reward_crystals": rule["reward"],
                       "outfit_reward": rule.get("outfit")})
    return result


def _award_achievements(state):
    earned, outfits, crystals = [], [], 0
    for key, rule in ACHIEVEMENTS.items():
        if key in state["achievements"] or not _achievement_met(state, rule):
            continue
        state["achievements"].append(key)
        earned.append(key)
        crystals += rule["reward"]
        outfit = rule.get("outfit")
        if outfit and outfit not in state["outfits"]:
            state["outfits"].append(outfit)
            outfits.append(outfit)
    state["crystals"] += crystals
    return earned, outfits, crystals


def _empty_receipt(state, run_id=None, *, duplicate=False):
    return {"run_id": run_id, "new_record": False, "duplicate": duplicate, "eligible": False,
            "xp": 0, "crystals": 0, "base_crystals": 0, "achievement_crystals": 0,
            "level": state["level"], "levels_gained": 0, "balance": state["crystals"],
            "achievements": [], "unlocked_outfits": []}


def _apply_run_rewards(profile, run, new_record):
    state, totals = profile["progression"], profile["progression"]["totals"]
    receipt = _empty_receipt(state, run.get("run_id"))
    receipt["new_record"] = new_record
    totals["runs"] += 1
    totals["wins"] += int(run["won"])
    totals["campaign_wins"] += int(run["won"] and run["mode"] == "campaign")
    totals["kills"] += run["kills"]
    totals["seals"] += run.get("sealed", 0)
    eligible = run["kills"] > 0 and run["time"] >= 10
    receipt["eligible"] = eligible
    if eligible:
        kills, seals, duration = run["kills"], run.get("sealed", 0), run["time"]
        xp = min(800, 20 + min(kills, 200) * 2 + min(seals, 100) * 3 +
                 min(12, int(duration // 30)) * 5 + (50 if run["won"] else 0))
        crystals = min(65, 6 + min(kills, 120) // 5 + min(seals, 60) // 3 +
                       min(6, int(duration // 60)) + (12 if run["won"] else 0))
        previous_level = state["level"]
        state["xp"] += xp
        state["level"] = level_from_xp(state["xp"])
        state["crystals"] += crystals
        strokes, distance = run.get("draw_strokes", 0), run.get("draw_distance", 0.0)
        if strokes > 0 and distance >= 8 * strokes:
            totals["draw_strokes"] += strokes
            totals["draw_distance"] += distance
        achievements, outfits, bonus = _award_achievements(state)
        receipt.update(xp=xp, crystals=crystals + bonus, base_crystals=crystals,
                       achievement_crystals=bonus, level=state["level"],
                       levels_gained=state["level"] - previous_level, balance=state["crystals"],
                       achievements=achievements, unlocked_outfits=outfits)
    state["last_reward"] = copy.deepcopy(receipt)
    if run.get("run_id") is not None:
        state["run_receipts"][run["run_id"]] = copy.deepcopy(receipt)
    return receipt


def settle_run(data, summary):
    """Record stats and rewards once. Pass the same run_id when retrying a save."""
    from .profile import _record_run_receipt
    return _record_run_receipt(data, summary)


def last_reward(data):
    return copy.deepcopy(_read(data)["progression"]["last_reward"])


def record_drawing(data, strokes=1, distance=0.0, event_id=None):
    """Track finished strokes, not every mouse frame; an event ID is idempotent.

    Drawing awards only the finite achievement bonuses. It cannot continuously
    produce account XP or crystals after those achievements are unlocked.
    """
    strokes, distance, event_id = _nonnegative(strokes, "strokes"), _distance(distance), _event_id(event_id)
    def record(profile):
        state = profile["progression"]
        if event_id is not None and event_id in state["drawing_events"]:
            return _empty_receipt(state, duplicate=True)
        receipt = _empty_receipt(state)
        if event_id is not None:
            state["drawing_events"].append(event_id)
        if strokes and distance >= 8 * strokes:
            state["totals"]["draw_strokes"] += strokes
            state["totals"]["draw_distance"] += distance
            achievements, outfits, bonus = _award_achievements(state)
            receipt.update(eligible=True, crystals=bonus, achievement_crystals=bonus,
                           balance=state["crystals"], achievements=achievements, unlocked_outfits=outfits)
        return receipt
    return _transact(data, record)
