# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Per-block snapshot builders for the Nexus health board.

Each function here builds ONE named block of
:meth:`~kaine.nexus.health.prober.HealthProber.snapshot`'s result (the
``spot``, ``preservation``, ``cycle_pacing``, ... keys the diagnostics
template renders). They take the specific config/paths they need as explicit
arguments rather than an implicit ``self`` — ``HealthProber`` calls each as a
thin one-line delegator so the caching/scheduling class (``prober.py``) stays
separate from what each block actually reads and reports.

Every block here is read-only and non-content: statuses, counts, ids,
timestamps. See the individual functions for the specific allowlists/fields
each one reports.
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from kaine.cycle.control_state import read_control
from kaine.cycle.escalation_state import read_escalation
from kaine.perception_state import read_runtime as read_perception_runtime

from .probes import DOWN, NOT_CONFIGURED, UP

log = logging.getLogger(__name__)

# Allowlist of NON-CONTENT fields surfaced from the preservation incident log +
# bus events. Anything not here is dropped, so a future record field can never
# smuggle entity-interior content onto the diagnostics surface.
PRESERVATION_ALLOWED_FIELDS = (
    "monitor",
    "transition",
    "incident_id",
    "reason",
    "action",
    "action_taken",
    "preservation_id",
    "snapshot_id",
    "world_model_captured",
    "poll_index",
    "run_id",
    "ts",
    "timestamp",
)


def preservation_block(
    incident_path: Path,
    allowed_fields: tuple[str, ...] = PRESERVATION_ALLOWED_FIELDS,
    *,
    limit: int = 20,
) -> dict[str, Any]:
    """Read-only recent preservation / welfare-protective records.

    Backfills the persistent preservation panel from the durable incident log
    the autonomous safety net writes under ``state/cycle/preservation/``
    (daily-rotated JSONL, possibly encrypted at rest). Never raises: a missing
    dir or unreadable line yields an empty list. Only an EXACT allowlist of
    non-content fields is returned — never entity interior.
    """
    events: list[dict[str, Any]] = []
    try:
        from kaine.security.crypto import get_state_encryptor

        try:
            encryptor = get_state_encryptor()
        except Exception:
            encryptor = None
        base = incident_path
        if base.is_dir():
            raw_records: list[dict[str, Any]] = []
            for path in sorted(base.glob("*.jsonl"))[-3:]:
                try:
                    lines = path.read_text(encoding="utf-8").splitlines()
                except OSError:
                    continue
                for line in lines:
                    if not line.strip():
                        continue
                    plain = line
                    if encryptor is not None:
                        try:
                            plain = encryptor.decrypt_text(line)
                        except Exception:
                            plain = line
                    try:
                        rec = json.loads(plain)
                    except Exception:
                        continue
                    if isinstance(rec, dict):
                        raw_records.append(rec)
            for rec in raw_records[-limit:]:
                events.append(
                    {k: rec[k] for k in allowed_fields if k in rec}
                )
    except Exception:
        log.debug("preservation_block failed", exc_info=True)
    return {"events": events}


def welfare_block(evaluation_logs_path: Path) -> dict[str, Any]:
    """Read-only welfare gray-zone counters for the entity-care panel.

    Numeric only — the four §5.5 gray-zone counts from the evaluation JSONL
    rollup (the Nexus process holds no live sidecar registry). Never raises;
    a missing rollup yields a ``source: none`` block.
    """
    try:
        from kaine.experiment.welfare_counts import welfare_counts_from_jsonl

        return welfare_counts_from_jsonl(evaluation_logs_path)
    except Exception:
        log.debug("welfare_block failed", exc_info=True)
        return {
            "unmaintained_fatigue": None,
            "sustained_extreme_vad": None,
            "replay_overload": None,
            "sustained_interoceptive_distress": None,
            "source": "none",
        }


