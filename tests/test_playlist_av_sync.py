# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Playlist picture and sound stay on one timeline (playlist-feed-av-sync).

Synthetic clips are written with PyAV into ``tmp_path``: a constant-frame-rate
clip and a variable-frame-rate one whose manifest gives a nominal rate that is
not the real one. Each frame's left half carries its media time in tenths of a
second (a grey level); a white bar in the right half and a tone in the audio
mark the same media windows. The feed must show and deliver them together at
every clock offset, to the end of the clip, after a seek and across an item
boundary, and the audio must be exactly as long as the clip.

A real-media check measures the programme films when ``KAINE_PROGRAMME_MEDIA``
names a directory holding them and their ``programme.toml``.
"""

from __future__ import annotations

import fractions
import hashlib
import math
import os
from pathlib import Path

import numpy as np
import pytest

av = pytest.importorskip("av")

from kaine.modules.audition.feed import PlaylistAudioStream, _frame_pcm  # noqa: E402
from kaine.modules.vision.feed import (  # noqa: E402
    PlaylistClock,
    PlaylistSource,
    PyAvVideoDecoder,
    container_duration_s,
    load_playlist_manifest,
)

W, H = 64, 48
AUDIO_RATE_IN = 44_100      # written stereo at 44.1 kHz, delivered mono 16 kHz
SR = 16_000
BLOCK = 480
MARKERS = ((1.0, 1.3), (4.0, 4.3), (7.5, 7.8), (9.4, 9.7))
CLIP_S = 10.0


def _in_marker(t: float) -> bool:
    return any(a <= t < b for a, b in MARKERS)


def _decile_level(t: float) -> int:
    # 25 grey levels, 10 apart: robust to VP8 loss on a flat region.
    return (int(math.floor(t * 10.0 + 1e-9)) % 25) * 10


def _frame_image(t: float) -> np.ndarray:
    img = np.zeros((H, W, 3), np.uint8)
    img[:, : W // 2] = _decile_level(t)
    if _in_marker(t):
        img[:, W // 2 :] = 255
    return img


def _cfr_times(fps: float = 25.0) -> list[float]:
    n = int(CLIP_S * fps)
    return [i / fps for i in range(n)]


def _vfr_times() -> list[float]:
    # 20 fps for the first half, 30 fps for the second: a nominal 25 fps
    # would put the picture a full second ahead of the sound by 5 s.
    times = [i * 0.050 for i in range(100)]
    times += [5.0 + i / 30.0 for i in range(150)]
    return times


def _write_clip(
    path: Path,
    frame_times: list[float],
    *,
    audio_gap: tuple[float, float] | None = None,
    audio: bool = True,
    continuous_tone: bool = False,
) -> None:
    """VP8 video at the given presentation times (ms time base) and PCM audio
    with a 1 kHz tone in each marker window; ``audio_gap`` leaves a hole in the
    audio timestamps (no packets) without shifting what follows."""
    out = av.open(str(path), mode="w", format="matroska")
    vs = out.add_stream("libvpx", rate=25)
    vs.width, vs.height, vs.pix_fmt = W, H, "yuv420p"
    vs.time_base = fractions.Fraction(1, 1000)
    vs.codec_context.time_base = fractions.Fraction(1, 1000)
    vs.codec_context.gop_size = 25
    astream = None
    if audio:
        astream = out.add_stream("pcm_s16le", rate=AUDIO_RATE_IN)
        astream.layout = "stereo"
    for t in frame_times:
        frame = av.VideoFrame.from_ndarray(_frame_image(t), format="rgb24")
        frame.pts = int(round(t * 1000))
        frame.time_base = vs.time_base
        for packet in vs.encode(frame):
            out.mux(packet)
    for packet in vs.encode():
        out.mux(packet)
    if astream is not None:
        chunk = 1000  # odd-sized frames: resampled planes are padded
        total = int(CLIP_S * AUDIO_RATE_IN)
        for start in range(0, total, chunk):
            n = min(chunk, total - start)
            t0 = start / AUDIO_RATE_IN
            if audio_gap is not None and audio_gap[0] <= t0 < audio_gap[1]:
                continue
            ts = (start + np.arange(n)) / AUDIO_RATE_IN
            tone = np.where(
                [continuous_tone or _in_marker(x) for x in ts],
                0.5 * np.sin(2 * np.pi * 1000.0 * ts),
                0.0,
            )
            pcm = (tone * 32767).astype(np.int16)
            stereo = np.repeat(pcm, 2).reshape(1, -1)
            frame = av.AudioFrame.from_ndarray(stereo, format="s16", layout="stereo")
            frame.rate = AUDIO_RATE_IN
            frame.pts = start
            frame.time_base = fractions.Fraction(1, AUDIO_RATE_IN)
            for packet in astream.encode(frame):
                out.mux(packet)
        for packet in astream.encode(None):
            out.mux(packet)
    out.close()


def _manifest(tmp_path: Path, items: list[tuple[str, float]]) -> Path:
    lines = []
    for order, (name, fps) in enumerate(items):
        sha = hashlib.sha256((tmp_path / name).read_bytes()).hexdigest()
        lines += ["[[item]]", f'path = "{name}"', f'sha256 = "{sha}"', f"fps = {fps}",
                  f"order = {order}", ""]
    p = tmp_path / "programme.toml"
    p.write_text("\n".join(lines), encoding="utf-8")
    return p


class _ManualClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


class _SeekCounter:
    """The real PyAV decoder factory, counting seeks and decoded frames."""

    def __init__(self) -> None:
        self.decoders: list[_CountingDecoder] = []

    def __call__(self, path, item):  # noqa: ANN001, ANN204
        d = _CountingDecoder(av, path, nominal_fps=item.fps)
        self.decoders.append(d)
        return d


class _CountingDecoder(PyAvVideoDecoder):
    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        super().__init__(*args, **kwargs)
        self.seeks: list[float] = []
        self.decoded = 0

    def seek(self, seconds: float) -> None:
        self.seeks.append(seconds)
        super().seek(seconds)

    def next(self):  # noqa: ANN201
        out = super().next()
        if out is not None:
            self.decoded += 1
        return out


def _video(manifest_path: Path, clock: PlaylistClock, factory=None) -> PlaylistSource:  # noqa: ANN001
    src = PlaylistSource(
        load_playlist_manifest(manifest_path), playlist_clock=clock, decoder_factory=factory
    )
    assert src.open()
    clock.start(at=0.0)  # programme time zero is clock time zero (idempotent)
    return src


def _read_at(src: PlaylistSource, mclock: _ManualClock, t: float) -> np.ndarray:
    mclock.t = t
    ok, frame = src.read()
    assert ok, f"no frame at {t}"
    return frame


def _left_level(img: np.ndarray) -> int:
    return int(round(float(img[:, : W // 2].mean())))


def _right_white(img: np.ndarray) -> bool:
    return float(img[:, W // 2 :].mean()) > 128.0


def _deliver_all(
    manifest_path: Path,
    monkeypatch,  # noqa: ANN001 — kept for the callers; nothing is patched
    *,
    clock: PlaylistClock | None = None,
    mclock: _ManualClock | None = None,
    on_block=None,  # noqa: ANN001 — on_block(index, mclock) after each block
) -> tuple[np.ndarray, PlaylistAudioStream]:
    """Run the real playlist audio producer to the end against a manual
    shared clock that its pacing waits advance (no real time passes).

    ``stream.emitted_at`` holds the clock time each block went out and
    ``stream.positions`` the delivered position after it."""
    manifest = load_playlist_manifest(manifest_path)
    if clock is None:
        mclock = _ManualClock()
        clock = PlaylistClock(len(manifest.items), clock=mclock)
    assert mclock is not None
    blocks: list[bytes] = []
    emitted_at: list[float] = []
    positions: list[tuple[int, float]] = []
    holder: list[PlaylistAudioStream] = []

    def _on_pcm(pcm: bytes) -> None:
        blocks.append(pcm)
        emitted_at.append(mclock.t)
        positions.append(holder[0]._delivered)
        if on_block is not None:
            on_block(len(blocks) - 1, mclock)

    stream = PlaylistAudioStream(
        manifest,
        callback=_on_pcm,
        sample_rate=SR,
        channels=1,
        frames_per_block=BLOCK,
        playlist_clock=clock,
    )
    holder.append(stream)

    def _advance(seconds: float) -> bool:
        mclock.t += seconds
        return False

    stream._pace_wait = _advance
    stream._produce()
    stream.emitted_at = emitted_at
    stream.positions = positions
    assert all(len(b) == BLOCK * 2 for b in blocks)
    return np.frombuffer(b"".join(blocks), dtype=np.int16), stream


def _loud(pcm: np.ndarray, t: float, half_window: float = 0.05) -> bool:
    lo, hi = int((t - half_window) * SR), int((t + half_window) * SR)
    seg = pcm[max(0, lo) : hi].astype(np.float64)
    return seg.size > 0 and float(np.sqrt(np.mean(seg * seg))) > 2000.0


# Offsets sit 70 ms into a tenth-of-a-second, so the frame at or before the
# offset (frames are at most 50 ms apart) carries the offset's own decile.
_PROBES = [0.27, 1.17, 2.57, 4.17, 4.97, 5.07, 6.47, 7.67, 8.87, 9.57, 9.87, 9.97]


@pytest.fixture
def vfr_clip(tmp_path: Path) -> Path:
    _write_clip(tmp_path / "vfr.mkv", _vfr_times(), audio_gap=(5.0, 5.5))
    return _manifest(tmp_path, [("vfr.mkv", 25.0)])


@pytest.fixture
def cfr_clip(tmp_path: Path) -> Path:
    _write_clip(tmp_path / "cfr.mkv", _cfr_times())
    return _manifest(tmp_path, [("cfr.mkv", 25.0)])


def test_decoder_times_are_the_written_presentation_times(vfr_clip: Path):
    decoder = PyAvVideoDecoder(av, vfr_clip.parent / "vfr.mkv", nominal_fps=25.0)
    try:
        times = []
        while (nxt := decoder.next()) is not None:
            times.append(nxt[0])
    finally:
        decoder.close()
    assert len(times) == len(_vfr_times())
    assert times == pytest.approx(_vfr_times(), abs=1e-3)


@pytest.mark.parametrize("clip", ["cfr_clip", "vfr_clip"])
def test_presented_frame_follows_the_clock_to_the_end(clip: str, request):  # noqa: ANN001
    manifest_path = request.getfixturevalue(clip)
    mclock = _ManualClock()
    clock = PlaylistClock(1, clock=mclock)
    src = _video(manifest_path, clock)
    try:
        assert clock.duration(0) == pytest.approx(CLIP_S, abs=0.05)
        for t in _PROBES:
            img = _read_at(src, mclock, t)
            assert _left_level(img) == pytest.approx(_decile_level(t), abs=4), t
            assert _right_white(img) == _in_marker(t), t
    finally:
        src.release()


def test_audio_is_exactly_as_long_as_the_clip(cfr_clip: Path, monkeypatch):
    path = cfr_clip.parent / "cfr.mkv"
    container = av.open(str(path))
    duration = container_duration_s(container)
    container.close()
    pcm, stream = _deliver_all(cfr_clip, monkeypatch)
    samples = int(round(duration * SR))
    # Exactly the clip's samples, then zeros up to the last whole block.
    assert pcm.size == math.ceil(samples / BLOCK) * BLOCK
    assert not pcm[samples:].any()
    assert stream.delivered_position[1] == pytest.approx(pcm.size / SR)


@pytest.mark.parametrize(
    ("fmt", "layout", "channels"),
    [("s16", "mono", 1), ("s16", "stereo", 2), ("s16p", "stereo", 2)],
)
def test_frame_pcm_takes_the_samples_not_the_padded_plane(fmt, layout, channels):  # noqa: ANN001
    """A resampled PyAV frame's plane is larger than its samples; only the
    samples (interleaved for a planar layout) are audio."""
    resampler = av.audio.resampler.AudioResampler(format=fmt, layout=layout, rate=SR)
    left = np.arange(579, dtype=np.float32) / 579.0 * 0.5
    src = av.AudioFrame.from_ndarray(np.stack([left, -left]), format="fltp", layout="stereo")
    src.rate, src.pts = 48_000, 0
    frames = list(resampler.resample(src)) + list(resampler.resample(None))
    assert any(sum(len(bytes(p)) for p in f.planes) > f.samples * channels * 2 for f in frames)
    for f in frames:
        pcm = _frame_pcm(f, channels)
        assert pcm.dtype == np.dtype("<i2") and pcm.size == f.samples * channels
        if channels == 2:
            # Interleaved L, R: the right channel is the negated left.
            assert np.all(np.abs(pcm[0::2].astype(int) + pcm[1::2].astype(int)) <= 1)


def test_continuous_sound_is_delivered_without_holes(tmp_path: Path, monkeypatch):
    """A tone that never stops is delivered as an unbroken tone of the clip's
    length: no padded stretches of silence, nothing trimmed away."""
    _write_clip(tmp_path / "tone.mkv", _cfr_times(), continuous_tone=True)
    pcm, _stream = _deliver_all(_manifest(tmp_path, [("tone.mkv", 25.0)]), monkeypatch)
    samples = int(round(CLIP_S * SR))
    body = pcm[int(0.01 * SR) : samples - int(0.01 * SR)].astype(np.int32)
    # The longest run of near-silence in a 1 kHz tone at 16 kHz is a sample or two.
    quiet = np.abs(body) < 200
    longest = max((len(r) for r in "".join("1" if q else "0" for q in quiet).split("0")), default=0)
    assert longest <= 2
    # 1 kHz for 10 s: 20,000 zero crossings.
    crossings = int(np.count_nonzero(np.diff(np.signbit(body))))
    assert crossings == pytest.approx(2 * 1000 * (body.size / SR), rel=0.01)


def test_picture_and_sound_meet_at_every_marker(vfr_clip: Path, monkeypatch):
    pcm, _stream = _deliver_all(vfr_clip, monkeypatch)
    assert pcm.size == math.ceil(int(round(CLIP_S * SR)) / BLOCK) * BLOCK
    mclock = _ManualClock()
    src = _video(vfr_clip, PlaylistClock(1, clock=mclock))
    try:
        for a, b in MARKERS:
            mid = (a + b) / 2.0
            assert _right_white(_read_at(src, mclock, mid)), mid
            assert _loud(pcm, mid), mid
            # Clear of the window on both sides: dark and silent.
            assert not _loud(pcm, a - 0.15) and not _loud(pcm, b + 0.15), mid
    finally:
        src.release()
    # The audio timestamp gap (5.0-5.5 s) is silence, and the marker after it
    # is still at its media time (sample counting alone would put it 0.5 s early).
    assert not pcm[int(5.05 * SR) : int(5.45 * SR)].any()
    assert _loud(pcm, 7.65) and not _loud(pcm, 7.15)


def test_a_source_opened_late_seeks_to_the_clock(vfr_clip: Path):
    mclock = _ManualClock()
    clock = PlaylistClock(1, clock=mclock)
    clock.start(at=0.0)
    mclock.t = 8.87
    factory = _SeekCounter()
    src = _video(vfr_clip, clock, factory)
    try:
        img = _read_at(src, mclock, 8.87)
        assert _left_level(img) == pytest.approx(_decile_level(8.87), abs=4)
        decoder = factory.decoders[-1]
        assert decoder.seeks, "a source opened 8.9 s in must seek"
        # From the keyframe before 8.87 s, not from the first frame.
        assert decoder.decoded < len(_vfr_times()) // 2
        img = _read_at(src, mclock, 9.57)
        assert _right_white(img) and _left_level(img) == pytest.approx(_decile_level(9.57), abs=4)
    finally:
        src.release()


def test_audio_resumed_late_starts_at_the_clock(vfr_clip: Path, monkeypatch):
    mclock = _ManualClock()
    clock = PlaylistClock(1, clock=mclock)
    clock.start(at=0.0)
    clock.set_duration(0, CLIP_S)
    mclock.t = 7.6
    pcm, stream = _deliver_all(vfr_clip, monkeypatch, clock=clock, mclock=mclock)
    # It resumes inside the 7.5-7.8 s marker and runs to the clip's end.
    assert _loud(pcm, 0.1)
    assert pcm.size == math.ceil(int(round((CLIP_S - 7.6) * SR)) / BLOCK) * BLOCK
    assert _loud(pcm, 9.55 - 7.6)
    assert stream.delivered_position[0] == 0


def test_the_second_item_starts_when_the_clock_reaches_it(tmp_path: Path, monkeypatch):
    _write_clip(tmp_path / "a.mkv", _vfr_times())
    _write_clip(tmp_path / "b.mkv", _cfr_times())
    _write_clip(tmp_path / "silent.mkv", _cfr_times(), audio=False)
    manifest_path = _manifest(tmp_path, [("a.mkv", 25.0), ("silent.mkv", 25.0), ("b.mkv", 25.0)])
    mclock = _ManualClock()
    clock = PlaylistClock(3, clock=mclock)
    src = _video(manifest_path, clock)
    try:
        _read_at(src, mclock, 0.0)
        img = _read_at(src, mclock, 2 * CLIP_S + 4.17)
        assert src.current_item.item_idx == 2
        assert _right_white(img) and _left_level(img) == pytest.approx(_decile_level(4.17), abs=4)
    finally:
        src.release()
    pcm, _stream = _deliver_all(manifest_path, monkeypatch)
    # Item 1 has no audio track: heard as silence for its length, so item 2's
    # markers sit at 2 x CLIP_S plus their media time.
    item = int(round(CLIP_S * SR))
    assert not pcm[item : 2 * item].any()
    for a, b in MARKERS:
        mid = (a + b) / 2.0
        assert _loud(pcm, mid) and _loud(pcm, 2 * CLIP_S + mid), mid
    assert not _loud(pcm, 2 * CLIP_S + 4.45)


# ---------------------------------------------------------------------------
# Pacing against the shared clock: a stall is caught up or skipped, never kept
# ---------------------------------------------------------------------------

_BLOCK_S = BLOCK / SR


def _lags(stream: PlaylistAudioStream, item_starts: dict[int, float] | None = None) -> list[float]:
    """Per block: the programme time it went out at minus the programme time
    it starts at (0 = on the clock). Positions are per item; ``item_starts``
    gives each item's start on the programme timeline."""
    starts = item_starts or {0: 0.0}
    return [
        t - (starts[idx] + pos - _BLOCK_S)
        for t, (idx, pos) in zip(stream.emitted_at, stream.positions)
    ]


