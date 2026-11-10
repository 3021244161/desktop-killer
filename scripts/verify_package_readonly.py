"""Probe the portable executable with no Python installation on its child PATH.

This is a local dependency check, not a replacement for a clean Windows 11 test.
Both child commands are read-only with respect to the desktop source windows.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import uuid


def restricted_environment(environment: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    removed = sorted(key for key in environment if key.upper().startswith(("PYTHON", "CONDA")))
    child = {key: value for key, value in environment.items()
             if key not in removed and key.upper() != "PATH"}
    windows = next((value for key, value in child.items() if key.upper() == "SYSTEMROOT"), r"C:\Windows")
    child["PATH"] = str(Path(windows) / "System32") + ";" + windows
    return child, removed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "artifacts" / "package-readonly")
    args = parser.parse_args()
    exe = args.exe.resolve(strict=True)
    if exe.suffix.lower() != ".exe" or not exe.is_file():
        parser.error("--exe must name the built DesktopKiller executable")
    output = args.output.resolve() / (datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6])
    output.mkdir(parents=True, exist_ok=False)
    env, removed = restricted_environment(dict(os.environ))
    report = {"exe": str(exe), "child_path": env["PATH"], "removed_environment_keys": removed,
              "host_environment_modified": False, "clean_windows11_validation": False, "commands": []}
    commands = [
        [str(exe), "--diagnose", "--window-check", "--output", str(output / "diagnostics.json")],
        [str(exe), "--probe", "--no-dialog", "--data-dir", str(output / "data"), "--output", str(output)],
    ]
    try:
        for command in commands:
            completed = subprocess.run(command, cwd=exe.parent, env=env, stdin=subprocess.DEVNULL,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       creationflags=subprocess.CREATE_NO_WINDOW, timeout=90)
            report["commands"].append({"command": command, "exit_code": completed.returncode})
            if completed.returncode:
                raise RuntimeError(f"Read-only executable check exited with {completed.returncode}")
        diagnostic = json.loads((output / "diagnostics.json").read_text(encoding="utf-8"))
        probe = json.loads((output / "probe" / "desktop.json").read_text(encoding="utf-8"))
        report.update(frozen=diagnostic.get("frozen"), os_family=diagnostic.get("os_family"),
                      os_build=diagnostic.get("os_build"), hidden_window=diagnostic.get("hidden_window"),
                      probe_icon_count=len(probe["icons"]))
        report["passed"] = bool(report["frozen"] and report["probe_icon_count"] > 0
                                and report["hidden_window"].get("upload_ok")
                                and not report["hidden_window"].get("visible"))
    except Exception as error:
        report.update(passed=False, error=f"{type(error).__name__}: {error}")
    (output / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
