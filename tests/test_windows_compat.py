"""DPI, input scoping and frozen recovery checks without touching the desktop."""
import ctypes
from types import SimpleNamespace

import pytest

from desktop_world import dpi, guardian, timing, winlayer


def _dpi_api(initial=0, process_ok=True, thread_ok=True):
    state = {"context": initial, "calls": []}
    def process(value):
        state["calls"].append("process")
        if process_ok:
            state["context"] = value.value
        return process_ok
    def thread(value):
        state["calls"].append("thread")
        if thread_ok:
            previous = state["context"] or 1
            state["context"] = value.value
            return previous
        return 0
    api = SimpleNamespace(GetThreadDpiAwarenessContext=lambda: state["context"],
        AreDpiAwarenessContextsEqual=lambda a, b: a == b.value,
        SetProcessDpiAwarenessContext=process, SetThreadDpiAwarenessContext=thread)
    return api, state


def test_manifest_configured_pmv2_does_not_try_to_reset_process():
    api, state = _dpi_api(initial=ctypes.c_void_p(-4).value)
    assert dpi._configure(api)["method"] == "already-configured"
    assert state["calls"] == []


def test_false_dpi_return_requires_verified_thread_recovery(monkeypatch):
    api, state = _dpi_api(process_ok=False)
    monkeypatch.setattr(dpi.ctypes, "get_last_error", lambda: 5)
    result = dpi._configure(api)
    assert result == {"awareness": "per-monitor-v2", "method": "thread", "process_error": 5}
    assert state["calls"] == ["process", "thread"]


def test_unrecoverable_dpi_state_cannot_silently_continue():
    api, _ = _dpi_api(process_ok=False, thread_ok=False)
    with pytest.raises(RuntimeError, match="no desktop changes"):
        dpi._configure(api)


def _input_window(monkeypatch):
    window = winlayer.LayeredWindow.__new__(winlayer.LayeredWindow)
    window._closed = False
    window._keys = {key: False for key in window._KEYS}
    window._buttons = {vk: False for vk, _ in window._BUTTONS}
    window._held_keys = set()
    window._held_buttons = set()
    window._allowed_buttons = set()
    window._activation_button = None
    window._input_active = False
    window._events = []
    window.desktop_active = lambda: True
    window._cursor_on_desktop = lambda point: True
    held, polls = set(), []
    monkeypatch.setattr(winlayer.win32api, "GetAsyncKeyState", lambda key: polls.append(key) or (0x8000 if key in held else 0))
    monkeypatch.setattr(winlayer.win32gui, "GetCursorPos", lambda: (-110, 200))
    monkeypatch.setattr(winlayer.win32api, "GetSystemMetrics", lambda metric: 0)
    return window, held, polls


def test_no_keyboard_or_mouse_poll_when_another_app_is_active(monkeypatch):
    window, held, polls = _input_window(monkeypatch)
    held.update((ord("W"), winlayer.win32con.VK_LBUTTON))
    window._poll_input(False)
    assert polls == [] and window._events == [] and window._held_keys == set()


def test_held_keys_are_desktop_scoped_and_edge_is_not_repeated(monkeypatch):
    window, held, _ = _input_window(monkeypatch)
    window._poll_input(True)
    held.add(ord("W"))
    window._poll_input(True)
    window._poll_input(True)
    assert window.keys() == {ord("W")}
    assert window._events == [("key", ord("W"))]
    window.desktop_active = lambda: False
    assert window.keys() == set()


def test_focus_return_does_not_replay_a_button_already_held_in_another_app(monkeypatch):
    window, held, _ = _input_window(monkeypatch)
    held.add(winlayer.win32con.VK_LBUTTON)
    window._poll_input(False)
    window._poll_input(True)
    assert window._events == []
    assert window.buttons() == set()
    held.clear()
    window._poll_input(True)
    held.add(winlayer.win32con.VK_LBUTTON)
    window._poll_input(True)
    window._poll_input(True)
    window._wndproc(123, winlayer.win32con.WM_LBUTTONDOWN, 0, 0)
    assert window._events == [("click", (-110, 200, 1))]


