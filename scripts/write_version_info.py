"""Prepare Windows file-version metadata from the single product version."""
from pathlib import Path
import runpy

from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo, StringFileInfo, StringStruct, StringTable,
    VarFileInfo, VarStruct, VSVersionInfo,
)

ROOT = Path(__file__).resolve().parents[1]
version = runpy.run_path(str(ROOT / "desktop_world" / "__init__.py"))["__version__"]
parts = tuple(int(part) for part in version.split("."))
if len(parts) != 3 or any(not 0 <= part <= 65535 for part in parts):
    raise ValueError("Expected a numeric major.minor.patch version")
resource = VSVersionInfo(
    ffi=FixedFileInfo(filevers=parts+(0,), prodvers=parts+(0,), mask=0x3F,
                      flags=0, OS=0x40004, fileType=1, subtype=0, date=(0, 0)),
    kids=[StringFileInfo([StringTable("080404b0", [
        StringStruct("FileDescription", "Desktop Killer - 桌面叛乱"),
        StringStruct("FileVersion", version), StringStruct("ProductVersion", version),
        StringStruct("ProductName", "Desktop Killer"),
        StringStruct("OriginalFilename", "DesktopKiller.exe"),
    ])]), VarFileInfo([VarStruct("Translation", [0x0804, 1200])])],
)
serialized = "\n".join(line.rstrip() for line in str(resource).splitlines()) + "\n"
(ROOT / "packaging" / "version_info.txt").write_text(serialized, encoding="utf-8")
print("Windows product version:", version)
