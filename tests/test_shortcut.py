"""Exercise real .lnk serialization only inside pytest's temporary directory."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "create_shortcut.ps1"
POWERSHELL = shutil.which("powershell.exe")


def _run(tmp_path, body):
    if not POWERSHELL:
        pytest.skip("Windows PowerShell is required for local Shell Link tests")
    script = tmp_path / "test-shortcut.ps1"
    script.write_text("$ErrorActionPreference = 'Stop'\n"
                      "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8\n"
                      f". '{str(SCRIPT).replace(chr(39), chr(39)*2)}'\n"
                      "$testDirectory = $PSScriptRoot\n"
                      "$target = Join-Path $testDirectory 'DesktopKiller.exe'\n"
                      "[IO.File]::WriteAllBytes($target, [byte[]](0, 1, 2))\n" + body,
                      encoding="utf-8-sig")
    result = subprocess.run([POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                            capture_output=True, text=True, encoding="utf-8-sig", timeout=25)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_new_link_roundtrips_target_directory_icon_and_normal_privileges(tmp_path):
    result = _run(tmp_path, """
$plan = Get-ProjectShortcutPlan -DesktopDirectory $testDirectory -TargetPath $target
Write-ProjectShortcut -Plan $plan | ConvertTo-Json -Compress
""")
    assert Path(result["ShortcutPath"]).parent == tmp_path
    assert Path(result["ShortcutPath"]).name == "桌面叛乱.lnk"
    assert Path(result["TargetPath"]) == tmp_path / "DesktopKiller.exe"
    assert Path(result["WorkingDirectory"]) == tmp_path
    assert result["IconLocation"] == str(tmp_path / "DesktopKiller.exe") + ",0"
    assert result["Arguments"] == "" and not result["RunAsUser"]


def test_foreign_same_name_link_is_untouched_and_own_suffix_is_reused(tmp_path):
    result = _run(tmp_path, """
$foreign = Join-Path $testDirectory '桌面叛乱.lnk'
$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut($foreign)
$link.TargetPath = Join-Path $testDirectory 'Unrelated.exe'
$link.Save()
[Runtime.InteropServices.Marshal]::ReleaseComObject($link) | Out-Null
[Runtime.InteropServices.Marshal]::ReleaseComObject($shell) | Out-Null
$before = Get-ShortcutFileHash -Path $foreign
$plan = Get-ProjectShortcutPlan -DesktopDirectory $testDirectory -TargetPath $target
$created = Write-ProjectShortcut -Plan $plan
$again = Get-ProjectShortcutPlan -DesktopDirectory $testDirectory -TargetPath $target
$updated = Write-ProjectShortcut -Plan $again
@{First=$created; Second=$updated; ForeignUnchanged=($before -eq (Get-ShortcutFileHash -Path $foreign))} | ConvertTo-Json -Depth 4 -Compress
""")
    assert result["ForeignUnchanged"]
    assert Path(result["First"]["ShortcutPath"]).name == "桌面叛乱 (2).lnk"
    assert result["Second"]["ShortcutPath"] == result["First"]["ShortcutPath"]
    assert result["Second"]["Action"] == "update"


def test_changed_owned_shortcut_is_not_overwritten_after_planning(tmp_path):
    result = _run(tmp_path, """
$plan = Get-ProjectShortcutPlan -DesktopDirectory $testDirectory -TargetPath $target
Write-ProjectShortcut -Plan $plan | Out-Null
$plan = Get-ProjectShortcutPlan -DesktopDirectory $testDirectory -TargetPath $target
[IO.File]::WriteAllText($plan.ShortcutPath, 'replacement after inspection')
$before = Get-ShortcutFileHash -Path $plan.ShortcutPath
$rejected = $false
try { Write-ProjectShortcut -Plan $plan | Out-Null } catch { $rejected = $true }
@{Rejected=$rejected; Unchanged=($before -eq (Get-ShortcutFileHash -Path $plan.ShortcutPath))} | ConvertTo-Json -Compress
""")
    assert result == {"Rejected": True, "Unchanged": True}


def test_existing_project_link_does_not_keep_old_run_as_or_arguments(tmp_path):
    result = _run(tmp_path, """
$plan = Get-ProjectShortcutPlan -DesktopDirectory $testDirectory -TargetPath $target
Write-ProjectShortcut -Plan $plan | Out-Null
$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut($plan.ShortcutPath)
$link.Arguments = '--recover'
$link.WorkingDirectory = [IO.Path]::GetTempPath()
$link.Save()
[Runtime.InteropServices.Marshal]::ReleaseComObject($link) | Out-Null
[Runtime.InteropServices.Marshal]::ReleaseComObject($shell) | Out-Null
$bytes = [IO.File]::ReadAllBytes($plan.ShortcutPath)
$flags = [BitConverter]::ToUInt32($bytes, 20) -bor 0x2000
[Array]::Copy([BitConverter]::GetBytes([uint32]$flags), 0, $bytes, 20, 4)
[IO.File]::WriteAllBytes($plan.ShortcutPath, $bytes)
$before = Get-ShortcutDetails -Path $plan.ShortcutPath
$updated = Write-ProjectShortcut -Plan (Get-ProjectShortcutPlan -DesktopDirectory $testDirectory -TargetPath $target)
@{BeforeRunAs=$before.RunAsUser; After=$updated} | ConvertTo-Json -Depth 4 -Compress
""")
    assert result["BeforeRunAs"] and not result["After"]["RunAsUser"]
    assert result["After"]["Arguments"] == ""
    assert Path(result["After"]["WorkingDirectory"]) == tmp_path


def test_new_name_claimed_after_planning_is_never_overwritten(tmp_path):
    result = _run(tmp_path, """
$plan = Get-ProjectShortcutPlan -DesktopDirectory $testDirectory -TargetPath $target
[IO.File]::WriteAllText($plan.ShortcutPath, 'unrelated file created after inspection')
$before = Get-ShortcutFileHash -Path $plan.ShortcutPath
$rejected = $false
try { Write-ProjectShortcut -Plan $plan | Out-Null } catch { $rejected = $true }
@{Rejected=$rejected; Unchanged=($before -eq (Get-ShortcutFileHash -Path $plan.ShortcutPath))} | ConvertTo-Json -Compress
""")
    assert result == {"Rejected": True, "Unchanged": True}


def test_default_target_prefers_portable_exe_and_falls_back_to_source_dist(tmp_path):
    result = _run(tmp_path, """
$portable = Get-ShortcutExecutablePath -ScriptDirectory $testDirectory
$sourceScripts = Join-Path $testDirectory 'scripts'
[IO.Directory]::CreateDirectory($sourceScripts) | Out-Null
$source = Get-ShortcutExecutablePath -ScriptDirectory $sourceScripts
@{Portable=$portable; Source=$source} | ConvertTo-Json -Compress
""")
    assert Path(result["Portable"]) == tmp_path / "DesktopKiller.exe"
    assert Path(result["Source"]) == tmp_path / "dist" / "DesktopKiller" / "DesktopKiller.exe"