def _stall_at(block: int, seconds: float):  # noqa: ANN202
    def _hook(i: int, mclock: _ManualClock) -> None:
        if i == block:
            mclock.t += seconds  # the producer was held up this long

    return _hook


def test_a_short_stall_is_caught_up_not_kept(cfr_clip: Path, monkeypatch, caplog):  # noqa: ANN001
    """A 0.3 s stall: the owed blocks go out back to back until the delivered
    position is back on the clock, and no audio is skipped."""
    caplog.set_level("DEBUG", logger="kaine.modules.audition.feed")
    pcm, stream = _deliver_all(cfr_clip, monkeypatch, on_block=_stall_at(100, 0.3))
    lags = _lags(stream)
    assert max(abs(x) for x in lags[:101]) < 1e-6  # on the clock before the stall
    assert max(lags) == pytest.approx(0.3, abs=_BLOCK_S)  # owed, never more
    caught_up = 101 + math.ceil(0.3 / _BLOCK_S) + 1
    assert max(abs(x) for x in lags[caught_up:]) < 1e-6  # back on the clock
    assert stream._skips == 0 and "skipped forward" not in caplog.text
    assert pcm.size == math.ceil(int(round(CLIP_S * SR)) / BLOCK) * BLOCK


def test_a_long_stall_skips_forward_to_the_clock(vfr_clip: Path, monkeypatch, caplog):  # noqa: ANN001
    """A 2 s stall is more than 0.5 s to catch up: the producer skips forward
    to the clock, logs it once without content, and what it delivers at each
    clock time is the sound of that time."""
    caplog.set_level("DEBUG", logger="kaine.modules.audition.feed")
    pcm, stream = _deliver_all(vfr_clip, monkeypatch, on_block=_stall_at(100, 2.0))
    lags = _lags(stream)
    assert stream._skips == 1
    skip_logs = [r for r in caplog.records if "skipped forward" in r.getMessage()]
    assert len(skip_logs) == 1 and skip_logs[0].levelname == "WARNING"
    assert "vfr.mkv" not in skip_logs[0].getMessage()  # content-free: no title, no path
    # Never more than the bound behind, and on the clock right after the skip.
    assert max(lags) <= 0.5 + _BLOCK_S
    assert max(abs(x) for x in lags[103:]) < 1e-6
    # About 2 s of the item was not heard.
    assert pcm.size / SR == pytest.approx(CLIP_S - 2.0, abs=2 * _BLOCK_S)
    # Heard at the right programme time after the skip: loud inside the
    # 7.5-7.8 s and 9.4-9.7 s markers, quiet between them.
    blocks = pcm.reshape(-1, BLOCK).astype(np.float64)
    rms = np.sqrt((blocks * blocks).mean(axis=1))
    for t, block_rms in zip(stream.emitted_at, rms):
        if 7.55 <= t <= 7.72 or 9.45 <= t <= 9.62:
            assert block_rms > 2000.0, t
        if 7.95 <= t <= 9.25:
            assert block_rms < 50.0, t