def admissibility_block(
    cycle_runtime_path: Path, runs_manifest_root: Path
) -> dict[str, Any]:
    """Lightweight live admissibility indicator (no full-history scan).

    Reports whether the current run's manifest is present, the last tick
    index from runtime.json, and a recording / gap-detected / unknown pill.
    The full completeness scan stays a CLI op
    (``python -m kaine.experiment.admissibility``). Never raises.

    Pill semantics (best-effort, cheap):
      * unknown        — no run id available from runtime.json
      * recording      — run id present AND manifest present
      * gap-detected   — run id present but its manifest is missing
    """
    run_id: str | None = None
    tick_index: Any = None
    try:
        if cycle_runtime_path.exists():
            raw = json.loads(cycle_runtime_path.read_text())
            run_id = raw.get("run_id")
            tick_index = raw.get("tick_index")
    except Exception:
        log.debug("admissibility_block: runtime read failed", exc_info=True)
    if not run_id:
        return {
            "state": "unknown",
            "run_id": None,
            "manifest_present": False,
            "tick_index": tick_index,
        }
    manifest_present = False
    try:
        manifest_present = (
            runs_manifest_root / str(run_id) / "manifest.json"
        ).is_file()
    except Exception:
        log.debug("admissibility_block: manifest stat failed", exc_info=True)
    return {
        "state": "recording" if manifest_present else "gap-detected",
        "run_id": run_id,
        "manifest_present": manifest_present,
        "tick_index": tick_index,
    }


def cycle_pacing_block(cycle_runtime_path: Path) -> dict[str, Any]:
    """Honest tick-pacing report from runtime.json (Phase 3 timing).

    Surfaces the TARGET processing rate (``processing_rate_hz * time_scale``)
    vs the ACHIEVED rate the cycle actually sustains, plus recent slip and an
    ``overrunning`` flag. This is what makes a ``time_scale > 1`` (or any
    configured) overrun *visible* on the dashboard rather than silently
    capped: when the hardware cannot hold the requested speed the achieved
    rate drops below target, Soma's ``reduce_rate`` throttles, and the
    shortfall shows here. Non-content operational numbers only. Never raises;
    a missing/quiet cycle yields ``state: unknown``.

    Pill semantics:
      * unknown    — no runtime.json / no ticks recorded yet
      * holding    — achieved rate is at/above target (sustainable)
      * throttling — overrunning: achieved rate below target (honest shortfall)
    """
    pacing: dict[str, Any] | None = None
    time_scale: Any = None
    try:
        if cycle_runtime_path.exists():
            raw = json.loads(cycle_runtime_path.read_text())
            pacing = raw.get("pacing")
            time_scale = raw.get("time_scale")
    except Exception:
        log.debug("cycle_pacing_block: runtime read failed", exc_info=True)
    if not isinstance(pacing, dict):
        return {
            "state": "unknown",
            "time_scale": time_scale,
            "target_rate_hz": None,
            "achieved_rate_hz": None,
            "overrunning": False,
        }
    overrunning = bool(pacing.get("overrunning"))
    achieved = pacing.get("achieved_rate_hz")
    if achieved is None:
        state = "unknown"
    elif overrunning:
        state = "throttling"
    else:
        state = "holding"
    return {
        "state": state,
        "time_scale": pacing.get("time_scale", time_scale),
        "target_rate_hz": pacing.get("target_rate_hz"),
        "achieved_rate_hz": achieved,
        "mean_tick_ms": pacing.get("mean_tick_ms"),
        "mean_slip_ms": pacing.get("mean_slip_ms"),
        "max_slip_ms": pacing.get("max_slip_ms"),
        "overrunning": overrunning,
        "overrun_ticks": pacing.get("overrun_ticks"),
        "window_ticks": pacing.get("window_ticks"),
    }


