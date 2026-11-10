"""Safety/alpha unit checks: these never hide a real desktop or create windows."""
import ctypes
import json
from types import SimpleNamespace

import pygame
import pytest

from desktop_world import guardian, winlayer


def test_present_writes_premultiplied_bgra_without_showing(monkeypatch):
    storage = (ctypes.c_ubyte * 12)()
    window = winlayer.LayeredWindow.__new__(winlayer.LayeredWindow)
    window._closed = False
    window.width, window.height = 3, 1
    window.bounds = (-100, 200, -97, 201)
    window._bits = ctypes.addressof(storage)
    window._byte_count = 12
    window._dc, window.hwnd = 123, 456
    uploads = []
    monkeypatch.setattr(winlayer, "_user", SimpleNamespace(
        UpdateLayeredWindow=lambda *args: uploads.append(args) or True))
    surface = pygame.Surface((3, 1), pygame.SRCALPHA, 32)
    surface.set_at((0, 0), (200, 100, 50, 128))
    surface.set_at((1, 0), (255, 255, 255, 0))
    surface.set_at((2, 0), (12, 34, 56, 255))
    window.present(surface)
    assert list(storage) == [25, 50, 100, 128, 0, 0, 0, 0, 56, 34, 12, 255]
    assert len(uploads) == 1
    assert uploads[0][-1] == 2  # ULW_ALPHA, not color-key mode.


@pytest.mark.parametrize("field,value", [("hwnd", 2), ("pid", 99),
    ("class", "AnotherClass"), ("process_created", 456)])
def test_window_identity_rejects_reuse(monkeypatch, field, value):
    recorded = {"hwnd": 1, "pid": 10, "class": "SysListView32", "process_created": 123}
    current = dict(recorded)
    current[field] = value
    monkeypatch.setattr(guardian, "_window_identity", lambda hwnd: current)
    assert not guardian._matches(recorded)


def test_restore_hides_overlay_before_showing_original(monkeypatch):
    state = {"overlay": {"hwnd": 1}, "listview": {"hwnd": 2}, "original_visible": True}
    visible = {1: True, 2: False}
    actions = []

    def request(hwnd, command):
        actions.append((hwnd, command))
        visible[hwnd] = command != guardian.win32con.SW_HIDE

    monkeypatch.setattr(guardian, "_matches", lambda identity: True)
    monkeypatch.setattr(guardian, "_request_visibility", request)
    monkeypatch.setattr(guardian.win32gui, "IsWindowVisible", lambda hwnd: visible[hwnd])
    result = guardian._restore(state)
    assert actions == [(1, guardian.win32con.SW_HIDE), (2, guardian.win32con.SW_SHOWNA)]
    assert result["overlay_hidden"] and result["icons_restored"]


def test_overlay_failure_cannot_skip_icon_recovery(monkeypatch):
    state = {"overlay": {"hwnd": 1}, "listview": {"hwnd": 2}, "original_visible": True}
    visible = {1: True, 2: False}
    overlay_exists = [True]

    def request(hwnd, command):
        if hwnd == 1:
            overlay_exists[0] = False  # Destroyed immediately after identity check.
            raise OSError("window exited")
        visible[hwnd] = True

    monkeypatch.setattr(guardian, "_matches", lambda identity: identity["hwnd"] == 2 or overlay_exists[0])
    monkeypatch.setattr(guardian, "_request_visibility", request)
    monkeypatch.setattr(guardian.win32gui, "IsWindowVisible", lambda hwnd: visible[hwnd])
    result = guardian._restore(state)
    assert result["icons_restored"]
    assert "overlay_error" in result


def test_recover_retries_incomplete_old_released_record(monkeypatch, tmp_path):
    state = {"status": "released", "owner_pid": 12, "overlay": {"hwnd": 1},
             "listview": {"hwnd": 2}, "recovery": {"icons_restored": False}}
    (tmp_path / "lease.json").write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.setattr(guardian, "_matches", lambda identity: True)
    monkeypatch.setattr(guardian, "_owner_alive", lambda state: False)
    monkeypatch.setattr(guardian, "_restore", lambda state: {"icons_restored": True, "overlay_hidden": True})
    assert guardian.recover(tmp_path)
    recovered = json.loads((tmp_path / "lease.json").read_text(encoding="utf-8"))
    assert recovered["status"] == "released"
    assert recovered["recovery"]["icons_restored"]


def test_release_signals_guardian_and_restores_despite_disk_failure(monkeypatch, tmp_path):
    events = []
    lease = guardian.DesktopLease(1, 2, tmp_path)
    lease._state = {"token": lease.token}
    lease._release_event, lease._mutex = 111, 222
    lease._active = True
    lease._watcher = SimpleNamespace(wait=lambda timeout: events.append("watcher_exit"))
    monkeypatch.setattr(guardian, "_kernel", SimpleNamespace(
        SetEvent=lambda handle: events.append("release_signal"), CloseHandle=lambda handle: None))
    monkeypatch.setattr(guardian, "_restore", lambda state: events.append("restore") or {"icons_restored": True})
    monkeypatch.setattr(guardian, "_restoration_complete", lambda state, result: True)

    def failed_write(*args):
        raise OSError("disk unavailable")

    monkeypatch.setattr(guardian, "_atomic_json", failed_write)
    lease.release()
    assert events == ["release_signal", "restore", "watcher_exit"]
    assert not lease._active and lease._state == {}
    assert lease._release_event is None and lease._mutex is None


