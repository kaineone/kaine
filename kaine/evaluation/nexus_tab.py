# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Evaluation tab for the Nexus diagnostics surface.

Privacy boundary: NEVER reads or renders message text from the A/B
bare-LLM logs or any logged event body. Only metrics (counts, ratios,
similarities, distributions) are surfaced.
"""
from __future__ import annotations

import json
import logging
import statistics
from pathlib import Path
from typing import Any, TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from kaine.evaluation.affect_correlation import correlate_from_log
from kaine.evaluation.attribution import AttributionRecorder
from kaine.evaluation.config import EvaluationConfig
from kaine.experiment.welfare_counts import (  # re-export: moved to a boundary-neutral home
    welfare_counts_from_jsonl,
)

__all__ = [
    "welfare_counts_from_jsonl",
    "empty_evaluation_metrics",
    "aggregate_evaluation_metrics",
    "build_evaluation_router",
]

if TYPE_CHECKING:
    from kaine.evaluation.registry import SidecarRegistry

log = logging.getLogger(__name__)


_PRIVACY_DROP_FIELDS = frozenset(
    {
        "text",
        "body",
        "content",
        "real_text",
        "bare_text",
        "transcription",
        "user_input",
        "user_text",
        "description",
    }
)


def _scrub(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in value.items() if k not in _PRIVACY_DROP_FIELDS}
    if isinstance(value, list):
        return [_scrub(item) for item in value]
    return value


def _latest_lines(log_dir: Path, *, name: str, limit: int = 200) -> list[dict[str, Any]]:
    if not log_dir.exists():
        return []
    out: list[dict[str, Any]] = []
    for jsonl in sorted(log_dir.glob(f"{name}-*.jsonl"))[-3:]:
        try:
            for line in jsonl.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                out.append(_scrub(entry))
        except Exception:
            log.debug("skipped %s", jsonl, exc_info=True)
    return out[-limit:]


_NEXUS_STATIC = Path(__file__).parent.parent / "nexus" / "static"


def _asset_url(path: str) -> str:
    """Cache-bust a `/static/...` URL with the file's mtime. A local copy (not an
    import from kaine.nexus — the evaluation sidecar must not depend on Nexus
    internals); it only references the shared template chrome's asset files on
    disk, which the boundary allows."""
    rel = path.split("?", 1)[0]
    if rel.startswith("/static/"):
        f = _NEXUS_STATIC / rel[len("/static/"):]
        try:
            return f"{rel}?v={int(f.stat().st_mtime)}"
        except OSError:
            return rel
    return path


def _templates() -> Jinja2Templates:
    base = Path(__file__).parent.parent / "nexus" / "templates"
    templates = Jinja2Templates(directory=str(base))
    templates.env.globals["asset"] = _asset_url
    return templates


def build_evaluation_router(
    config: EvaluationConfig,
    *,
    attribution: AttributionRecorder | None,
    registry: "SidecarRegistry | None" = None,
) -> APIRouter:
    router = APIRouter(prefix="/diagnostics/evaluation")
    templates = _templates()

    @router.get("/", response_class=HTMLResponse)
    async def evaluation_page(request: Request):
        if not config.enabled:
            raise HTTPException(404, "evaluation sidecar disabled")
        metrics = _aggregate(config, attribution, registry)
        return templates.TemplateResponse(
            request, "evaluation.html", {"metrics": metrics}
        )

    @router.get("/summary.json")
    async def evaluation_summary():
        if not config.enabled:
            raise HTTPException(404, "evaluation sidecar disabled")
        return JSONResponse(_aggregate(config, attribution, registry))

    return router


def _aggregate_welfare(
    logs_root: Path,
    registry: "SidecarRegistry | None",
) -> dict[str, Any]:
    """Aggregate welfare Gray-Zone counts.

    Prefer the live registry counters when available; fall back to reading
    the most recent JSONL entry so the tab works against a stopped cycle.
    Returns a dict with keys unmaintained_fatigue, sustained_extreme_vad,
    replay_overload plus a ``source`` field ('live' | 'jsonl' | 'none').
    """
    # 1. Live registry (preferred).
    wo = getattr(registry, "welfare_observer", None) if registry else None
    if wo is not None:
        return {
            "unmaintained_fatigue": wo.unmaintained_fatigue_count,
            "sustained_extreme_vad": wo.sustained_extreme_vad_count,
            "replay_overload": wo.replay_overload_count,
            "sustained_interoceptive_distress": wo.sustained_interoceptive_distress_count,
            "source": "live",
        }

    # 2. JSONL rollup (cold dashboard / Nexus restart).
    return welfare_counts_from_jsonl(logs_root)


def _aggregate_prediction_error(
    logs_root: Path,
    registry: "SidecarRegistry | None",
) -> dict[str, Any]:
    """Aggregate prediction-error sliding-window statistics.

    Returns a dict with per-source mean/p95/p99 plus total event counts.
    When no data exists returns ``{"source": "none"}``.
    """
    # 1. Live registry.
    pe_obs = getattr(registry, "prediction_error_observer", None) if registry else None
    if pe_obs is not None:
        event_counts = pe_obs.event_counts
        per_source: dict[str, Any] = {}
        for stream in event_counts:
            stats = pe_obs._stats_for_source(stream)
            per_source[stream] = stats
        return {
            "event_counts": event_counts,
            "per_source": per_source,
            "source": "live",
        }

    # 2. JSONL rollup.
    pe_dir = logs_root / "prediction_error"
    entries = _latest_lines(pe_dir, name="prediction_error", limit=50)
    if not entries:
        return {"source": "none"}
    # The JSONL entries carry ``sources`` (per-stream stats) and
    # ``event_counts``; use the most recent entry.
    latest = entries[-1]
    return {
        "event_counts": latest.get("event_counts") or {},
        "per_source": latest.get("sources") or {},
        "source": "jsonl",
    }


def _aggregate_coherence(
    logs_root: Path,
) -> dict[str, Any]:
    """Aggregate PLV coherence from the JSONL rollup.

    Returns latest coherence pair map and mean per pair, or empty when absent.
    """
    coh_dir = logs_root / "coherence"
    entries = _latest_lines(coh_dir, name="coherence", limit=200)
    if not entries:
        return {"latest": None, "mean_per_pair": {}, "n": 0, "source": "none"}

    latest_coh = entries[-1].get("coherence") or {}
    # Compute mean PLV per pair across all entries.
    pair_values: dict[str, list[float]] = {}
    for e in entries:
        coh = e.get("coherence") or {}
        for pair, val in coh.items():
            if isinstance(val, (int, float)):
                pair_values.setdefault(pair, []).append(float(val))
    mean_per_pair = {
        pair: round(statistics.fmean(vals), 4)
        for pair, vals in pair_values.items()
        if vals
    }
    return {
        "latest": latest_coh,
        "mean_per_pair": mean_per_pair,
        "n": len(entries),
        "source": "jsonl",
    }


def _aggregate_nous_policy(logs_root: Path) -> dict[str, Any]:
    """Aggregate the nous_policy rollup (active-inference policy logs).

    The NousPolicyObserver records ``expected_free_energy`` (EFE), ``horizon``,
    and the selected ``policy`` (action id string) to
    ``<evaluation_logs>/nous_policy/nous_policy-*.jsonl`` — numeric/string
    metadata only, no raw content. Returns the recent EFE series, the latest
    selected policy, and a count; ``source: none`` when no rollup exists.

    Honesty note: belief-divergence is NOT in this rollup — the observer logs
    EFE/horizon/policy only. We surface what exists and never fabricate a
    divergence metric here (fork/posterior divergence lives in the
    individuation and entity-care surfaces).
    """
    pol_dir = logs_root / "nous_policy"
    entries = _latest_lines(pol_dir, name="nous_policy", limit=200)
    if not entries:
        return {"source": "none", "series": [], "latest_policy": None, "n": 0}
    series = [
        {
            "ts": e.get("ts"),
            "expected_free_energy": e.get("expected_free_energy"),
            "horizon": e.get("horizon"),
            "policy": e.get("policy"),
        }
        for e in entries
    ]
    latest_policy = next(
        (e.get("policy") for e in reversed(entries) if e.get("policy") is not None),
        None,
    )
    efe_values = [
        float(e["expected_free_energy"])
        for e in entries
        if isinstance(e.get("expected_free_energy"), (int, float))
    ]
    return {
        "source": "jsonl",
        "series": series[-100:],
        "latest_policy": latest_policy,
        "n": len(entries),
        "mean_efe": statistics.fmean(efe_values) if efe_values else None,
    }


def _aggregate_individuation(config: EvaluationConfig) -> dict[str, Any] | None:
    """Return the most recent individuation-boundary result, or None."""
    try:
        output_dir = Path(config.individuation.output_dir)
    except AttributeError:
        return None
    if not output_dir.exists():
        return None
    jsonl_files = sorted(output_dir.glob("*.jsonl"))
    if not jsonl_files:
        return None
    # Read lines from the newest file; return the last valid entry.
    last_entry: dict[str, Any] | None = None
    try:
        for line in jsonl_files[-1].read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                last_entry = _scrub(entry)
            except json.JSONDecodeError:
                pass
    except Exception:
        log.debug("individuation JSONL read failed", exc_info=True)
    return last_entry


def empty_evaluation_metrics() -> dict[str, Any]:
    """The evaluation-metrics shape with every section empty.

    The unified console at ``/`` always renders the evaluation panels; when the
    sidecar is disabled (or unavailable) it renders them from this empty shape
    rather than crashing on a missing key. Mirrors the keys ``_aggregate``
    returns.
    """
    return {
        "ab_divergence": {"n": 0, "mean_divergence": 0.0, "max_divergence": 0.0, "series": []},
        "voice_tracking": [],
        "proactive_triggers": {},
        "sleep_snapshots": [],
        "eidolon_accuracy": [],
        "affect_correlation": {},
        "attribution_total": {},
        "attribution_hour": {},
        "memory_probes": {"n": 0, "real_mean": 0.0, "bare_mean": 0.0, "advantage_mean": 0.0},
        "welfare": {"source": "none"},
        "prediction_error": {"source": "none"},
        "coherence": {"latest": None, "mean_per_pair": {}, "n": 0, "source": "none"},
        "nous_policy": {"source": "none", "series": [], "latest_policy": None, "n": 0},
        "individuation": None,
    }


def aggregate_evaluation_metrics(
    config: EvaluationConfig,
    *,
    attribution: AttributionRecorder | None = None,
    registry: "SidecarRegistry | None" = None,
) -> dict[str, Any]:
    """Public entrypoint for the evaluation metrics aggregate.

    Used by the unified console at ``/`` (via the Nexus composition root) to
    render the evaluation panels server-side. Returns the empty shape when the
    sidecar is disabled.
    """
    if not config.enabled:
        return empty_evaluation_metrics()
    return _aggregate(config, attribution, registry)


def _aggregate(
    config: EvaluationConfig,
    attribution: AttributionRecorder | None,
    registry: "SidecarRegistry | None" = None,
) -> dict[str, Any]:
    logs_root = Path(config.paths.evaluation_logs)

    ab_dir = logs_root / "ab_divergence"
    ab_entries = _latest_lines(ab_dir, name="ab_divergence", limit=500)
    ab_divergences = [
        float(e["divergence"]) for e in ab_entries
        if isinstance(e.get("divergence"), (int, float))
    ]
    ab_summary = {
        "n": len(ab_entries),
        "mean_divergence": statistics.fmean(ab_divergences) if ab_divergences else 0.0,
        "max_divergence": max(ab_divergences) if ab_divergences else 0.0,
        "series": [
            {"ts": e.get("ts"), "divergence": e.get("divergence")}
            for e in ab_entries[-100:]
        ],
    }

    voice_dir = logs_root / "voice_tracking"
    voice_entries = _latest_lines(voice_dir, name="voice_tracking", limit=200)
    voice_series = [
        {
            "ts": e.get("ts"),
            "before": e.get("mean_similarity_before"),
            "after": e.get("mean_similarity_after"),
        }
        for e in voice_entries
    ]

    proactive_dir = logs_root / "proactive_audit"
    proactive_entries = _latest_lines(proactive_dir, name="proactive_audit", limit=500)
    proactive_triggers: dict[str, int] = {}
    for e in proactive_entries:
        tm = e.get("trigger_module") or "unknown"
        proactive_triggers[tm] = proactive_triggers.get(tm, 0) + 1

    sleep_dir = logs_root / "sleep_snapshots"
    sleep_entries = _latest_lines(sleep_dir, name="sleep_snapshots", limit=20)

    eidolon_dir = logs_root / "eidolon_accuracy"
    eidolon_entries = _latest_lines(eidolon_dir, name="eidolon_accuracy", limit=60)
    eidolon_series = [
        {"ts": e.get("ts"), "aggregate": e.get("aggregate_accuracy")}
        for e in eidolon_entries
    ]

    affect_dir = logs_root / "affect_correlation"
    # The correlator can be expensive over many lines — Phase 5 says it
    # runs as a batch during Hypnos. Here we cache by checking only the
    # latest file.
    correlation_matrix: dict[str, dict[str, float]] = {}
    if affect_dir.exists():
        latest = sorted(affect_dir.glob("affect_correlation-*.jsonl"))
        if latest:
            try:
                correlation_matrix = correlate_from_log(latest[-1])
            except Exception:
                log.debug("affect correlation failed", exc_info=True)

    attribution_total: dict[str, int] = {}
    attribution_hour: dict[str, int] = {}
    if attribution is not None:
        attribution_total = attribution.running_total
        attribution_hour = attribution.current_hour_counts

    memory_dir = logs_root / "memory_probes"
    memory_entries = _latest_lines(memory_dir, name="memory_probes", limit=200)
    memory_summary = {
        "n": len(memory_entries),
        "real_mean": statistics.fmean(
            [e["real_accuracy"] for e in memory_entries if isinstance(e.get("real_accuracy"), (int, float))]
        ) if memory_entries else 0.0,
        "bare_mean": statistics.fmean(
            [e["bare_accuracy"] for e in memory_entries if isinstance(e.get("bare_accuracy"), (int, float))]
        ) if memory_entries else 0.0,
        "advantage_mean": statistics.fmean(
            [e["advantage"] for e in memory_entries if isinstance(e.get("advantage"), (int, float))]
        ) if memory_entries else 0.0,
    }

    # --- sidecar observer surfaces ---
    welfare = _aggregate_welfare(logs_root, registry)
    prediction_error = _aggregate_prediction_error(logs_root, registry)
    coherence = _aggregate_coherence(logs_root)
    nous_policy = _aggregate_nous_policy(logs_root)
    individuation = _aggregate_individuation(config)

    return {
        "ab_divergence": ab_summary,
        "voice_tracking": voice_series,
        "proactive_triggers": proactive_triggers,
        "sleep_snapshots": sleep_entries,
        "eidolon_accuracy": eidolon_series,
        "affect_correlation": correlation_matrix,
        "attribution_total": attribution_total,
        "attribution_hour": attribution_hour,
        "memory_probes": memory_summary,
        # sidecar observer additions
        "welfare": welfare,
        "prediction_error": prediction_error,
        "coherence": coherence,
        "nous_policy": nous_policy,
        "individuation": individuation,
    }
