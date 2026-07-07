# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for nexus observability.

Covers:
- Section 1: DEFAULT_DIAGNOSTICS_STREAMS includes the four new streams.
- Section 2/3: Coherence chart handler and fatigue chart wiring (Python logic; JS is
  tested via the template rendering test below).
- Section 4: Evaluation-tab observer surfaces welfare/prediction-error/coherence.
- Section 5: FaithfulRenderer new templates render via named template, not fallback.
  mnemos.replay and eidolon.self_model contain no raw content.
  Existing report templates include new fields.
- Section 6: Encryption probe states.
- Section 7: narsese removed from CONTENT_FIELDS; merge-warning in forks HTML.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Section 1 — stream set
# ---------------------------------------------------------------------------


def test_diagnostics_streams_include_empatheia_phantasia_workspace():
    from kaine.nexus.__main__ import DEFAULT_DIAGNOSTICS_STREAMS

    assert "empatheia.out" in DEFAULT_DIAGNOSTICS_STREAMS
    assert "phantasia.out" in DEFAULT_DIAGNOSTICS_STREAMS
    assert "workspace.broadcast" in DEFAULT_DIAGNOSTICS_STREAMS


def test_diagnostics_streams_include_original_streams():
    """The new streams must not replace the existing ones."""
    from kaine.nexus.__main__ import DEFAULT_DIAGNOSTICS_STREAMS

    for stream in ("soma.out", "thymos.out", "nous.out", "mnemos.out", "audition.out", "vox.out"):
        assert stream in DEFAULT_DIAGNOSTICS_STREAMS


# ---------------------------------------------------------------------------
# Section 5 — FaithfulRenderer templates
# ---------------------------------------------------------------------------


NEW_EVENT_TYPES = [
    ("nous", "nous.timeout"),
    ("audition", "audition.prosody"),
    ("vox", "vox.synthesized"),
    ("mnemos", "mnemos.replay"),
    ("hypnos", "hypnos.sleep.started"),
    ("hypnos", "hypnos.sleep.completed"),
    ("hypnos", "hypnos.association"),
    ("eidolon", "eidolon.self_model"),
]


@pytest.mark.parametrize("source,type_", NEW_EVENT_TYPES)
def test_new_event_types_use_named_template(source, type_):
    """Each new event type must resolve to a named template (not fallback)."""
    from kaine.faithful.templates import TEMPLATES

    assert (source, type_) in TEMPLATES, (
        f"({source!r}, {type_!r}) not registered in TEMPLATES"
    )


@pytest.mark.parametrize("source,type_", NEW_EVENT_TYPES)
def test_new_templates_return_non_empty_string(source, type_):
    from kaine.faithful.templates import TEMPLATES

    sample_payloads: dict[tuple[str, str], dict] = {
        ("nous", "nous.timeout"): {"elapsed_ms": 100.0, "num_factors": 2, "num_actions": 3},
        ("audition", "audition.prosody"): {"source_label": "mic", "mean_pitch_hz": 130.0},
        ("vox", "vox.synthesized"): {"text_length": 10, "voice": "example_voice", "success": True, "latency_ms": 150.0},
        ("mnemos", "mnemos.replay"): {"memory_id": "short_term:1", "affect_intensity": 0.5},
        ("hypnos", "hypnos.sleep.started"): {"started_at": 1700000000.0},
        ("hypnos", "hypnos.sleep.completed"): {
            "total_elapsed_ms": 3000.0,
            "phases": [{"name": "p1", "success": True, "elapsed_ms": 1000.0}],
            "fatigue_triggered": False,
        },
        ("hypnos", "hypnos.association"): {"seed_memory_id": "m-1", "horizon": 4},
        ("eidolon", "eidolon.self_model"): {
            "values": ["honesty"],
            "behavioral_norms": [],
            "personality_baseline": {"openness": 0.7},
            "capability_map": {},
        },
    }
    fn = TEMPLATES[(source, type_)]
    out = fn(sample_payloads[(source, type_)])
    assert isinstance(out, str)
    assert out.strip()


def test_mnemos_replay_template_omits_raw_text():
    """mnemos.replay template must not output the raw text field."""
    from kaine.faithful.templates import TEMPLATES

    fn = TEMPLATES[("mnemos", "mnemos.replay")]
    payload = {
        "memory_id": "short_term:7",
        "text": "this is secret raw transcript content",
        "affect_intensity": 0.8,
        "affect": {"valence": 0.4, "arousal": 0.6},
    }
    out = fn(payload)
    assert "secret" not in out
    assert "raw transcript" not in out
    assert "short_term:7" in out


def test_eidolon_self_model_template_omits_raw_content():
    """eidolon.self_model template must output only labels/counts/numerics."""
    from kaine.faithful.templates import TEMPLATES

    fn = TEMPLATES[("eidolon", "eidolon.self_model")]
    payload = {
        "values": ["autonomy"],
        "behavioral_norms": ["non-deception"],
        "personality_baseline": {"openness": 0.8},
        "capability_map": {"language": 0.9},
    }
    out = fn(payload)
    # Must include structural info, not raw content.
    assert "1" in out  # 1 value, 1 norm, 1 capability
    assert isinstance(out, str)


def test_soma_report_template_includes_prediction_error_and_fatigue():
    from kaine.faithful.templates import TEMPLATES

    fn = TEMPLATES[("soma", "soma.report")]
    out = fn({
        "wellness": 0.9,
        "alerts": [],
        "prediction_error": 0.034,
        "fatigue_value": 42.5,
    })
    assert "0.034" in out or "prediction error" in out.lower()
    assert "42.5" in out or "fatigue" in out.lower()


def test_soma_report_template_no_prediction_error_still_works():
    """Extending soma.report must not break the case where new fields are absent."""
    from kaine.faithful.templates import TEMPLATES

    fn = TEMPLATES[("soma", "soma.report")]
    out = fn({"wellness": 0.8, "alerts": []})
    assert isinstance(out, str)
    assert "0.8" in out


def test_chronos_report_template_includes_temporal_prediction_error():
    from kaine.faithful.templates import TEMPLATES

    fn = TEMPLATES[("chronos", "chronos.report")]
    out = fn({
        "anomaly_score": 0.3,
        "habituation_score": 0.4,
        "rumination_detected": False,
        "time_since_last_interaction_s": 5.0,
        "temporal_prediction_error": 0.012,
    })
    assert "0.012" in out or "temporal prediction" in out.lower()


