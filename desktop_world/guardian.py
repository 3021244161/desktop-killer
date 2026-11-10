"""Independent visibility lease: restore exact original HWNDs if the renderer dies."""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

import win32con
import win32gui
import win32process


_MUTEX = "Local\\DesktopKillerPrototypeVisibilityLease_v1"
_kernel = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
_kernel.CreateMutexW.restype = wintypes.HANDLE
_kernel.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
_kernel.OpenMutexW.restype = wintypes.HANDLE
_kernel.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
_kernel.CreateEventW.restype = wintypes.HANDLE
_kernel.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
_kernel.OpenEventW.restype = wintypes.HANDLE
_kernel.SetEvent.argtypes = [wintypes.HANDLE]
_kernel.SetEvent.restype = wintypes.BOOL
_kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_kernel.OpenProcess.restype = wintypes.HANDLE
_kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
_kernel.WaitForSingleObject.restype = wintypes.DWORD
_kernel.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel.CloseHandle.restype = wintypes.BOOL
_kernel.GetProcessTimes.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.FILETIME),
    ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME)]
_kernel.GetProcessTimes.restype = wintypes.BOOL
_kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
_kernel.TerminateProcess.restype = wintypes.BOOL
_kernel.GetCurrentThreadId.argtypes = []
_kernel.GetCurrentThreadId.restype = wintypes.DWORD
_kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                             wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
_kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
_user = ctypes.WinDLL("user32", use_last_error=True)
_user.ShowWindowAsync.argtypes = [wintypes.HWND, ctypes.c_int]
_user.ShowWindowAsync.restype = wintypes.BOOL


def _atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _process_created(handle) -> int:
    creation, end, kernel, user = (wintypes.FILETIME() for _ in range(4))
    if not _kernel.GetProcessTimes(handle, ctypes.byref(creation), ctypes.byref(end),
                                   ctypes.byref(kernel), ctypes.byref(user)):
        raise ctypes.WinError(ctypes.get_last_error())
    return (creation.dwHighDateTime << 32) | creation.dwLowDateTime


def _process_info(pid: int, terminate: bool = False):
    access = 0x00100000 | 0x1000 | (0x0001 if terminate else 0)
    handle = _kernel.OpenProcess(access, False, pid)
    if not handle:
        return None, None
    try:
        created = _process_created(handle)
        return handle, created
    except OSError:
        _kernel.CloseHandle(handle)
        return None, None


def _window_identity(hwnd: int) -> dict:
    if not win32gui.IsWindow(hwnd):
        raise RuntimeError(f"window no longer exists: {hwnd}")
    pid = win32process.GetWindowThreadProcessId(hwnd)[1]
    handle, created = _process_info(pid)
    if handle:
        _kernel.CloseHandle(handle)
    if created is None:
        raise RuntimeError("cannot verify the window owner's process identity")
    return {"hwnd": int(hwnd), "pid": pid, "class": win32gui.GetClassName(hwnd),
            "process_created": created}


def _matches(identity: dict) -> bool:
    try:
        return bool(identity) and _window_identity(int(identity["hwnd"])) == identity
    except (RuntimeError, OSError, KeyError, TypeError, win32gui.error):
        return False


def _process_name(pid: int) -> str:
    handle, _ = _process_info(pid)
    if not handle:
        raise RuntimeError("cannot verify desktop helper executable")
    try:
        capacity = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(capacity.value)
        if not _kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(capacity)):
            raise ctypes.WinError(ctypes.get_last_error())
        return Path(buffer.value).name.lower()
    finally:
        _kernel.CloseHandle(handle)


def _style_visible(hwnd: int) -> bool:
    """Read the window's own visibility bit, independently of parent visibility."""
    return bool(win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE) & win32con.WS_VISIBLE)


def _capture_target(hwnd: int, *, source: bool = False) -> dict:
    identity = _window_identity(hwnd)
    if source:
        title = win32gui.GetWindowText(hwnd)
        name = _process_name(identity["pid"])
        if (identity["class"] != "360DirectUICls" or title != "360DTFenceLite"
                or name not in {"360desktoplite.exe", "360desktoplite64.exe", "360desktoplite32.exe"}):
            raise RuntimeError("extra icon source must be the explicitly identified 360 DesktopLite icon window")
    elif identity["class"] != "SysListView32":
        raise RuntimeError("visibility lease requires an actual SysListView32 window")
    target = {"identity": identity, "original_visible": bool(win32gui.IsWindowVisible(hwnd)),
              "original_style_visible": _style_visible(hwnd),
              "role": "desktoplite" if source else "explorer"}
    if source:
        target.update(title=title, executable=name)
    return target


