"""Bounded desktop recovery verification; --exe tests a built package.

Default mode retains the prototype regression. --game exercises the full game.
--crash ends only our child. Profiles live in isolated runtime/verify-* folders.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from desktop_world.dpi import enable_physical_coordinates
enable_physical_coordinates()
import win32gui
from desktop_world.shell import capture_desktop
from desktop_world.guardian import _kernel, _process_info, _style_visible, recover


def read_state(data_dir: Path) -> dict:
    try:
        return json.loads((data_dir / "lease.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def geometry(snapshot):
    return {icon.key: (icon.x, icon.y, icon.width, icon.height, icon.label_rect) for icon in snapshot.icons}


def child_command(*, exe: Path | None, game: bool, duration: float,
                  data_dir: Path, output: Path, crash: bool, mode: str | None = None) -> list[str]:
    if mode is not None and mode not in ("campaign", "blitz", "endless", "drawing"):
        raise ValueError("Unsupported verification mode")
    command = [str(exe)] if exe is not None else [sys.executable, str(ROOT / "main.py")]
    command += ["--demo", "--duration", str(duration), "--no-dialog",
                "--data-dir", str(data_dir), "--output", str(output)]
    if mode is not None:
        command += ["--mode", mode]
    elif not game:
        command.append("--prototype")
    if not crash:
        command.append("--export-frames")
    return command


def verify(crash: bool = False, *, exe: Path | None = None, game: bool = False,
           duration: float = 12.0, output: Path | None = None, mode: str | None = None) -> dict:
    if not 4 <= duration <= 120:
        raise ValueError("Verification duration must be between 4 and 120 seconds")
    if exe is not None:
        exe = exe.resolve(strict=True)
        if not exe.is_file() or exe.suffix.lower() != ".exe":
            raise ValueError("--exe must identify the built DesktopKiller executable")
    variant = "package" if exe is not None else "source"
    run_mode = mode or ("game" if game else "prototype")
    case = "crash" if crash else "normal"
    data_dir = ROOT / "runtime" / f"verify-{variant}"
    output_root = (output or ROOT / "artifacts" / "verification").resolve()
    run_dir = output_root / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{variant}-{run_mode}-{case}-{uuid.uuid4().hex[:6]}"
    run_dir.mkdir(parents=True, exist_ok=False)
    report_path = run_dir / "result.json"
    report = {"case": case, "variant": variant, "mode": run_mode, "duration_limit": duration,
              "data_dir": str(data_dir), "output": str(run_dir), "passed": False}
    before = capture_desktop()
    report.update(count_before=len(before.icons), source_kind=before.diagnostics.get("source_kind"))
    command = child_command(exe=exe, game=game, duration=duration, data_dir=data_dir,
                            output=run_dir / "game", crash=crash, mode=mode)
    report["command"] = command
    child = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=subprocess.CREATE_NO_WINDOW)
    handle, owner_created = _process_info(child.pid)
    if handle:
        _kernel.CloseHandle(handle)
    report["child_pid"] = child.pid
    failure: BaseException | None = None
    try:
        if owner_created is None:
            raise RuntimeError("Cannot verify the spawned child's process identity")
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            state = read_state(data_dir)
            if (state.get("owner_pid") == child.pid and state.get("owner_created") == owner_created
                    and state.get("status") == "active"):
                break
            if child.poll() is not None:
                raise RuntimeError(f"Game exited before acquiring desktop: {child.returncode}; see {data_dir / 'game.log'}")
            time.sleep(.05)
        else:
            raise RuntimeError("Game did not acquire desktop within 30 seconds")
        source_handles = list(dict.fromkeys([before.listview_hwnd] + getattr(before, "source_windows", [])))
        report.update(original_hidden_during_play=not _style_visible(before.listview_hwnd),
                      source_count=len(source_handles),
                      all_sources_hidden_during_play=all(not _style_visible(hwnd) for hwnd in source_handles))
        if crash:
            time.sleep(1.5)
            if child.poll() is None:
                child.terminate()
        child.wait(timeout=duration + 8)
        report["exit_code"] = child.returncode
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            state = read_state(data_dir)
            if (state.get("owner_pid") == child.pid and state.get("owner_created") == owner_created
                    and state.get("status") == "released" and win32gui.IsWindowVisible(before.listview_hwnd)):
                break
            time.sleep(.05)
        else:
            raise RuntimeError("Guardian did not confirm desktop recovery")
        after = capture_desktop()
        report.update(count_after=len(after.icons), geometry_unchanged=geometry(before) == geometry(after),
                      icons_visible=bool(win32gui.IsWindowVisible(after.listview_hwnd)),
                      all_sources_restored=all(_style_visible(hwnd) for hwnd in source_handles),
                      guardian_reason=state.get("released_reason"), recovery=state.get("recovery"))
        failed = [key for key in ("original_hidden_during_play", "geometry_unchanged", "icons_visible",
                  "all_sources_hidden_during_play", "all_sources_restored") if not report[key]]
        if failed:
            raise RuntimeError("Recovery verification failed: " + ", ".join(failed))
        if not crash and child.returncode != 0:
            raise RuntimeError(f"Normal game run returned {child.returncode}")
        report["passed"] = True
    except BaseException as exc:
        failure = exc
        report["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        try:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=5)
            # Never restore a stale lease belonging to another run or a reused PID.
            state = read_state(data_dir)
            if (state.get("owner_pid") == child.pid and state.get("owner_created") == owner_created
                    and owner_created is not None):
                recover(data_dir)
        except Exception as exc:
            report["passed"] = False
            report["cleanup_error"] = f"{type(exc).__name__}: {exc}"
            if failure is None:
                failure = exc
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"report": str(report_path), **report}, ensure_ascii=False))
    if failure is not None:
        raise failure
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--crash", action="store_true")
    parser.add_argument("--exe", type=Path, help="Built DesktopKiller.exe to test instead of source")
    parser.add_argument("--game", action="store_true", help="Exercise the formal game instead of the prototype")
    parser.add_argument("--mode", choices=("campaign", "blitz", "endless", "drawing"),
                        help="Select a formal mode, implying --game")
    parser.add_argument("--duration", type=float, default=12.0)
    parser.add_argument("--output", type=Path, help="Parent of a unique evidence folder")
    args = parser.parse_args()
    verify(args.crash, exe=args.exe, game=args.game, duration=args.duration, output=args.output, mode=args.mode)