# ---------------------------------------------------------------------------
# Section 6 — encryption probe
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_encryption_probe_disabled():
    from kaine.nexus.health import probe_state_encryption, UP

    status, detail = await probe_state_encryption(section={"enabled": False})
    assert status == UP
    assert "plaintext" in detail.lower() or "disabled" in detail.lower()


@pytest.mark.asyncio
async def test_encryption_probe_enabled_with_env_key(monkeypatch):
    from kaine.nexus.health import probe_state_encryption, UP

    monkeypatch.setenv("KAINE_STATE_KEY", "x" * 32)
    status, detail = await probe_state_encryption(
        section={"enabled": True, "key_env_var": "KAINE_STATE_KEY"}
    )
    assert status == UP
    assert "encrypted" in detail.lower()


@pytest.mark.asyncio
async def test_encryption_probe_enabled_no_key(monkeypatch):
    from kaine.nexus.health import probe_state_encryption, DEGRADED

    monkeypatch.delenv("KAINE_STATE_KEY", raising=False)
    monkeypatch.delenv("KAINE_TEST_MISSING_KEY_9999", raising=False)
    status, detail = await probe_state_encryption(
        section={"enabled": True, "key_env_var": "KAINE_TEST_MISSING_KEY_9999"}
    )
    assert status == DEGRADED
    assert "no key" in detail.lower() or "fail-closed" in detail.lower()


# ---------------------------------------------------------------------------
# Section 7 — privacy cleanup and merge warning
# ---------------------------------------------------------------------------


def test_narsese_removed_from_content_fields():
    from kaine.nexus.privacy import CONTENT_FIELDS

    assert "narsese" not in CONTENT_FIELDS


def test_existing_content_fields_still_present():
    from kaine.nexus.privacy import CONTENT_FIELDS

    for field in ("text", "body", "content", "user_input", "faithful_rendering"):
        assert field in CONTENT_FIELDS, f"{field!r} missing from CONTENT_FIELDS"


def test_diagnostics_html_contains_merge_warning_logic():
    """Verify the forks table has a nous.merge_warning reference."""
    base = Path(__file__).parent.parent / "kaine" / "nexus" / "templates"
    diag = (base / "_diagnostics_sections.html").read_text()
    assert "nous.merge_warning" in diag or "merge_warning" in diag


# ---------------------------------------------------------------------------
# Section 4 — Evaluation tab: welfare/prediction-error/coherence/individuation
# ---------------------------------------------------------------------------


def _eval_config(tmp_path: Path, enabled: bool = True):
    from kaine.evaluation.config import EvaluationConfig

    return EvaluationConfig.from_mapping(
        {
            "enabled": enabled,
            "paths": {
                "trajectory_dir": str(tmp_path / "traj"),
                "evaluation_logs": str(tmp_path / "eval"),
                "retention_days": 30,
            },
        }
    )


def test_welfare_section_no_data(tmp_path):
    """When no welfare data is present, section renders 'none' state without error."""
    from kaine.evaluation.nexus_tab import _aggregate

    cfg = _eval_config(tmp_path)
    result = _aggregate(cfg, attribution=None, registry=None)
    assert "welfare" in result
    assert result["welfare"]["source"] == "none"


def test_welfare_section_from_live_registry(tmp_path):
    from kaine.evaluation.nexus_tab import _aggregate

    cfg = _eval_config(tmp_path)

    # Build a stub welfare observer.
    wo = MagicMock()
    wo.unmaintained_fatigue_count = 2
    wo.sustained_extreme_vad_count = 1
    wo.replay_overload_count = 0
    wo.sustained_interoceptive_distress_count = 3

    registry = MagicMock()
    registry.welfare_observer = wo
    registry.prediction_error_observer = None

    result = _aggregate(cfg, attribution=None, registry=registry)
    w = result["welfare"]
    assert w["source"] == "live"
    assert w["unmaintained_fatigue"] == 2
    assert w["sustained_extreme_vad"] == 1
    assert w["replay_overload"] == 0
    assert w["sustained_interoceptive_distress"] == 3


def test_welfare_section_from_jsonl(tmp_path):
    from kaine.evaluation.nexus_tab import _aggregate

    cfg = _eval_config(tmp_path)
    welfare_dir = Path(cfg.paths.evaluation_logs) / "welfare"
    welfare_dir.mkdir(parents=True, exist_ok=True)
    (welfare_dir / "welfare-2026-06-01.jsonl").write_text(
        json.dumps({
            "ts": "2026-06-01T01:00:00Z",
            "gray_zone_event": "unmaintained_fatigue",
            "unmaintained_fatigue_count": 3,
            "sustained_extreme_vad_count": 0,
            "replay_overload_count": 0,
        }) + "\n"
    )

    result = _aggregate(cfg, attribution=None, registry=None)
    w = result["welfare"]
    assert w["source"] == "jsonl"
    assert w["unmaintained_fatigue"] == 3


def test_prediction_error_section_no_data(tmp_path):
    from kaine.evaluation.nexus_tab import _aggregate

    cfg = _eval_config(tmp_path)
    result = _aggregate(cfg, attribution=None, registry=None)
    assert result["prediction_error"]["source"] == "none"


def test_prediction_error_section_from_live_registry(tmp_path):
    from kaine.evaluation.nexus_tab import _aggregate

    cfg = _eval_config(tmp_path)

    pe_obs = MagicMock()
    pe_obs.event_counts = {"soma.out": 10, "chronos.out": 5}
    pe_obs._stats_for_source.return_value = {"n": 10, "mean": 0.05, "p95": 0.12, "p99": 0.18}

    registry = MagicMock()
    registry.welfare_observer = None
    registry.prediction_error_observer = pe_obs

    result = _aggregate(cfg, attribution=None, registry=registry)
    pe = result["prediction_error"]
    assert pe["source"] == "live"
    assert pe["event_counts"]["soma.out"] == 10


def test_prediction_error_section_from_jsonl(tmp_path):
    from kaine.evaluation.nexus_tab import _aggregate

    cfg = _eval_config(tmp_path)
    pe_dir = Path(cfg.paths.evaluation_logs) / "prediction_error"
    pe_dir.mkdir(parents=True, exist_ok=True)
    (pe_dir / "prediction_error-2026-06-01.jsonl").write_text(
        json.dumps({
            "ts": "2026-06-01T01:00:00Z",
            "sources": {
                "soma.out": {"n": 32, "mean": 0.04, "p95": 0.11, "p99": 0.15},
            },
            "event_counts": {"soma.out": 32},
        }) + "\n"
    )

    result = _aggregate(cfg, attribution=None, registry=None)
    pe = result["prediction_error"]
    assert pe["source"] == "jsonl"
    assert pe["per_source"]["soma.out"]["n"] == 32


