"""Writable player data lives outside a possibly read-only installed game folder."""
import os
from pathlib import Path
import sys

FROZEN = bool(getattr(sys, "frozen", False))
SOURCE_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "DesktopKiller"
DEFAULT_OUTPUT = DATA_DIR / "diagnostics" if FROZEN else SOURCE_ROOT / "artifacts"