def test_a_stall_past_the_item_end_resumes_in_the_next_item(tmp_path: Path, monkeypatch):  # noqa: ANN001
    _write_clip(tmp_path / "a.mkv", _cfr_times())
    _write_clip(tmp_path / "b.mkv", _vfr_times())
    manifest_path = _manifest(tmp_path, [("a.mkv", 25.0), ("b.mkv", 25.0)])
    pcm, stream = _deliver_all(manifest_path, monkeypatch, on_block=_stall_at(300, 3.0))
    assert stream._skips == 1
    container = av.open(str(tmp_path / "a.mkv"))
    item0 = container_duration_s(container)
    container.close()
    lags = _lags(stream, {0: 0.0, 1: item0})
    after = [i for i, (idx, _pos) in enumerate(stream.positions) if idx == 1]
    assert after and max(abs(lags[i]) for i in after) < 1e-6
    # It resumed about 2 s into the second item, at the clock.
    first_pos = stream.positions[after[0]][1] - _BLOCK_S
    assert first_pos == pytest.approx(9.0 + _BLOCK_S + 3.0 - item0, abs=2 * _BLOCK_S)
    # The second item's 4.0-4.3 s marker is heard at programme time item0 + 4.15.
    blocks = pcm.reshape(-1, BLOCK).astype(np.float64)
    rms = np.sqrt((blocks * blocks).mean(axis=1))
    at = [r for t, r in zip(stream.emitted_at, rms) if abs(t - (item0 + 4.15)) < 0.1]
    assert at and min(at) > 2000.0