def test_continuous_mouse_requires_a_fresh_press_in_the_active_work_area(monkeypatch):
    window, held, polls = _input_window(monkeypatch)
    window._poll_input(True)
    held.update((winlayer.win32con.VK_CONTROL, winlayer.win32con.VK_LBUTTON))
    window._poll_input(True)
    assert window.keys() == {winlayer.win32con.VK_CONTROL}
    assert window.buttons() == {1}
    window._poll_input(True)
    assert window._events == [("key", winlayer.win32con.VK_CONTROL), ("click", (-110, 200, 1))]
    window._cursor_on_desktop = lambda point: False
    assert window.buttons() == set()
    window._poll_input(True)
    assert window.buttons() == set()
    window.desktop_active = lambda: False
    before = len(polls)
    window._poll_input(False)
    assert window.buttons() == set() and len(polls) == before
    window.desktop_active = lambda: True
    window._cursor_on_desktop = lambda point: True
    window._poll_input(True)
    assert window.buttons() == set()  # Re-entering with the old press cannot draw.


def test_button_pressed_over_another_app_cannot_start_drawing_by_dragging_in(monkeypatch):
    window, held, _ = _input_window(monkeypatch)
    window._poll_input(True)
    window._cursor_on_desktop = lambda point: False
    held.add(winlayer.win32con.VK_LBUTTON)
    window._poll_input(True)
    window._cursor_on_desktop = lambda point: True
    window._poll_input(True)
    assert window.buttons() == set() and window._events == []


def test_swapped_buttons_report_continuous_logical_primary(monkeypatch):
    window, held, _ = _input_window(monkeypatch)
    monkeypatch.setattr(winlayer.win32api, "GetSystemMetrics", lambda metric: 1)
    window._poll_input(True)
    held.add(winlayer.win32con.VK_RBUTTON)
    window._poll_input(True)
    assert window.buttons() == {1}
    assert window._events == [("click", (-110, 200, 1))]


@pytest.mark.parametrize("swapped", [False, True])
def test_click_that_activates_our_input_surface_is_delivered_once(monkeypatch, swapped):
    window, held, _ = _input_window(monkeypatch)
    window._input_rect = object()
    window._point_in_input = lambda point: True
    window._place_above_desktop = lambda: None
    monkeypatch.setattr(winlayer.win32api, "GetSystemMetrics", lambda metric: int(swapped))
    monkeypatch.setattr(winlayer.win32gui, "SetForegroundWindow", lambda hwnd: None)
    trigger = winlayer.win32con.WM_LBUTTONDOWN
    window._wndproc(123, winlayer.win32con.WM_MOUSEACTIVATE, 0, trigger << 16)
    window._wndproc(123, trigger, 0, 0)
    held.add(winlayer.win32con.VK_RBUTTON if swapped else winlayer.win32con.VK_LBUTTON)
    window._poll_input(True)
    window._poll_input(True)
    assert window._events == [("click", (-110, 200, 1))]
    assert window.buttons() == {1}


def test_v03_entry_keys_have_single_edges(monkeypatch):
    window, held, _ = _input_window(monkeypatch)
    window._poll_input(True)
    expected = {winlayer.win32con.VK_CONTROL, winlayer.win32con.VK_BACK,
                winlayer.win32con.VK_F1, ord("4"), ord("C"), ord("H")}
    held.update(expected)
    window._poll_input(True)
    window._poll_input(True)
    assert window.keys() == expected
    assert len(window._events) == len(expected)
    assert {value for event, value in window._events if event == "key"} == expected


def test_click_over_an_unfocused_application_is_not_a_game_skill(monkeypatch):
    window, held, _ = _input_window(monkeypatch)
    window._poll_input(True)
    window._cursor_on_desktop = lambda point: False
    held.add(winlayer.win32con.VK_RBUTTON)
    window._poll_input(True)
    assert window._events == []


