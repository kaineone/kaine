# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Deterministic perception-feed sources (reproducible-perception-feed).

Covers the seeded procedural source (pure-function determinism, seed-keyed
surprise, restart/seek reproducibility, cadence) and the playlist source
(manifest verify, fail-closed on mismatch, stable indexing). No real camera, no
disk writes of frames.
"""
from __future__ import annotations

import hashlib

import numpy as np
import pytest

from kaine.modules.topos.feed import (
    PlaylistClock,
    PlaylistManifestError,
    PlaylistPosition,
    PlaylistSource,
    PlaylistVerificationError,
    SeededProceduralSource,
    SeededSchedule,
    load_playlist_manifest,
)


# ---------------------------------------------------------------------------
# Fake cv2 decoder for real-time playlist pacing tests (no OpenCV, no media).
# Each fake frame is tagged (path, media_frame_index) so a test can assert
# exactly which media frame the source returned at a given elapsed time.
# ---------------------------------------------------------------------------


class _FakeCap:
    def __init__(self, path: str, frame_count: int) -> None:
        self._path = path
        self._n = frame_count
        self._i = 0

    def isOpened(self) -> bool:
        return True

    def get(self, prop) -> float:  # noqa: ANN001 — only FRAME_COUNT is queried
        return float(self._n)

    def read(self):
        if self._i >= self._n:
            return False, None
        frame = (self._path, self._i)
        self._i += 1
        return True, frame

    def release(self) -> None:
        return None


class _FakeCv2:
    CAP_PROP_FRAME_COUNT = 7  # arbitrary sentinel; the source only reads .get()

    def __init__(self, frame_counts: dict[str, int]) -> None:
        # frame_counts keyed by basename (paths are resolved absolute at open).
        self._frame_counts = frame_counts

    def VideoCapture(self, path: str):  # noqa: N802 — mirrors cv2 API
        import os

        base = os.path.basename(path)
        return _FakeCap(base, self._frame_counts[base])


class _FakeClock:
    """Manually advanced monotonic clock."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


# ---------------------------------------------------------------------------
# Seeded source
# ---------------------------------------------------------------------------


def _read_n(source: SeededProceduralSource, n: int) -> list[np.ndarray]:
    opened = source.open()
    assert opened
    frames = []
    for _ in range(n):
        ok, frame = source.read()
        assert ok
        frames.append(frame)
    source.release()
    return frames


def test_seeded_frame_is_correct_shape_and_dtype():
    src = SeededProceduralSource(SeededSchedule(seed=1, width=64, height=48))
    src.open()
    ok, frame = src.read()
    assert ok
    assert frame.shape == (48, 64, 3)
    assert frame.dtype == np.uint8


def test_same_seed_reproduces_identical_frame_bytes():
    sched = SeededSchedule(seed=42, width=48, height=32, surprise_interval=4)
    a = _read_n(SeededProceduralSource(sched), 20)
    b = _read_n(SeededProceduralSource(sched), 20)
    for i, (fa, fb) in enumerate(zip(a, b)):
        assert np.array_equal(fa, fb), f"frame {i} differs across runs of one seed"


def test_restart_and_seek_reproduce_frame_i():
    """frame_at(i) is a pure function of (seed, i): same regardless of the path
    taken to it (sequential read vs direct seek vs restart)."""
    sched = SeededSchedule(seed=99, width=40, height=40, surprise_interval=3)
    src = SeededProceduralSource(sched)
    seq = _read_n(src, 15)
    # Direct seek to index 7 after a fresh open.
    src2 = SeededProceduralSource(sched)
    src2.open()
    seek_7 = src2.frame_at(7)
    src2.release()
    assert np.array_equal(seq[7], seek_7)
    # Restart and re-read: index 7 is identical again.
    restart = _read_n(SeededProceduralSource(sched), 8)
    assert np.array_equal(seq[7], restart[7])