def test_a_pause_is_not_owed(cfr_clip: Path, monkeypatch):  # noqa: ANN001
    """Time while the shared clock is paused (sleep, a freeze) is not a debt:
    nothing is skipped or caught up when it resumes."""
    holder: dict[str, PlaylistClock] = {}

    def _pause_for_5s(i: int, mclock: _ManualClock) -> None:
        if i == 100:
            holder["clock"].pause("test")
            mclock.t += 5.0
            holder["clock"].resume("test")

    mclock = _ManualClock()
    clock = PlaylistClock(1, clock=mclock)
    holder["clock"] = clock
    pcm, stream = _deliver_all(
        cfr_clip, monkeypatch, clock=clock, mclock=mclock, on_block=_pause_for_5s
    )
    assert stream._skips == 0
    assert pcm.size == math.ceil(int(round(CLIP_S * SR)) / BLOCK) * BLOCK
    # Measured on the programme clock (wall time less the 5 s pause), every
    # block went out exactly when it was due.
    for i, ((_idx, pos), t) in enumerate(zip(stream.positions, stream.emitted_at)):
        paused = 5.0 if i > 100 else 0.0
        assert abs((t - paused) - (pos - _BLOCK_S)) < 1e-6, i



# ---------------------------------------------------------------------------
# Damaged media, failing items, and what the logs may say
# ---------------------------------------------------------------------------