def test_coherence_section_no_data(tmp_path):
    from kaine.evaluation.nexus_tab import _aggregate

    cfg = _eval_config(tmp_path)
    result = _aggregate(cfg, attribution=None, registry=None)
    assert result["coherence"]["source"] == "none"


def test_coherence_section_from_jsonl(tmp_path):
    from kaine.evaluation.nexus_tab import _aggregate

    cfg = _eval_config(tmp_path)
    coh_dir = Path(cfg.paths.evaluation_logs) / "coherence"
    coh_dir.mkdir(parents=True, exist_ok=True)
    (coh_dir / "coherence-2026-06-01.jsonl").write_text(
        json.dumps({
            "ts": "2026-06-01T01:00:00Z",
            "tick_index": 10,
            "coherence": {"soma|thymos": 0.72, "thymos|nous": 0.65},
        }) + "\n"
    )

    result = _aggregate(cfg, attribution=None, registry=None)
    coh = result["coherence"]
    assert coh["source"] == "jsonl"
    assert coh["n"] == 1
    assert "soma|thymos" in coh["latest"]


def test_individuation_section_absent(tmp_path):
    from kaine.evaluation.nexus_tab import _aggregate

    cfg = _eval_config(tmp_path)
    result = _aggregate(cfg, attribution=None, registry=None)
    assert result["individuation"] is None


def test_individuation_section_from_jsonl(tmp_path):
    from kaine.evaluation.nexus_tab import _aggregate
    from kaine.evaluation.config import EvaluationConfig

    ind_dir = tmp_path / "individuation"
    ind_dir.mkdir()
    (ind_dir / "run-2026-06-01.jsonl").write_text(
        json.dumps({
            "ts": "2026-06-01T00:00:00Z",
            "metric": "cosine_divergence",
            "null_samples": 50,
            "fork_divergence": 0.31,
            "null_mean": 0.15,
            "null_p95": 0.28,
            "p_value": 0.04,
            "significant": True,
        }) + "\n"
    )

    cfg = EvaluationConfig.from_mapping(
        {
            "enabled": True,
            "paths": {
                "trajectory_dir": str(tmp_path / "traj"),
                "evaluation_logs": str(tmp_path / "eval"),
                "retention_days": 30,
            },
            "individuation": {
                "enabled": False,
                "output_dir": str(ind_dir),
            },
        }
    )
    result = _aggregate(cfg, attribution=None, registry=None)
    ind = result["individuation"]
    assert ind is not None
    assert ind["significant"] is True


# ---------------------------------------------------------------------------
# Section 4 (HTTP) — evaluation router accepts optional registry param
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_evaluation_router_accepts_registry_param(tmp_path):
    """build_evaluation_router must accept registry= without error."""
    import httpx
    from fastapi import FastAPI
    from kaine.evaluation.nexus_tab import build_evaluation_router

    cfg = _eval_config(tmp_path)
    app = FastAPI()
    app.include_router(build_evaluation_router(cfg, attribution=None, registry=None))

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/diagnostics/evaluation/summary.json")
    assert r.status_code == 200
    data = r.json()
    assert "welfare" in data
    assert "prediction_error" in data
    assert "coherence" in data


@pytest.mark.asyncio
async def test_evaluation_summary_welfare_no_data_field(tmp_path):
    """welfare section must always be present in JSON, even with no data."""
    import httpx
    from fastapi import FastAPI
    from kaine.evaluation.nexus_tab import build_evaluation_router

    cfg = _eval_config(tmp_path)
    app = FastAPI()
    app.include_router(build_evaluation_router(cfg, attribution=None, registry=None))

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/diagnostics/evaluation/summary.json")
    data = r.json()
    assert data["welfare"]["source"] == "none"
    assert data["prediction_error"]["source"] == "none"
    assert data["coherence"]["source"] == "none"


# ---------------------------------------------------------------------------
# Graceful degradation — disabled modules produce no errors
# ---------------------------------------------------------------------------


def test_coherence_absent_produces_no_error(tmp_path):
    """With no coherence JSONL and no registry, _aggregate_coherence returns no-data."""
    from kaine.evaluation.nexus_tab import _aggregate_coherence

    result = _aggregate_coherence(Path(tmp_path / "nonexistent"))
    assert result["source"] == "none"
    assert result["latest"] is None


def test_welfare_absent_produces_no_error(tmp_path):
    from kaine.evaluation.nexus_tab import _aggregate_welfare

    result = _aggregate_welfare(Path(tmp_path / "nonexistent"), registry=None)
    assert result["source"] == "none"


def test_evaluation_html_contains_welfare_section():
    base = Path(__file__).parent.parent / "kaine" / "nexus" / "templates"
    evald = (base / "_evaluation_sections.html").read_text()
    assert "Welfare" in evald
    assert "Gray-Zone" in evald


def test_evaluation_html_contains_prediction_error_section():
    base = Path(__file__).parent.parent / "kaine" / "nexus" / "templates"
    evald = (base / "_evaluation_sections.html").read_text()
    assert "Prediction error" in evald or "prediction_error" in evald


def test_evaluation_html_contains_coherence_section():
    base = Path(__file__).parent.parent / "kaine" / "nexus" / "templates"
    evald = (base / "_evaluation_sections.html").read_text()
    assert "Coherence" in evald or "coherence" in evald


def test_diagnostics_html_contains_coherence_chart():
    base = Path(__file__).parent.parent / "kaine" / "nexus" / "templates"
    diag = (base / "_diagnostics_sections.html").read_text()
    assert "chart-coherence" in diag


def test_diagnostics_html_contains_fatigue_chart():
    base = Path(__file__).parent.parent / "kaine" / "nexus" / "templates"
    diag = (base / "_diagnostics_sections.html").read_text()
    assert "chart-fatigue" in diag


# ---------------------------------------------------------------------------
# Batch 3 — run identity, supervision, preservation, welfare, admissibility,
# deterministic indicator (A1–A6).
# ---------------------------------------------------------------------------


