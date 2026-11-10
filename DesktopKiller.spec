# -*- mode: python ; coding: utf-8 -*-
"""Portable onedir build: retain the full folder when copying to another PC."""
from pathlib import Path

root = Path(SPECPATH)
data = [(str(root / name), ".") for name in ("README.md", "compatibility.md", "VALIDATION.md", "RELEASE_NOTES.md") if (root / name).is_file()]
data += [(str(root / name), name) for name in ("assets", "config") if (root / name).is_dir()]
data += [(str(root / "output" / "pdf" / "玩法指南.pdf"), "docs"),
         (str(root / "packaging" / "licenses"), "licenses")]
a = Analysis([str(root / "main.py")], pathex=[str(root)], binaries=[], datas=data,
             hiddenimports=["pythoncom", "pywintypes", "win32timezone", "win32com.shell.shell",
                            "desktop_world.guardian", "desktop_world.diagnostics"],
             hookspath=[], hooksconfig={}, runtime_hooks=[],
             excludes=["tkinter", "matplotlib", "scipy", "pandas", "PyQt5", "PyQt6", "PySide2", "PySide6"],
             noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="DesktopKiller", debug=False,
          bootloader_ignore_signals=False, strip=False, upx=False, console=False,
          disable_windowed_traceback=False, manifest=str(root / "packaging" / "DesktopKiller.manifest"),
          version=str(root / "packaging" / "version_info.txt"))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="DesktopKiller")