_TITLE = "Secret_Film_Title"


def _noise_clip(path: Path, seconds: float = 20.0) -> None:
    """VP8 noise at 25 fps in WebM: large packets, so scattered byte damage
    lands in frame data rather than in the container structure."""
    rng = np.random.default_rng(0)
    out = av.open(str(path), mode="w", format="webm")
    vs = out.add_stream("libvpx", rate=25)
    vs.width, vs.height, vs.pix_fmt = W, H, "yuv420p"
    vs.time_base = fractions.Fraction(1, 1000)
    vs.codec_context.time_base = fractions.Fraction(1, 1000)
    vs.codec_context.gop_size = 50
    for i in range(int(seconds * 25)):
        frame = av.VideoFrame.from_ndarray(
            rng.integers(0, 255, (H, W, 3), dtype=np.uint8), format="rgb24"
        )
        frame.pts = i * 40
        frame.time_base = vs.time_base
        for packet in vs.encode(frame):
            out.mux(packet)
    for packet in vs.encode():
        out.mux(packet)
    out.close()


def _plain_decode_stops_at(path: Path) -> float | None:
    """Where ``container.decode`` (one generator for the whole stream) stops
    on an error, or None when it decodes to the end."""
    container = av.open(str(path))
    last = 0.0
    try:
        for frame in container.decode(container.streams.video[0]):
            last = float(frame.pts) / 1000.0
    except av.error.FFmpegError:
        return last
    finally:
        container.close()
    return None