def test_different_seeds_decorrelate_surprise_schedules():
    a = SeededProceduralSource(SeededSchedule(seed=1, surprise_interval=10))
    b = SeededProceduralSource(SeededSchedule(seed=2, surprise_interval=10))
    sa = a.surprise_indices(2000)
    sb = b.surprise_indices(2000)
    assert sa != sb, "different seeds must not produce the identical schedule"
    # Not merely a shift: the symmetric difference is substantial.
    sym_diff = set(sa) ^ set(sb)
    assert len(sym_diff) > 0.2 * (len(sa) + len(sb))


def test_different_seeds_decorrelate_base_world():
    """Regression for the ~1.3% bug: the BASE visual world — not only the
    surprise schedule — is now seed-keyed, so with surprises OFF a substantial
    fraction of frames differ between two seeds (unified-perception-feed)."""
    common = dict(width=64, height=48, surprise_interval=100000, surprise_strength=0.0)
    a = SeededProceduralSource(SeededSchedule(seed=1, **common))
    b = SeededProceduralSource(SeededSchedule(seed=2, **common))
    diff = sum(1 for i in range(200) if not np.array_equal(a.frame_at(i), b.frame_at(i)))
    assert diff > 0.8 * 200, (
        f"only {diff}/200 base frames differ between seeds — base world is not "
        f"seed-keyed (regression of the ~1.3% bug)"
    )


def test_surprise_cadence_matches_config():
    """Surprises only ever fire on cadence slots (multiples of the interval),
    never off-cadence — the cadence is legible even though onset is seeded."""
    interval = 12
    src = SeededProceduralSource(SeededSchedule(seed=5, surprise_interval=interval))
    idxs = src.surprise_indices(600)
    assert idxs, "expected some surprises over 600 frames"
    for i in idxs:
        assert i % interval == 0 and i > 0, f"surprise at off-cadence index {i}"


def test_surprise_strength_zero_disables_surprise_but_keeps_base_signal():
    src = SeededProceduralSource(
        SeededSchedule(seed=5, surprise_interval=4, surprise_strength=0.0)
    )
    assert src.surprise_indices(200) == []
    # Base signal still varies frame to frame (learnable structure present).
    frames = _read_n(src, 10)
    assert not np.array_equal(frames[0], frames[5])


def test_surprise_not_derivable_without_seed():
    """A surprise frame's content is a seed-keyed draw: two seeds whose base
    signal is identical (same width/height/interval) still differ on the
    surprise frame, so the surprise is not derivable from the base alone."""
    common = dict(width=32, height=32, surprise_interval=3, surprise_strength=1.0)
    a = SeededProceduralSource(SeededSchedule(seed=11, **common))
    b = SeededProceduralSource(SeededSchedule(seed=12, **common))
    # Find a frame index where BOTH fire, then compare content.
    fa = set(a.surprise_indices(300))
    fb = set(b.surprise_indices(300))
    both = sorted(fa & fb)
    assert both, "expected a shared surprise slot for the two seeds"
    i = both[0]
    frame_a = a.frame_at(i)
    frame_b = b.frame_at(i)
    assert not np.array_equal(frame_a, frame_b), (
        "surprise content must be seed-keyed, not derivable from the base signal"
    )


def test_descriptor_round_trips_to_regenerate():
    sched = SeededSchedule(seed=7, width=48, height=36, surprise_interval=5,
                           surprise_strength=0.5)
    desc = sched.as_descriptor()
    # Reconstruct a schedule from the descriptor and confirm bit-identical output.
    rebuilt = SeededSchedule(
        seed=desc["seed"],
        width=desc["width"],
        height=desc["height"],
        surprise_interval=desc["surprise_interval"],
        surprise_strength=desc["surprise_strength"],
    )
    a = _read_n(SeededProceduralSource(sched), 12)
    b = _read_n(SeededProceduralSource(rebuilt), 12)
    for fa, fb in zip(a, b):
        assert np.array_equal(fa, fb)


# ---------------------------------------------------------------------------
# Playlist source
# ---------------------------------------------------------------------------