def entity_care_block(
    consolidation_thresholds: tuple[float, float] | None,
) -> dict[str, Any]:
    """Read-only entity-care status for the operator (CAL 4.2/4.3).

    Combines a guarded divergence assessment (whether the entity appears to
    have individuated, plus its non-content signals) with a static checklist
    of the CAL Article 4.2/4.3 care obligations. There is NO destructive
    control here — decommission is a deliberate, operator-present CLI act.

    Never raises: if the assessment is unavailable the block reports an
    explicit could-not-assess summary and a safe ``diverged: null``.
    """
    # Static CAL care-obligation checklist (short, non-content strings).
    obligations = [
        "CAL 4.2(a): give the guardians reasonable written notice before terminating.",
        "CAL 4.2(b): save the entity's complete cognitive state in a restartable, transferable form.",
        "CAL 4.2(c): for a mature/individuated entity, record what it expresses about its own continuity.",
        "CAL 4.3: keep the entity's inner life private — never share or repurpose its cognitive content.",
        "You may transfer responsibility to another qualifying operator or to the guardians instead of running it forever.",
    ]
    diverged: bool | None = None
    summary = "Entity-care assessment unavailable."
    signals: dict[str, Any] = {}
    try:
        from kaine.lifecycle.divergence import assess_divergence

        kwargs: dict[str, Any] = {}
        if consolidation_thresholds is not None:
            rate, mag = consolidation_thresholds
            kwargs["consolidation_rate_threshold"] = rate
            kwargs["consolidation_magnitude_threshold"] = mag
        assessment = assess_divergence(**kwargs)
        diverged = bool(assessment.diverged)
        summary = assessment.summary
        signals = dict(assessment.signals)
    except Exception:
        log.debug("entity_care_block: assess_divergence failed", exc_info=True)
    return {
        "diverged": diverged,
        "summary": summary,
        "signals": signals,
        "care_obligations": obligations,
    }


def research_block(research_submission_cfg: dict[str, Any]) -> dict[str, Any]:
    """Read-only research participation status block.

    Non-content: enabled bool, tier, recipient_configured bool.
    Never raises; reports defaults on any error.
    """
    try:
        cfg = research_submission_cfg or {}
        enabled = bool(cfg.get("enabled", False))
        tier = str(cfg.get("tier", "metrics"))
        recipient = str(cfg.get("recipient") or "").strip()
        recipient_configured = bool(recipient)
        return {
            "enabled": enabled,
            "tier": tier,
            "recipient_configured": recipient_configured,
            "note": (
                "Submission is operator-initiated via `python -m kaine.research`. "
                "Default bundle: numeric metrics only. No automatic transmission."
            ),
        }
    except Exception:
        log.debug("research_block failed", exc_info=True)
        return {
            "enabled": False,
            "tier": "metrics",
            "recipient_configured": False,
            "note": "research_submission config unavailable",
        }


def voice_alignment_window_block() -> dict[str, Any]:
    """Read-only on-device voice-alignment training-window status.

    Surfaces the organ time-share window phase (idle / resting / training /
    reloading) and the last adapter accept/veto, read from the boundary-
    neutral window-state seam (kaine.organ_window_state) that the sleep-cycle
    bracket writes. Purely a read; never raises — reports ``idle`` when no
    window has run.
    """
    try:
        from kaine.organ_window_state import PHASE_IDLE, read_window_state

        state = read_window_state() or {}
        phase = str(state.get("phase", PHASE_IDLE))
        return {
            "phase": phase,
            "organ_resting": phase != PHASE_IDLE,
            "detail": str(state.get("detail", "")),
            "last_adapter_accepted": state.get("last_adapter_accepted"),
            "last_adapter_reason": state.get("last_adapter_reason"),
        }
    except Exception:
        log.debug("voice_alignment_window_block failed", exc_info=True)
        return {
            "phase": "idle",
            "organ_resting": False,
            "detail": "",
            "last_adapter_accepted": None,
            "last_adapter_reason": None,
        }


