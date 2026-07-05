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
    PlaylistManifestError,
    PlaylistSource,
    PlaylistVerificationError,
    SeededProceduralSource,
    SeededSchedule,
    load_playlist_manifest,
)


# ---------------------------------------------------------------------------
# Seeded source
# ---------------------------------------------------------------------------


def _read_n(source: SeededProceduralSource, n: int) -> list[np.ndarray]:
    assert source.open()
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
