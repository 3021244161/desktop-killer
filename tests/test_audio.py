"""Audio is optional, bounded, and never touches a real audio device in tests."""
from array import array

import pygame
import pytest

from desktop_world import audio


class Channel:
    def __init__(self, sound):
        self.sound = sound
        self.busy = True
        self.stops = 0

    def get_busy(self):
        return self.busy

    def get_sound(self):
        return self.sound if self.busy else None

    def stop(self):
        self.stops += 1
        self.busy = False


class Sound:
    def __init__(self, mixer, buffer):
        self.mixer, self.buffer = mixer, buffer

    def play(self):
        if self.mixer.fail_play:
            raise pygame.error("device disconnected")
        channel = Channel(self)
        self.mixer.played.append(channel)
        return channel


class Mixer:
    def __init__(self, initialized=False, fail_init=False):
        self.settings = (22050, -16, 2) if initialized else None
        self.fail_init, self.fail_play = fail_init, False
        self.inits, self.quits = 0, 0
        self.played = []
        self.sounds = []

    def get_init(self):
        return self.settings

    def init(self, **kwargs):
        self.inits += 1
        if self.fail_init:
            raise pygame.error("no audio device")
        self.settings = (kwargs["frequency"], kwargs["size"], kwargs["channels"])

    def quit(self):
        self.quits += 1
        self.settings = None

    def Sound(self, *, buffer):
        sound = Sound(self, buffer)
        self.sounds.append(sound)
        return sound


@pytest.fixture
def device(monkeypatch):
    mixer, clock = Mixer(), [0.0]
    monkeypatch.setattr(audio.pygame, "mixer", mixer)
    monkeypatch.setattr(audio.time, "monotonic", lambda: clock[0])
    return mixer, clock


def test_muted_start_is_lazy_and_muting_stops_current_feedback(device):
    mixer, clock = device
    bank = audio.SoundBank(muted=True)
    assert mixer.inits == 0 and not bank.play("shoot")
    bank.set_muted(False)
    assert mixer.inits == 1 and bank.available and bank.play("shoot")
    bank.set_muted(True)
    assert mixer.played[0].stops == 1 and not bank.play("victory")
    bank.close()
    bank.close()
    assert mixer.quits == 1
    bank.set_muted(False)
    assert not bank.play("shoot") and mixer.inits == 1


def test_missing_or_lost_audio_device_degrades_to_silence(monkeypatch):
    mixer = Mixer(fail_init=True)
    monkeypatch.setattr(audio.pygame, "mixer", mixer)
    bank = audio.SoundBank()
    assert not bank.available and not bank.play("shoot")
    bank.set_muted(True)
    bank.set_muted(False)
    assert mixer.inits == 1  # no repeated driver errors every frame
    working = Mixer()
    monkeypatch.setattr(audio.pygame, "mixer", working)
    bank = audio.SoundBank()
    working.fail_play = True
    assert not bank.play("hurt") and not bank.available and working.quits == 1


def test_per_event_and_global_limits_keep_critical_feedback_audible(device):
    mixer, clock = device
    bank = audio.SoundBank()
    assert bank.play("shoot")
    clock[0] = .01
    assert not bank.play("shoot") and not bank.play("hit")
    assert bank.play("hurt")  # important feedback bypasses the global limiter
    clock[0] = .05
    assert not bank.play("shoot")
    clock[0] = .1
    assert bank.play("shoot")
    assert not bank.play("unknown-event")
    assert len(mixer.played) == 3


def test_victory_replaces_combat_sounds_and_normal_polyphony_is_bounded(device):
    mixer, clock = device
    bank = audio.SoundBank()
    for index, name in enumerate(("shoot", "hit", "kill", "reboot")):
        clock[0] = index * .1
        assert bank.play(name)
    clock[0] = .5
    assert not bank.play("dash")
    assert bank.play("victory")
    assert all(channel.stops == 1 for channel in mixer.played[:-1])
    assert len(bank._channels) == 1


def test_borrowed_mixer_and_reused_channels_are_not_stopped(device):
    mixer, _ = device
    mixer.settings = (22050, -16, 1)
    bank = audio.SoundBank()
    assert bank.play("shoot")
    old_channel = mixer.played[0]
    old_channel.sound = object()  # another component reused this free channel
    bank.close()
    assert old_channel.stops == 0 and mixer.quits == 0


def test_all_feedback_has_nonzero_quiet_pcm_and_faded_boundaries(device):
    mixer, _ = device
    bank = audio.SoundBank()
    expected = {"shoot", "hit", "kill", "reboot", "seal", "upgrade", "hurt",
                "dash", "boss", "victory", "defeat"}
    assert set(bank._sounds) == expected
    for sound in mixer.sounds:
        values = array("h", sound.buffer)
        assert len(values) % 2 == 0
        assert 0 < max(abs(value) for value in values) <= round(.19 * 32767)
        assert values[0] == values[1] == values[-1] == values[-2] == 0