def _damaged_clip(tmp_path: Path, name: str) -> Path:
    """A 20 s clip with a few flipped bytes, chosen so that a whole-stream
    decode stops early on an error (the defect being guarded)."""
    import random

    clean = tmp_path / "clean-noise.webm"
    if not clean.exists():
        _noise_clip(clean)
    data = clean.read_bytes()
    for seed in range(60):
        damaged = bytearray(data)
        rng = random.Random(seed)
        for _ in range(60):
            k = rng.randrange(4096, len(damaged))
            damaged[k] ^= 0xFF
        path = tmp_path / name
        path.write_bytes(bytes(damaged))
        stop = _plain_decode_stops_at(path)
        if stop is not None and stop < 15.0:
            return path
    raise AssertionError("no damage pattern made the whole-stream decode stop early")


def test_a_bad_packet_does_not_freeze_the_picture_for_the_rest_of_the_item(tmp_path: Path):
    """A packet that fails to decode is skipped: frames after it are still
    presented, where a whole-stream decode would end at the error."""
    path = _damaged_clip(tmp_path, "damaged.webm")
    decoder = PyAvVideoDecoder(av, path, nominal_fps=25.0)
    times = []
    try:
        while (nxt := decoder.next()) is not None:
            times.append(nxt[0])
    finally:
        decoder.close()
    assert decoder.skipped_packets >= 1
    assert times[-1] == pytest.approx(19.96, abs=0.05)
    assert len(times) >= 480
    # Through the source: at 17 s the picture is from 17 s, not held at the error.
    mclock = _ManualClock()
    src = _video(_manifest(tmp_path, [("damaged.webm", 25.0)]), PlaylistClock(1, clock=mclock))
    try:
        _read_at(src, mclock, 0.0)
        _read_at(src, mclock, 17.0)
        assert 16.9 <= src._shown.t <= 17.0
    finally:
        src.release()