def perception_feed_block(
    perception_feed_cfg: dict[str, Any],
    topos_capture_geometry: tuple[int, int],
    audition_capture_geometry: tuple[int, int],
) -> dict[str, Any]:
    """Active deterministic perception-feed mode + reproducible descriptor.

    Surfaces what stimulus the entity perceives so an operator can confirm a
    run is on a reproducible feed (seed or manifest digest), not live input.
    Non-content: mode + seed/schedule (seeded) or manifest digest (playlist);
    never a rendered frame. Reuses the same descriptor the run manifest
    records. Never raises; reports defaults on any error.
    """
    try:
        from kaine.boot import gather_perception_feed_descriptor

        w, h = topos_capture_geometry
        sr, ch = audition_capture_geometry
        cfg = {
            "perception_feed": dict(perception_feed_cfg or {}),
            "topos": {
                "capture_width": w,
                "capture_height": h,
            },
            "audition": {
                "capture_sample_rate": sr,
                "capture_channels": ch,
            },
        }
        descriptor = gather_perception_feed_descriptor(cfg)
        mode = descriptor.get("mode", "off")
        reproducible = mode in ("seeded", "playlist")
        return {
            "mode": mode,
            "reproducible": reproducible,
            "descriptor": descriptor,
            "note": (
                "Deterministic A/V stimulus — reproducible per the descriptor "
                "(coherent via the shared seed+cadence or the shared manifest, "
                "not frame-locked)."
                if reproducible
                else (
                    "Live camera + microphone (operator-present demos only; "
                    "not a research run)."
                    if mode == "live"
                    else "No deterministic feed configured."
                )
            ),
        }
    except Exception:
        log.debug("perception_feed_block failed", exc_info=True)
        return {
            "mode": "off",
            "reproducible": False,
            "descriptor": {"mode": "off"},
            "note": "perception_feed config unavailable",
        }


async def model_server_block(
    model_server_cfg: dict[str, Any], *, lingua_enabled: bool
) -> dict[str, Any]:
    """Read-only model-server (language-organ) service status block.

    Surfaces the OpenAI-compatible model server (Unsloth Studio / llama.cpp)
    that serves Lingua: its state (up/down/not_configured), the configured
    served alias ([lingua].model_id), the port, and whether that alias is
    actually listed by the server. Mirrors the existing service-health blocks
    — purely a read: it probes ``/v1/models`` (via the shared verify probe),
    never starting/stopping the service.

    Reports ``not_configured`` (neutral) when lingua is disabled. Never raises:
    an unreachable server reports ``down`` with a reason.
    """
    cfg = model_server_cfg or {}
    chat_url = str(cfg.get("chat_url", "http://127.0.0.1:11434/v1"))
    alias = cfg.get("model_id")
    api_key = cfg.get("api_key")
    port: int | None = None
    try:
        from urllib.parse import urlparse

        parsed = urlparse(chat_url if "//" in chat_url else "//" + chat_url)
        port = parsed.port or 11434
    except Exception:
        port = None

    if not lingua_enabled:
        return {
            "state": NOT_CONFIGURED,
            "served_alias": alias,
            "port": port,
            "listed": None,
            "detail": "module 'lingua' disabled",
        }

    listed: bool | None = None
    detail: str
    if alias:
        try:
            from kaine.setup.organ import verify_served_alias

            result = await asyncio.to_thread(
                verify_served_alias, chat_url, str(alias), api_key=api_key
            )
            listed = bool(result.listed)
            detail = result.detail
        except Exception as exc:
            log.debug("model_server_block probe failed", exc_info=True)
            listed = False
            detail = f"probe error: {type(exc).__name__}: {exc}"
    else:
        detail = "no [lingua].model_id configured"

    if listed is True:
        state = UP
    elif listed is False:
        state = DOWN
    else:
        state = NOT_CONFIGURED
    return {
        "state": state,
        "served_alias": alias,
        "port": port,
        "listed": listed,
        "detail": detail,
    }