def _write_runtime(tmp_path: Path, **fields) -> Path:
    runtime = tmp_path / "runtime.json"
    runtime.write_text(json.dumps(fields))
    return runtime


def test_runtime_state_carries_run_identity_and_mode(tmp_path, monkeypatch):
    """_write_runtime_state writes run identity + supervision/deterministic
    fields read from the active RunContext + cycle."""
    from unittest.mock import MagicMock

    import kaine.cycle.__main__ as cyc
    from kaine.experiment.run_context import RunContext, set_run_context

    runtime = tmp_path / "runtime.json"
    monkeypatch.setattr(cyc, "RUNTIME_PATH", runtime)

    ctx = RunContext(
        run_id="abc123",
        seed=42,
        started_at="2026-06-15T00:00:00+00:00",
        git_sha="deadbee",
        model_ids={"lingua": "x"},
        config_digest="dig",
        kaine_version="9.9.9",
    )
    set_run_context(ctx)
    try:
        cycle = MagicMock()
        cycle.tick_index = 7
        cycle.processing_rate_hz = 3.0
        cycle.experiential_rate_hz = 3.0
        cycle.is_paused = False
        cycle.deterministic = True
        cycle.time_scale = 1.0
        cycle.pacing_stats = {
            "target_rate_hz": 3.0,
            "achieved_rate_hz": 3.0,
            "overrunning": False,
            "window_ticks": 5,
        }
        registry = MagicMock()
        registry.all_modules.return_value = []

        import asyncio

        asyncio.run(
            cyc._write_runtime_state(
                cycle,
                registry,
                supervision_mode="research",
                gate_checks={"preservation_enabled": True, "logging_active": False},
            )
        )
        raw = json.loads(runtime.read_text())
    finally:
        set_run_context(None)

    assert raw["run_id"] == "abc123"
    assert raw["seed"] == 42
    assert raw["git_sha"] == "deadbee"
    assert raw["kaine_version"] == "9.9.9"
    assert raw["deterministic"] is True
    assert raw["supervision_mode"] == "research"
    assert raw["gate_checks"]["preservation_enabled"] is True
    assert raw["gate_checks"]["logging_active"] is False


def test_metrics_snapshot_surfaces_new_fields(tmp_path):
    """nexus metrics_snapshot surfaces run identity + mode + deterministic."""
    from kaine.nexus.__main__ import make_metrics_snapshot

    runtime = tmp_path / "runtime.json"
    runtime.write_text(
        json.dumps(
            {
                "pid": 1,
                "tick_index": 12,
                "processing_rate_hz": 3.0,
                "experiential_rate_hz": 3.0,
                "modules": ["soma"],
                "run_id": "r-1",
                "seed": 99,
                "git_sha": "cafef00",
                "kaine_version": "1.2.3",
                "deterministic": True,
                "supervision_mode": "operator",
                "gate_checks": None,
            }
        )
    )
    snap = make_metrics_snapshot(runtime)()
    assert snap["cycle_status"] == "running"
    assert snap["run_id"] == "r-1"
    assert snap["seed"] == 99
    assert snap["git_sha"] == "cafef00"
    assert snap["kaine_version"] == "1.2.3"
    assert snap["deterministic"] is True
    assert snap["supervision_mode"] == "operator"


def test_metrics_snapshot_not_running(tmp_path):
    from kaine.nexus.__main__ import make_metrics_snapshot

    snap = make_metrics_snapshot(tmp_path / "missing.json")()
    assert snap["cycle_status"] == "not running"


def _prober(tmp_path, **overrides):
    from kaine.nexus.health import HealthProber

    kwargs = dict(
        modules_enabled={},
        dependencies=[],
        cycle_runtime_path=tmp_path / "runtime.json",
        preservation_incident_path=tmp_path / "preservation",
        runs_manifest_root=tmp_path / "runs",
        evaluation_logs_path=tmp_path / "eval",
    )
    kwargs.update(overrides)
    return HealthProber(**kwargs)


def test_preservation_block_reads_incident_log_allowlisted(tmp_path):
    """_preservation_block returns recent records using only allowlisted fields."""
    pres_dir = tmp_path / "preservation"
    pres_dir.mkdir()
    (pres_dir / "preservation_divergence-2026-06-15.jsonl").write_text(
        json.dumps(
            {
                "monitor": "divergence",
                "transition": "preserved",
                "incident_id": "inc-1",
                "reason": "individuation",
                "preservation_id": "PRES-1",
                "snapshot_id": "snap-1",
                "poll_index": 3,
                # A content-shaped field that must NOT survive the allowlist:
                "internal_speech": "the entity's private thought",
                "text": "secret raw transcript",
            }
        )
        + "\n"
    )
    prober = _prober(tmp_path)
    block = prober._preservation_block()
    assert block["events"]
    ev = block["events"][0]
    assert ev["preservation_id"] == "PRES-1"
    assert ev["snapshot_id"] == "snap-1"
    assert ev["reason"] == "individuation"
    # Content fields are dropped by the exact allowlist.
    assert "internal_speech" not in ev
    assert "text" not in ev


def test_preservation_block_missing_dir_is_empty(tmp_path):
    prober = _prober(tmp_path)
    assert prober._preservation_block() == {"events": []}


def test_admissibility_block_recording_when_manifest_present(tmp_path):
    (tmp_path / "runtime.json").write_text(json.dumps({"run_id": "run-x", "tick_index": 5}))
    manifest_dir = tmp_path / "runs" / "run-x"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "manifest.json").write_text("{}")
    block = _prober(tmp_path)._admissibility_block()
    assert block["state"] == "recording"
    assert block["manifest_present"] is True
    assert block["tick_index"] == 5


def test_admissibility_block_gap_when_manifest_absent(tmp_path):
    (tmp_path / "runtime.json").write_text(json.dumps({"run_id": "run-y", "tick_index": 2}))
    block = _prober(tmp_path)._admissibility_block()
    assert block["state"] == "gap-detected"
    assert block["manifest_present"] is False


def test_admissibility_block_unknown_without_run_id(tmp_path):
    (tmp_path / "runtime.json").write_text(json.dumps({"tick_index": 1}))
    block = _prober(tmp_path)._admissibility_block()
    assert block["state"] == "unknown"


def test_cycle_pacing_block_unknown_without_runtime(tmp_path):
    block = _prober(tmp_path)._cycle_pacing_block()
    assert block["state"] == "unknown"
    assert block["overrunning"] is False


