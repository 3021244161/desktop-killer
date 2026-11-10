"""Quiet, synthesized arcade feedback that remains optional on every machine."""
from __future__ import annotations

from array import array
from functools import lru_cache
import logging
import math
from pathlib import Path
import random
import time
import wave

import numpy as np
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

# Original compositions: eight / sixteen bars with four-bar melodic variations.
# These are code-generated instruments, not samples from another soundtrack.
MUSIC_TRACKS = {
    "menu": {"title": "桌面醒来之前", "bpm": 92, "bars": 8},
    "drawing": {"title": "给图标放个假", "bpm": 80, "bars": 8},
    "battle": {"title": "快捷方式暴走", "bpm": 128, "bars": 16},
    "boss": {"title": "最后一个进程", "bpm": 144, "bars": 16},
}
_MUSIC_FADE_SECONDS = .65


@lru_cache(maxsize=12)
def generate_music_pcm(context: str, frequency: int = 22050, channels: int = 2) -> bytes:
    """Return an original, seamless signed-16-bit loop; never opens an audio device.

    The four arrangements last 20.87, 24, 30 and 26.67 seconds. Generation is
    cached and performed by SoundBank before desktop handover, never per frame.
    """
    if context not in MUSIC_TRACKS:
        raise ValueError(f"unknown music context: {context}")
    if frequency < 8000 or frequency > 96000 or channels not in (1, 2):
        raise ValueError("music requires 8–96 kHz mono or stereo PCM")
    config = MUSIC_TRACKS[context]
    beat = 60.0 / config["bpm"]
    bars = config["bars"]
    count = round(frequency * bars * 4 * beat)
    mix = np.zeros((count, 2), dtype=np.float32)
    melody = np.zeros_like(mix)
    rng = np.random.default_rng({"menu": 2101, "drawing": 7103,
                                 "battle": 4409, "boss": 9011}[context])
    tone_cache = {}

    def tone(note, duration, kind):
        key = (note, round(duration, 6), kind)
        if key in tone_cache:
            return tone_cache[key]
        length = max(4, round(duration * frequency))
        t = np.arange(length, dtype=np.float32) / frequency
        hz = 440.0 * 2 ** ((note - 69) / 12)
        phase = t * (2 * np.pi * hz)
        signal = np.sin(phase)
        if kind == "pad":
            signal = .72 * signal + .18 * np.sin(phase * 1.003) + .10 * np.sin(2 * phase)
            attack, release, decay = .11, .20, .15
        elif kind == "bell":
            signal = .72 * signal + .20 * np.sin(2 * phase) + .08 * np.sin(3 * phase)
            attack, release, decay = .006, .10, 4.2
        elif kind == "bass":
            signal = .85 * signal + .12 * np.sin(3 * phase) / 3 + .03 * np.sin(5 * phase)
            attack, release, decay = .006, .035, 1.0
        else:
            # Rounded pulse: finite harmonics keep the chip voice gentle and clean.
            for harmonic, gain in ((3, .16), (5, .055), (7, .025)):
                if hz * harmonic < frequency * .43:
                    signal += gain * np.sin(harmonic * phase)
            signal *= .80
            attack, release, decay = .007, .045, 1.5
        envelope = np.minimum(1, t / attack) * np.minimum(
            1, (length - 1 - np.arange(length)) / (frequency * release))
        envelope *= np.exp(-t * decay)
        result = (signal * envelope).astype(np.float32)
        tone_cache[key] = result
        return result

    def add(bus, signal, at, gain, pan=0.0):
        # Wrap instrument tails into the beginning, including the last-bar echo.
        start = round(at * frequency) % count
        stereo = signal[:, None] * np.array(
            [math.cos((pan + 1) * math.pi / 4), math.sin((pan + 1) * math.pi / 4)],
            dtype=np.float32)[None, :] * gain
        first = min(len(signal), count - start)
        bus[start:start + first] += stereo[:first]
        if first < len(signal):
            bus[:len(signal) - first] += stereo[first:]

    drum_cache = {}

    def drum(kind):
        if kind in drum_cache:
            return drum_cache[kind]
        duration = {"kick": .24, "snare": .15, "hat": .055, "open": .15}[kind]
        t = np.arange(round(duration * frequency), dtype=np.float32) / frequency
        noise = rng.uniform(-1, 1, len(t)).astype(np.float32)
        if kind == "kick":
            phase = 2 * np.pi * (48 * t + 100 * .028 * (1 - np.exp(-t / .028)))
            signal = np.sin(phase) * np.exp(-t * 19) + noise * np.exp(-t * 240) * .08
        elif kind == "snare":
            high = noise - np.roll(noise, 1) * .65
            signal = .65 * high * np.exp(-t * 30) + .25 * np.sin(2 * np.pi * 185 * t) * np.exp(-t * 40)
        else:
            high = noise - np.roll(noise, 1)
            signal = .36 * high * np.exp(-t * (70 if kind == "hat" else 25))
        edge = min(64, len(t) // 4)
        signal[:edge] *= np.linspace(0, 1, edge)
        signal[-edge:] *= np.linspace(1, 0, edge)
        drum_cache[kind] = signal.astype(np.float32)
        return drum_cache[kind]

    roots, thirds = {
        "menu": ([48, 45, 41, 43], [4, 3, 4, 4]),
        "drawing": ([53, 50, 46, 48], [4, 3, 4, 4]),
        "battle": ([45, 41, 48, 43], [3, 4, 4, 4]),
        "boss": ([40, 36, 33, 35], [3, 4, 3, 4]),
    }[context]
    calm = context in ("menu", "drawing")
    motifs = {
        "menu": ((12, 7, 4, 7, 14, 12, 7, 4), (7, 12, 16, 14, 12, 7, 4, 7)),
        "drawing": ((12, 16, 19, 16, 14, 12, 7, 12), (19, 16, 12, 7, 12, 14, 16, 12)),
        "battle": ((12, 7, 12, 15, 19, 15, 14, 7), (19, 15, 12, 7, 14, 15, 19, 22)),
        "boss": ((12, 7, 12, 15, 19, 20, 19, 11), (24, 19, 15, 12, 11, 15, 19, 23)),
    }[context]
    for bar in range(bars):
        chord = bar % 4
        root, third = roots[chord], thirds[chord]
        at = bar * 4 * beat
        phrase = bar // 4
        # Change inversions on the answering phrase, keeping harmony consistent.
        notes = [root + 12, root + third + 12, root + 19]
        if phrase % 2:
            notes[0] += 12
        for index, note in enumerate(notes):
            add(mix, tone(note, 4.12 * beat, "pad"), at,
                .085 if calm else .065, (-.50, .05, .50)[index])
        bass_beats = (0, 2, 3.5) if calm else (0, .75, 1.5, 2, 2.75, 3.5)
        for index, step in enumerate(bass_beats):
            bass_note = root - 12 + (7 if index == len(bass_beats) - 1 and bar % 2 else 0)
            add(mix, tone(bass_note, beat * (.72 if calm else .48), "bass"),
                at + step * beat, .18 if calm else .26)
        motif = motifs[phrase % 2]
        for step, offset in enumerate(motif):
            if (calm and step in (3, 7)) or (not calm and (bar + step) % 7 == 4):
                continue
            # Transpose the phrase with its chord; use the actual chord third.
            if offset in (4, 16) and third == 3:
                offset -= 1
            if offset == 15 and third == 4:
                offset += 1
            note = root + offset + (12 if context == "drawing" else 0)
            add(melody, tone(note, beat * (.78 if calm else .40),
                             "bell" if calm else "lead"),
                at + step * .5 * beat,
                (.115 if calm else .13) * (1 if step % 2 == 0 else .82),
                .20 if bar % 2 else -.20)
        if calm:
            for step in (0, 2):
                add(mix, drum("kick"), at + step * beat, .075)
            for step in (.5, 1.5, 2.5, 3.5):
                add(mix, drum("hat"), at + step * beat, .025, .35)
            if context == "menu":
                add(mix, drum("snare"), at + 3 * beat, .045, -.15)
        else:
            for step in ((0, 1.5, 2, 2.75) if context == "battle" else (0, .75, 1.5, 2, 3)):
                add(mix, drum("kick"), at + step * beat, .29)
            for step in (1, 3):
                add(mix, drum("snare"), at + step * beat, .20, -.12)
            hat_steps = 8 if context == "battle" else 16
            for step in range(hat_steps):
                add(mix, drum("open" if step == hat_steps - 1 else "hat"),
                    at + step * 4 / hat_steps * beat,
                    .065 if step % 2 else .045, .35)
            if bar % 4 == 3:
                for step in (3.25, 3.5, 3.75):
                    add(mix, drum("snare"), at + step * beat, .09 + (step - 3) * .07, -.25)
            if phrase >= 2 and bar % 2:
                add(melody, tone(root + 31, beat * .28, "bell"),
                    at + 3.75 * beat, .10, -.40)
    mix += melody
    for delay, gain in ((.75, .16), (1.5, .07)):
        mix += np.roll(melody[:, ::-1], round(delay * beat * frequency), axis=0) * gain
    # Gentle limiting, generous headroom, and an exact zero-crossing loop splice.
    np.tanh(mix * 1.25, out=mix)
    limit = .42 if calm else .55
    peak = float(np.max(np.abs(mix)))
    if peak > limit:
        mix *= limit / peak
    edge = min(round(frequency * .006), count // 4)
    mix[:edge] *= np.linspace(0, 1, edge, dtype=np.float32)[:, None]
    mix[-edge:] *= np.linspace(1, 0, edge, dtype=np.float32)[:, None]
    if channels == 1:
        mix = mix.mean(axis=1)
    return np.rint(mix * 32767).astype("<i2").tobytes()


def export_music_previews(destination: Path, frequency: int = 22050,
                          channels: int = 2) -> list[Path]:
    """Export full unattenuated loops for offline listening; does not play audio."""
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    paths = []
    for context in MUSIC_TRACKS:
        path = destination / f"{context}.wav"
        with wave.open(str(path), "wb") as output:
            output.setnchannels(channels)
            output.setsampwidth(2)
            output.setframerate(frequency)
            output.writeframes(generate_music_pcm(context, frequency, channels))
        paths.append(path)
    return paths


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
        self.music_available = False
        self._sfx_pool = []
        self._music_channels = []
        self._music_sounds = {}
        self._music_contexts = [None, None]
        self._music_levels = [0.0, 0.0]
        self._music_targets = [0.0, 0.0]
        self._music_paused = False
        self._context_paused = False
        self._music_requested = None
        self._music_pcm = {}
        self._prepared_format = (22050, -16, 2)
        before = time.perf_counter()
        try:
            settings = pygame.mixer.get_init()
            if settings and settings[1] == -16 and settings[2] in (1, 2):
                self._prepared_format = settings
            frequency, _, channels = self._prepared_format
            self._music_pcm = {name: generate_music_pcm(name, frequency, channels)
                               for name in MUSIC_TRACKS}
        except Exception as exc:
            logging.info("Music composition unavailable: %s", exc)
        self.music_generation_seconds = time.perf_counter() - before
        if not self.muted:
            self._initialize()

    def _initialize(self) -> None:
        if self._closed or self._attempted:
            return
        self._attempted = True
        try:
            settings = pygame.mixer.get_init()
            if settings is None:
                pygame.mixer.init(frequency=22050, size=-16, channels=2, buffer=512,
                                  allowedchanges=0)
                self._owns_mixer = True
                settings = pygame.mixer.get_init()
            if not settings or settings[1] != -16 or settings[2] not in (1, 2):
                raise ValueError("unsupported shared audio sample format")
            frequency, _, channels = settings
            self._sounds = {name: pygame.mixer.Sound(buffer=_synthesize(name, frequency, channels))
                            for name in _SOUNDS}
            # Append channels: never borrow a channel already owned by another
            # mixer user, change global reservations, or use automatic Sound.play.
            start = pygame.mixer.get_num_channels()
            pygame.mixer.set_num_channels(start + 8)
            self._sfx_pool = [pygame.mixer.Channel(start + index) for index in range(6)]
            self._music_channels = [pygame.mixer.Channel(start + index) for index in (6, 7)]
            if settings == self._prepared_format and self._music_pcm:
                self._music_sounds = {
                    name: pygame.mixer.Sound(buffer=pcm) for name, pcm in self._music_pcm.items()}
                self.music_available = True
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
        self._stop_music()
        self._sfx_pool.clear()
        self._sounds.clear()
        if self._owns_mixer:
            try:
                pygame.mixer.quit()
            except Exception:
                pass
            self._owns_mixer = False

    def play(self, name: str) -> bool:
        """Play when enabled and below per-event/global limits; unknown names are safe."""
        if (self._closed or self.muted or self._context_paused or not self.available
                or name not in self._sounds):
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
            channel = next((candidate for candidate in self._sfx_pool
                            if not candidate.get_busy()), None)
            if channel is None and name in _IMPORTANT:
                # Critical cues may replace only our own oldest sound.
                channel = next((candidate for candidate, previous in self._channels
                                if candidate.get_sound() is previous), None)
            if channel is None:
                return False
            self._channels = [(old_channel, old_sound) for old_channel, old_sound in self._channels
                              if old_channel is not channel]
            channel.play(sound)
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
            try:
                self._pause_music()
            except Exception:
                self._stop_music()
        elif not self.available:
            self._initialize()

    def _owns_music_channel(self, index: int) -> bool:
        context = self._music_contexts[index]
        return (context is not None and
                self._music_channels[index].get_sound() is self._music_sounds.get(context))

    def _pause_music(self) -> None:
        for index, channel in enumerate(self._music_channels):
            if self._owns_music_channel(index):
                channel.set_volume(0)
                channel.pause()
        self._music_paused = True

    def _stop_music(self) -> None:
        for index, channel in enumerate(self._music_channels):
            try:
                if self._owns_music_channel(index):
                    channel.stop()
            except Exception:
                pass
        self._music_contexts = [None, None]
        self._music_levels = [0.0, 0.0]
        self._music_targets = [0.0, 0.0]
        self._music_channels.clear()
        self._music_sounds.clear()
        self.music_available = False

    def update_music(self, context: str | None, dt: float, paused: bool = False,
                     enabled: bool = True, volume: float = .35,
                     suspended: bool = False) -> bool:
        """Update looping music without synthesis or device initialization.

        Contexts: menu, drawing, battle, boss. Campaign/blitz/endless alias battle;
        None fades to silence. Call on every frame, including focus loss. Paused
        suspends music only, leaving upgrade/result cues audible. Suspended stops
        all sound for focus loss or explicit pause. Enabled/volume affect music
        only; mute is global. Resuming preserves position, never restarts.
        """
        self._context_paused = bool(suspended)
        if suspended:
            self._stop_channels()
        if self._closed or not self.available or not self.music_available:
            return False
        try:
            volume = float(volume)
            volume = max(0.0, min(1.0, volume)) if math.isfinite(volume) else .35
            dt = float(dt)
            dt = max(0.0, min(1.0, dt)) if math.isfinite(dt) else 0.0
            if self.muted or paused or suspended or not enabled or volume == 0:
                if not self._music_paused:
                    self._pause_music()
                return False
            context = {"campaign": "battle", "blitz": "battle", "endless": "battle"}.get(
                context, context)
            if context not in self._music_sounds:
                context = None
            if self._music_paused:
                for index, channel in enumerate(self._music_channels):
                    if self._owns_music_channel(index):
                        # Gain is restored below after paused scene changes apply.
                        channel.unpause()
                self._music_paused = False
            # A foreign automatic mixer user can take an idle appended channel.
            # Detect that before touching it, and stop only our remaining music.
            for index, channel in enumerate(self._music_channels):
                current = channel.get_sound()
                if current is not None and not self._owns_music_channel(index):
                    self._stop_music()
                    return False
                if current is None and self._music_contexts[index] is not None:
                    self._music_contexts[index] = None
                    self._music_levels[index] = 0.0
            if context != self._music_requested or (context and context not in self._music_contexts):
                self._music_requested = context
                if context is None:
                    self._music_targets = [0.0, 0.0]
                else:
                    if context in self._music_contexts:
                        chosen = self._music_contexts.index(context)
                    else:
                        chosen = min(range(2), key=lambda index: self._music_levels[index])
                        channel = self._music_channels[chosen]
                        # Native fade prevents any initial buffer at full volume
                        # before the explicit crossfade gain is applied.
                        channel.play(self._music_sounds[context], loops=-1, fade_ms=30)
                        channel.set_volume(0)
                        self._music_contexts[chosen] = context
                        self._music_levels[chosen] = 0.0
                    self._music_targets = [1.0 if index == chosen else 0.0 for index in range(2)]
            step = dt / _MUSIC_FADE_SECONDS
            for index, channel in enumerate(self._music_channels):
                if not self._owns_music_channel(index):
                    continue
                level, target = self._music_levels[index], self._music_targets[index]
                level = min(target, level + step) if level < target else max(target, level - step)
                self._music_levels[index] = level
                channel.set_volume(level * volume)
                if level == 0 and target == 0:
                    channel.stop()
                    self._music_contexts[index] = None
            return context is not None
        except Exception as exc:
            logging.info("Music disabled during playback: %s", exc)
            self._stop_music()
            return False

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._disable()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Export Desktop Killer's original music loops")
    parser.add_argument("--export-music", type=Path, required=True)
    options = parser.parse_args()
    started = time.perf_counter()
    for preview in export_music_previews(options.export_music):
        print(preview)
    print(f"Generated in {time.perf_counter() - started:.3f}s; no audio device opened.")