def _write_manifest(tmp_path, items):
    lines = []
    for it in items:
        lines.append("[[item]]")
        lines.append(f'path = "{it["path"]}"')
        lines.append(f'sha256 = "{it["sha256"]}"')
        lines.append(f'fps = {it["fps"]}')
        if "order" in it:
            lines.append(f'order = {it["order"]}')
        lines.append("")
    manifest = tmp_path / "playlist.toml"
    manifest.write_text("\n".join(lines), encoding="utf-8")
    return manifest


def test_load_manifest_orders_by_order_key(tmp_path):
    (tmp_path / "b.mp4").write_bytes(b"bbb")
    (tmp_path / "a.mp4").write_bytes(b"aaa")
    sha_b = hashlib.sha256(b"bbb").hexdigest()
    sha_a = hashlib.sha256(b"aaa").hexdigest()
    manifest = _write_manifest(
        tmp_path,
        [
            {"path": "b.mp4", "sha256": sha_b, "fps": 30, "order": 1},
            {"path": "a.mp4", "sha256": sha_a, "fps": 24, "order": 0},
        ],
    )
    parsed = load_playlist_manifest(manifest)
    assert [it.path for it in parsed.items] == ["a.mp4", "b.mp4"]
    assert parsed.items[0].fps == 24.0


def test_manifest_rejects_bad_sha(tmp_path):
    manifest = _write_manifest(
        tmp_path, [{"path": "x.mp4", "sha256": "not-hex", "fps": 30}]
    )
    with pytest.raises(PlaylistManifestError):
        load_playlist_manifest(manifest)


def test_verified_manifest_opens_and_descriptor_records_digests(tmp_path):
    (tmp_path / "clip.mp4").write_bytes(b"hello-media")
    sha = hashlib.sha256(b"hello-media").hexdigest()
    manifest = _write_manifest(tmp_path, [{"path": "clip.mp4", "sha256": sha, "fps": 30}])
    parsed = load_playlist_manifest(manifest)
    src = PlaylistSource(parsed)
    # verify() alone passes for a matching file (open() also decodes via cv2,
    # which a 11-byte non-video file can't do — verification is the invariant).
    src.verify()
    desc = parsed.as_descriptor()
    assert desc["manifest_sha256"] == hashlib.sha256(manifest.read_bytes()).hexdigest()
    assert desc["item_digests"][0]["sha256"] == sha


def test_digest_mismatch_fails_closed(tmp_path):
    (tmp_path / "clip.mp4").write_bytes(b"original")
    sha = hashlib.sha256(b"original").hexdigest()
    manifest = _write_manifest(tmp_path, [{"path": "clip.mp4", "sha256": sha, "fps": 30}])
    parsed = load_playlist_manifest(manifest)
    # Operator (or attacker) swaps the file after the manifest was authored.
    (tmp_path / "clip.mp4").write_bytes(b"tampered")
    src = PlaylistSource(parsed)
    with pytest.raises(PlaylistVerificationError):
        src.verify()
    # open() must also fail closed (verify is called first).
    with pytest.raises(PlaylistVerificationError):
        src.open()


def test_missing_media_fails_closed(tmp_path):
    sha = hashlib.sha256(b"whatever").hexdigest()
    manifest = _write_manifest(tmp_path, [{"path": "gone.mp4", "sha256": sha, "fps": 30}])
    parsed = load_playlist_manifest(manifest)
    src = PlaylistSource(parsed)
    with pytest.raises(PlaylistVerificationError):
        src.verify()


# ---------------------------------------------------------------------------
# Real-time playlist pacing (playlist-realtime-av-sync)
# ---------------------------------------------------------------------------


