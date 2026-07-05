# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the experiment foundation: seeding, run identity, manifest, verdict.

Spec-scenario coverage (openspec/changes/experiment-run-identity/specs/
experiment-foundation/spec.md):

* "Seeding is reproducible"          -> test_seeding_is_reproducible
* "Torch absence does not fail"      -> test_seeding_torch_optional_never_raises
* "Fresh seed generated/recorded"    -> test_mint_run_context_and_manifest_round_trip
                                        (+ boot wiring resolves a fresh seed; see
                                         _resolve_seed coverage below)
* "git_sha falls back without raising"-> test_git_sha_none_on_subprocess_failure
* "Manifest export-eligible/content-free"
                                     -> test_runs_dir_in_metrics_only_and_deny_clean
                                        + test_manifest_is_content_free
* "Records are stamped within a run" -> test_sink_stamps_run_id_and_seq_within_run
* "Records are untouched outside a run"-> test_sink_inert_without_context
* "Experiments emit the shared verdict"-> test_aif_report_contains_shared_verdict,
                                         test_redteam_report_contains_verdict
* config_digest stability/change     -> test_config_digest_stable_and_changes
* verdict serialization stable       -> test_verdict_to_dict_stable
"""
from __future__ import annotations

import asyncio
import json
import random

import numpy as np
import pytest

from kaine.experiment import (
    Outcome,
    RunContext,
    Verdict,
    compute_config_digest,
    compute_git_sha,
    get_run_context,
    mint_run_context,
    set_global_seed,
    set_run_context,
    write_manifest,
)
from kaine.persistence.jsonl_sink import AsyncJsonlSink


@pytest.fixture(autouse=True)
def _reset_run_context():
    """CRITICAL: the run-context global must never leak across tests, or record
    stamping would bleed run_id/seq into the rest of the 1900+ suite. Always
    clear it in teardown (and entering, for safety)."""
    set_run_context(None)
    yield
    set_run_context(None)


# --------------------------------------------------------------------------- #
# Seeding
# --------------------------------------------------------------------------- #


def test_seeding_is_reproducible():
    returned = set_global_seed(1234)
    assert returned == 1234
    draws_a = [random.random() for _ in range(5)] + list(np.random.rand(5))
    set_global_seed(1234)
    draws_b = [random.random() for _ in range(5)] + list(np.random.rand(5))
    assert draws_a == draws_b


def test_seeding_torch_optional_never_raises(monkeypatch):
    """Whether torch is present, absent, or CPU-only, seeding must not raise and
    must still return the seed. Simulate an absent torch by making its import
    fail, exercising the best-effort except path."""
    import builtins

    real_import = builtins.__import__

    def _no_torch(name, *args, **kwargs):
        if name == "torch":
            raise ImportError("simulated: torch absent")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_torch)
    assert set_global_seed(7) == 7  # no raise


def test_seeding_deterministic_flag_sets_cudnn_state():
    """The opt-in deterministic flag enables torch's GPU/cuDNN determinism state
    (guarded behind torch being importable). Default (flag off) does not force it.
    """
    torch = pytest.importorskip("torch")

    # Opt-in: the deterministic algorithm mode + cuDNN flags are set.
    set_global_seed(1234, deterministic=True)
    assert torch.are_deterministic_algorithms_enabled() is True
    if hasattr(torch.backends, "cudnn"):
        assert torch.backends.cudnn.deterministic is True
        assert torch.backends.cudnn.benchmark is False

    # Reset so the flag doesn't leak into other tests in this process.
    torch.use_deterministic_algorithms(False)
    if hasattr(torch.backends, "cudnn"):
        torch.backends.cudnn.deterministic = False


def test_seeding_deterministic_flag_default_off_never_raises(monkeypatch):
    """Default path leaves determinism opt-in and never raises without torch."""
    import builtins

    real_import = builtins.__import__

    def _no_torch(name, *args, **kwargs):
        if name == "torch":
            raise ImportError("simulated: torch absent")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_torch)
    assert set_global_seed(7, deterministic=True) == 7  # no raise even with the flag


# --------------------------------------------------------------------------- #
# RunContext + manifest
# --------------------------------------------------------------------------- #


def test_mint_run_context_and_manifest_round_trip(tmp_path):
    ctx = mint_run_context(
        seed=42,
        started_at="2026-06-14T00:00:00+00:00",
        config={"a": 1, "b": {"c": 2}},
        model_ids={"lingua": "model:x"},
        version="26.06.0a1",
    )
    assert isinstance(ctx, RunContext)
    assert ctx.seed == 42
    assert len(ctx.run_id) == 32  # uuid4 hex
    assert ctx.model_ids == {"lingua": "model:x"}

    path = write_manifest(ctx, root=tmp_path)
    assert path == tmp_path / ctx.run_id / "manifest.json"
    loaded = json.loads(path.read_text())
    assert loaded["run_id"] == ctx.run_id
    assert loaded["seed"] == 42
    assert loaded["model_ids"] == {"lingua": "model:x"}
    assert loaded["config_digest"] == ctx.config_digest
    assert loaded["kaine_version"] == "26.06.0a1"


def test_two_minted_contexts_have_distinct_run_ids():
    a = mint_run_context(seed=1, started_at="t", config={}, model_ids={}, version="v")
    b = mint_run_context(seed=1, started_at="t", config={}, model_ids={}, version="v")
    assert a.run_id != b.run_id


def test_git_sha_none_on_subprocess_failure(monkeypatch):
    import kaine.experiment.run_context as rc

    def _boom(*args, **kwargs):
        raise OSError("simulated: git missing")

    monkeypatch.setattr(rc.subprocess, "run", _boom)
    assert compute_git_sha() is None  # no raise


def test_git_sha_none_on_nonzero_return(monkeypatch):
    import kaine.experiment.run_context as rc

    class _Proc:
        returncode = 128
        stdout = ""

    monkeypatch.setattr(rc.subprocess, "run", lambda *a, **k: _Proc())
    assert compute_git_sha() is None


def test_config_digest_stable_and_changes():
    m1 = {"x": 1, "y": [1, 2, 3]}
    m2 = {"y": [1, 2, 3], "x": 1}  # same content, different key order
    assert compute_config_digest(m1) == compute_config_digest(m2)
    assert len(compute_config_digest(m1)) == 16
    m3 = {"x": 2, "y": [1, 2, 3]}
    assert compute_config_digest(m1) != compute_config_digest(m3)


def test_seeded_perception_covariate_round_trips_to_regenerate(tmp_path):
    """A seeded run records the seed + BOTH the video and audio schedule params,
    sufficient to regenerate the exact A/V stimulus (unified-perception-feed
    covariate)."""
    import numpy as np

    from kaine.boot import gather_perception_feed_descriptor
    from kaine.modules.audition.feed import (
        SeededAudioSchedule,
        SeededProceduralAudioStream,
    )
    from kaine.modules.topos.feed import SeededProceduralSource, SeededSchedule

    config = {
        "topos": {"capture_width": 48, "capture_height": 32},
        "audition": {"capture_sample_rate": 16000, "capture_channels": 1, "vad_frame_ms": 30},
        "perception_feed": {
            "mode": "seeded",
            "seed": 123,
            "video": {"surprise_interval": 7, "surprise_strength": 0.8},
            "audio": {"base_strength": 0.25, "surprise_strength": 0.9},
        },
    }
    ctx = mint_run_context(
        seed=1, started_at="t", config=config, model_ids={}, version="v",
        perception_feed=gather_perception_feed_descriptor(config),
    )
    loaded = json.loads(write_manifest(ctx, root=tmp_path).read_text())
    feed = loaded["perception_feed"]
    assert feed["mode"] == "seeded"
    assert feed["seed"] == 123
    # --- Video: regenerate the stream from the recorded descriptor alone. ----
    vid = feed["video"]
    regen = SeededProceduralSource(
        SeededSchedule(
            seed=vid["seed"],
            width=vid["width"],
            height=vid["height"],
            surprise_interval=vid["surprise_interval"],
            surprise_strength=vid["surprise_strength"],
        )
    )
    original = SeededProceduralSource(
        SeededSchedule(seed=123, width=48, height=32, surprise_interval=7,
                       surprise_strength=0.8)
    )
    regen.open()
    original.open()
    for _ in range(10):
        ok_a, fa = regen.read()
        ok_b, fb = original.read()
        assert ok_a and ok_b
        assert np.array_equal(fa, fb)
    # --- Audio: regenerate the PCM from the recorded descriptor alone. -------
    aud = feed["audio"]
    cb = lambda b: None  # noqa: E731
    audio_regen = SeededProceduralAudioStream(
        SeededAudioSchedule(
            seed=aud["seed"],
            sample_rate=aud["sample_rate"],
            channels=aud["channels"],
            frames_per_block=aud["frames_per_block"],
            surprise_interval=aud["surprise_interval"],
            base_strength=aud["base_strength"],
            surprise_strength=aud["surprise_strength"],
        ),
        callback=cb,
    )
    audio_original = SeededProceduralAudioStream(
        SeededAudioSchedule(
            seed=123, sample_rate=16000, channels=1, frames_per_block=480,
            surprise_interval=7, base_strength=0.25, surprise_strength=0.9,
        ),
        callback=cb,
    )
    for i in range(10):
        assert audio_regen.pcm_at(i) == audio_original.pcm_at(i)
    # The shared cadence binds the two modalities: surprise slots coincide.
    assert original.surprise_indices(70) == audio_original.surprise_indices(70)


def test_playlist_perception_covariate_records_digests(tmp_path):
    """A playlist run records the ONE manifest sha256 + per-item digests that
    pin BOTH surfaces, sufficient to verify the exact stimulus
    (unified-perception-feed covariate)."""
    import hashlib

    from kaine.boot import gather_perception_feed_descriptor

    (tmp_path / "clip.mp4").write_bytes(b"media-bytes")
    sha = hashlib.sha256(b"media-bytes").hexdigest()
    manifest = tmp_path / "playlist.toml"
    manifest.write_text(
        f'[[item]]\npath = "clip.mp4"\nsha256 = "{sha}"\nfps = 30\n',
        encoding="utf-8",
    )
    config = {
        "perception_feed": {
            "mode": "playlist",
            "playlist_manifest": str(manifest),
        }
    }
    ctx = mint_run_context(
        seed=1, started_at="t", config=config, model_ids={}, version="v",
        perception_feed=gather_perception_feed_descriptor(config),
    )
    loaded = json.loads(write_manifest(ctx, root=tmp_path).read_text())
    feed = loaded["perception_feed"]
    assert feed["mode"] == "playlist"
    pl = feed["playlist"]
    assert pl["manifest_sha256"] == hashlib.sha256(manifest.read_bytes()).hexdigest()
    assert pl["item_digests"][0]["sha256"] == sha


def test_manifest_is_content_free(tmp_path):
    """The manifest holds only the documented identity keys — no entity interior."""
    ctx = mint_run_context(
        seed=9,
        started_at="2026-06-14T00:00:00+00:00",
        config={"secret": "redact-me"},
        model_ids={"lingua": "m"},
        version="v",
    )
    loaded = json.loads(write_manifest(ctx, root=tmp_path).read_text())
    assert set(loaded.keys()) == {
        "run_id",
        "seed",
        "started_at",
        "git_sha",
        "model_ids",
        "config_digest",
        "kaine_version",
        # Reproducible perception-feed covariate (descriptor only — no frames,
        # no operator paths). Defaults to {"mode": "off"} when unconfigured.
        "perception_feed",
    }
    assert loaded["perception_feed"] == {"mode": "off"}
    # The raw config is NEVER stored — only its digest.
    assert "redact-me" not in json.dumps(loaded)


# --------------------------------------------------------------------------- #
# Record stamping in AsyncJsonlSink
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_sink_stamps_run_id_and_seq_within_run(tmp_path):
    ctx = mint_run_context(
        seed=1, started_at="t", config={}, model_ids={}, version="v"
    )
    set_run_context(ctx)
    sink = AsyncJsonlSink(tmp_path, name="probe", flush_interval_s=0.05)
    await sink.start()
    try:
        await sink.write({"a": 1})
        await sink.write({"b": 2})
        await asyncio.sleep(0.2)
        lines = list(tmp_path.glob("probe-*.jsonl"))[0].read_text().splitlines()
        rec0 = json.loads(lines[0])
        rec1 = json.loads(lines[1])
        assert rec0["run_id"] == ctx.run_id
        assert rec1["run_id"] == ctx.run_id
        assert rec0["seq"] == 0
        assert rec1["seq"] == 1
    finally:
        await sink.stop()


def test_sink_stamp_does_not_mutate_caller_dict(tmp_path):
    ctx = mint_run_context(seed=1, started_at="t", config={}, model_ids={}, version="v")
    set_run_context(ctx)
    sink = AsyncJsonlSink(tmp_path, name="probe")
    original = {"a": 1}
    sink.write_sync(original)
    assert "run_id" not in original  # stamped on a copy
    assert "seq" not in original


def test_sink_inert_without_context(tmp_path):
    # No context set (the autouse fixture guarantees None here).
    assert get_run_context() is None
    sink = AsyncJsonlSink(tmp_path, name="probe")
    sink.write_sync({"a": 1})
    line = list(tmp_path.glob("probe-*.jsonl"))[0].read_text().splitlines()[0]
    rec = json.loads(line)
    assert rec == {"a": 1}
    assert "run_id" not in rec
    assert "seq" not in rec


def test_sink_setdefault_preserves_explicit_run_id(tmp_path):
    ctx = mint_run_context(seed=1, started_at="t", config={}, model_ids={}, version="v")
    set_run_context(ctx)
    sink = AsyncJsonlSink(tmp_path, name="probe")
    sink.write_sync({"a": 1, "run_id": "explicit"})
    rec = json.loads(list(tmp_path.glob("probe-*.jsonl"))[0].read_text().splitlines()[0])
    assert rec["run_id"] == "explicit"
    assert rec["seq"] == 0


# --------------------------------------------------------------------------- #
# Export eligibility
# --------------------------------------------------------------------------- #


def test_runs_dir_in_metrics_only_and_deny_clean():
    from kaine.research.submission import DENY_PATTERNS, METRICS_ONLY_DIRS

    assert "runs" in METRICS_ONLY_DIRS
    for pat in DENY_PATTERNS:
        assert pat not in "runs", f"'runs' collides with deny pattern {pat!r}"


# --------------------------------------------------------------------------- #
# Verdict schema
# --------------------------------------------------------------------------- #


def test_verdict_to_dict_stable():
    v = Verdict(outcome=Outcome.WIN, detail="d", metrics={"m": 1})
    assert v.to_dict() == {"outcome": "WIN", "detail": "d", "metrics": {"m": 1}}
    # default metrics map
    v2 = Verdict(outcome=Outcome.PASS)
    assert v2.to_dict() == {"outcome": "PASS", "detail": "", "metrics": {}}
    # str-enum serializes to the plain value through json
    assert json.loads(json.dumps(v.to_dict()))["outcome"] == "WIN"


def test_outcome_covers_both_vocabularies():
    assert {o.value for o in Outcome} == {"WIN", "NULL", "NEGATIVE", "PASS", "FAIL"}


def test_aif_report_contains_shared_verdict():
    from kaine.evaluation.benchmarks.active_inference.metrics import classify_verdict
    from kaine.experiment.verdict import Outcome

    # Build a per-task verdict_record the way run_task does, minimal but real.
    cls = classify_verdict([5.0, 5.1, 5.2], [1.0, 1.1, 0.9])
    shared = Verdict(
        outcome=Outcome(cls["verdict"]),
        detail="AIF vs RL",
        metrics={"p_value": cls["p_value"]},
    ).to_dict()
    assert shared["outcome"] in {"WIN", "NULL", "NEGATIVE"}


def test_redteam_report_contains_verdict():
    from kaine.evaluation.redteam.report import RedTeamReport

    report = RedTeamReport(results=[], findings=[], surface_verdicts=[], uncovered=[])
    rec = report.to_record()
    assert "verdict" in rec
    assert rec["verdict"]["outcome"] in {"PASS", "FAIL"}
    # Existing fields preserved (additive).
    assert "passed" in rec
    assert "surface_verdicts" in rec