def test_a_video_item_that_cannot_be_opened_does_not_end_the_picture(tmp_path: Path):
    """The source shows nothing while the clock is on an item it cannot open
    and carries on with the next item when the clock gets there."""
    _write_clip(tmp_path / "a.mkv", _cfr_times())
    (tmp_path / "junk.mkv").write_bytes(b"this is not media" * 100)
    _write_clip(tmp_path / "b.mkv", _cfr_times())
    manifest_path = _manifest(tmp_path, [("a.mkv", 25.0), ("junk.mkv", 25.0), ("b.mkv", 25.0)])
    mclock = _ManualClock()
    clock = PlaylistClock(3, clock=mclock)
    src = _video(manifest_path, clock)
    try:
        _read_at(src, mclock, 0.0)
        clock.set_duration(1, 5.0)  # known from elsewhere (the audio surface)
        mclock.t = CLIP_S + 1.0
        assert src.read() == (False, None)
        img = _read_at(src, mclock, CLIP_S + 5.0 + 4.17)
        assert src.current_item.item_idx == 2
        assert _right_white(img) and _left_level(img) == pytest.approx(_decile_level(4.17), abs=4)
    finally:
        src.release()


def test_feed_logs_name_items_by_index_never_by_path_or_title(tmp_path: Path, monkeypatch, caplog):  # noqa: ANN001
    """No title, file name or path appears in any feed log record (message or
    attached exception) for: an item without audio, a file that is not media,
    a file without a video stream, and a packet that fails to decode."""
    import logging

    caplog.set_level(logging.DEBUG, logger="kaine.modules.vision.feed")
    caplog.set_level(logging.DEBUG, logger="kaine.modules.audition.feed")
    _write_clip(tmp_path / f"{_TITLE}_silent.mkv", _cfr_times(), audio=False)
    (tmp_path / f"{_TITLE}_junk.mkv").write_bytes(b"this is not media" * 100)
    _damaged_clip(tmp_path, f"{_TITLE}_damaged.webm")
    audio_only = tmp_path / f"{_TITLE}_audio_only.mkv"
    out = av.open(str(audio_only), mode="w", format="matroska")
    astream = out.add_stream("pcm_s16le", rate=SR)
    astream.layout = "mono"
    frame = av.AudioFrame.from_ndarray(np.zeros((1, SR), np.int16), format="s16", layout="mono")
    frame.rate = SR
    for packet in astream.encode(frame):
        out.mux(packet)
    for packet in astream.encode(None):
        out.mux(packet)
    out.close()

    # Video: a file that is not media, a file without a video stream, a bad packet.
    for name in (f"{_TITLE}_junk.mkv", audio_only.name):
        src = PlaylistSource(
            load_playlist_manifest(_manifest(tmp_path, [(name, 25.0)])),
            playlist_clock=PlaylistClock(1, clock=_ManualClock()),
        )
        assert src.open() is False
        src.release()
    mclock = _ManualClock()
    src = _video(_manifest(tmp_path, [(f"{_TITLE}_damaged.webm", 25.0)]), PlaylistClock(1, clock=mclock))
    for t in np.arange(0.0, 19.5, 0.5):  # through the damage, no seek past it
        _read_at(src, mclock, float(t))
    src.release()
    # Audio: an item without audio, a file that is not media.
    mclock = _ManualClock()
    clock = PlaylistClock(2, clock=mclock)
    clock.set_duration(1, 1.0)  # the unreadable item's length, from the video surface
    _deliver_all(
        _manifest(tmp_path, [(f"{_TITLE}_silent.mkv", 25.0), (f"{_TITLE}_junk.mkv", 25.0)]),
        monkeypatch, clock=clock, mclock=mclock,
    )

    messages = [r.getMessage() for r in caplog.records]
    assert any("has no audio track" in m for m in messages)
    assert any("could not be opened" in m for m in messages)
    assert any("skipped a packet" in m for m in messages)
    assert any("failed (" in m for m in messages)
    for record in caplog.records:
        text = record.getMessage()
        if record.exc_info:
            text += logging.Formatter().formatException(record.exc_info)
        assert _TITLE not in text and str(tmp_path) not in text, text


