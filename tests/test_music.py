"""Offline composition and playback contracts; never opens the host audio device."""
from pathlib import Path
import subprocess
import sys
import wave

import numpy as np
import pygame
import pytest

from desktop_world import audio


class FakeSound:
    def __init__(self, buffer):
        self.buffer = buffer

    def play(self, *args, **kwargs):
        raise AssertionError("automatic channel allocation can interrupt music")


class FakeChannel:
    def __init__(self, device):
        self.device = device
        self.sound = None
        self.volume = 1.0
        self.paused = False
        self.starts = self.stops = 0
        self.loops = 0

    def play(self, sound, loops=0, fade_ms=0):
        if self.device.failed:
            raise pygame.error("lost device")
        self.sound, self.loops = sound, loops
        self.paused = False
        self.volume = 1.0
        self.starts += 1

    def get_sound(self):
        return self.sound

    def get_busy(self):
        return self.sound is not None

    def set_volume(self, value):
        if self.device.failed:
            raise pygame.error("lost device")
        self.volume = value

    def pause(self):
        self.paused = True

    def unpause(self):
        self.paused = False

    def stop(self):
        self.sound = None
        self.stops += 1


class FakeMixer:
    def __init__(self, borrowed=False, fail_init=False):
        self.settings = (22050, -16, 2) if borrowed else None
        self.channels = [FakeChannel(self) for _ in range(8)]
        self.inits = self.quits = 0
        self.failed = False
        self.fail_init = fail_init

    def get_init(self):
        return self.settings

    def init(self, **kwargs):
        self.inits += 1
        if self.fail_init:
            raise pygame.error("no device")
        self.settings = (kwargs["frequency"], kwargs["size"], kwargs["channels"])

    def quit(self):
        self.quits += 1
        self.settings = None

    def get_num_channels(self):
        return len(self.channels)

    def set_num_channels(self, count):
        assert count >= len(self.channels), "never remove external mixer channels"
        self.channels.extend(FakeChannel(self) for _ in range(count - len(self.channels)))

    def Channel(self, index):
        return self.channels[index]

    def Sound(self, *, buffer):
        return FakeSound(buffer)

    def set_reserved(self, count):
        raise AssertionError("do not change global mixer channel reservations")


@pytest.fixture
def device(monkeypatch):
    mixer = FakeMixer()
    monkeypatch.setattr(audio.pygame, "mixer", mixer)
    return mixer


def active_music(bank):
    return [channel for channel in bank._music_channels
            if channel.get_sound() in bank._music_sounds.values()]


@pytest.mark.parametrize("context", audio.MUSIC_TRACKS)
def test_compositions_are_quiet_seamless_stereo_and_have_phrase_variation(context):
    config = audio.MUSIC_TRACKS[context]
    pcm = audio.generate_music_pcm(context)
    samples = np.frombuffer(pcm, dtype="<i2").reshape(-1, 2)
    assert 16 <= len(samples) / 22050 <= 32
    assert 1000 < np.max(np.abs(samples.astype(np.int32))) <= round(.55 * 32767)
    assert np.all(samples[[0, -1]] == 0)
    # Both the splice and its adjacent slopes are quiet, including stereo tails.
    boundary = np.concatenate((samples[-8:], samples[:8])).astype(np.int32)
    assert np.max(np.abs(np.diff(boundary, axis=0))) < 180
    assert np.sqrt(np.mean(samples.astype(np.float32) ** 2)) > 500
    assert np.mean(np.abs(samples[:, 0].astype(float) - samples[:, 1])) > 100
    phrase = round(16 * 60 / config["bpm"] * 22050)
    first, answer = samples[:phrase], samples[phrase:phrase * 2]
    size = min(len(first), len(answer))
    assert np.mean(np.abs(first[:size].astype(float) - answer[:size])) > 250
    assert audio.generate_music_pcm(context) is pcm