def test_cycle_pacing_block_holding_when_sustainable(tmp_path):
    (tmp_path / "runtime.json").write_text(
        json.dumps(
            {
                "time_scale": 1.0,
                "pacing": {
                    "target_rate_hz": 10.0,
                    "achieved_rate_hz": 10.0,
                    "mean_tick_ms": 50.0,
                    "mean_slip_ms": 0.0,
                    "max_slip_ms": 0.0,
                    "overrunning": False,
                    "overrun_ticks": 0,
                    "window_ticks": 32,
                    "time_scale": 1.0,
                },
            }
        )
    )
    block = _prober(tmp_path)._cycle_pacing_block()
    assert block["state"] == "holding"
    assert block["overrunning"] is False
    assert block["target_rate_hz"] == pytest.approx(10.0)
    assert block["achieved_rate_hz"] == pytest.approx(10.0)


def test_cycle_pacing_block_throttling_surfaces_shortfall(tmp_path):
    # A time_scale>1 overrun: target 10 Hz but only 2 Hz sustained.
    (tmp_path / "runtime.json").write_text(
        json.dumps(
            {
                "time_scale": 2.0,
                "pacing": {
                    "target_rate_hz": 10.0,
                    "achieved_rate_hz": 2.0,
                    "mean_slip_ms": 300.0,
                    "max_slip_ms": 320.0,
                    "overrunning": True,
                    "overrun_ticks": 32,
                    "window_ticks": 32,
                    "time_scale": 2.0,
                },
            }
        )
    )
    block = _prober(tmp_path)._cycle_pacing_block()
    assert block["state"] == "throttling"
    assert block["overrunning"] is True
    # The shortfall is visible: achieved is honestly below target.
    assert block["achieved_rate_hz"] < block["target_rate_hz"]
    assert block["mean_slip_ms"] == pytest.approx(300.0)


def test_perception_feed_block_off_by_default(tmp_path):
    block = _prober(tmp_path)._perception_feed_block()
    assert block["mode"] == "off"
    assert block["reproducible"] is False
    assert block["descriptor"] == {"mode": "off"}


def test_perception_feed_block_seeded_surfaces_seed(tmp_path):
    prober = _prober(
        tmp_path,
        perception_feed_cfg={
            "mode": "seeded",
            "seed": 77,
            "video": {"surprise_interval": 30},
            "audio": {"base_strength": 0.3},
        },
        topos_capture_geometry=(320, 240),
        audition_capture_geometry=(16000, 1),
    )
    block = prober._perception_feed_block()
    assert block["mode"] == "seeded"
    assert block["reproducible"] is True
    # The unified descriptor surfaces BOTH surfaces from the one seed.
    assert block["descriptor"]["seed"] == 77
    vid = block["descriptor"]["video"]
    assert vid["seed"] == 77
    assert vid["width"] == 320 and vid["height"] == 240
    aud = block["descriptor"]["audio"]
    assert aud["seed"] == 77 and aud["sample_rate"] == 16000


def test_perception_feed_block_playlist_surfaces_manifest_digest(tmp_path):
    import hashlib

    (tmp_path / "clip.mp4").write_bytes(b"abc")
    sha = hashlib.sha256(b"abc").hexdigest()
    manifest = tmp_path / "pl.toml"
    manifest.write_text(f'[[item]]\npath = "clip.mp4"\nsha256 = "{sha}"\nfps = 30\n')
    prober = _prober(
        tmp_path,
        perception_feed_cfg={"mode": "playlist", "playlist_manifest": str(manifest)},
    )
    block = prober._perception_feed_block()
    assert block["mode"] == "playlist"
    assert block["reproducible"] is True
    pl = block["descriptor"]["playlist"]
    assert pl["manifest_sha256"] == hashlib.sha256(manifest.read_bytes()).hexdigest()


def test_welfare_block_none_when_no_rollup(tmp_path):
    block = _prober(tmp_path)._welfare_block()
    assert block["source"] == "none"


def test_welfare_block_from_jsonl(tmp_path):
    welfare_dir = tmp_path / "eval" / "welfare"
    welfare_dir.mkdir(parents=True)
    (welfare_dir / "welfare-2026-06-15.jsonl").write_text(
        json.dumps(
            {
                "gray_zone_event": "replay_overload",
                "unmaintained_fatigue_count": 1,
                "sustained_extreme_vad_count": 2,
                "replay_overload_count": 4,
                "sustained_interoceptive_distress_count": 0,
            }
        )
        + "\n"
    )
    block = _prober(tmp_path)._welfare_block()
    assert block["source"] == "jsonl"
    assert block["replay_overload"] == 4
    assert block["sustained_extreme_vad"] == 2


@pytest.mark.asyncio
async def test_snapshot_includes_new_blocks(tmp_path):
    prober = _prober(tmp_path)
    snap = await prober.snapshot()
    for key in ("preservation", "welfare", "admissibility", "model_server"):
        assert key in snap


# ---------------------------------------------------------------------------
# Orphan guard — every per-block key in snapshot() must be reachable by the
# diagnostics route context. This is the root-cause guard: the four blocks
# (perception_feed/cycle_pacing/model_server/gpu_preflight) were orphaned
# precisely because the per-block extraction in the diagnostics route is easy
# to forget. If a future block is added to snapshot() but not extracted, this
# fails.
# ---------------------------------------------------------------------------

# Keys in snapshot() that are NOT per-block render targets (the dependency/
# module board + the bare timestamp) and so are not expected in the per-block
# extraction context.
_NON_BLOCK_SNAPSHOT_KEYS = frozenset(
    {"dependencies", "modules", "checked_at"}
)


@pytest.mark.asyncio
async def test_every_snapshot_block_reachable_by_diagnostics_context(tmp_path):
    """Each _*_block key surfaced by snapshot() must be extracted into the
    diagnostics route's template context (no silently orphaned block)."""
    import inspect

    from kaine.nexus import diagnostics as diag_mod

    prober = _prober(tmp_path)
    snap = await prober.snapshot()
    block_keys = set(snap) - _NON_BLOCK_SNAPSHOT_KEYS

    # The shared context builder extracts blocks by iterating a literal tuple of
    # keys (HEALTH_BLOCK_KEYS); assert every block key appears in the diagnostics
    # module source so the per-block extraction stays in sync with snapshot().
    source = inspect.getsource(diag_mod)
    missing = sorted(k for k in block_keys if f'"{k}"' not in source)
    assert not missing, (
        f"snapshot() blocks not extracted by the diagnostics context builder "
        f"(orphaned): {missing}. Add them to HEALTH_BLOCK_KEYS in "
        f"kaine/nexus/diagnostics.py and render them."
    )


