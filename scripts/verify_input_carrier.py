"""Bounded hit-test check using only a tiny owned window; no desktop takeover."""
from pathlib import Path
import sys
import json
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from desktop_world.dpi import enable_physical_coordinates
enable_physical_coordinates()
import os
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import pygame
import win32con
import win32gui
from desktop_world.winlayer import LayeredWindow

foreground = win32gui.GetForegroundWindow()
with LayeredWindow((100, 100, 132, 132), "Desktop Killer owned input test",
                   input_bounds=(108, 108, 124, 124)) as window:
    surface = pygame.Surface((32, 32), pygame.SRCALPHA, 32)
    surface.fill((0, 0, 0, 0))
    window.present(surface)
    # Raise only this tiny test window, without activation; never touch another HWND.
    win32gui.SetWindowPos(window.hwnd, win32con.HWND_TOP, 0, 0, 0, 0,
                          win32con.SWP_NOMOVE | win32con.SWP_NOSIZE |
                          win32con.SWP_NOACTIVATE | win32con.SWP_SHOWWINDOW)
    time.sleep(0.05)
    inside = win32gui.WindowFromPoint((112, 112))
    outside = win32gui.WindowFromPoint((104, 104))
    outcomes = {"carrier_hit": inside == window.hwnd,
                "alpha_zero_outside_passes_through": outside != window.hwnd,
                "foreground_unchanged": win32gui.GetForegroundWindow() == foreground,
                "scene_alpha_unchanged": surface.get_at((12, 12)).a == 0,
                "right_down_consumed": win32gui.SendMessage(window.hwnd, win32con.WM_RBUTTONDOWN, 0, (12 << 16) | 12) == 0,
                "right_up_consumed": win32gui.SendMessage(window.hwnd, win32con.WM_RBUTTONUP, 0, (12 << 16) | 12) == 0,
                "context_menu_consumed": win32gui.SendMessage(window.hwnd, win32con.WM_CONTEXTMENU, 0, (112 << 16) | 112) == 0}
out = ROOT / "artifacts" / "input-carrier-verification.json"
out.parent.mkdir(exist_ok=True)
out.write_text(json.dumps(outcomes, indent=2), encoding="utf-8")
print(json.dumps(outcomes, indent=2))
raise SystemExit(0 if all(outcomes.values()) else 1)