def test_frozen_guardian_uses_dedicated_entrypoint(monkeypatch, tmp_path):
    monkeypatch.setattr(guardian.sys, "frozen", True, raising=False)
    monkeypatch.setattr(guardian.sys, "executable", r"C:\Games\DesktopKiller.exe")
    command = guardian._guardian_command(tmp_path, "token")
    assert command == [r"C:\Games\DesktopKiller.exe", "--guardian", "--watch", str(tmp_path), "token"]


def test_nested_shell_view_still_finds_desktop_root(monkeypatch):
    classes = {10: "Progman", 11: "WorkerW", 12: "SHELLDLL_DefView",
               20: "WorkerW", 30: "CabinetWClass", 31: "SHELLDLL_DefView"}
    monkeypatch.setattr(winlayer.win32gui, "EnumWindows", lambda callback, data: [callback(h, data) for h in (10, 20, 30)])
    monkeypatch.setattr(winlayer.win32gui, "EnumChildWindows", lambda h, callback, data: [callback(c, data) for c in {10: [11, 12], 20: [], 30: [31]}[h]])
    monkeypatch.setattr(winlayer.win32gui, "GetClassName", classes.__getitem__)
    assert winlayer._desktop_host() == 10


def test_mouse_mapping_respects_windows_swapped_buttons(monkeypatch):
    window, held, _ = _input_window(monkeypatch)
    window._poll_input(True)
    monkeypatch.setattr(winlayer.win32api, "GetSystemMetrics", lambda metric: 1)
    held.add(winlayer.win32con.VK_RBUTTON)
    window._poll_input(True)
    assert window._events == [("click", (-110, 200, 1))]


def test_timer_failure_falls_back_and_close_releases_exactly_once(monkeypatch):
    pacer = timing.FramePacer.__new__(timing.FramePacer)
    actions = []
    pacer._timer, pacer._requested = 123, False
    pacer._kernel = SimpleNamespace(SetWaitableTimer=lambda *args: False,
        CancelWaitableTimer=lambda h: actions.append(("cancel", h)),
        CloseHandle=lambda h: actions.append(("close", h)))
    monkeypatch.setattr(timing.time, "perf_counter", lambda: 10.0)
    monkeypatch.setattr(timing.time, "sleep", lambda value: actions.append(("sleep", value)))
    pacer.wait_until(10.25)
    pacer.close()
    pacer.close()
    assert actions == [("sleep", 0.25), ("cancel", 123), ("close", 123)]


def test_shell_cloaked_overlay_requests_lease_recovery_instead_of_reshowing(monkeypatch):
    window, _, _ = _input_window(monkeypatch)
    window._shown, window._desktop_lost, window._last_order = True, False, -1
    window._cloaked = lambda: True
    window.desktop_active = lambda: False
    monkeypatch.setattr(winlayer.win32gui, "PumpWaitingMessages", lambda: None)
    def unexpected_raise():
        raise AssertionError("A window on another virtual desktop must not be raised")
    window._place_above_desktop = unexpected_raise
    assert window.pump() == [("desktop_lost", None)]
    assert window.keys() == set()


def test_input_carrier_changes_only_premultiplied_copy_inside_work_area(monkeypatch):
    import pygame
    window = winlayer.LayeredWindow.__new__(winlayer.LayeredWindow)
    window._closed = False
    window.width, window.height = 4, 1
    window.bounds = (-100, 200, -96, 201)
    window._dc, window.hwnd = 12, 13
    window._byte_count = 16
    storage = (ctypes.c_ubyte * 16)()
    window._bits = ctypes.addressof(storage)
    window.set_input_bounds((-99, 200, -97, 201))
    monkeypatch.setattr(winlayer, "_user", SimpleNamespace(UpdateLayeredWindow=lambda *args: True))
    surface = pygame.Surface((4, 1), pygame.SRCALPHA, 32)
    surface.fill((0, 0, 0, 0))
    surface.set_at((2, 0), (200, 100, 50, 128))
    window.present(surface)
    assert list(storage) == [0, 0, 0, 0, 0, 0, 0, 1, 25, 50, 100, 128, 0, 0, 0, 0]
    assert surface.get_at((1, 0)).a == 0
    window.set_input_bounds(None)
    window.present(surface)
    assert storage[7] == 0  # Prototype retains true alpha zero.


