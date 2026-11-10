"""Offline cosmetic ownership and six transparent, vector-drawn companions."""
from __future__ import annotations

import math


OUTFITS = {
    "ghost": {"title": "小幽灵", "description": "熟悉的柔白小幽灵，保留最初的模样。", "price": 0,
              "unlock_hint": "初始拥有", "unlock_achievement": None},
    "courier": {"title": "围巾信使", "description": "飘动的珊瑚围巾与随身邮包。", "price": 70,
                "unlock_hint": "70 数据晶片", "unlock_achievement": None},
    "cat": {"title": "像素猫", "description": "尖耳、长尾和一双好奇的眼睛。", "price": 95,
            "unlock_hint": "95 数据晶片", "unlock_achievement": None},
    "robot": {"title": "小机器人", "description": "方形面罩、天线和分开的机械短腿。", "price": 120,
              "unlock_hint": "120 晶片，或完成一次三章行动", "unlock_achievement": "campaign_clear"},
    "knight": {"title": "桌面骑士", "description": "羽饰头盔、护盾与一把短剑。", "price": 140,
               "unlock_hint": "140 晶片，或累计赢得 3 局", "unlock_achievement": "three_wins"},
    "wizard": {"title": "光笔巫师", "description": "星纹尖帽、宽袍与发光笔杖。", "price": 160,
               "unlock_hint": "160 晶片，或完成光笔魔法师成就", "unlock_achievement": "desktop_artist"},
}


def outfit_catalog(data):
    from .progression import _read
    state = _read(data)["progression"]
    return [{"id": key, **rule, "owned": key in state["outfits"],
             "equipped": state["equipped"] == key,
             "affordable": key not in state["outfits"] and state["crystals"] >= rule["price"]}
            for key, rule in OUTFITS.items()]


def purchase_outfit(data, outfit_id):
    from .progression import _transact
    if outfit_id not in OUTFITS:
        raise ValueError("unknown outfit")
    def purchase(profile):
        state = profile["progression"]
        price = OUTFITS[outfit_id]["price"]
        result = {"ok": False, "id": outfit_id, "cost": 0, "balance": state["crystals"]}
        if outfit_id in state["outfits"]:
            return {**result, "reason": "already_owned"}
        if state["crystals"] < price:
            return {**result, "reason": "insufficient_crystals", "cost": price}
        state["crystals"] -= price
        state["outfits"].append(outfit_id)
        return {**result, "ok": True, "reason": "purchased", "cost": price, "balance": state["crystals"]}
    return _transact(data, purchase)


def unlock_outfit(data, outfit_id):
    """Grant a cosmetic reward without spending currency; does not auto-equip it."""
    from .progression import _transact
    if outfit_id not in OUTFITS:
        raise ValueError("unknown outfit")
    def unlock(profile):
        state = profile["progression"]
        changed = outfit_id not in state["outfits"]
        if changed:
            state["outfits"].append(outfit_id)
        return {"ok": True, "id": outfit_id, "changed": changed,
                "reason": "unlocked" if changed else "already_owned", "balance": state["crystals"]}
    return _transact(data, unlock)


def equip_outfit(data, outfit_id):
    from .progression import _transact
    if outfit_id not in OUTFITS:
        raise ValueError("unknown outfit")
    def equip(profile):
        state = profile["progression"]
        if outfit_id not in state["outfits"]:
            return {"ok": False, "id": outfit_id, "reason": "locked", "changed": False}
        changed = state["equipped"] != outfit_id
        state["equipped"] = outfit_id
        return {"ok": True, "id": outfit_id, "reason": "equipped", "changed": changed}
    return _transact(data, equip)


def equipped_outfit(data):
    from .progression import _read
    return _read(data)["progression"]["equipped"]