def _targets(state: dict) -> list[dict]:
    """Read version-two target sets or the original single-ListView state format."""
    if state.get("targets"):
        return state["targets"]
    return [{"identity": state.get("listview", {}),
             "original_visible": bool(state.get("original_visible")), "role": "explorer"}]


def _target_visibility(target: dict) -> bool:
    hwnd = target["identity"]["hwnd"]
    return (_style_visible(hwnd) if "original_style_visible" in target
            else bool(win32gui.IsWindowVisible(hwnd)))


def _visibility_violation(state: dict) -> str | None:
    """Never fight a provider that reasserts visibility; relinquish the whole lease."""
    for target in _targets(state):
        identity = target["identity"]
        if not _matches(identity):
            return f"target_identity_changed:{identity.get('hwnd', 0)}"
        try:
            if _style_visible(identity["hwnd"]):
                return f"target_reshown:{identity['hwnd']}"
        except (OSError, win32gui.error):
            return f"target_query_failed:{identity['hwnd']}"
    return None


def _owner_alive(state: dict) -> bool:
    handle, created = _process_info(int(state.get("owner_pid", 0)))
    if not handle:
        return False
    try:
        return (created == state.get("owner_created") and
                _kernel.WaitForSingleObject(handle, 0) == 0x102)
    finally:
        _kernel.CloseHandle(handle)


def _request_visibility(hwnd: int, command: int) -> None:
    thread_id, _ = win32process.GetWindowThreadProcessId(hwnd)
    if thread_id == _kernel.GetCurrentThreadId():
        win32gui.ShowWindow(hwnd, command)  # Safe: never crosses a message queue.
    else:
        _user.ShowWindowAsync(hwnd, command)


def _restore(state: dict) -> dict:
    """Hide our overlay, then independently restore every exact original painter."""
    targets = _targets(state)
    result = {"overlay_hidden": False, "icons_restored": False,
              "target_results": [{"hwnd": t["identity"].get("hwnd", 0), "restored": False}
                                 for t in targets]}
    overlay = state.get("overlay", {})
    try:
        if _matches(overlay):
            _request_visibility(overlay["hwnd"], win32con.SW_HIDE)
            result["overlay_hidden"] = not bool(win32gui.IsWindowVisible(overlay["hwnd"]))
    except (OSError, win32gui.error) as exc:
        result["overlay_error"] = str(exc)
    for target, recovery in zip(targets, result["target_results"]):
        try:
            identity = target["identity"]
            if _matches(identity):
                wanted = target.get("original_style_visible", target.get("original_visible", False))
                _request_visibility(identity["hwnd"], win32con.SW_SHOWNA if wanted else win32con.SW_HIDE)
                recovery["restored"] = _target_visibility(target) == wanted
            else:
                recovery["skipped"] = "identity_changed"
        except (OSError, win32gui.error) as exc:
            recovery["error"] = str(exc)
    # ShowWindowAsync crosses message queues. Confirm its effect for a bounded
    # interval, without synchronously messaging a possibly frozen window thread.
    deadline = time.monotonic() + 0.4
    while time.monotonic() < deadline:
        try:
            if _matches(overlay):
                result["overlay_hidden"] = not bool(win32gui.IsWindowVisible(overlay["hwnd"]))
            for target, recovery in zip(targets, result["target_results"]):
                try:
                    if _matches(target["identity"]):
                        wanted = target.get("original_style_visible", target.get("original_visible", False))
                        recovery["restored"] = _target_visibility(target) == wanted
                    else:
                        recovery["skipped"] = "identity_changed"
                except (OSError, win32gui.error) as exc:
                    recovery["error"] = str(exc)
            result["icons_restored"] = all(r["restored"] or r.get("skipped")
                                            for r in result["target_results"])
            if _restoration_complete(state, result):
                break
        except (OSError, win32gui.error):
            pass
        time.sleep(0.02)
    return result