def test_input_work_area_excludes_taskbar_and_other_monitors():
    window = winlayer.LayeredWindow.__new__(winlayer.LayeredWindow)
    window.bounds = (-1920, 0, 1920, 1080)
    window.set_input_bounds((0, 0, 1920, 1042))
    assert window._point_in_input((120, 400))
    assert not window._point_in_input((120, 1050))
    assert not window._point_in_input((-100, 400))
    with pytest.raises(ValueError, match="inside the overlay"):
        window.set_input_bounds((0, 0, 1921, 1042))


def test_explicit_input_click_activates_only_our_window_and_reestablishes_order(monkeypatch):
    import pygame
    window = winlayer.LayeredWindow.__new__(winlayer.LayeredWindow)
    window.bounds = (0, 0, 100, 100)
    window._input_rect = pygame.Rect(0, 0, 100, 90)
    actions = []
    monkeypatch.setattr(winlayer.win32gui, "GetCursorPos", lambda: (20, 20))
    monkeypatch.setattr(winlayer.win32gui, "SetForegroundWindow", lambda hwnd: actions.append(("activate", hwnd)))
    window._place_above_desktop = lambda: actions.append(("desktop-order",))
    assert window._wndproc(123, winlayer.win32con.WM_MOUSEACTIVATE, 0, 0) == winlayer.win32con.MA_NOACTIVATE
    assert actions == [("activate", 123), ("desktop-order",)]
    assert window._wndproc(123, winlayer.win32con.WM_CONTEXTMENU, 0, 0) == 0


@pytest.mark.parametrize("nonstandard", [False, True])
def test_pixel_copy_preserves_channel_order_black_and_alpha_for_both_formats(nonstandard):
    import pygame
    masks = ((0x000000FF, 0x0000FF00, 0x00FF0000, 0xFF000000) if nonstandard
             else (0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000))
    surface = pygame.Surface((3, 1), pygame.SRCALPHA, 32, masks)
    surface.set_at((0, 0), (200, 100, 50, 128))
    surface.set_at((1, 0), (0, 0, 0, 255))
    surface.set_at((2, 0), (255, 255, 255, 0))
    frame = surface.premul_alpha()
    storage = (ctypes.c_ubyte * 12)()
    window = winlayer.LayeredWindow.__new__(winlayer.LayeredWindow)
    window._bits, window._byte_count = ctypes.addressof(storage), 12
    window._copy_pixels(frame)
    assert bytes(storage) == pygame.image.tobytes(frame, "BGRA")
    assert list(storage) == [25, 50, 100, 128, 0, 0, 0, 255, 0, 0, 0, 0]


def test_subsurface_pitch_does_not_copy_padding_as_pixels():
    import pygame
    parent = pygame.Surface((5, 2), pygame.SRCALPHA, 32)
    parent.fill((255, 0, 255, 255))  # Padding would be unmistakably magenta.
    frame = parent.subsurface((1, 0, 2, 2))
    frame.fill((11, 22, 33, 255))
    assert not winlayer._is_contiguous_bgra(frame)
    storage = (ctypes.c_ubyte * 16)()
    window = winlayer.LayeredWindow.__new__(winlayer.LayeredWindow)
    window._bits, window._byte_count = ctypes.addressof(storage), 16
    window._copy_pixels(frame)
    assert list(storage) == [33, 22, 11, 255] * 4