def test_pcm_export_is_exact_and_requires_no_mixer(tmp_path, monkeypatch):
    class NoDevice:
        def __getattr__(self, key):
            raise AssertionError("offline WAV export must not touch the mixer")
    monkeypatch.setattr(audio.pygame, "mixer", NoDevice())
    paths = audio.export_music_previews(tmp_path, frequency=11025, channels=1)
    assert {path.stem for path in paths} == set(audio.MUSIC_TRACKS)
    for path in paths:
        with wave.open(str(path), "rb") as wav:
            assert (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) == (1, 2, 11025)
            assert wav.readframes(wav.getnframes()) == audio.generate_music_pcm(path.stem, 11025, 1)


def test_repeated_updates_continue_one_loop_and_never_generate_on_frame(device, monkeypatch):
    bank = audio.SoundBank()
    assert bank.available and bank.music_available
    def forbidden(*args, **kwargs):
        raise AssertionError("generation belongs before desktop handover")
    monkeypatch.setattr(audio, "generate_music_pcm", forbidden)
    for _ in range(240):
        assert bank.update_music("menu", 1 / 60)
    channels = active_music(bank)
    assert len(channels) == 1 and channels[0].starts == 1
    assert channels[0].loops == -1 and channels[0].volume == pytest.approx(.35)
    bank.close()


def test_context_crossfade_is_bounded_and_retiring_loop_stops(device):
    bank = audio.SoundBank()
    bank.update_music("menu", 1)
    old = active_music(bank)[0]
    bank.update_music("battle", .325)
    channels = active_music(bank)
    assert len(channels) == 2
    assert [channel.volume for channel in channels] == pytest.approx([.175, .175])
    bank.update_music("battle", .325)
    assert old.sound is None and old.stops == 1
    assert len(active_music(bank)) == 1
    bank.update_music("boss", .1)
    bank.update_music("drawing", .1)
    bank.update_music("drawing", 1)
    assert len(active_music(bank)) == 1
    assert active_music(bank)[0].sound is bank._music_sounds["drawing"]


def test_mode_aliases_share_one_battle_loop(device):
    bank = audio.SoundBank()
    for context in ("campaign", "blitz", "endless", "battle"):
        bank.update_music(context, 1)
    assert len(active_music(bank)) == 1
    assert active_music(bank)[0].starts == 1


@pytest.mark.parametrize("reason", ("pause", "suspended", "mute", "disabled", "volume"))
def test_silencing_and_resuming_preserves_playhead_without_new_play(device, reason):
    bank = audio.SoundBank()
    bank.update_music("battle", 1)
    channel = active_music(bank)[0]
    options = {"pause": {"paused": True}, "disabled": {"enabled": False},
               "volume": {"volume": 0}, "mute": {},
               "suspended": {"suspended": True}}[reason]
    if reason == "mute":
        bank.set_muted(True)
        assert channel.paused and channel.volume == 0  # immediate, before next frame
    for _ in range(10):
        assert not bank.update_music("battle", .1, **options)
    assert channel.paused and channel.volume == 0 and channel.starts == 1
    bank.set_muted(False)
    assert bank.update_music("battle", .1)
    assert not channel.paused and channel.volume == pytest.approx(.35)
    assert channel.starts == 1


def test_focus_suspension_stops_sfx_but_music_setting_does_not_mute_effects(device):
    bank = audio.SoundBank()
    bank.update_music("battle", 1)
    assert bank.play("shoot")
    effect = bank._channels[0][0]
    bank.update_music("battle", .1, suspended=True)
    assert effect.sound is None and not bank.play("hurt")
    bank.update_music("battle", .1, enabled=False)
    assert bank.play("hurt")
    assert all(channel.paused for channel in active_music(bank))


def test_result_and_upgrade_music_pause_does_not_cut_off_feedback(device):
    bank = audio.SoundBank()
    bank.update_music("battle", 1)
    assert bank.play("upgrade")
    upgrade = bank._channels[0][0]
    bank.update_music("battle", .1, paused=True)
    assert upgrade.get_busy() and not upgrade.paused
    assert bank.play("victory")
    victory = bank._channels[0][0]
    bank.update_music("battle", .1, paused=True)
    assert victory.get_busy() and not victory.paused
    assert all(channel.paused for channel in active_music(bank))