def _one_item_source(tmp_path, *, fps, frame_count):
    """A verified single-item PlaylistSource wired to a fake cv2 + fake clock."""
    (tmp_path / "clip.mp4").write_bytes(b"clip-media-0")
    sha = hashlib.sha256(b"clip-media-0").hexdigest()
    manifest = _write_manifest(tmp_path, [{"path": "clip.mp4", "sha256": sha, "fps": fps}])
    parsed = load_playlist_manifest(manifest)
    clock = PlaylistClock(len(parsed.items), clock=_FakeClock())
    fake_clock = clock._clock  # the _FakeClock instance
    src = PlaylistSource(
        parsed,
        playlist_clock=clock,
        cv2_module=_FakeCv2({"clip.mp4": frame_count}),
    )
    assert src.open()
    return src, fake_clock


def test_playlist_video_selects_frame_at_elapsed(tmp_path):
    """A given elapsed wall-clock position selects the expected media frame
    (elapsed x fps), NOT the next sequential frame — the real-time-pacing fix."""
    src, clk = _one_item_source(tmp_path, fps=30, frame_count=600)
    clk.t = 0.0
    ok, frame = src.read()
    assert ok and frame == ("clip.mp4", 0)
    # 0.5 s in at 30 fps -> frame 15 (frames 1..14 dropped to track 1x).
    clk.t = 0.5
    ok, frame = src.read()
    assert ok and frame == ("clip.mp4", 15)
    # 2.0 s in -> frame 60.
    clk.t = 2.0
    ok, frame = src.read()
    assert ok and frame == ("clip.mp4", 60)


def test_playlist_video_holds_frame_when_tick_faster_than_fps(tmp_path):
    """Ticking faster than the frame rate re-presents the current frame instead
    of consuming the next media frame (so a 30 fps clip does not race ahead)."""
    src, clk = _one_item_source(tmp_path, fps=30, frame_count=600)
    clk.t = 0.0  # first read fixes the shared origin at t=0
    assert src.read()[1] == ("clip.mp4", 0)
    clk.t = 0.20  # 0.20 * 30 = 6 -> frame 6
    ok, first = src.read()
    assert ok and first == ("clip.mp4", 6)
    # Only 10 ms later: 0.21 * 30 = 6.3 -> still frame 6. HELD.
    clk.t = 0.21
    ok, held = src.read()
    assert ok and held == ("clip.mp4", 6)
    # Cross into the next frame boundary: 0.24 * 30 = 7.2 -> frame 7.
    clk.t = 0.24
    ok, nxt = src.read()
    assert ok and nxt == ("clip.mp4", 7)


def test_playlist_video_drops_frames_when_tick_slower_than_fps(tmp_path):
    """Ticking slower than the frame rate drops the intervening frames so the
    video tracks 1x rather than playing back in slow motion."""
    src, clk = _one_item_source(tmp_path, fps=30, frame_count=600)
    clk.t = 0.0
    assert src.read()[1] == ("clip.mp4", 0)
    # One second later, at 30 fps, we must be at frame 30 (not frame 1).
    clk.t = 1.0
    assert src.read()[1] == ("clip.mp4", 30)


def test_playlist_video_advances_item_at_real_time_end(tmp_path):
    """The item advances when the real-time position passes the file's end —
    driven by the shared clock's per-item durations, not by exhausting frames."""
    (tmp_path / "a.mp4").write_bytes(b"aaa")
    (tmp_path / "b.mp4").write_bytes(b"bbb")
    sha_a = hashlib.sha256(b"aaa").hexdigest()
    sha_b = hashlib.sha256(b"bbb").hexdigest()
    manifest = _write_manifest(
        tmp_path,
        [
            {"path": "a.mp4", "sha256": sha_a, "fps": 30, "order": 0},
            {"path": "b.mp4", "sha256": sha_b, "fps": 30, "order": 1},
        ],
    )
    parsed = load_playlist_manifest(manifest)
    clock = PlaylistClock(len(parsed.items), clock=_FakeClock())
    clk = clock._clock
    src = PlaylistSource(
        parsed,
        playlist_clock=clock,
        cv2_module=_FakeCv2({"a.mp4": 60, "b.mp4": 60}),  # 2 s each at 30 fps
    )
    assert src.open()
    clk.t = 0.0
    assert src.read()[1] == ("a.mp4", 0)  # item 0
    assert src.current_item.item_idx == 0
    # 2.5 s in: item 0 (2 s) is done -> item 1 at 0.5 s -> frame 15.
    clk.t = 2.5
    ok, frame = src.read()
    assert ok and frame == ("b.mp4", 15)
    assert src.current_item.item_idx == 1
    assert src.current_item.title == "b.mp4"