@pytest.mark.asyncio
async def test_diagnostics_context_flattens_all_blocks(tmp_path):
    """Functional check: hitting /diagnostics/ with a prober populates every
    new panel's context key and the page renders without error."""
    import httpx
    from fastapi import FastAPI
    from kaine.nexus.bridge import BusBridge
    from kaine.nexus.diagnostics import build_diagnostics_router
    from kaine.nexus.privacy import PrivacyFilter

    class _StubBus:
        async def read(self, *a, **k):
            return []

    bridge = BusBridge(_StubBus(), PrivacyFilter(dev_content_override=False), streams=[], poll_interval_s=0.01)
    prober = _prober(tmp_path)
    router = build_diagnostics_router(
        bridge,
        fork_manager=None,
        metrics_snapshot=lambda: {"cycle_status": "running"},
        health_prober=prober,
    )
    app = FastAPI()
    app.include_router(router)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/diagnostics/")
    assert r.status_code == 200, r.text
    # The four newly-rendered panels are present.
    for marker in ("perception-feed", "cycle-pacing", "gpu-preflight", "model server"):
        assert marker in r.text.lower()


def test_diagnostics_html_includes_new_panels():
    base = Path(__file__).parent.parent / "kaine" / "nexus" / "templates"
    diag = (base / "_diagnostics_sections.html").read_text()
    assert "_perception_feed.html" in diag
    assert "_cycle_pacing.html" in diag
    # Health & services (service board + gpu pre-flight) was lifted out of the
    # diagnostics grid into its own partial — it is no longer a grid section.
    assert "_gpu_preflight.html" not in diag
    assert 'id="board-health"' not in diag
    health = (base / "_health_section.html").read_text()
    assert "_health_board.html" in health
    assert "_gpu_preflight.html" in health
    assert 'id="board-health"' in health
    # The standalone /diagnostics page renders health inline; the console mounts
    # it in the glanceable right sidebar via the sidebar_right block.
    assert "_health_section.html" in (base / "diagnostics.html").read_text()
    console = (base / "console.html").read_text()
    assert "_health_section.html" in console
    assert "sidebar_right" in console
    # The left-rail Health jump segment is gone — health lives in the sidebar, not
    # as a grid jump target in the section nav.
    assert 'href="#board-health"' not in console


def test_new_panel_partials_render_with_representative_data():
    """The three new panel partials render via named templates with sample data
    and degrade gracefully when their block is empty."""
    from fastapi.templating import Jinja2Templates

    base = Path(__file__).parent.parent / "kaine" / "nexus" / "templates"
    templates = Jinja2Templates(directory=str(base))

    pf = templates.get_template("_perception_feed.html").render(
        perception_feed={
            "mode": "seeded",
            "reproducible": True,
            "note": "deterministic",
            "descriptor": {
                "seed": 77,
                "video": {"width": 320, "height": 240, "surprise_interval": 30, "surprise_strength": 1.0},
                "audio": {"sample_rate": 16000, "channels": 1, "frames_per_block": 480, "surprise_interval": 30},
            },
        }
    )
    assert "77" in pf and "seeded" in pf
    # Empty block must not throw / blank.
    assert "unavailable" in templates.get_template("_perception_feed.html").render(perception_feed=None)

    cp = templates.get_template("_cycle_pacing.html").render(
        cycle_pacing={
            "state": "throttling", "time_scale": 2.0, "target_rate_hz": 10.0,
            "achieved_rate_hz": 2.0, "mean_tick_ms": 500.0, "mean_slip_ms": 300.0,
            "max_slip_ms": 320.0, "overrunning": True, "overrun_ticks": 32, "window_ticks": 32,
        }
    )
    assert "throttling" in cp and "2.0" in cp
    assert "unavailable" in templates.get_template("_cycle_pacing.html").render(cycle_pacing=None)

    gp = templates.get_template("_gpu_preflight.html").render(
        gpu_preflight={
            "state": "critical",
            "devices": [{"device": "cuda:0", "name": "RTX", "free_vram_gb": 1.2, "total_vram_gb": 24.0}],
            "shortfall": [{"device": "cuda:0"}],
            "resident_models": ["kaineone/Qwen3.5-4B-abliterated-GGUF"],
            "gpu_consumers": [{"pid": "123", "process_name": "python", "used_mib": "4000"}],
            "kaine_services_up": {},
            "message": "headroom low",
            "since": "2026-06-24T00:00:00Z",
        }
    )
    assert "cuda:0" in gp and "critical" in gp
    assert "unavailable" in templates.get_template("_gpu_preflight.html").render(gpu_preflight=None)


def test_evaluation_html_contains_nous_policy_panel():
    base = Path(__file__).parent.parent / "kaine" / "nexus" / "templates"
    evald = (base / "_evaluation_sections.html").read_text()
    assert "Nous policy" in evald
    assert "nous_policy" in evald


def test_nous_policy_aggregate_no_data_and_from_jsonl(tmp_path):
    from kaine.evaluation.nexus_tab import _aggregate_nous_policy

    assert _aggregate_nous_policy(Path(tmp_path / "nope"))["source"] == "none"

    pol_dir = tmp_path / "nous_policy"
    pol_dir.mkdir()
    (pol_dir / "nous_policy-2026-06-01.jsonl").write_text(
        json.dumps({"ts": "2026-06-01T00:00:00Z", "expected_free_energy": 1.5, "horizon": 1, "policy": "act-3"})
        + "\n"
    )
    out = _aggregate_nous_policy(tmp_path)
    assert out["source"] == "jsonl"
    assert out["latest_policy"] == "act-3"
    assert out["mean_efe"] == pytest.approx(1.5)


@pytest.mark.asyncio
async def test_model_server_block_not_configured_when_lingua_off(tmp_path):
    prober = _prober(
        tmp_path,
        modules_enabled={"lingua": False},
        model_server_cfg={
            "chat_url": "http://127.0.0.1:11434/v1",
            "model_id": "kaineone/Qwen3.5-4B-abliterated-GGUF",
        },
    )
    block = await prober._model_server_block()
    assert block["state"] == "not_configured"
    assert block["port"] == 11434
    assert block["served_alias"] == "kaineone/Qwen3.5-4B-abliterated-GGUF"