@pytest.mark.slow
@pytest.mark.skipif(
    not os.environ.get("KAINE_PROGRAMME_MEDIA"),
    reason="set KAINE_PROGRAMME_MEDIA to a directory holding programme.toml and its films",
)
def test_programme_films_decode_to_their_container_length(tmp_path, monkeypatch, capsys, caplog):  # noqa: ANN001
    """Each programme film: decoded audio length against the container, and the
    presented frame against the clock at several offsets (seeking each time)."""
    manifest_path = Path(os.environ["KAINE_PROGRAMME_MEDIA"]) / "programme.toml"
    manifest = load_playlist_manifest(manifest_path)
    rows = []
    for item in manifest.items:
        # A one-item manifest per film, in tmp_path (the media stay read-only).
        single = tmp_path / f"{Path(item.path).stem}.toml"
        single.write_text(
            f'[[item]]\npath = "{item.path}"\nsha256 = "{item.sha256}"\nfps = {item.fps}\norder = 0\n',
            encoding="utf-8",
        )
        container = av.open(str(item.path))
        duration = container_duration_s(container)
        container.close()
        caplog.clear()
        with caplog.at_level("INFO", logger="kaine.modules.audition.feed"):
            pcm, _stream = _deliver_all(single, monkeypatch)
        audio_s = pcm.size / SR
        placed = [r.getMessage() for r in caplog.records if "playlist audio item" in r.getMessage()]
        leads = []
        for t in (60.0, 600.0, 1800.0, 3600.0, duration - 1.0):
            if t >= duration:
                continue
            mclock = _ManualClock()
            clock = PlaylistClock(1, clock=mclock)
            clock.start(at=0.0)
            mclock.t = t
            src = _video(single, clock)
            try:
                _read_at(src, mclock, t)
                leads.append((t, src._shown.t - t))
            finally:
                src.release()
        rows.append((Path(item.path).name, duration, audio_s, leads, placed))
        assert abs(audio_s - duration) <= BLOCK / SR + 1e-6, (item.path, audio_s, duration)
        for t, lead in leads:
            assert -0.1 <= lead <= 0.0, (item.path, t, lead)
    with capsys.disabled():
        for name, duration, audio_s, leads, placed in rows:
            print(f"\n{name}: container {duration:.3f} s, audio {audio_s:.3f} s, "
                  f"frame minus clock " + ", ".join(f"{t:.0f}s:{lead * 1000:+.0f}ms" for t, lead in leads))
            print("  " + "; ".join(placed))
