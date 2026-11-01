# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Deterministic auditory-feed sources (unified-perception-feed).

Covers the seeded procedural audio stream (pure-function determinism,
seek-safety, seed decorrelation, shared cross-modal surprise cadence, block
shape) and the playlist audio stream (manifest verify fail-closed; honest
failure when PyAV is absent). No real microphone, no disk writes of PCM.
"""
from __future__ import annotations

import hashlib
import importlib.util

import pytest

from kaine.modules.audition.feed import (
    _SALT_SHARED_ONSET,
    PlaylistAudioStream,
    SeededAudioSchedule,
    SeededProceduralAudioStream,
)
from kaine.modules.audition.live import PerceptionUnavailableError
from kaine.modules.vision.feed import (
    PlaylistVerificationError,
    SeededProceduralSource,
    SeededSchedule,
    load_playlist_manifest,
)

_HAS_AV = importlib.util.find_spec("av") is not None


def _noop(_b: bytes) -> None:
    return None


# ---------------------------------------------------------------------------
# Seeded audio stream
# ---------------------------------------------------------------------------


def test_seeded_audio_block_shape_and_dtype():
    s = SeededAudioSchedule(seed=1, sample_rate=16000, channels=1, frames_per_block=480)
    stream = SeededProceduralAudioStream(s, callback=_noop)
    block = stream.pcm_at(0)
    # int16 LE mono → frames_per_block * channels * 2 bytes.
    assert len(block) == 480 * 1 * 2
    # Stereo doubles the byte count.
    s2 = SeededAudioSchedule(seed=1, channels=2, frames_per_block=480)
    assert len(SeededProceduralAudioStream(s2, callback=_noop).pcm_at(0)) == 480 * 2 * 2


def test_same_seed_reproduces_identical_pcm_bytes():
    s = SeededAudioSchedule(seed=42, surprise_interval=4, base_strength=0.4)
    a = SeededProceduralAudioStream(s, callback=_noop)
    b = SeededProceduralAudioStream(s, callback=_noop)
    for i in range(30):
        assert a.pcm_at(i) == b.pcm_at(i), f"block {i} differs across runs of one seed"


def test_restart_and_seek_reproduce_block_i():
    """pcm_at(i) is a pure function of (seed, i): identical regardless of the
    path taken to it (sequential vs direct seek vs restart)."""
    s = SeededAudioSchedule(seed=99, surprise_interval=3)
    a = SeededProceduralAudioStream(s, callback=_noop)
    seq = [a.pcm_at(i) for i in range(15)]
    b = SeededProceduralAudioStream(s, callback=_noop)
    assert b.pcm_at(7) == seq[7]  # direct seek
    c = SeededProceduralAudioStream(s, callback=_noop)
    assert [c.pcm_at(i) for i in range(8)][7] == seq[7]  # restart


def test_different_seeds_decorrelate_base_soundscape():
    """The BASE soundscape — not only the surprise schedule — differs between
    seeds: with surprises off, a substantial fraction of blocks still differ."""
    common = dict(surprise_interval=100000, surprise_strength=0.0, base_strength=0.4)
    a = SeededProceduralAudioStream(SeededAudioSchedule(seed=1, **common), callback=_noop)
    b = SeededProceduralAudioStream(SeededAudioSchedule(seed=2, **common), callback=_noop)
    diff = sum(1 for i in range(60) if a.pcm_at(i) != b.pcm_at(i))
    assert diff > 0.8 * 60, f"only {diff}/60 base blocks differ between seeds"


def test_surprise_strength_zero_disables_bursts_but_keeps_base():
    s = SeededAudioSchedule(seed=5, surprise_interval=4, surprise_strength=0.0,
                            base_strength=0.4)
    stream = SeededProceduralAudioStream(s, callback=_noop)
    assert stream.surprise_indices(200) == []
    # Base soundscape still varies block to block (learnable structure present).
    assert stream.pcm_at(0) != stream.pcm_at(5)


def test_surprise_cadence_matches_config():
    interval = 12
    stream = SeededProceduralAudioStream(
        SeededAudioSchedule(seed=5, surprise_interval=interval), callback=_noop
    )
    idxs = stream.surprise_indices(600)
    assert idxs, "expected some surprise bursts over 600 blocks"
    for i in idxs:
        assert i % interval == 0 and i > 0, f"burst at off-cadence index {i}"


def test_shared_onset_salt_matches_video_source():
    """The audio onset draw uses the SAME salt as the video source so the two
    modalities decide a slot fires from the identical coin flip."""
    assert _SALT_SHARED_ONSET == SeededProceduralSource._SALT_ONSET


def test_seeded_surprises_are_cross_modal():
    """For one seed and one surprise_interval, the seeded VIDEO and AUDIO sources
    fire surprises on the IDENTICAL cadence slots — a blob and a burst together
    (unified-perception-feed cross-modal binding)."""
    seed, interval = 42, 10
    vid = SeededProceduralSource(SeededSchedule(seed=seed, surprise_interval=interval))
    aud = SeededProceduralAudioStream(
        SeededAudioSchedule(seed=seed, surprise_interval=interval), callback=_noop
    )
    assert vid.surprise_indices(200) == aud.surprise_indices(200)
    assert vid.surprise_indices(200), "expected shared surprise slots to exist"


def test_descriptor_round_trips_to_regenerate():
    s = SeededAudioSchedule(seed=7, sample_rate=16000, channels=1,
                            frames_per_block=320, surprise_interval=5,
                            base_strength=0.25, surprise_strength=0.5)
    desc = s.as_descriptor()
    rebuilt = SeededAudioSchedule(
        seed=desc["seed"],
        sample_rate=desc["sample_rate"],
        channels=desc["channels"],
        frames_per_block=desc["frames_per_block"],
        surprise_interval=desc["surprise_interval"],
        base_strength=desc["base_strength"],
        surprise_strength=desc["surprise_strength"],
    )
    a = SeededProceduralAudioStream(s, callback=_noop)
    b = SeededProceduralAudioStream(rebuilt, callback=_noop)
    for i in range(12):
        assert a.pcm_at(i) == b.pcm_at(i)


def test_producer_thread_emits_blocks_to_callback():
    """start()/stop() actually drive blocks into the callback (the _AudioStream
    contract LiveMicrophone relies on)."""
    import time

    captured: list[bytes] = []
    s = SeededAudioSchedule(seed=1, sample_rate=16000, frames_per_block=160)
    stream = SeededProceduralAudioStream(s, callback=captured.append)
    stream.start()
    try:
        deadline = time.monotonic() + 2.0
        while len(captured) < 3 and time.monotonic() < deadline:
            time.sleep(0.02)
    finally:
        stream.stop()
        stream.close()
    assert len(captured) >= 3, "producer thread did not emit blocks"
    # Each emitted block is the right size and matches the pure synthesis.
    assert captured[0] == stream.pcm_at(0)


# ---------------------------------------------------------------------------
# Playlist audio stream
# ---------------------------------------------------------------------------


def _write_manifest(tmp_path, items):
    lines = []
    for it in items:
        lines.append("[[item]]")
        lines.append(f'path = "{it["path"]}"')
        lines.append(f'sha256 = "{it["sha256"]}"')
        lines.append(f'fps = {it["fps"]}')
        lines.append("")
    manifest = tmp_path / "playlist.toml"
    manifest.write_text("\n".join(lines), encoding="utf-8")
    return manifest


def test_playlist_audio_digest_mismatch_fails_closed(tmp_path):
    (tmp_path / "clip.mp4").write_bytes(b"original")
    sha = hashlib.sha256(b"original").hexdigest()
    manifest = _write_manifest(tmp_path, [{"path": "clip.mp4", "sha256": sha, "fps": 30}])
    parsed = load_playlist_manifest(manifest)
    # Tamper after the manifest was authored.
    (tmp_path / "clip.mp4").write_bytes(b"tampered")
    stream = PlaylistAudioStream(parsed, callback=_noop)
    with pytest.raises(PlaylistVerificationError):
        stream.verify()
    # start() verifies first, so it must also fail closed BEFORE touching av.
    with pytest.raises(PlaylistVerificationError):
        stream.start()


def test_playlist_audio_missing_media_fails_closed(tmp_path):
    sha = hashlib.sha256(b"whatever").hexdigest()
    manifest = _write_manifest(tmp_path, [{"path": "gone.mp4", "sha256": sha, "fps": 30}])
    parsed = load_playlist_manifest(manifest)
    stream = PlaylistAudioStream(parsed, callback=_noop)
    with pytest.raises(PlaylistVerificationError):
        stream.verify()


@pytest.mark.skipif(_HAS_AV, reason="PyAV installed — honest-failure path is N/A")
def test_playlist_audio_honest_failure_when_av_absent(tmp_path):
    """With a VERIFIED manifest but no PyAV, the source raises a clear
    unavailable error with an install hint — never a silent no-op or synthetic
    audio (no pretend processes)."""
    (tmp_path / "clip.mp4").write_bytes(b"verified-media")
    sha = hashlib.sha256(b"verified-media").hexdigest()
    manifest = _write_manifest(tmp_path, [{"path": "clip.mp4", "sha256": sha, "fps": 30}])
    parsed = load_playlist_manifest(manifest)
    stream = PlaylistAudioStream(parsed, callback=_noop)
    with pytest.raises(PerceptionUnavailableError) as exc:
        stream.start()
    assert "av" in str(exc.value).lower() or "pyav" in str(exc.value).lower()
    assert "install" in str(exc.value).lower()


@pytest.mark.skipif(not _HAS_AV, reason="PyAV not installed — real decode smoke skipped")
def test_playlist_audio_decodes_real_media(tmp_path):
    """When PyAV IS present, a tiny generated media file decodes to real PCM
    blocks (no synthetic substitute). Synthesizes the media with PyAV itself."""
    import time

    import av  # type: ignore[import-untyped]
    import numpy as np

    media = tmp_path / "tone.wav"
    # Write a 0.3 s sine tone to a WAV via PyAV (input fixture only — NOT the
    # source under test, which never writes).
    container = av.open(str(media), mode="w")
    stream_out = container.add_stream("pcm_s16le", rate=16000)
    stream_out.layout = "mono"
    t = np.arange(int(16000 * 0.3))
    samples = (0.3 * np.sin(2 * np.pi * 220.0 * t / 16000) * 32767).astype(np.int16)
    frame = av.AudioFrame.from_ndarray(samples.reshape(1, -1), format="s16", layout="mono")
    frame.rate = 16000
    for packet in stream_out.encode(frame):
        container.mux(packet)
    for packet in stream_out.encode(None):
        container.mux(packet)
    container.close()

    sha = hashlib.sha256(media.read_bytes()).hexdigest()
    manifest = _write_manifest(tmp_path, [{"path": "tone.wav", "sha256": sha, "fps": 30}])
    parsed = load_playlist_manifest(manifest)
    captured: list[bytes] = []
    stream = PlaylistAudioStream(
        parsed, callback=captured.append, sample_rate=16000, channels=1,
        frames_per_block=160,
    )
    stream.start()
    try:
        deadline = time.monotonic() + 3.0
        while len(captured) < 2 and time.monotonic() < deadline:
            time.sleep(0.02)
    finally:
        stream.stop()
        stream.close()
    assert captured, "playlist audio decoded no PCM from real media"
    assert len(captured[0]) == 160 * 1 * 2



# ---------------------------------------------------------------------------
# Playlist audio on the item timeline (playlist-feed-av-sync)
# ---------------------------------------------------------------------------


def test_item_timeline_fills_gaps_trims_overlaps_and_caps_at_the_end():
    from kaine.modules.audition.feed import _ItemTimeline

    tl = _ItemTimeline(1000, start_s=0.0, end_s=1.0, tolerance_s=0.04)
    assert tl.place(0.0) == 0 and tl.take(100) == (0, 100)
    # Within tolerance (timestamp rounding, resampler delay): appended as is.
    assert tl.place(0.130) == 0 and tl.take(100) == (0, 100)
    # A 300 ms hole in the timestamps is heard as silence.
    assert tl.place(0.5) == 300 and tl.pos == 500
    # Audio stamped 100 ms before the position: its head is trimmed.
    assert tl.place(0.4) == 0 and tl.take(150) == (100, 50)
    # Never past the item's end; the remainder pads to it.
    assert tl.place(0.55) == 0 and tl.take(1000) == (0, 450)
    assert tl.pos == 1000 and tl.remaining() == 0


def test_item_timeline_starts_at_the_resync_offset():
    from kaine.modules.audition.feed import _ItemTimeline

    tl = _ItemTimeline(1000, start_s=2.5, end_s=None)
    assert tl.pos == 2500 and tl.remaining() == 0
    assert tl.place(2.0) == 0 and tl.take(400) == (400, 0)  # wholly before: dropped
    assert tl.place(2.49) == 0 and tl.take(100) == (0, 100)


def _run_fake_av_stream(tmp_path, monkeypatch, containers, *, clock=None):  # noqa: ANN001, ANN202
    """Run PlaylistAudioStream._produce over fake PyAV containers (one per
    manifest item, in order), without 1x pacing."""
    import sys
    from types import SimpleNamespace

    import numpy as np

    from kaine.modules.audition import feed as audition_feed
    from tests._playlist_fakes import fake_av_module

    items = []
    for i in range(len(containers)):
        name = f"item{i}.webm"
        data = f"media-{i}".encode()
        (tmp_path / name).write_bytes(data)
        items.append({"path": name, "sha256": hashlib.sha256(data).hexdigest(), "fps": 25})
    parsed = load_playlist_manifest(_write_manifest(tmp_path, items))
    by_name = {f"item{i}.webm": c for i, c in enumerate(containers)}
    monkeypatch.setitem(
        sys.modules, "av", fake_av_module(lambda path: by_name[path.rsplit("/", 1)[-1]])
    )
    ticks = iter(range(1, 10**9))
    monkeypatch.setattr(
        audition_feed, "time", SimpleNamespace(monotonic=lambda: float(next(ticks)) * 1e3)
    )
    blocks: list[bytes] = []
    stream = PlaylistAudioStream(
        parsed, callback=blocks.append, sample_rate=1000, channels=1,
        frames_per_block=100, playlist_clock=clock,
    )
    stream._produce()
    return np.frombuffer(b"".join(blocks), dtype=np.int16), stream


class _TimedContainer:
    """Fake PyAV container: ``frames`` as (pts_ms, samples, value) at 1 kHz."""

    def __init__(self, frames, *, duration_s, audio=True, seek_raises=False):  # noqa: ANN001
        from types import SimpleNamespace

        self.duration = int(duration_s * 1_000_000)
        self.streams = SimpleNamespace(audio=[object()] if audio else [])
        self._frames = frames
        self._seek_raises = seek_raises
        self.seeks: list[int] = []

    def seek(self, offset_us, any_frame=False):  # noqa: ANN001
        self.seeks.append(offset_us)
        if self._seek_raises:
            raise OSError("not seekable")

    def decode(self, stream):  # noqa: ANN001, ANN201
        from tests._playlist_fakes import FakeAudioFrame

        for pts, n, value in self._frames:
            yield FakeAudioFrame(
                int(value).to_bytes(2, "little", signed=True) * n,
                pts=pts, time_base=0.001, sample_rate=1000,
            )

    def close(self) -> None:
        return None


def test_playlist_audio_pads_each_item_to_its_length_and_plays_a_silent_item(tmp_path, monkeypatch):
    """Item 0's audio stops 300 ms before its container ends, item 1 has no
    audio track: each is padded with silence to its length, so item 2's sound
    starts exactly where the clock puts it (at 2.0 s)."""
    pcm, _ = _run_fake_av_stream(
        tmp_path, monkeypatch,
        [
            _TimedContainer([(0, 700, 7)], duration_s=1.0),
            _TimedContainer([], duration_s=1.0, audio=False),
            _TimedContainer([(0, 500, 9)], duration_s=0.5),
        ],
    )
    assert pcm.size == 2500
    assert (pcm[:700] == 7).all() and not pcm[700:2000].any() and (pcm[2000:] == 9).all()


def test_playlist_audio_resumes_at_the_offset_when_the_seek_fails(tmp_path, monkeypatch):
    """A producer restarted 0.6 s into an item whose container refuses to seek
    decodes from the start and trims everything before 0.6 s."""
    from kaine.modules.vision.feed import PlaylistClock

    clock = PlaylistClock(1, clock=lambda: 0.6)  # 0.6 s into the item
    clock.start(at=0.0)
    container = _TimedContainer(
        [(0, 250, 1), (250, 250, 2), (500, 250, 3), (750, 250, 4)],
        duration_s=1.0, seek_raises=True,
    )
    pcm, stream = _run_fake_av_stream(tmp_path, monkeypatch, [container], clock=clock)
    assert container.seeks == [600_000]
    # 0.6-0.75 s of the third frame, then the fourth: 400 samples.
    assert pcm.size == 400
    assert (pcm[:150] == 3).all() and (pcm[150:] == 4).all()
    assert stream.delivered_position == (0, pytest.approx(1.0))
