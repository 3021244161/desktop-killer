"""Quiet, synthesized arcade feedback that remains optional on every machine."""
from __future__ import annotations

from array import array
import logging
import math
import random
import time

import pygame


# Each segment is (start Hz, end Hz, seconds, noise fraction).
_SOUNDS = {
    "shoot": ((1120, 670, .045, .03),),
    "hit": ((200, 90, .065, .35),),
    "kill": ((660, 880, .06, 0), (990, 1320, .07, 0)),
    "reboot": ((520, 260, .11, .03), (390, 520, .11, 0)),
    "seal": ((392, 392, .08, 0), (523, 523, .08, 0), (784, 784, .12, 0)),
    "upgrade": ((523, 523, .07, 0), (659, 659, .07, 0),
                (784, 784, .07, 0), (1047, 1047, .13, 0)),
    "hurt": ((230, 80, .17, .28),),
    "dash": ((280, 1080, .1, .13),),
    "boss": ((98, 98, .13, .07), (123, 123, .13, .07), (98, 98, .16, .07)),
    "victory": ((523, 523, .12, 0), (659, 659, .12, 0),
                (784, 784, .12, 0), (1047, 1047, .3, 0)),
    "defeat": ((392, 392, .16, .04), (311, 311, .16, .04), (196, 147, .3, .03)),
}
_INTERVAL = {"shoot": .09, "hit": .08, "kill": .1, "reboot": .22,
             "seal": .25, "upgrade": .25, "hurt": .18, "dash": .14,
             "boss": 1.0, "victory": 1.0, "defeat": 1.0}
_IMPORTANT = {"upgrade", "hurt", "boss", "victory", "defeat", "seal"}


def _synthesize(name: str, frequency: int, channels: int) -> bytes:
    """Generate signed 16-bit PCM, with fades to avoid sharp sample boundaries."""
    samples = array("h")
    random_source = random.Random(name)
    phase = 0.0
    for first, last, duration, noise in _SOUNDS[name]:
        count = max(2, round(frequency * duration))
        for index in range(count):
            position = index / (count - 1)
            hz = first + (last - first) * position
            phase += 2 * math.pi * hz / frequency
            attack = min(1.0, index / max(1, frequency * .004))
            release = min(1.0, (count - 1 - index) / max(1, frequency * .025))
            wave = .78 * math.sin(phase) + .22 * math.sin(phase * 2)
            wave = wave * (1 - noise) + random_source.uniform(-1, 1) * noise
            value = round(wave * attack * release * .19 * 32767)
            samples.extend([value] * channels)
    return samples.tobytes()


class SoundBank:
    """A failed audio device disables sound without interrupting a desktop lease."""

    def __init__(self, muted: bool = False) -> None:
        self.muted = bool(muted)
        self.available = False
        self._closed = False
        self._owns_mixer = False
        self._sounds = {}
        self._channels = []
        self._last_play = {}
        self._last_any = -math.inf
        self._attempted = False
        if not self.muted:
            self._initialize()

    def _initialize(self) -> None:
        if self._closed or self._attempted:
            return
        self._attempted = True
        try:
            settings = pygame.mixer.get_init()
            if settings is None:
                pygame.mixer.init(frequency=22050, size=-16, channels=2, buffer=512)
                self._owns_mixer = True
                settings = pygame.mixer.get_init()
            if not settings or settings[1] != -16 or settings[2] not in (1, 2):
                raise ValueError("unsupported shared audio sample format")
            frequency, _, channels = settings
            self._sounds = {name: pygame.mixer.Sound(buffer=_synthesize(name, frequency, channels))
                            for name in _SOUNDS}
            self.available = True
        except Exception as exc:
            logging.info("Sound disabled: %s", exc)
            self._disable()

    def _stop_channels(self) -> None:
        for channel, sound in self._channels:
            try:
                if channel.get_sound() is sound:
                    channel.stop()
            except Exception:
                pass
        self._channels.clear()

    def _disable(self) -> None:
        self.available = False
        self._stop_channels()
        self._sounds.clear()
        if self._owns_mixer:
            try:
                pygame.mixer.quit()
            except Exception:
                pass
            self._owns_mixer = False

    def play(self, name: str) -> bool:
        """Play when enabled and below per-event/global limits; unknown names are safe."""
        if self._closed or self.muted or not self.available or name not in self._sounds:
            return False
        now = time.monotonic()
        if now - self._last_play.get(name, -math.inf) < _INTERVAL[name]:
            return False
        if name not in _IMPORTANT and now - self._last_any < .025:
            return False
        try:
            self._channels = [(channel, sound) for channel, sound in self._channels
                              if channel.get_busy() and channel.get_sound() is sound]
            if name in ("victory", "defeat"):
                self._stop_channels()
            elif len(self._channels) >= 4 and name not in _IMPORTANT:
                return False
            sound = self._sounds[name]
            channel = sound.play()
            if channel is None:
                return False
            self._channels.append((channel, sound))
            self._last_play[name] = self._last_any = now
            return True
        except Exception as exc:
            logging.info("Sound disabled during playback: %s", exc)
            self._disable()
            return False

    def set_muted(self, muted: bool) -> None:
        self.muted = bool(muted)
        if self.muted:
            self._stop_channels()
        elif not self.available:
            self._initialize()

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._disable()