def draw_character(surface, pos, outfit="ghost", scale=1.0, clock=0.0, hurt=0.0,
                   dashing=False, facing=(1, 0), alpha=255):
    """Draw a cosmetic at its center, returning its dirty rectangle.

    The source is entirely vector geometry on a transparent local canvas. No
    screenshot, wallpaper pixels, display/window access, or assets are needed.
    Cosmetic silhouette changes do not alter a game's collision radius.
    """
    import pygame
    if outfit not in OUTFITS:
        raise ValueError("unknown outfit")
    if not isinstance(scale, (int, float)) or not math.isfinite(scale) or not 0 < scale <= 12:
        raise ValueError("character scale must be finite and between 0 and 12")
    if len(pos) != 2 or not all(math.isfinite(v) for v in pos):
        raise ValueError("character position must be finite")
    clock = float(clock)
    if not math.isfinite(clock):
        raise ValueError("animation clock must be finite")
    alpha = max(0, min(255, round(alpha)))
    size = (max(1, round(72 * scale)), max(1, round(80 * scale)))
    supersample = 2
    zoom = scale * supersample
    canvas = pygame.Surface((size[0] * supersample, size[1] * supersample), pygame.SRCALPHA)
    center = (canvas.get_width() / 2, canvas.get_height() / 2)
    bob = round(math.sin(clock * 8) * 1.5)
    hurt_amount = min(1.0, max(0.0, float(hurt)) / .32)
    direction = -1 if facing[0] < 0 else 1
    outline = (42, 59, 60, 255)
    eyes = (30, 64, 62, 255)

    def point(x, y):
        return round(center[0] + x * zoom), round(center[1] + y * zoom)

    def tone(rgb):
        return tuple(round(value * (1 - hurt_amount) + target * hurt_amount)
                     for value, target in zip(rgb[:3], (255, 126, 113))) + (255,)

    def polygon(color, vertices, width=0):
        pygame.draw.polygon(canvas, color, [point(x, y) for x, y in vertices], max(1, round(width * zoom)) if width else 0)

    def ellipse(color, rect, width=0):
        x, y = point(rect[0], rect[1])
        target = pygame.Rect(x, y, max(1, round(rect[2] * zoom)), max(1, round(rect[3] * zoom)))
        pygame.draw.ellipse(canvas, color, target, max(1, round(width * zoom)) if width else 0)

    def line(color, first, last, width=1):
        pygame.draw.line(canvas, color, point(*first), point(*last), max(1, round(width * zoom)))

    def rectangle(color, rect, radius=2):
        x, y = point(rect[0], rect[1])
        pygame.draw.rect(canvas, color, (x, y, round(rect[2] * zoom), round(rect[3] * zoom)),
                         border_radius=max(0, round(radius * zoom)))

    def face(y=0, color=eyes):
        look = direction * .7
        line(color, (-3 + look, y - 2 + bob), (-3 + look, y + 1 + bob), 2)
        line(color, (4 + look, y - 2 + bob), (4 + look, y + 1 + bob), 2)

    def ghost_body(color):
        body = [(-8, -11 + bob), (5, -11 + bob), (11, -5 + bob), (8, 10 + bob),
                (3, 7 + bob), (-1, 13 + bob), (-7, 9 + bob), (-10, -3 + bob)]
        polygon(outline, body)
        polygon(tone(color), [(x * .8, y * .8) for x, y in body])

    ellipse((0, 0, 0, 64), (-10, 13, 22, 7))
    if dashing:
        for row in (-7, 0, 7):
            line((117, 236, 189, 160), (-direction * 17, row + bob), (-direction * 29, row + bob), 2)
    if outfit == "ghost":
        ghost_body((244, 247, 239))
        face()
    elif outfit == "courier":
        tail = math.sin(clock * 6) * 3
        polygon((231, 100, 86, 255), [(-7, -4 + bob), (-24, -2 + bob + tail),
                                     (-19, 3 + bob + tail), (-25, 6 + bob + tail), (-5, 2 + bob)])
        ghost_body((244, 231, 200))
        rectangle((128, 91, 64, 255), (7, 2 + bob, 9, 9))
        line((221, 187, 135, 255), (7, 4 + bob), (15, 4 + bob), 1)
        polygon((250, 127, 105, 255), [(-9, 0 + bob), (9, 0 + bob), (9, 5 + bob), (-9, 5 + bob)])
        face(-4)
    elif outfit == "cat":
        tail = math.sin(clock * 4) * 3
        line(outline, (6, 8 + bob), (18, 6 + bob), 5)
        line(outline, (18, 6 + bob), (18 + tail, -4 + bob), 5)
        line(tone((213, 177, 238)), (7, 8 + bob), (18, 6 + bob), 3)
        line(tone((213, 177, 238)), (18, 6 + bob), (18 + tail, -4 + bob), 3)
        polygon(outline, [(-11, -7 + bob), (-10, -19 + bob), (-3, -12 + bob),
                          (4, -12 + bob), (11, -19 + bob), (12, -5 + bob),
                          (9, 11 + bob), (-9, 11 + bob)])
        polygon(tone((218, 188, 238)), [(-9, -6 + bob), (-9, -15 + bob), (-2, -10 + bob),
                                      (4, -10 + bob), (9, -15 + bob), (10, -4 + bob),
                                      (7, 9 + bob), (-7, 9 + bob)])
        face(-2)
        polygon((229, 120, 160, 255), [(-1, 2 + bob), (3, 2 + bob), (1, 4 + bob)])
        for side in (-1, 1):
            line(eyes, (side * 7, 1 + bob), (side * 14, 0 + bob))
            line(eyes, (side * 7, 4 + bob), (side * 14, 5 + bob))
    elif outfit == "robot":
        line(outline, (0, -13 + bob), (0, -22 + bob), 2)
        ellipse((255, 190, 83, 255), (-3, -25 + bob, 6, 6))
        rectangle(outline, (-13, -14 + bob, 26, 23), 4)
        rectangle(tone((143, 200, 218)), (-11, -12 + bob, 22, 19), 3)
        rectangle((35, 66, 75, 255), (-8, -8 + bob, 16, 10), 2)
        face(-4, (156, 255, 218, 255))
        rectangle(outline, (-9, 8 + bob, 7, 8), 1)
        rectangle(outline, (3, 8 + bob, 7, 8), 1)
        rectangle(tone((143, 200, 218)), (-8, 9 + bob, 5, 5), 1)
        rectangle(tone((143, 200, 218)), (4, 9 + bob, 5, 5), 1)
        line((143, 200, 218, 255), (-13, -1 + bob), (-17, 7 + bob), 3)
        line((143, 200, 218, 255), (13, -1 + bob), (17, 7 + bob), 3)
    elif outfit == "knight":
        ghost_body((192, 205, 225))
        polygon((238, 114, 107, 255), [(-1, -13 + bob), (-2, -27 + bob), (7, -21 + bob), (3, -12 + bob)])
        ellipse(outline, (-12, -18 + bob, 24, 20))
        ellipse(tone((195, 213, 227)), (-10, -16 + bob, 20, 16))
        rectangle((42, 59, 69, 255), (-8, -9 + bob, 16, 5), 1)
        line((147, 176, 197, 255), (0, -15 + bob), (0, -1 + bob), 2)
        polygon(outline, [(-18, -1 + bob), (-8, -3 + bob), (-6, 6 + bob), (-12, 14 + bob), (-19, 7 + bob)])
        polygon((115, 196, 172, 255), [(-16, 1 + bob), (-10, 0 + bob), (-9, 6 + bob), (-12, 10 + bob), (-16, 6 + bob)])
        line((232, 242, 245, 255), (16, 5 + bob), (18, -14 + bob), 3)
        line((242, 194, 90, 255), (12, 4 + bob), (21, 5 + bob), 2)
        line((121, 90, 65, 255), (16, 5 + bob), (16, 11 + bob), 3)
    else:  # wizard
        polygon(outline, [(-7, -6 + bob), (6, -6 + bob), (15, 15 + bob), (-14, 15 + bob)])
        polygon(tone((153, 149, 227)), [(-6, -4 + bob), (5, -4 + bob), (12, 13 + bob), (-11, 13 + bob)])
        ellipse((243, 225, 202, 255), (-7, -11 + bob, 14, 14))
        face(-3)
        polygon(outline, [(-14, -8 + bob), (-2, -29 + bob), (9, -9 + bob), (15, -6 + bob), (-16, -5 + bob)])
        polygon((112, 111, 198, 255), [(-11, -9 + bob), (-2, -25 + bob), (7, -8 + bob)])
        line((241, 198, 103, 255), (-9, -9 + bob), (7, -9 + bob), 2)
        ellipse((255, 221, 129, 255), (-4, -19 + bob, 3, 3))
        line((134, 98, 77, 255), (20, 13 + bob), (17, -14 + bob), 3)
        ellipse((143, 226, 247, 110), (11, -25 + bob, 13, 13))
        polygon((182, 253, 245, 255), [(17, -23 + bob), (21, -17 + bob), (17, -12 + bob), (13, -17 + bob)])
    if hurt_amount:
        ellipse((255, 150, 130, round(180 * hurt_amount)), (-23, -23, 46, 46), 1)
    final = pygame.transform.smoothscale(canvas, size)
    if alpha < 255:
        final.set_alpha(alpha)
    target = final.get_rect(center=(round(pos[0]), round(pos[1])))
    return surface.blit(final, target)
