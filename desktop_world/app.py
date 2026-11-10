"""Game lifecycle, desktop lease, persistence and bounded diagnostic runs."""
from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
import sys
import time

from .runtime_paths import SOURCE_ROOT as ROOT, DATA_DIR, DEFAULT_OUTPUT


def export_probe(snapshot, destination: Path) -> dict:
    """Export independently extracted RGBA assets, never desktop screenshots."""
    destination.mkdir(parents=True, exist_ok=True)
    icons = []
    for index, icon in enumerate(snapshot.icons):
        filename = f"icon-{index:03d}.png"
        icon.image.save(destination / filename)
        if getattr(icon, "label_image", None) is not None:
            icon.label_image.save(destination / f"label-{index:03d}.png")
        alpha = icon.image.convert("RGBA").getchannel("A")
        icons.append({"key": icon.key, "name": icon.name, "x": icon.x, "y": icon.y,
                      "width": icon.width, "height": icon.height,
                      "label_rect": icon.label_rect, "asset": filename,
                      "alpha_extrema": alpha.getextrema()})
    data = {"bounds": snapshot.bounds, "work_area": snapshot.work_area,
            "icon_count": len(icons), "font": [snapshot.font_name, snapshot.font_size],
            "diagnostics": snapshot.diagnostics, "icons": icons}
    (destination / "desktop.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Desktop Killer · 桌面叛乱")
    result.add_argument("--probe", action="store_true", help="只读检查桌面，导出透明图标，不接管显示")
    result.add_argument("--recover", action="store_true", help="重试恢复已退出游戏遗留的图标显示状态")
    result.add_argument("--duration", type=float, default=0, help="指定秒数后自动还原退出（墙钟时间）")
    result.add_argument("--demo", action="store_true", help="小人自动走位，适合验收")
    result.add_argument("--no-auto-wake", action="store_true", help="仅通过空格或按钮唤醒")
    result.add_argument("--prototype", action="store_true", help="运行最初的融合演示，供桌面接管回归")
    result.add_argument("--mode", choices=("campaign", "blitz", "endless", "drawing"), help="直接进入指定模式")
    result.add_argument("--seed", type=int, help="指定局内随机种子，便于复现")
    result.add_argument("--data-dir", type=Path, default=DATA_DIR, help="本地存档与恢复状态目录")
    result.add_argument("--no-dialog", action="store_true", help="错误只写日志和标准错误")
    result.add_argument("--export-frames", action="store_true", help="保存验证用透明帧，不截桌面")
    result.add_argument("--capture-screen", action="store_true", help="诊断：等待桌面前台，保存接管前/静止/离位/恢复后的实际屏幕")
    result.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return result