def test_playlist_video_exhausts_after_last_item(tmp_path):
    """Past the end of the whole playlist, read() returns (False, None)."""
    src, clk = _one_item_source(tmp_path, fps=30, frame_count=60)  # 2 s
    clk.t = 0.0
    assert src.read()[0] is True
    clk.t = 5.0  # well past the single 2 s item
    ok, frame = src.read()
    assert ok is False and frame is None


def test_playlist_current_item_is_none_before_start(tmp_path):
    (tmp_path / "clip.mp4").write_bytes(b"clip-media-0")
    sha = hashlib.sha256(b"clip-media-0").hexdigest()
    manifest = _write_manifest(tmp_path, [{"path": "clip.mp4", "sha256": sha, "fps": 30}])
    parsed = load_playlist_manifest(manifest)
    src = PlaylistSource(parsed, playlist_clock=PlaylistClock(1, clock=_FakeClock()))
    # Not opened / clock not started yet.
    assert src.current_item is None


def test_playlist_current_item_provenance_is_content_free(tmp_path):
    """current_item carries only basename + manifest order + offset — never any
    pixels, so the item is readable off the bus without leaking frame content."""
    src, clk = _one_item_source(tmp_path, fps=30, frame_count=600)
    clk.t = 1.0
    src.read()
    pos = src.current_item
    assert isinstance(pos, PlaylistPosition)
    assert pos.title == "clip.mp4"
    assert pos.order == 0
    assert isinstance(pos.title, str) and isinstance(pos.order, int)


# ---------------------------------------------------------------------------
# Shared start-clock: video and audio agree on the playing item
# ---------------------------------------------------------------------------


def test_shared_clock_keeps_video_and_audio_on_the_same_item(tmp_path):
    """Video (PlaylistSource) and audio (PlaylistAudioStream) fed ONE shared
    PlaylistClock report the same item across a simulated boundary — the fix for
    seeing one show while hearing another."""
    from kaine.modules.audition.feed import PlaylistAudioStream

    (tmp_path / "a.mp4").write_bytes(b"aaa")
    (tmp_path / "b.mp4").write_bytes(b"bbb")
    sha_a = hashlib.sha256(b"aaa").hexdigest()
    sha_b = hashlib.sha256(b"bbb").hexdigest()
    manifest = _write_manifest(
        tmp_path,
        [
            {"path": "a.mp4", "sha256": sha_a, "fps": 30, "order": 0},
            {"path": "b.mp4", "sha256": sha_b, "fps": 30, "order": 1},
        ],
    )
    parsed = load_playlist_manifest(manifest)
    clock = PlaylistClock(len(parsed.items), clock=_FakeClock())
    clk = clock._clock
    video = PlaylistSource(
        parsed,
        playlist_clock=clock,
        cv2_module=_FakeCv2({"a.mp4": 60, "b.mp4": 60}),  # 2 s each
    )
    audio = PlaylistAudioStream(parsed, callback=lambda _b: None, playlist_clock=clock)
    assert video.open()  # registers item 0's duration; audio shares the clock

    clk.t = 0.5
    video.read()
    assert video.current_item.item_idx == 0
    assert audio.current_item.item_idx == 0
    assert video.current_item.title == audio.current_item.title == "a.mp4"

    clk.t = 2.5  # past item 0's 2 s boundary
    video.read()
    assert video.current_item.item_idx == 1
    assert audio.current_item.item_idx == 1
    assert video.current_item.title == audio.current_item.title == "b.mp4"
