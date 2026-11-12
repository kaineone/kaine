# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the model_rungs field on RunContext (task 11.3)."""

from __future__ import annotations

import pytest

from kaine.experiment.run_context import RunContext, mint_run_context

# ---------------------------------------------------------------------------
# Minimal kwargs for mint_run_context
# ---------------------------------------------------------------------------

_MINT_DEFAULTS: dict = {
    "seed": 42,
    "started_at": "2026-01-01T00:00:00Z",
    "config": {"modules": {}},
    "model_ids": {},
    "version": "0.0.0",
}


# ---------------------------------------------------------------------------
# RunContext dataclass
# ---------------------------------------------------------------------------


def test_model_rungs_default_empty() -> None:
    """model_rungs defaults to an empty dict on a bare RunContext."""
    ctx = RunContext(run_id="aaa", seed=1, started_at="t", git_sha=None)
    assert ctx.model_rungs == {}


def test_frozen_rejects_assignment() -> None:
    """RunContext is frozen: assigning to model_rungs raises."""
    ctx = RunContext(run_id="aaa", seed=1, started_at="t", git_sha=None)
    with pytest.raises(AttributeError):
        ctx.model_rungs = {"x": {}}  # type: ignore[misc]


# ---------------------------------------------------------------------------
# mint_run_context
# ---------------------------------------------------------------------------


def test_mint_none_gives_empty_dict() -> None:
    """Passing model_rungs=None (the default) produces an empty dict."""
    ctx = mint_run_context(**_MINT_DEFAULTS)
    assert ctx.model_rungs == {}


def test_mint_stores_rungs() -> None:
    """Explicit rungs are stored and accessible."""
    rung = {
        "vocal.tts": {
            "backend": "sherpa_onnx",
            "model_id": "kokoro-en",
            "quantization": "int8",
            "weights_sha256": None,
        },
    }
    ctx = mint_run_context(**_MINT_DEFAULTS, model_rungs=rung)
    assert ctx.model_rungs == rung


def test_mint_deep_copies_rungs() -> None:
    """mint_run_context deep-copies the mapping so mutations do not leak."""
    inner: dict[str, str | None] = {"backend": "x", "model_id": "y", "quantization": None, "weights_sha256": None}
    src = {"comp": inner}
    ctx = mint_run_context(**_MINT_DEFAULTS, model_rungs=src)
    inner["backend"] = "CHANGED"
    assert ctx.model_rungs["comp"]["backend"] == "x"


def test_to_dict_includes_model_rungs() -> None:
    """to_dict() output contains model_rungs."""
    rung = {
        "audition.stt": {
            "backend": "speaches",
            "model_id": "faster-distil-whisper-medium.en",
            "quantization": None,
            "weights_sha256": None,
        },
    }
    ctx = mint_run_context(**_MINT_DEFAULTS, model_rungs=rung)
    d = ctx.to_dict()
    assert "model_rungs" in d
    assert d["model_rungs"] == rung


# ---------------------------------------------------------------------------
# _gather_model_rungs (from kaine.cycle.__main__)
# ---------------------------------------------------------------------------


def test_gather_empty_config() -> None:
    """Empty config produces no rungs."""
    from kaine.cycle.__main__ import _gather_model_rungs

    assert _gather_model_rungs({}) == {}


def test_gather_vocal_tts() -> None:
    """vocal section with a backend populates vocal.tts rung."""
    from kaine.cycle.__main__ import _gather_model_rungs

    config = {"vocal": {"backend": "sherpa_onnx", "sherpa_model_id": "kokoro-en"}}
    rungs = _gather_model_rungs(config)
    assert "vocal.tts" in rungs
    assert rungs["vocal.tts"]["backend"] == "sherpa_onnx"
    assert rungs["vocal.tts"]["model_id"] == "kokoro-en"


def test_gather_vocal_tts_fallback_model_id() -> None:
    """Without sherpa_model_id, model_id falls back to backend."""
    from kaine.cycle.__main__ import _gather_model_rungs

    config = {"vocal": {"backend": "qwen3_tts"}}
    rungs = _gather_model_rungs(config)
    assert rungs["vocal.tts"]["model_id"] == "qwen3_tts"


def test_gather_audition_stt() -> None:
    """audition section with a backend populates audition.stt rung."""
    from kaine.cycle.__main__ import _gather_model_rungs

    config = {"audition": {"backend": "speaches", "stt_model": "faster-distil-whisper-medium.en"}}
    rungs = _gather_model_rungs(config)
    assert "audition.stt" in rungs
    assert rungs["audition.stt"]["backend"] == "speaches"
    assert rungs["audition.stt"]["model_id"] == "faster-distil-whisper-medium.en"


def test_gather_audition_sherpa_model_id_preferred() -> None:
    """sherpa_model_id takes precedence over stt_model for audition."""
    from kaine.cycle.__main__ import _gather_model_rungs

    config = {
        "audition": {
            "backend": "sherpa_onnx",
            "sherpa_model_id": "whisper-tiny",
            "stt_model": "should-not-be-used",
        },
    }
    rungs = _gather_model_rungs(config)
    assert rungs["audition.stt"]["model_id"] == "whisper-tiny"


def test_gather_no_backend_means_no_rung() -> None:
    """Sections without a backend key produce no rungs."""
    from kaine.cycle.__main__ import _gather_model_rungs

    config = {"vocal": {"volume": 0.8}, "audition": {"gain": 1.0}}
    assert _gather_model_rungs(config) == {}
