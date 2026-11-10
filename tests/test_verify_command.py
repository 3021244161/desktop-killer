"""Check recovery-verifier commands without launching a game."""
from pathlib import Path
from scripts.verify_desktop import child_command
from scripts.verify_package_readonly import restricted_environment


def test_default_source_verifier_retains_prototype_and_isolated_paths(tmp_path):
    command = child_command(exe=None, game=False, duration=12, data_dir=tmp_path / "data",
                            output=tmp_path / "evidence", crash=False)
    assert "--prototype" in command
    assert "--export-frames" in command
    assert command[command.index("--data-dir") + 1] == str(tmp_path / "data")
    assert command[command.index("--output") + 1] == str(tmp_path / "evidence")


def test_exe_game_crash_verifier_never_invokes_python_or_prototype(tmp_path):
    exe = Path(r"C:\Games With Spaces\DesktopKiller.exe")
    command = child_command(exe=exe, game=True, duration=8, data_dir=tmp_path / "data",
                            output=tmp_path / "evidence", crash=True)
    assert command[0] == str(exe)
    assert "--prototype" not in command
    assert "--export-frames" not in command
    assert command[command.index("--duration") + 1] == "8"


def test_package_readonly_check_removes_python_only_from_child_environment():
    host = {"Path": r"C:\Anaconda;C:\Windows", "SYSTEMROOT": r"C:\Windows",
            "PYTHONHOME": r"C:\Anaconda", "PythonPath": r"C:\modules",
            "CONDA_PREFIX": r"C:\Anaconda", "TEMP": r"C:\Temp"}
    child, removed = restricted_environment(host)
    assert child == {"SYSTEMROOT": r"C:\Windows", "PATH": r"C:\Windows\System32;C:\Windows",
                     "TEMP": r"C:\Temp"}
    assert set(removed) == {"PYTHONHOME", "PythonPath", "CONDA_PREFIX"}
    assert host["PYTHONHOME"] == r"C:\Anaconda" and "Path" in host


def test_drawing_mode_never_inherits_the_default_prototype_flag(tmp_path):
    command = child_command(exe=Path("DesktopKiller.exe"), game=False, mode="drawing", duration=12,
                            data_dir=tmp_path / "data", output=tmp_path / "evidence", crash=False)
    assert "--prototype" not in command
    assert command[command.index("--mode") + 1] == "drawing"
    assert "--demo" in command and "--export-frames" in command
