# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Playback abstraction, retention helper, and player construction."""
import io
import wave

import pytest

from kaine.modules.vox import (
    FakePlayer,
    NullPlayer,
    SoundDevicePlayer,
    build_player,
    wav_duration_s,
)


def _wav_bytes(seconds: float, rate: int = 24000) -> bytes:
    n = int(seconds * rate)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * n)
    return buf.getvalue()


def test_wav_duration_parses_real_wav():
    assert wav_duration_s(_wav_bytes(1.5)) == pytest.approx(1.5, abs=0.01)


def test_wav_duration_on_garbage_is_zero():
    # A parse failure must never raise into the synthesis path.
    assert wav_duration_s(b"not a wav at all") == 0.0
    assert wav_duration_s(b"") == 0.0


def test_build_player_disabled_returns_null_player():
    assert isinstance(build_player(playback_enabled=False), NullPlayer)


def test_build_player_enabled_returns_sounddevice_player():
    assert isinstance(build_player(playback_enabled=True), SoundDevicePlayer)


@pytest.mark.asyncio
async def test_null_player_is_noop():
    await NullPlayer().play(_wav_bytes(0.1))  # must not raise


@pytest.mark.asyncio
async def test_fake_player_records_clips():
    p = FakePlayer()
    clip = _wav_bytes(0.2)
    await p.play(clip)
    assert p.played == [clip]


@pytest.mark.asyncio
async def test_sounddevice_player_degrades_without_device(monkeypatch):
    """If the audio system can't be imported/used, play() is a no-op, not a
    crash, and stays disabled afterward."""
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "sounddevice":
            raise ImportError("no PortAudio in this environment")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    player = SoundDevicePlayer()
    await player.play(_wav_bytes(0.1))  # must not raise
    assert player._disabled is True
