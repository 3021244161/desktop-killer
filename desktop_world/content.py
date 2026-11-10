"""Static combat content, independent of rendering and the operating system."""

CHAPTERS = (
    {"title": "第一章 · 桌面叛变", "limit": 90.0, "seals": 4},
    {"title": "第二章 · 进程风暴", "limit": 110.0, "seals": 6},
    {"title": "第三章 · 系统核心", "limit": 130.0, "seals": 8},
)
UPGRADES = {
    "multishot": ("分叉协议", "每轮多发一枚子弹，形成扇形火力。", 3),
    "chain": ("连锁电弧", "命中后跳向邻敌，每层增加跳跃和伤害。", 3),
    "blades": ("环绕刃", "增加一把自动旋转的近身防御刃。", 3),
    "damage": ("高压弹芯", "子弹伤害 +20%，电弧和刀刃同步增强。", 4),
    "fire_rate": ("超频连发", "自动射击速度 +18%。", 4),
    "pierce": ("穿透缓存", "每枚子弹额外穿透一个敌人。", 2),
    "vitality": ("应急修复", "生命上限 +20，立即恢复 40 生命。", 3),
    "shield": ("自愈防火墙", "护盾上限 +15，脱战后逐步回复护盾。", 3),
    "speed": ("轻量引擎", "移动速度 +12%，冲刺冷却缩短。", 3),
    "pulse": ("脉冲增幅", "脉冲伤害和范围增加，冷却缩短。", 3),
    "magnet": ("经验聚合", "经验获取 +20%，碎片吸取距离增加。", 3),
    "seal": ("快速断链", "断链停留时间减少，成功后的恢复量增加。", 3),
}
STAGE_REWARDS = (
    {"id": "repair", "title": "整备补给", "description": "生命回满，护盾上限 +15 并补满。", "level": 1},
    {"id": "overclock", "title": "攻击超频", "description": "永久伤害 +15%，射速 +10%，恢复 25 生命。", "level": 1},
    {"id": "mobility", "title": "战术升级", "description": "永久移速 +10%，技能冷却 -15%，恢复 25 生命。", "level": 1},
)
ENEMIES = {
    "chaser": {"hp": 34.0, "speed": 72.0, "contact": 9.0, "xp": 14.0},
    "ranger": {"hp": 28.0, "speed": 54.0, "contact": 8.0, "xp": 16.0},
    "charger": {"hp": 52.0, "speed": 62.0, "contact": 15.0, "xp": 20.0},
    "orbiter": {"hp": 40.0, "speed": 82.0, "contact": 10.0, "xp": 18.0},
}


def classify_role(name: str, fallback_index: int = 0) -> str:
    """Give familiar software a recognizable behavior, with a balanced fallback."""
    label = name.casefold().strip()
    if any(word in label for word in ("chrome", "edge", "firefox", "chromium", "opera",
                                      "brave", "vivaldi", "browser", "浏览器")):
        return "ranger"
    if any(word in label for word in ("steam", "epic", "wegame", "battle.net", "battlenet",
                                      "ubisoft", "游戏", "game", "riot", "gog")):
        return "charger"
    if label.endswith((".txt", ".md", ".doc", ".docx", ".pdf", ".xls", ".xlsx",
                       ".ppt", ".pptx", ".png", ".jpg", ".jpeg", ".webp")):
        return "orbiter"
    return tuple(ENEMIES)[fallback_index % len(ENEMIES)]
