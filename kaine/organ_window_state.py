# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Boundary-neutral seam for the on-device voice-alignment GPU window.

During the sleep-cycle voice-alignment training window the served language organ
is unloaded to free the single GPU for the LoRA training step (see
:mod:`kaine.modules.hypnos.organ_window`). Organ-dependent consumers that live on
the OTHER side of the evaluation sidecar boundary — Lingua's chat client (core)
and the A/B-divergence eval arm (sidecar) — need to know the organ is "resting"
so they degrade gracefully (defer / skip) instead of crashing on the dead
endpoint.

This module is the shared, dependency-free home for that signal: a tiny state
file plus pure readers. It depends only on the stdlib, so BOTH the core runtime
(Hypnos writes it, Lingua reads it) and the evaluation sidecar (the A/B arm reads
it) can use it without either side importing the other — the same written-record
pattern Hypnos already uses for the consolidation-divergence metric.

Content-free: only a phase tag + a short human detail + the last adapter verdict
ever leave here. Never utterance text.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger(__name__)

#: Where the bracket publishes the window phase; consumers read it.
ORGAN_WINDOW_STATE = Path("state/hypnos/organ_window.json")

#: Window phases (surfaced to consumers + Nexus).
PHASE_IDLE = "idle"  # no training window; organ serving normally
PHASE_RESTING = "resting"  # organ unloaded for training; consumers defer/skip
PHASE_TRAINING = "training"  # trainer running against the safetensors base
PHASE_RELOADING = "reloading"  # organ being restored (preflight + start)

#: Phases in which the served organ is absent (consumers defer/skip).
_ORGAN_ABSENT_PHASES = (PHASE_RESTING, PHASE_TRAINING, PHASE_RELOADING)


def write_window_state(
    phase: str,
    *,
    detail: str = "",
    last_adapter_accepted: Optional[bool] = None,
    last_adapter_reason: Optional[str] = None,
    path: Optional[Path] = None,
) -> None:
    """Persist the current organ-window phase for consumers + Nexus.

    Guarded — a write failure logs and is swallowed (the bracket always writes
    RESTING before it unloads, so a missing file safely means "organ available").
    """
    path = path if path is not None else ORGAN_WINDOW_STATE
    payload: dict[str, Any] = {
        "phase": str(phase),
        "detail": str(detail),
        "ts": time.time(),
    }
    if last_adapter_accepted is not None:
        payload["last_adapter_accepted"] = bool(last_adapter_accepted)
    if last_adapter_reason is not None:
        payload["last_adapter_reason"] = str(last_adapter_reason)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
    except Exception:
        log.warning("organ window: state write failed", exc_info=True)


def read_window_state(path: Optional[Path] = None) -> Optional[dict[str, Any]]:
    """Read the latest organ-window phase, or None if absent/unreadable.

    Pure + guarded — any error yields None (treated as "no window / organ
    available").
    """
    path = path if path is not None else ORGAN_WINDOW_STATE
    try:
        if not path.is_file():
            return None
        raw = path.read_text(encoding="utf-8").strip()
        if not raw:
            return None
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except Exception:
        log.debug("organ window: state read failed", exc_info=True)
        return None


def organ_unloaded(path: Optional[Path] = None) -> bool:
    """True iff the organ is currently unloaded for the training window.

    The boolean organ-dependent consumers branch on: ``resting``/``training``/
    ``reloading`` mean the served organ is absent, so generation requests should
    DEFER and the eval arm should SKIP (not raise/fail). ``idle`` or an
    absent/unreadable file means the organ is available.
    """
    state = read_window_state(path)
    if not state:
        return False
    return str(state.get("phase")) in _ORGAN_ABSENT_PHASES