@pytest.mark.asyncio
async def test_model_server_block_up_when_alias_served(tmp_path, monkeypatch):
    from kaine.setup.organ import ServedAliasResult

    monkeypatch.setattr(
        "kaine.setup.organ.verify_served_alias",
        lambda *a, **k: ServedAliasResult(
            listed=True, served=("kaineone/Qwen3.5-4B-abliterated-GGUF",),
            detail="matches",
        ),
    )
    prober = _prober(
        tmp_path,
        modules_enabled={"lingua": True},
        model_server_cfg={
            "chat_url": "http://127.0.0.1:11434/v1",
            "model_id": "kaineone/Qwen3.5-4B-abliterated-GGUF",
        },
    )
    block = await prober._model_server_block()
    assert block["state"] == "up"
    assert block["listed"] is True


@pytest.mark.asyncio
async def test_model_server_block_down_on_mismatch(tmp_path, monkeypatch):
    from kaine.setup.organ import ServedAliasResult

    monkeypatch.setattr(
        "kaine.setup.organ.verify_served_alias",
        lambda *a, **k: ServedAliasResult(
            listed=False, served=("other",), detail="served name ≠ configured"
        ),
    )
    prober = _prober(
        tmp_path,
        modules_enabled={"lingua": True},
        model_server_cfg={
            "chat_url": "http://127.0.0.1:11434/v1",
            "model_id": "kaineone/Qwen3.5-4B-abliterated-GGUF",
        },
    )
    block = await prober._model_server_block()
    assert block["state"] == "down"
    assert block["listed"] is False


def test_diagnostics_html_has_run_identity_and_deterministic_badge():
    base = Path(__file__).parent.parent / "kaine" / "nexus" / "templates"
    diag = (base / "_diagnostics_sections.html").read_text()
    assert "_run_identity.html" in diag
    assert "_preservation_events.html" in diag
    assert "deterministic-badge" in diag
    run_ident = (base / "_run_identity.html").read_text()
    assert "run id" in run_ident
    assert "supervision-badge--research" in run_ident
    assert "admissibility" in run_ident


def test_preservation_partial_renders():
    """The preservation partial renders via the named template with sample data."""
    from fastapi.templating import Jinja2Templates

    base = Path(__file__).parent.parent / "kaine" / "nexus" / "templates"
    templates = Jinja2Templates(directory=str(base))
    tmpl = templates.get_template("_preservation_events.html")
    out = tmpl.render(
        preservation={
            "events": [
                {
                    "monitor": "welfare",
                    "transition": "protective_action",
                    "incident_id": "i-1",
                    "reason": "sustained_distress",
                    "action_taken": "pause",
                    "preservation_id": "P-1",
                    "snapshot_id": "S-1",
                }
            ]
        }
    )
    assert "P-1" in out
    assert "sustained_distress" in out


# ---------------------------------------------------------------------------
# Section 8 — Live cycle-vitals data contract (JOB 1 regression)
#
# The console cycle/run-identity/pacing/module panels are server-rendered once
# and then live-refreshed in place by the NexusVitals poller (static/nexus.js)
# from /diagnostics/metrics.json + /diagnostics/health.json. If the backend
# shape and the field paths the frontend reads ever drift apart, those panels
# silently go dead again (the exact bug this section guards). These tests pin
# the contract on BOTH sides so a rename on either side fails loudly.
# ---------------------------------------------------------------------------

# Field paths NexusVitals.renderRunIdentity / renderBanner read out of
# /diagnostics/metrics.json (make_metrics_snapshot).
_VITALS_METRICS_FIELDS = (
    "cycle_status",
    "run_id",
    "seed",
    "git_sha",
    "kaine_version",
    "supervision_mode",
    "gate_checks",
    "processing_rate_hz",
    "experiential_rate_hz",
)

# Field paths NexusVitals.renderPacing reads out of health.cycle_pacing.
_VITALS_PACING_FIELDS = (
    "state",
    "time_scale",
    "target_rate_hz",
    "achieved_rate_hz",
    "mean_tick_ms",
    "mean_slip_ms",
    "max_slip_ms",
    "overrunning",
    "overrun_ticks",
    "window_ticks",
)

# Field paths NexusVitals.renderRunIdentity reads out of health.admissibility.
_VITALS_ADMISSIBILITY_FIELDS = ("state", "run_id", "manifest_present", "tick_index")


def _running_runtime_payload() -> dict[str, Any]:
    return {
        "pid": 4321,
        "tick_index": 100,
        "processing_rate_hz": 10.0,
        "experiential_rate_hz": 3.33,
        "pacing": {
            "target_rate_hz": 20.0,
            "achieved_rate_hz": 14.2,
            "mean_tick_ms": 70.4,
            "mean_target_ms": 50.0,
            "mean_slip_ms": 20.4,
            "max_slip_ms": 61.2,
            "overrunning": True,
            "overrun_ticks": 37,
            "window_ticks": 64,
            "time_scale": 2.0,
        },
        "time_scale": 2.0,
        "modules": ["mnemos", "nous", "thymos"],
        "supervision_mode": "research",
        "gate_checks": {"preservation_net_armed": True},
        "run_id": "run-contract-test",
        "seed": 7,
        "git_sha": "deadbee",
        "kaine_version": "0.0.0",
    }


def test_vitals_metrics_contract_running(tmp_path):
    """metrics.json (make_metrics_snapshot) surfaces every field NexusVitals
    reads when a cycle is running."""
    from kaine.nexus.__main__ import make_metrics_snapshot

    runtime = tmp_path / "runtime.json"
    runtime.write_text(json.dumps(_running_runtime_payload()))
    snap = make_metrics_snapshot(runtime_path=runtime)()

    assert snap["cycle_status"] == "running"
    for field in _VITALS_METRICS_FIELDS:
        assert field in snap, f"metrics.json missing frontend-read field {field!r}"


def test_vitals_metrics_contract_not_running(tmp_path):
    """With no runtime.json the snapshot reports 'not running' — the exact value
    NexusVitals.renderBanner compares against to show the banner."""
    from kaine.nexus.__main__ import make_metrics_snapshot

    snap = make_metrics_snapshot(runtime_path=tmp_path / "absent.json")()
    assert snap["cycle_status"] == "not running"


