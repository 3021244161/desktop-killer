"""Headless play-throughs using only normal movement, abilities and reward choices.

This is a reproducible smoke/balance probe, not a proof of human difficulty. It
does not edit health, damage, enemies, clocks, or any desktop windows.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desktop_world.scene import GameSession
from desktop_world.profile import record_run


def icons_for(count, width, height):
    rows = max(1, round(math.sqrt(count * height / width)))
    columns = math.ceil(count / rows)
    return [dict(key=str(i), name=f"Icon {i}",
                 home=((i // rows + .5) * width / columns, (i % rows + .5) * height / rows),
                 size=(45, 45)) for i in range(count)]


def choose_reward(session):
    order = ["chain", "multishot", "damage", "fire_rate", "shield", "blades",
             "pulse", "speed", "seal", "magnet", "pierce", "vitality"]
    if session.player.hp < session.player.max_hp * .55:
        order = ["vitality", "shield"] + order
    options = session.upgrade_choices
    return min(range(len(options)), key=lambda i: order.index(options[i]["id"]))


def steer(session):
    p, scale = session.player, session.scale
    active = [actor for actor in session.actors if actor.state == "active"]
    ports = [actor for actor in session.actors if actor.state == "rebooting"]
    # Prefer ports that can still be reached before they revive.
    reachable = [a for a in ports if math.dist(p.pos, a.home) / p.speed + session.seal_duration < a.reboot_left]
    ports = reachable or ports
    if ports:
        goal = min(ports, key=lambda a: math.dist(p.pos, a.home)).home
    elif active:
        goal = min(active, key=lambda a: math.dist(p.pos, a.home)).home
    else:
        homes = [a for a in session.actors if a.state in ("home", "waking")]
        goal = min(homes, key=lambda a: math.dist(p.pos, a.home)).home if homes else p.pos
    nearby = [a for a in active if math.dist(p.pos, a.pos) < session.pulse_radius + a.radius]
    if nearby:
        session.pulse()
    # During the one-second sealing hold, accept an occasional hit rather than
    # endlessly abandoning objective progress. Else dodge close attackers.
    holding = ports and math.dist(p.pos, goal) < 40 * scale
    if not holding and active:
        closest = min(active, key=lambda a: math.dist(p.pos, a.pos))
        distance = math.dist(p.pos, closest.pos)
        if distance < 105 * scale:
            dx, dy = p.x - closest.x, p.y - closest.y
            length = max(.001, math.hypot(dx, dy))
            dx, dy = dx / length, dy / length
            goal = (p.x + (dx - .8 * dy) * 145 * scale,
                    p.y + (dy + .8 * dx) * 145 * scale)
            if distance < 48 * scale:
                session.dash(goal)
    left, top, right, bottom = session.bounds
    return (max(left + p.radius, min(right - p.radius, goal[0])),
            max(top + p.radius, min(bottom - p.radius, goal[1])))


def simulate(count=72, width=1920, height=1042, mode="campaign", seed=1, max_time=420,
             *, icons=None, bounds=None):
    session = GameSession(icons or icons_for(count, width, height), bounds or (0, 0, width, height),
                          mode=mode, seed=seed)
    checkpoints = []
    lowest_health = session.player.hp
    for _ in range(math.ceil(max_time / .05) + 1000):
        if session.state in ("won", "lost"):
            break
        if session.state == "upgrade":
            session.choose_upgrade(choose_reward(session))
            continue
        if session.state == "intermission":
            checkpoints.append({"chapter": session.chapter, "time": round(session.total_time, 2),
                                "hp": round(session.player.hp, 1), "score": session.score})
            if mode == "endless" and session.chapter >= 3:
                session.retire()
            else:
                session.choose_stage(0 if session.player.hp < 65 else 1)
            continue
        if session.state != "playing":
            raise RuntimeError(f"unexpected state {session.state}")
        session.update(.05, steer(session))
        lowest_health = min(lowest_health, session.player.hp)
        session.drain_events()
        if session.total_time >= max_time:
            break
    summary = session.summary()
    if session.state in ("won", "lost"):
        data = {"version": 1}
        assert record_run(data, summary)
        assert data["runs"] == 1
    return {"icons": len(session.actors), "area": [width, height], "seed": seed,
            "hp": round(session.player.hp, 1), "lowest_hp": round(lowest_health, 1),
            "checkpoints": checkpoints, **summary}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("campaign", "blitz", "endless"), default="campaign")
    parser.add_argument("--icons", type=int, default=72)
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1042)
    parser.add_argument("--seeds", type=int, default=3)
    parser.add_argument("--max-time", type=float, default=420)
    parser.add_argument("--snapshot", type=Path, help="use a saved probe's exact icon centers, without touching the desktop")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    extra = {}
    if args.snapshot:
        saved = json.loads(args.snapshot.read_text(encoding="utf-8"))
        extra["icons"] = [dict(key=i["key"], name=i["name"],
                               home=(i["x"] + i["width"] / 2, i["y"] + i["height"] / 2),
                               size=(i["width"], i["height"])) for i in saved["icons"]]
        extra["bounds"] = saved["work_area"]
        l, t, r, b = extra["bounds"]
        args.width, args.height = r - l, b - t
    results = [simulate(args.icons, args.width, args.height, args.mode, seed, args.max_time, **extra)
               for seed in range(1, args.seeds + 1)]
    text = json.dumps(results, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
