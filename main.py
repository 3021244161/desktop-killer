"""Windows entry point: establish physical pixel coordinates before GUI imports."""
import os
import sys

from desktop_world.dpi import enable_physical_coordinates

DPI_STATUS = enable_physical_coordinates()

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--guardian":
        from desktop_world.guardian import guardian_main
        raise SystemExit(guardian_main(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "--diagnose":
        from desktop_world.diagnostics import main
        raise SystemExit(main(sys.argv[2:]))
    from desktop_world.app import main
    raise SystemExit(main())
