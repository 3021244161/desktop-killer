"""Process-owned high-resolution Windows frame timer, without busy waiting."""
import ctypes
from ctypes import wintypes
import math
import time


class FramePacer:
    def __init__(self) -> None:
        self._kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self._kernel.CreateWaitableTimerExW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR,
                                                       wintypes.DWORD, wintypes.DWORD]
        self._kernel.CreateWaitableTimerExW.restype = wintypes.HANDLE
        self._kernel.SetWaitableTimer.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_longlong),
                                                  wintypes.LONG, ctypes.c_void_p, ctypes.c_void_p, wintypes.BOOL]
        self._kernel.SetWaitableTimer.restype = wintypes.BOOL
        self._kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self._kernel.WaitForSingleObject.restype = wintypes.DWORD
        self._kernel.CancelWaitableTimer.argtypes = [wintypes.HANDLE]
        self._kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self._timer = self._kernel.CreateWaitableTimerExW(None, None, 0x2, 0x001F0003)
        self._requested = False
        self.backend = "high-resolution-waitable-timer" if self._timer else "sleep-with-timer-period"
        if self._timer:
            return
        self._winmm = ctypes.WinDLL("winmm")
        self._winmm.timeBeginPeriod.argtypes = [ctypes.c_uint]
        self._winmm.timeEndPeriod.argtypes = [ctypes.c_uint]
        self._requested = self._winmm.timeBeginPeriod(1) == 0

    def wait_until(self, deadline: float) -> None:
        remaining = deadline - time.perf_counter()
        if remaining > 0:
            if self._timer:
                due = ctypes.c_longlong(-max(1, math.ceil(remaining * 10_000_000)))
                if self._kernel.SetWaitableTimer(self._timer, ctypes.byref(due), 0, None, None, False):
                    result = self._kernel.WaitForSingleObject(self._timer, max(1, math.ceil(remaining * 1000) + 50))
                    if result == 0:
                        return
                # Timer failure must not freeze the game or interrupt restoration.
                remaining = deadline - time.perf_counter()
            if remaining > 0:
                time.sleep(remaining)

    def close(self) -> None:
        if self._timer:
            self._kernel.CancelWaitableTimer(self._timer)
            self._kernel.CloseHandle(self._timer)
            self._timer = None
        if self._requested:
            self._winmm.timeEndPeriod(1)
            self._requested = False