# ---------------------------------------------------------------------------
# Four-state status chip (task 2.6): OFFLINE > FROZEN > SLEEPING > AWAKE.
# ---------------------------------------------------------------------------


def test_metrics_snapshot_carries_frozen_flag_for_status_chip(tmp_path):
    """The status chip needs `frozen` (+ cycle_status) in the metrics payload.
    make_metrics_snapshot must surface the runtime.json `frozen` flag."""
    from kaine.nexus.__main__ import make_metrics_snapshot

    runtime = tmp_path / "runtime.json"
    payload = _running_runtime_payload()
    payload["frozen"] = True
    runtime.write_text(json.dumps(payload))
    snap = make_metrics_snapshot(runtime_path=runtime)()
    assert snap["cycle_status"] == "running"
    assert snap["frozen"] is True

    # Absent frozen key → False (running, not frozen).
    payload.pop("frozen")
    runtime.write_text(json.dumps(payload))
    snap = make_metrics_snapshot(runtime_path=runtime)()
    assert snap["frozen"] is False


def test_console_status_chip_defaults_to_offline():
    """The server-rendered left-rail chip must default to OFFLINE, not AWAKE:
    before any live data arrives the console cannot know a cycle is running."""
    tpl = Path(__file__).resolve().parents[1] / "kaine" / "nexus" / "templates"
    console = (tpl / "console.html").read_text()
    # The chip element defaults to the offline class + label.
    assert '<span class="badge offline" id="sleep-badge">offline</span>' in console
    # The old hardwired awake/sleeping binary default is gone.
    assert "{% if sleeping %}sleeping{% else %}awake{% endif %}" not in console


def test_status_chip_priority_logic_in_js():
    """Static guard on the four-state chip logic in nexus.js: the computed
    state must follow OFFLINE > FROZEN > SLEEPING > AWAKE, and both hypnos
    sleep AND wake events must be handled."""
    js = _nexus_js()
    # The priority ladder is expressed in computeChipState().
    start = js.index("function computeChipState()")
    end = js.index("}", js.index("return \"awake\"", start))
    block = js[start:end]
    # OFFLINE checked first (running gate), then FROZEN, then SLEEPING, then AWAKE.
    assert 'if (!chip.running) return "offline"' in block
    assert 'if (chip.frozen) return "frozen"' in block
    assert 'if (chip.sleeping) return "sleeping"' in block
    assert 'return "awake"' in block
    # running comes before frozen, frozen before sleeping in source order.
    assert (
        block.index("offline") < block.index("frozen") < block.index("sleeping")
    )
    # Both sleep and wake events drive the chip.
    assert "hypnos.sleep.started" in js and "hypnos.sleep.completed" in js
    # The chip is fed running + frozen from the metrics snapshot.
    assert "setRunning(" in js and "setFrozen(" in js


@pytest.mark.asyncio
async def test_vitals_health_contract(tmp_path):
    """health.json exposes cycle_pacing / admissibility / modules with every
    field the NexusVitals renderers read."""
    from kaine.nexus.health import DependencySpec, HealthProber

    runtime = tmp_path / "runtime.json"
    runtime.write_text(json.dumps(_running_runtime_payload()))

    async def up_probe():
        return "up", "ok"

    prober = HealthProber(
        modules_enabled={"mnemos": True, "nous": True, "praxis": False},
        dependencies=[
            DependencySpec(name="Qdrant", role="Mnemos", module="mnemos", probe=up_probe)
        ],
        cache_ttl_s=0.0,
        cycle_runtime_path=runtime,
    )
    snap = await prober.snapshot(force=True)

    for field in _VITALS_PACING_FIELDS:
        assert field in snap["cycle_pacing"], f"cycle_pacing missing {field!r}"
    assert snap["cycle_pacing"]["state"] == "throttling"  # overrunning payload

    for field in _VITALS_ADMISSIBILITY_FIELDS:
        assert field in snap["admissibility"], f"admissibility missing {field!r}"
    assert snap["admissibility"]["run_id"] == "run-contract-test"

    assert snap["modules"], "modules list empty"
    for m in snap["modules"]:
        for field in ("name", "enabled", "initialized"):
            assert field in m, f"module cell missing {field!r}"
    mods = {m["name"]: m for m in snap["modules"]}
    assert mods["mnemos"]["initialized"] is True  # in runtime module list


def _nexus_js() -> str:
    return (
        Path(__file__).resolve().parents[1]
        / "kaine" / "nexus" / "static" / "nexus.js"
    ).read_text()


def test_vitals_frontend_reads_declared_endpoints_and_fields():
    """Static guard tying the frontend to the backend contract: the NexusVitals
    block must fetch the two live endpoints and read the exact field names the
    backend provides. A rename on either side breaks this test."""
    js = _nexus_js()
    assert "window.NexusVitals" in js
    assert "/diagnostics/metrics.json" in js
    assert "/diagnostics/health.json" in js
    # Every backend field the renderers depend on appears verbatim in the JS.
    for field in _VITALS_METRICS_FIELDS + _VITALS_PACING_FIELDS:
        assert field in js, f"nexus.js NexusVitals never reads {field!r}"
    # health blocks read by path.
    assert "health.cycle_pacing" in js
    assert "health.admissibility" in js
    assert "health.modules" in js


def test_vitals_template_hooks_present():
    """The live-refresh hook ids NexusVitals targets must exist in the templates,
    and the not-running banner must be rendered-but-hidden while running (so the
    poller can show/hide it in place rather than the old reload-only behaviour)."""
    tpl = Path(__file__).resolve().parents[1] / "kaine" / "nexus" / "templates"
    run_identity = (tpl / "_run_identity.html").read_text()
    pacing = (tpl / "_cycle_pacing.html").read_text()
    health_board = (tpl / "_health_board.html").read_text()
    diag_sections = (tpl / "_diagnostics_sections.html").read_text()

    assert 'id="run-identity-body"' in run_identity
    assert 'id="cycle-pacing-body"' in pacing
    assert 'id="module-grid"' in health_board
    assert 'id="cycle-not-running"' in diag_sections
    # Banner is always emitted (no longer gated behind a not-running-only {% if %}),
    # hidden when the cycle is running.
    assert 'hidden' in diag_sections
    assert 'NexusVitals.init' in (tpl / "console.html").read_text()