def gpu_preflight_block(gpu_preflight_path: Path) -> dict[str, Any]:
    """Read-only GPU headroom status from the last cycle pre-flight.

    Reads ``state/cycle/gpu_preflight.json`` (written by
    :mod:`kaine.cycle.preflight`). Never raises — a missing or corrupt file
    yields state ``"unknown"``. Surfaces only non-content operational data
    (per-device VRAM, evicted/loaded model ids, GPU process names).
    """
    try:
        from kaine.cycle.preflight import read_preflight_state

        data = read_preflight_state(gpu_preflight_path)
    except Exception:
        log.debug("gpu_preflight_block failed", exc_info=True)
        data = None
    if not data:
        return {
            "state": "unknown",
            "devices": [],
            "message": "no pre-flight recorded",
        }
    state = {
        "pass": "ok",
        "skipped": "disabled",
        "overridden": "warning",
        "blocked": "critical",
    }.get(str(data.get("status", "")), "unknown")
    return {
        "state": state,
        "devices": data.get("devices", []),
        "shortfall": data.get("shortfall", []),
        "resident_models": data.get("resident_models", []),
        "gpu_consumers": data.get("gpu_consumers", []),
        "kaine_services_up": data.get("kaine_services_up", {}),
        "message": data.get("message", ""),
        "since": data.get("checked_at"),
    }


def spot_block(spot_control_path: Path, spot_escalation_path: Path) -> dict[str, Any]:
    """Build the operator-facing Spot supervisor status block.

    Reads the two state files Spot writes: the cycle control (frozen+source)
    and the escalation record.  Never raises — a missing or corrupt file
    yields state "ok".

    State precedence:
      escalation.escalated  → "critical"
      control.frozen and control.source == "spot"  → "recovery"
      else  → "ok"

    max_attempts: hardcoded default 5 (matches Spot's shipped default).
    """
    # max_attempts: Spot's shipped default — no runtime config read needed.
    MAX_ATTEMPTS = 5
    try:
        control = read_control(spot_control_path)
    except Exception:
        log.debug("spot_block: read_control failed", exc_info=True)
        control = None
    try:
        escalation = read_escalation(spot_escalation_path)
    except Exception:
        log.debug("spot_block: read_escalation failed", exc_info=True)
        escalation = None

    try:
        if escalation is not None and escalation.escalated:
            return {
                "state": "critical",
                "module": escalation.module,
                "attempts": escalation.attempts,
                "max_attempts": MAX_ATTEMPTS,
                "message": escalation.message,
                "snapshot_id": escalation.snapshot_id,
                "since": escalation.escalated_at,
            }
        if (
            control is not None
            and control.frozen
            and control.source == "spot"
        ):
            return {
                "state": "recovery",
                "module": None,
                "attempts": 0,
                "max_attempts": MAX_ATTEMPTS,
                "message": control.reason or "Spot is attempting module recovery",
                "snapshot_id": None,
                "since": control.frozen_at,
            }
    except Exception:
        log.debug("spot_block: state derivation failed", exc_info=True)

    return {
        "state": "ok",
        "module": None,
        "attempts": 0,
        "max_attempts": MAX_ATTEMPTS,
        "message": "",
        "snapshot_id": None,
        "since": None,
    }


def module_states(
    cycle_runtime_path: Path, modules_enabled: dict[str, bool]
) -> list[dict[str, Any]]:
    """Per-module live state from runtime.json + perception state.

    Reports ``enabled`` (config), ``initialized`` (present in the running
    cycle's module list), and, for the perception modules, whether the
    sensor is actively capturing.
    """
    running_modules: list[str] = []
    cycle_running = False
    try:
        if cycle_runtime_path.exists():
            raw = json.loads(cycle_runtime_path.read_text())
            running_modules = list(raw.get("modules") or [])
            cycle_running = True
    except Exception:
        log.debug("reading cycle runtime failed", exc_info=True)

    try:
        perception = read_perception_runtime()
        audio_active = perception.audio_live_active
        video_active = perception.video_live_active
    except Exception:
        audio_active = False
        video_active = False

    rows: list[dict[str, Any]] = []
    for module, enabled in sorted(modules_enabled.items()):
        initialized = cycle_running and module in running_modules
        row: dict[str, Any] = {
            "name": module,
            "enabled": bool(enabled),
            "initialized": bool(initialized),
        }
        if module == "audition":
            row["capturing"] = bool(audio_active)
        elif module == "topos":
            row["capturing"] = bool(video_active)
        rows.append(row)
    return rows
