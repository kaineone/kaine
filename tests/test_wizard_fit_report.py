# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the wizard fit report step (task 8.2)."""
from __future__ import annotations

from typing import Any

import pytest

from kaine.residency.fit import DomainFit, FitReport
from kaine.residency.speech_rungs import RungSelection, SpeechRung
from kaine.setup.steps import StepContext
from kaine.setup.wizard_steps import fit_report_step


def _out_sink() -> tuple[list[str], Any]:
    """Return (lines_list, sink_fn) for capturing wizard output."""
    lines: list[str] = []

    def sink(text: str = "") -> None:
        lines.append(text)

    return lines, sink


def _ctx(
    *,
    catalogue: dict[str, int] | None = None,
    defaults: bool = False,
    shipped_config: dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
) -> tuple[StepContext, list[str]]:
    """Build a minimal StepContext; returns ``(ctx, output_lines)``."""
    out_lines, sink = _out_sink()
    return (
        StepContext(
            config=config if config is not None else {},
            host={
                "backend": "cpu",
                "device": "cpu",
                "cuda_devices": [],
                "gpu_count": 0,
                "cpu_count": 8,
            },
            extra={
                "catalogue": catalogue if catalogue is not None else {},
                "defaults": defaults,
                "shipped_config": shipped_config or {},
                "out": sink,
                "input_fn": lambda _prompt: "",
            },
        ),
        out_lines,
    )


_FAKE_FIT_REPORT = FitReport(
    domains=(
        DomainFit(
            domain="system",
            budget_bytes=8 * (1 << 30),
            need_bytes=4 * (1 << 30),
            status="co-resides",
            shortfall_bytes=0,
            pinned=None,
            multiplexed=(),
            rungs={},
            feel="everything stays loaded; no swaps",
        ),
    ),
    co_resides=True,
    uncalibrated=(),
)

_TTS_RUNG = SpeechRung(
    backend="sherpa_onnx",
    model_id="kokoro-en",
    label="Kokoro English int8 (CPU)",
    licence="Apache-2.0",
    mapped=False,
    fetch_command="python -m kaine.setup.speech_models --tts kokoro-en",
)

_STT_RUNG = SpeechRung(
    backend="sherpa_onnx",
    model_id="moonshine-base-en",
    label="Moonshine base English (CPU)",
    licence="MIT",
    mapped=False,
    fetch_command="python -m kaine.setup.speech_models --stt moonshine-base-en",
)

_TTS_SELECTION = RungSelection(
    rung=_TTS_RUNG,
    reason="heaviest installed rung",
    hints=(),
)

_STT_SELECTION = RungSelection(
    rung=_STT_RUNG,
    reason="heaviest installed rung",
    hints=(),
)

_TTS_FOOTPRINT = 150 * (1 << 20)  # 150 MiB
_STT_FOOTPRINT = 200 * (1 << 20)  # 200 MiB


def _mock_select_rung(
    ladder: Any, component: str, entries: Any, host_class: str, budget_bytes: Any
) -> RungSelection | None:
    if component == "vocal.tts":
        return _TTS_SELECTION
    if component == "audition.stt":
        return _STT_SELECTION
    return None


def _mock_lookup_footprint(
    rung: SpeechRung, component: str, entries: Any, host_class: str
) -> int | None:
    if component == "vocal.tts":
        return _TTS_FOOTPRINT
    if component == "audition.stt":
        return _STT_FOOTPRINT
    return None