@pytest.mark.parametrize("class_name,title,executable,allowed", [
    ("360DirectUICls", "360DTFenceLite", "360desktoplite64.exe", True),
    ("360DirectUICls", "360DTFenceLite", "360desktoplite32.exe", True),
    ("OtherClass", "360DTFenceLite", "360desktoplite64.exe", False),
    ("360DirectUICls", "OtherWindow", "360desktoplite64.exe", False),
    ("360DirectUICls", "360DTFenceLite", "unrelated.exe", False),
])
def test_additional_source_requires_exact_desktoplite_identity(
        monkeypatch, class_name, title, executable, allowed):
    identity = {"hwnd": 10, "pid": 20, "class": class_name, "process_created": 30}
    monkeypatch.setattr(guardian, "_window_identity", lambda hwnd: identity)
    monkeypatch.setattr(guardian.win32gui, "GetWindowText", lambda hwnd: title)
    monkeypatch.setattr(guardian.win32gui, "IsWindowVisible", lambda hwnd: True)
    monkeypatch.setattr(guardian, "_style_visible", lambda hwnd: True)
    monkeypatch.setattr(guardian, "_process_name", lambda pid: executable)
    if allowed:
        target = guardian._capture_target(10, source=True)
        assert target["identity"] == identity
        assert target["role"] == "desktoplite"
    else:
        with pytest.raises(RuntimeError, match="explicitly identified"):
            guardian._capture_target(10, source=True)


def test_restore_multiple_sources_preserves_each_own_visibility(monkeypatch):
    targets = [
        {"identity": {"hwnd": 2}, "original_visible": True, "original_style_visible": True},
        {"identity": {"hwnd": 3}, "original_visible": False, "original_style_visible": False},
    ]
    state = {"targets": targets, "overlay": {"hwnd": 1}}
    visible = {1: True, 2: False, 3: True}
    actions = []

    def request(hwnd, command):
        actions.append((hwnd, command))
        visible[hwnd] = command != guardian.win32con.SW_HIDE

    monkeypatch.setattr(guardian, "_matches", lambda identity: True)
    monkeypatch.setattr(guardian, "_request_visibility", request)
    monkeypatch.setattr(guardian, "_style_visible", lambda hwnd: visible[hwnd])
    monkeypatch.setattr(guardian.win32gui, "IsWindowVisible", lambda hwnd: visible[hwnd])
    result = guardian._restore(state)
    assert actions == [(1, guardian.win32con.SW_HIDE),
                       (2, guardian.win32con.SW_SHOWNA), (3, guardian.win32con.SW_HIDE)]
    assert result["icons_restored"]
    assert all(entry["restored"] for entry in result["target_results"])


def test_one_target_destroyed_does_not_skip_other_target_restore(monkeypatch):
    targets = [
        {"identity": {"hwnd": 2}, "original_style_visible": True},
        {"identity": {"hwnd": 3}, "original_style_visible": True},
    ]
    state = {"targets": targets, "overlay": {"hwnd": 1}}
    visible = {1: True, 2: False, 3: False}
    missing = set()

    def request(hwnd, command):
        if hwnd == 2:
            missing.add(2)
            raise OSError("first icon source exited")
        visible[hwnd] = command != guardian.win32con.SW_HIDE

    monkeypatch.setattr(guardian, "_matches", lambda identity: identity["hwnd"] not in missing)
    monkeypatch.setattr(guardian, "_request_visibility", request)
    monkeypatch.setattr(guardian, "_style_visible", lambda hwnd: visible[hwnd])
    monkeypatch.setattr(guardian.win32gui, "IsWindowVisible", lambda hwnd: visible[hwnd])
    result = guardian._restore(state)
    assert result["target_results"][0]["skipped"] == "identity_changed"
    assert result["target_results"][1]["restored"]
    assert guardian._restoration_complete(state, result)


def test_source_reshown_is_detected_even_when_parent_is_hidden(monkeypatch):
    state = {"targets": [{"identity": {"hwnd": 2}}, {"identity": {"hwnd": 3}}]}
    monkeypatch.setattr(guardian, "_matches", lambda identity: True)
    monkeypatch.setattr(guardian.win32gui, "IsWindowVisible", lambda hwnd: False)
    monkeypatch.setattr(guardian, "_style_visible", lambda hwnd: hwnd == 3)
    assert guardian._visibility_violation(state) == "target_reshown:3"


def test_heartbeat_releases_instead_of_rehiding_reshown_source(monkeypatch, tmp_path):
    lease = guardian.DesktopLease(2, 1, tmp_path, source_windows=[3])
    lease._active = True
    lease._last_heartbeat = -100
    lease._watcher = SimpleNamespace(poll=lambda: None)
    actions = []
    monkeypatch.setattr(guardian, "_visibility_violation", lambda state: "target_reshown:3")
    monkeypatch.setattr(lease, "release", lambda: actions.append("release"))
    monkeypatch.setattr(lease, "_write_heartbeat", lambda: actions.append("heartbeat"))
    with pytest.raises(RuntimeError, match="visibility lease ended"):
        lease.heartbeat()
    assert actions == ["release"]