def run(args) -> int:
    if args.recover:
        from desktop_world.guardian import recover
        restored = recover(args.data_dir)
        if sys.stdout is not None:
            print("桌面图标已恢复。" if restored else "没有需要恢复的桌面租约。")
        return 0
    from desktop_world.guardian import session_active
    if session_active(args.data_dir):
        raise RuntimeError("已有游戏正在运行。请切到桌面继续，或点击右下角的退出按钮。")
    from desktop_world.shell import capture_desktop
    started = time.perf_counter()
    snapshot = capture_desktop()
    summary = {key: value for key, value in snapshot.diagnostics.items() if key != "items"}
    logging.info("Desktop read: count=%d bounds=%s elapsed=%.3f diagnostics=%s",
                 len(snapshot.icons), snapshot.bounds, time.perf_counter() - started,
                 summary)
    if not snapshot.icons:
        raise RuntimeError("当前桌面没有可读取的图标。请在桌面放置一个图标后重试。")
    if args.probe:
        data = export_probe(snapshot, args.output / "probe")
        print(json.dumps({"icon_count": data["icon_count"], "bounds": data["bounds"],
                          "diagnostics": summary}, ensure_ascii=False))
        return 0

    import pygame
    from desktop_world.winlayer import LayeredWindow
    from desktop_world.guardian import DesktopLease
    from desktop_world.timing import FramePacer

    from desktop_world.profile import load_profile, save_profile
    from desktop_world.progression import settle_run
    from desktop_world.audio import SoundBank
    profile_path = args.data_dir / "profile.json"
    profile = load_profile(profile_path)
    audio = SoundBank(muted=profile.get("muted", False))
    logging.info("Audio prepared before desktop handover: effects=%s music=%s compose_s=%.3f muted=%s",
                 audio.available, audio.music_available, audio.music_generation_seconds, audio.muted)
    profile_dirty = False
    save_retry_at = 0.0

    def persist_profile():
        nonlocal profile_dirty, save_retry_at
        try:
            save_profile(profile_path, profile)
            profile_dirty = False
            return True
        except OSError:
            profile_dirty = True
            save_retry_at = time.monotonic() + 3.0
            logging.exception("Could not save player profile")
            return False

    def on_result(summary):
        receipt = settle_run(profile, summary)
        receipt["saved"] = persist_profile()
        logging.info("Run result: %s", summary)
        return receipt

    def open_support(action):
        from desktop_world.support import open_manual, open_data_directory
        try:
            if action == "help":
                open_manual()
            else:
                open_data_directory(args.data_dir)
        except OSError:
            logging.exception("Could not open support content")
            scene._say("无法打开文件。可在游戏文件夹内查看 docs 中的 PDF 手册。")

    if args.prototype:
        from desktop_world.prototype import DesktopScene
        scene = DesktopScene(snapshot, auto_wake=not args.no_auto_wake)
    else:
        from desktop_world.game_view import GameView
        scene = GameView(snapshot, profile, audio, on_result,
                         start_mode=args.mode or ("campaign" if args.demo else None), seed=args.seed,
                         on_profile_change=persist_profile)
    layer = LayeredWindow(snapshot.bounds,
                          input_bounds=None if args.prototype else snapshot.work_area)
    lease = DesktopLease(snapshot.listview_hwnd, layer.hwnd, args.data_dir,
                         source_windows=getattr(snapshot, "source_windows", []))
    pacer = FramePacer()
    frame_times: list[float] = []
    captured: set[int] = set()
    screen_stages: list[str] = []
    running = True
    entered = time.perf_counter()
    previous = entered
    frames = 0
    was_active = True
    try:
        # Prepare every idle icon BEFORE touching the real icon view.
        layer.present(scene.render())
        if args.capture_screen:
            from desktop_world.diagnostics import capture_screen
            deadline = time.monotonic() + 45
            while not layer.desktop_active():
                if time.monotonic() >= deadline:
                    raise RuntimeError("合成画面验收等待超时。请切到桌面后再运行该诊断。")
                layer.pump()
                time.sleep(.1)
            if capture_screen(layer, args.output, "before"):
                screen_stages.append("before")
        lease.acquire()
        layer.show()
        entered = previous = time.perf_counter()
        if args.capture_screen and capture_screen(layer, args.output, "idle"):
            screen_stages.append("idle")
        while running:
            now = time.perf_counter()
            dt = now - previous
            previous = now
            if args.duration > 0 and now - entered >= args.duration:
                break
            lease.heartbeat()
            if profile_dirty and time.monotonic() >= save_retry_at and persist_profile():
                if not args.prototype:
                    if scene.reward:
                        scene.reward["saved"] = True
                    scene._say("档案已重新保存")
            for kind, value in layer.pump():
                if kind in ("quit", "display_changed", "desktop_lost"):
                    running = False
                elif kind == "key":
                    if value == 0x74:  # F5 always restores the desktop and exits.
                        running = False
                    elif not args.prototype:
                        action = scene.handle_key(value, layer.cursor())
                        if action == "quit":
                            running = False
                        elif action == "settings":
                            persist_profile()
                        elif action in ("help", "open_data"):
                            open_support(action)
                    elif value == 0x1B:
                        running = False
                    elif value == 0x20:
                        scene.wake_next()
                    elif value == 0x52:
                        scene.reset()
                elif kind == "click":
                    x, y, button = value
                    if not args.prototype:
                        action = scene.handle_click(x, y, button)
                        if action == "quit":
                            running = False
                        elif action == "settings":
                            persist_profile()
                        elif action in ("help", "open_data"):
                            open_support(action)
                    elif button in (1, "left"):
                        action = scene.action_at(x, y)
                        if action == "quit":
                            running = False
                        elif action == "wake":
                            scene.wake_next()
                        elif action == "reset":
                            scene.reset()
                        else:
                            scene.pulse()
            if not running:
                break
            desktop_active = layer.desktop_active()
            active = args.demo or desktop_active
            if not args.prototype and active != was_active:
                scene.focus_changed(active)
            was_active = active
            if not args.prototype:
                # Apply focus/resume before the frame can emit effects; modal
                # victory/upgrade cues may finish while their music is paused.
                scene.update_audio(0, foreground=desktop_active)
            if active:
                if args.prototype:
                    scene.update(dt, layer.cursor(), demo=args.demo)
                else:
                    scene.update(dt, layer.cursor(), keys=layer.keys(), buttons=layer.buttons(), demo=args.demo)
            if not args.prototype:
                scene.update_audio(dt, foreground=desktop_active)
            frame = scene.render()
            layer.present(frame)
            if (args.capture_screen and scene.time >= 6 and "departed" not in screen_stages
                    and capture_screen(layer, args.output, "departed")):
                screen_stages.append("departed")
            frames += 1
            frame_times.append(time.perf_counter() - now)
            if args.export_frames:
                checkpoint = next((t for t in (0, 3, 6, 10) if scene.time >= t and t not in captured), None)
                if checkpoint is not None:
                    args.output.mkdir(parents=True, exist_ok=True)
                    pygame.image.save(frame, str(args.output / f"scene-{checkpoint:02d}.png"))
                    captured.add(checkpoint)
            # Avoid a tight loop; the guardian has its own process and independent clock.
            pacer.wait_until(now + (1 / 60 if active else .1))
    finally:
        # The lease restores Explorer even if drawing, input, or serialization failed.
        try:
            layer.hide()
        finally:
            try:
                lease.release()
                if args.capture_screen and "before" in screen_stages:
                    from desktop_world.diagnostics import capture_screen
                    if capture_screen(layer, args.output, "restored"):
                        screen_stages.append("restored")
            finally:
                try:
                    layer.close()
                finally:
                    pacer.close()
                    audio.close()
                    if profile_dirty and not persist_profile() and not args.no_dialog:
                        import ctypes
                        ctypes.windll.user32.MessageBoxW(None,
                            f"桌面已恢复，但本次档案仍无法保存。\n请检查目录权限或可用空间：\n{args.data_dir}",
                            "Desktop Killer · 档案未保存", 0x30)
        elapsed = time.perf_counter() - entered
        metrics = {"frames": frames, "elapsed_s": round(elapsed, 3),
                   "scene_time_s": round(scene.time, 3), "icon_count": len(scene.actors),
                   "awake": sum(a.state not in ("idle", "home", "sealed") for a in scene.actors), "contacts": scene.hits,
                   "mode": "prototype" if args.prototype else scene.mode,
                   "state": "prototype" if args.prototype else (scene.session.state if scene.session else "menu"),
                   "average_frame_ms": round(1000 * sum(frame_times) / max(1, len(frame_times)), 3),
                   "p95_frame_ms": round(1000 * sorted(frame_times)[int(len(frame_times) * .95)], 3) if frame_times else 0}
        logging.info("Session finished: %s", metrics)
        args.output.mkdir(parents=True, exist_ok=True)
        if frames:
            (args.output / "last-run.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
        if args.capture_screen:
            from desktop_world.diagnostics import save_capture_index
            save_capture_index(args.output, screen_stages)
    return 0


def main() -> int:
    args = parser().parse_args()
    args.data_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=args.data_dir / "game.log", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", encoding="utf-8")
    try:
        if os.name != "nt":
            raise RuntimeError("此游戏需要 Windows。")
        return run(args)
    except Exception as exc:
        logging.exception("Game failed")
        message = f"桌面叛乱未能继续：\n{exc}\n\n诊断日志：{args.data_dir / 'game.log'}"
        if sys.stderr is not None:
            print(message, file=sys.stderr)
        if not args.no_dialog and os.name == "nt":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, "Desktop Killer", 0x10)
        return 1
