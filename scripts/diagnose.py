"""Generate a local Windows compatibility report without taking over the desktop."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desktop_world.dpi import enable_physical_coordinates
enable_physical_coordinates()
from desktop_world.diagnostics import main

if __name__ == "__main__":
    raise SystemExit(main())
