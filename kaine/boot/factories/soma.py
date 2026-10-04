# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The Soma factory."""
from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any, Mapping, Optional

if TYPE_CHECKING:
    pass
from kaine.boot.common import _check_injections
from kaine.boot.errors import _pop
from kaine.boot.perception_feed import _shared_womb_objects, _womb_params
from kaine.bus.client import AsyncBus
from kaine.entity_clock import EntityClock
from kaine.modules.base import BaseModule


def make_soma(
    bus: AsyncBus,
    section: dict[str, Any],
    *,
    entity_clock: Optional[EntityClock] = None,
    injections: Optional[Mapping[str, Any]] = None,
) -> BaseModule:
    from kaine.modules.soma.module import Soma
    from kaine.modules.womb_drive import MaternalDriveProvider
    from kaine.oscillator.module_oscillator import make_self_rhythm_oscillator

    allowed = {
        "read_interval_s",
        "cycle_latency_target_ms",
        "cycle_latency_window",  # → SystemMetricsReader latency-averaging window
        "baseline_salience",
        "alert_salience",
        "thresholds",
        "weights",
        # Predictive interoception (soma-forward-model-fatigue)
        "forward_model_units",
        "cfc_backend",
        "prediction_error_window",
        "fatigue_decay_per_s",
        "fatigue_maintenance_threshold",
        "regulation_sustain_window_s",
        "regulation_threshold",
        "expected_error_tau_s",
        "expected_error_band",
        # Developmental warm-up (soma-coldstart-regulation-warmup)
        "regulation_warmup_enabled",
        "regulation_warmup_min_samples",
        "regulation_warmup_min_seconds",
        "regulation_warmup_require_error_stabilized",
        "regulation_warmup_stable_window",
        "regulation_warmup_stable_variance",
        # Self-rhythm oscillator
        "self_rhythm_enabled",
        "self_rhythm_step_hz",
        "self_rhythm_eta",
    }
    feed_section = dict(section.pop("perception_feed", {}) or {})
    kw = _pop(section, allowed)
    kw.update(_check_injections("soma", injections, {"forward_model"}))

    if kw.get("self_rhythm_enabled"):
        kw.pop("self_rhythm_enabled")
        step_hz = float(kw.pop("self_rhythm_step_hz", 20.0))
        eta = kw.pop("self_rhythm_eta", 0.0)
        if isinstance(eta, bool) or not isinstance(eta, (int, float)) or not math.isfinite(float(eta)) or float(eta) < 0.0:
            raise ValueError("[soma].self_rhythm_eta must be a finite number >= 0")
        # The oscillator integrates at the rate Soma steps it; a mismatch would
        # silently change the rhythm's frequency.
        osc = make_self_rhythm_oscillator(
            seed=int(feed_section.get("seed", 0)), step_hz=step_hz, eta=float(eta)
        )
        if osc is None:
            raise ValueError(
                "[soma].self_rhythm_enabled requires the oscillator extra (snnTorch)"
            )
        kw["self_rhythm"] = osc
        kw["self_rhythm_step_hz"] = step_hz
        if feed_section.get("mode") == "womb":
            params = _womb_params(feed_section)
            if params.external_drive_to_self_rhythm:
                from kaine.cycle.gestation import GestationReadoutConfig

                clock, _ = _shared_womb_objects(feed_section)
                # Start at the usual drive, validated from the readout settings
                # at boot; the gestation owner only ever moves it for bounded,
                # announced probes.
                readout = GestationReadoutConfig.from_dict(
                    (feed_section.get("womb") or {}).get("readout")
                )
                kw["maternal_drive"] = MaternalDriveProvider(
                    clock,
                    params,
                    seed=int(feed_section.get("seed", 0)),
                    scale=readout.baseline_drive_fraction,
                )
    else:
        kw.pop("self_rhythm_enabled", None)
        kw.pop("self_rhythm_step_hz", None)
        eta = kw.pop("self_rhythm_eta", 0.0)
        if isinstance(eta, bool) or not isinstance(eta, (int, float)) or not math.isfinite(float(eta)) or float(eta) < 0.0:
            raise ValueError("[soma].self_rhythm_eta must be a finite number >= 0")

    return Soma(bus, entity_clock=entity_clock, **kw)