def _restoration_complete(state: dict, result: dict) -> bool:
    """An Explorer restart invalidates the lease, never authorizes another HWND."""
    target_results = result.get("target_results")
    targets = _targets(state)
    if target_results is not None:
        restored = len(target_results) == len(targets) and all(
            recovery.get("restored", False) or not _matches(target["identity"])
            for target, recovery in zip(targets, target_results))
    else:
        restored = (result.get("icons_restored", False)
                    or all(not _matches(target["identity"]) for target in targets))
    return (restored
            and (result.get("overlay_hidden", False) or not _matches(state.get("overlay", {}))))


def recover(runtime_dir: Path, force: bool = False) -> bool:
    """Recover a saved inactive lease. A live renderer must exit before manual recovery."""
    path = Path(runtime_dir) / "lease.json"
    state = _read_json(path)
    if not state:
        return False
    if state.get("status") == "released" and _restoration_complete(state, state.get("recovery", {})):
        return False
    if _owner_alive(state) and not force:
        raise RuntimeError("another renderer is still alive; close it before recovery")
    result = _restore(state)
    status = "released" if _restoration_complete(state, result) else "recovery_pending"
    state.update(status=status, released_reason="manual_recovery", recovery=result)
    _atomic_json(path, state)
    return result["icons_restored"]


def session_active(runtime_dir: Path) -> bool:
    """Recognize our live lease before a second launch attempts desktop capture."""
    state = _read_json(Path(runtime_dir) / "lease.json")
    return state.get("status") in ("arming", "active") and _owner_alive(state)