def test_victory_cannot_replace_music_and_external_channels_remain_untouched(device):
    external = device.channels[0]
    external.sound = sentinel = object()
    external.volume = .73
    bank = audio.SoundBank()
    bank.update_music("boss", 1)
    music_channel = active_music(bank)[0]
    assert bank.play("shoot") and bank.play("victory")
    assert music_channel.starts == 1 and music_channel.stops == 0
    assert music_channel.sound is bank._music_sounds["boss"]
    assert external.sound is sentinel and external.volume == .73 and external.stops == 0


def test_foreign_reuse_is_not_paused_stopped_or_replaced(monkeypatch):
    device = FakeMixer(borrowed=True)
    monkeypatch.setattr(audio.pygame, "mixer", device)
    bank = audio.SoundBank()
    bank.update_music("menu", 1)
    channel = active_music(bank)[0]
    channel.sound = sentinel = object()
    channel.volume = .62
    bank.set_muted(True)
    bank.set_muted(False)
    assert not bank.update_music("battle", 1)
    bank.close()
    assert channel.sound is sentinel and channel.volume == .62
    assert not channel.paused and channel.stops == 0 and device.quits == 0


def test_no_context_fades_out_and_close_is_idempotent(device):
    bank = audio.SoundBank()
    bank.update_music("menu", 1)
    channel = active_music(bank)[0]
    assert not bank.update_music(None, .1)
    assert 0 < channel.volume < .35
    bank.update_music(None, 1)
    assert channel.sound is None
    bank.close()
    bank.close()
    assert device.quits == 1
    assert not bank.update_music("boss", 1) and not bank.play("victory")


def test_initial_mute_prepares_pcm_without_opening_device_or_frame_generation(device, monkeypatch):
    bank = audio.SoundBank(muted=True)
    assert device.inits == 0 and len(bank._music_pcm) == 4
    def forbidden(*args, **kwargs):
        raise AssertionError("unmute must use already prepared music")
    monkeypatch.setattr(audio, "generate_music_pcm", forbidden)
    bank.set_muted(False)
    assert device.inits == 1 and bank.update_music("menu", 1)


def test_missing_device_and_later_loss_do_not_escape_audio_boundary(monkeypatch):
    device = FakeMixer(fail_init=True)
    monkeypatch.setattr(audio.pygame, "mixer", device)
    bank = audio.SoundBank()
    for _ in range(100):
        assert not bank.update_music("battle", .016)
    bank.close()
    assert device.inits == 1
    device = FakeMixer()
    monkeypatch.setattr(audio.pygame, "mixer", device)
    bank = audio.SoundBank()
    bank.update_music("battle", 1)
    device.failed = True
    assert not bank.update_music("boss", .1)
    assert not bank.music_available
    bank.close()
    assert device.quits == 1


def test_composition_failure_leaves_effects_available(device, monkeypatch):
    def failed(*args, **kwargs):
        raise MemoryError("cannot allocate music buffers")
    monkeypatch.setattr(audio, "generate_music_pcm", failed)
    bank = audio.SoundBank()
    assert bank.available and not bank.music_available
    assert bank.play("hurt") and not bank.update_music("battle", 1)


def test_real_sdl_dummy_mixer_can_loop_pause_crossfade_and_close():
    # Exercise actual pygame Channel/Sound identity, in a child with no hardware.
    script = """
import os
os.environ['SDL_AUDIODRIVER'] = 'dummy'
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = '1'
from desktop_world.audio import SoundBank
bank = SoundBank()
assert bank.music_available
assert bank.update_music('menu', 1)
assert bank.play('shoot')
assert not bank.update_music('menu', .1, paused=True)
assert bank.update_music('menu', .1)
assert bank.update_music('battle', .325)
assert bank.update_music('battle', .325)
assert bank.play('victory')
assert sum(channel.get_busy() for channel in bank._music_channels) == 1
bank.close()
bank.close()
"""
    result = subprocess.run([sys.executable, "-c", script], cwd=Path(__file__).resolve().parents[1],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
