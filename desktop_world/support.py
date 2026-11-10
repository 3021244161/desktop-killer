"""Open bundled help and the player's writable data directory on explicit request."""
from pathlib import Path
import os
import sys

from .runtime_paths import SOURCE_ROOT


def manual_path() -> Path:
    roots = [Path(sys.executable).resolve().parent / "docs", SOURCE_ROOT / "docs", SOURCE_ROOT / "output" / "pdf"]
    for root in roots:
        candidates = sorted(root.glob("*.pdf")) if root.is_dir() else []
        if candidates:
            return candidates[0]
    raise FileNotFoundError("The bundled PDF manual is missing")


def open_manual() -> None:
    os.startfile(str(manual_path()))


def open_data_directory(path: Path) -> None:
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    os.startfile(str(path.resolve()))