class DesktopLease:
    """Guard temporary ListView visibility with a separate pythonw watchdog.

    No icon location, file, registry value, or Explorer parent relationship is
    changed. The watchdog is ready before the first visibility change occurs.
    """

    HEARTBEAT_INTERVAL = 0.5
    TIMEOUT = 6.0

    def __init__(self, listview_hwnd: int, overlay_hwnd: int, runtime_dir: Path,
                 source_windows: list[int] | None = None) -> None:
        self.listview_hwnd = int(listview_hwnd)
        self.overlay_hwnd = int(overlay_hwnd)
        self.runtime_dir = Path(runtime_dir).resolve()
        self._mutex = None
        self._release_event = None
        self._active_event = None
        self.source_windows = list(dict.fromkeys(int(hwnd) for hwnd in (source_windows or [])
                                                if int(hwnd) != self.listview_hwnd))
        self._watcher: subprocess.Popen | None = None
        self._state: dict = {}
        self._active = False
        self._last_heartbeat = 0.0
        self.token = uuid.uuid4().hex

    def _path(self, kind: str) -> Path:
        return self.runtime_dir / f"{self.token}.{kind}.json"

    def acquire(self) -> None:
        """Start a ready watchdog, then hide only the verified original ListView."""
        if self._active:
            return
        ctypes.set_last_error(0)
        self._mutex = _kernel.CreateMutexW(None, False, _MUTEX)
        if not self._mutex:
            raise ctypes.WinError(ctypes.get_last_error())
        if ctypes.get_last_error() == 183:
            _kernel.CloseHandle(self._mutex)
            self._mutex = None
            raise RuntimeError("another desktop prototype or its recovery guardian is running")
        try:
            self.runtime_dir.mkdir(parents=True, exist_ok=True)
            recover(self.runtime_dir)
            targets = [_capture_target(self.listview_hwnd)]
            targets.extend(_capture_target(hwnd, source=True) for hwnd in self.source_windows)
            original = targets[0]["identity"]
            overlay = _window_identity(self.overlay_hwnd)
            if not targets[0]["original_visible"]:
                raise RuntimeError("desktop icons are already hidden; leave the user's setting unchanged")
            if overlay["pid"] != os.getpid():
                raise RuntimeError("overlay must belong to this renderer process")
            owner, created = _process_info(os.getpid())
            if not owner:
                raise RuntimeError("cannot open the renderer process")
            _kernel.CloseHandle(owner)
            event_name = f"Local\\DesktopKillerRelease_{self.token}"
            self._release_event = _kernel.CreateEventW(None, True, False, event_name)
            if not self._release_event:
                raise ctypes.WinError(ctypes.get_last_error())
            active_name = f"Local\\DesktopKillerActive_{self.token}"
            self._active_event = _kernel.CreateEventW(None, True, False, active_name)
            if not self._active_event:
                raise ctypes.WinError(ctypes.get_last_error())
            self._state = {"version": 2, "token": self.token, "status": "arming",
                "owner_pid": os.getpid(), "owner_created": created,
                "release_event": event_name, "active_event": active_name,
                "targets": targets,
                "listview": original, "overlay": overlay,
                "original_visible": targets[0]["original_visible"],
                "timeout": self.TIMEOUT, "started": time.time()}
            _atomic_json(self.runtime_dir / "lease.json", self._state)
            self._write_heartbeat()
            self._watcher = subprocess.Popen(
                _guardian_command(self.runtime_dir, self.token), stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW, close_fds=True)
            deadline = time.monotonic() + 4.0
            while time.monotonic() < deadline:
                ready = _read_json(self._path("ready"))
                if ready.get("token") == self.token:
                    break
                if self._watcher.poll() is not None:
                    raise RuntimeError("desktop recovery guardian failed before readiness")
                time.sleep(0.025)
            else:
                raise RuntimeError("desktop recovery guardian did not become ready")
            if self._watcher.poll() is not None or any(not _matches(t["identity"]) for t in targets):
                raise RuntimeError("desktop identity changed while starting the guardian")
            self._write_heartbeat()
            for target in targets:
                identity = target["identity"]
                if not _matches(identity):
                    raise RuntimeError("desktop source changed before temporary hiding")
                _request_visibility(identity["hwnd"], win32con.SW_HIDE)
            hide_deadline = time.monotonic() + 0.6
            while _visibility_violation(self._state):
                if time.monotonic() >= hide_deadline:
                    raise RuntimeError("an icon drawing window did not accept temporary hiding")
                time.sleep(0.02)
            self._state["status"] = "active"
            _atomic_json(self.runtime_dir / "lease.json", self._state)
            self._active = True
            if not _kernel.SetEvent(self._active_event):
                raise ctypes.WinError(ctypes.get_last_error())
        except BaseException:
            self.release()
            raise

    def _write_heartbeat(self) -> None:
        _atomic_json(self._path("heartbeat"), {"token": self.token, "at": time.monotonic()})
        self._last_heartbeat = time.monotonic()

    def heartbeat(self) -> None:
        """Refresh liveness; fail closed if the guardian has already restored desktop."""
        if not self._active:
            raise RuntimeError("desktop lease is not active")
        if self._path("done").exists() or self._watcher.poll() is not None:
            self._active = False
            _restore(self._state)
            raise RuntimeError("desktop lease was restored by its guardian")
        if time.monotonic() - self._last_heartbeat >= self.HEARTBEAT_INTERVAL:
            violation = _visibility_violation(self._state)
            if violation:
                self.release()
                raise RuntimeError(f"desktop source changed; visibility lease ended ({violation})")
            self._write_heartbeat()

    def release(self) -> None:
        """Restore visibility synchronously; ask the watchdog to repeat and acknowledge."""
        self._active = False
        try:
            if self._release_event:
                _kernel.SetEvent(self._release_event)
            if self._state:
                result = _restore(self._state)
                # Disk failure must never precede or suppress visibility recovery.
                try:
                    _atomic_json(self._path("release"), {"token": self.token})
                except OSError:
                    pass
                status = "released" if _restoration_complete(self._state, result) else "recovery_pending"
                self._state.update(status=status, released_reason="normal_exit", recovery=result)
                try:
                    _atomic_json(self.runtime_dir / "lease.json", self._state)
                except OSError:
                    pass
                if self._watcher is not None:
                    try:
                        self._watcher.wait(timeout=2.0)
                    except subprocess.TimeoutExpired:
                        # Do not kill the recovery process: it owns the second chance.
                        pass
                self._state = {}
        finally:
            if self._mutex:
                _kernel.CloseHandle(self._mutex)
                self._mutex = None
            if self._release_event:
                _kernel.CloseHandle(self._release_event)
                self._release_event = None
            if self._active_event:
                _kernel.CloseHandle(self._active_event)
                self._active_event = None

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *_):
        self.release()