@pytest.fixture()
def _patch_fit_deps(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch all lazy imports used by the fit report step."""
    monkeypatch.setattr(
        "kaine.setup.footprint.quick_fit",
        lambda config=None, **kw: _FAKE_FIT_REPORT,
    )
    monkeypatch.setattr(
        "kaine.setup.footprint.host_class",
        lambda **kw: "cpu",
    )
    monkeypatch.setattr(
        "kaine.residency.catalogue.load_catalogue",
        lambda path=None: (),
    )
    monkeypatch.setattr(
        "kaine.residency.speech_rungs.select_rung",
        _mock_select_rung,
    )
    monkeypatch.setattr(
        "kaine.residency.speech_rungs.is_rung_installed",
        lambda _rung: True,
    )
    monkeypatch.setattr(
        "kaine.residency.speech_rungs.lookup_footprint",
        _mock_lookup_footprint,
    )


# --------------------------------------------------------------------------
# 1. Step skipped when no catalogue
# --------------------------------------------------------------------------


def test_step_skipped_when_no_catalogue() -> None:
    ctx, _ = _ctx(catalogue={})
    step = fit_report_step()
    assert step.applies(ctx) is False


# --------------------------------------------------------------------------
# 2. Step skipped in defaults mode
# --------------------------------------------------------------------------


def test_step_skipped_in_defaults_mode() -> None:
    ctx, _ = _ctx(catalogue={"embedding": 100_000_000}, defaults=True)
    step = fit_report_step()
    assert step.applies(ctx) is False


# --------------------------------------------------------------------------
# 3. Explanation shows fit report lines
# --------------------------------------------------------------------------


@pytest.mark.usefixtures("_patch_fit_deps")
def test_explanation_shows_fit_report_lines() -> None:
    ctx, _ = _ctx(catalogue={"embedding": 100_000_000})
    step = fit_report_step()
    assert step.applies(ctx) is True

    lines = step.explanation(ctx)
    text = "\n".join(lines)
    assert "Everything co-resides" in text
    assert ctx.extra.get("fit_report") is not None


# --------------------------------------------------------------------------
# 4. Speech rung recommendation shown
# --------------------------------------------------------------------------


@pytest.mark.usefixtures("_patch_fit_deps")
def test_speech_rung_recommendation_shown() -> None:
    ctx, _ = _ctx(catalogue={"embedding": 100_000_000})
    step = fit_report_step()
    lines = step.explanation(ctx)
    text = "\n".join(lines)

    assert "Kokoro English int8 (CPU)" in text
    assert "Moonshine base English (CPU)" in text
    assert ctx.extra.get("speech_selections") is not None
    assert "vocal.tts" in ctx.extra["speech_selections"]
    assert "audition.stt" in ctx.extra["speech_selections"]


# --------------------------------------------------------------------------
# 5. Apply sets config on consent
# --------------------------------------------------------------------------


@pytest.mark.usefixtures("_patch_fit_deps")
def test_apply_sets_config_on_consent() -> None:
    ctx, _ = _ctx(
        catalogue={"embedding": 100_000_000},
        shipped_config={
            "vocal": {"backend": "chatterbox"},
            "audition": {"backend": "speaches"},
        },
    )
    step = fit_report_step()
    step.explanation(ctx)

    # Fields should be present (recommendations differ from shipped)
    flds = step.fields(ctx)
    field_names = {f.name for f in flds}
    assert "apply_tts_rung" in field_names
    assert "apply_stt_rung" in field_names

    # Consent to apply
    step.apply(ctx, {"apply_tts_rung": True, "apply_stt_rung": True})
    assert ctx.config["vocal"]["backend"] == "sherpa_onnx"
    assert ctx.config["vocal"]["sherpa_model_id"] == "kokoro-en"
    assert ctx.config["audition"]["backend"] == "sherpa_onnx"
    assert ctx.config["audition"]["sherpa_model_id"] == "moonshine-base-en"


# --------------------------------------------------------------------------
# 6. No config change when declined
# --------------------------------------------------------------------------


@pytest.mark.usefixtures("_patch_fit_deps")
def test_no_config_change_when_declined() -> None:
    ctx, _ = _ctx(
        catalogue={"embedding": 100_000_000},
        shipped_config={
            "vocal": {"backend": "chatterbox"},
            "audition": {"backend": "speaches"},
        },
    )
    step = fit_report_step()
    step.explanation(ctx)

    step.apply(ctx, {"apply_tts_rung": False, "apply_stt_rung": False})
    assert "vocal" not in ctx.config
    assert "audition" not in ctx.config


# --------------------------------------------------------------------------
# 7. Cost note when heavier kept
# --------------------------------------------------------------------------


@pytest.mark.usefixtures("_patch_fit_deps")
def test_cost_note_when_heavier_kept() -> None:
    ctx, out_lines = _ctx(
        catalogue={"embedding": 100_000_000},
        shipped_config={
            "vocal": {"backend": "chatterbox"},
            "audition": {"backend": "speaches"},
        },
    )
    step = fit_report_step()
    step.explanation(ctx)

    step.apply(ctx, {"apply_tts_rung": False, "apply_stt_rung": False})
    cost_notes = ctx.extra.get("speech_cost_notes", [])
    assert len(cost_notes) == 2
    assert any("TTS" in n and "chatterbox" in n for n in cost_notes)
    assert any("STT" in n and "speaches" in n for n in cost_notes)
    # Notes should mention the recommended rung labels
    assert any("Kokoro" in n for n in cost_notes)
    assert any("Moonshine" in n for n in cost_notes)


# --------------------------------------------------------------------------
# 8. No field when recommendation matches shipped config
# --------------------------------------------------------------------------


@pytest.mark.usefixtures("_patch_fit_deps")
def test_no_field_when_recommendation_matches_config() -> None:
    ctx, _ = _ctx(
        catalogue={"embedding": 100_000_000},
        shipped_config={
            "vocal": {"backend": "sherpa_onnx", "sherpa_model_id": "kokoro-en"},
            "audition": {"backend": "sherpa_onnx", "sherpa_model_id": "moonshine-base-en"},
        },
    )
    step = fit_report_step()
    step.explanation(ctx)

    flds = step.fields(ctx)
    assert len(flds) == 0, "no field when recommendation matches shipped config"