def _watch(runtime_dir: Path, token: str) -> int:
    state_path = runtime_dir / "lease.json"
    state = _read_json(state_path)
    if state.get("token") != token:
        return 2
    owner, created = _process_info(int(state["owner_pid"]), terminate=True)
    mutex = _kernel.OpenMutexW(0x00100000, False, _MUTEX)
    release_event = (_kernel.OpenEventW(0x00100000, False, state["release_event"])
                     if state.get("release_event") else None)
    active_event = (_kernel.OpenEventW(0x00100000, False, state["active_event"])
                    if state.get("active_event") else None)
    if (not owner or not mutex or created != state["owner_created"]
            or (state.get("release_event") and not release_event)
            or (state.get("active_event") and not active_event)):
        if owner:
            _kernel.CloseHandle(owner)
        if mutex:
            _kernel.CloseHandle(mutex)
        if release_event:
            _kernel.CloseHandle(release_event)
        if active_event:
            _kernel.CloseHandle(active_event)
        return 3
    path = lambda kind: runtime_dir / f"{token}.{kind}.json"
    reason = "guardian_error"
    try:
        _atomic_json(path("ready"), {"token": token, "pid": os.getpid()})
        last_visibility_check = 0.0
        while True:
            if _kernel.WaitForSingleObject(owner, 0) != 0x102:
                reason = "renderer_exit"
                break
            if release_event and _kernel.WaitForSingleObject(release_event, 0) == 0:
                reason = "normal_exit"
                break
            if _read_json(path("release")).get("token") == token:
                reason = "normal_exit"
                break
            pulse = _read_json(path("heartbeat"))
            if pulse.get("token") != token or time.monotonic() - pulse.get("at", 0) > state["timeout"]:
                reason = "heartbeat_timeout"
                break
            now = time.monotonic()
            if now - last_visibility_check >= 0.5:
                last_visibility_check = now
                armed = (_kernel.WaitForSingleObject(active_event, 0) == 0 if active_event
                         else _read_json(state_path).get("status") == "active")
                if armed:
                    violation = _visibility_violation(state)
                    if violation:
                        reason = violation
                        break
                elif any(not _matches(t["identity"]) for t in _targets(state)):
                    reason = "desktop_changed_while_arming"
                    break
            time.sleep(0.1)
    finally:
        try:
            if reason == "heartbeat_timeout":
                # This handle was opened for exactly the renderer PID + creation
                # time before readiness. It cannot be reused for Explorer or a
                # later process. Destroying a hung renderer also removes its
                # stale layered pixels before the desktop icons reappear.
                _kernel.TerminateProcess(owner, 121)
                _kernel.WaitForSingleObject(owner, 1500)
            result = _restore(state)
            current = _read_json(state_path)
            if current.get("token") == token:
                status = "released" if _restoration_complete(state, result) else "recovery_pending"
                state.update(status=status, released_reason=reason, recovery=result)
                _atomic_json(state_path, state)
            _atomic_json(path("done"), {"token": token, "reason": reason, "recovery": result})
        finally:
            _kernel.CloseHandle(owner)
            _kernel.CloseHandle(mutex)
            if release_event:
                _kernel.CloseHandle(release_event)
            if active_event:
                _kernel.CloseHandle(active_event)
    return 0


def _guardian_command(runtime_dir: Path, token: str) -> list[str]:
    """Use a dedicated frozen entry point rather than reopening the game."""
    if getattr(sys, "frozen", False):
        return [sys.executable, "--guardian", "--watch", str(runtime_dir), token]
    executable = Path(sys.executable)
    pythonw = executable.with_name("pythonw.exe")
    if pythonw.is_file():
        executable = pythonw
    return [str(executable), str(Path(__file__).resolve()), "--watch", str(runtime_dir), token]


def guardian_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--watch", nargs=2, metavar=("RUNTIME_DIR", "TOKEN"))
    arguments = parser.parse_args(argv)
    if arguments.watch:
        return _watch(Path(arguments.watch[0]), arguments.watch[1])
    parser.error("--watch is required for the recovery process")
    return 2


if __name__ == "__main__":
    raise SystemExit(guardian_main())
