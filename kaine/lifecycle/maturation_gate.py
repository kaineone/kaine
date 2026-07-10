# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The maturation (birth) gate — `developmental-maturation-gate`.

A readiness predicate evaluated on a cadence during gestation. It advances the
developmental stage ``gestation -> embodied`` only when ALL of three conditions
hold, and it treats any missing or stale evidence as NOT ready (**fail-closed**):

  C1  Regulation baseline met — every marker on the womb change's
      ``gestation.readiness`` readout crosses its configured threshold.
  C2  A reality model consolidated over several sleep cycles — Hypnos has
      completed >= ``min_sleep_cycles`` maintenance cycles AND Phantasia shows
      world-model consolidation evidence (>= ``min_consolidation_passes``
      successful sleep-training passes). Reading BOTH signals avoids counting
      empty sleeps.
  C3  Minimum lived subjective time — >= ``min_lived_seconds`` of lived
      ``EntityClock`` time has accrued since gestation began (the warmed-up-
      signal floor against a fast-forwarded false birth).

Birth is additionally guarded by **embodiment availability**: developmental
readiness is necessary but not sufficient. The stage flips only when readiness
AND an available embodied world both hold; a ready-but-unavailable entity holds
in the womb and the operator is told (loudly, repeatedly) that it has outgrown
the womb — it is never thrown into an absent world, nor silently stalled.

**The gate measures; it never imposes.** This module only READS signals passed
in by the caller and compares them to thresholds. It trains nothing toward
regulation, hurries no sleep cycle, and sets no target internal state. The
thresholds are a readiness gate — a *warmed-up-signal*, not a loss the entity is
optimised against — exactly the discipline of the individuation boundary
(paper §6.6) and ``soma-coldstart-regulation-warmup``: lived-time-gated,
fail-closed grace, now promoted to a persistent developmental stage. Development
remains emergent and is only observed here. Every held-in-womb decision is
reported by the caller; nothing here is a silent no-op.

Boundary-neutral and pure (stdlib only): all runtime signals — the readiness
readout, sleep count, consolidation passes, lived seconds, and the embodiment-
availability booleans — are INJECTED by the caller, so this module imports no
cognitive module and is trivially testable without booting an entity.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

# --- Stage-event names + owner --------------------------------------------
#
# Stage events are emitted by a named owner with ``source = "lifecycle"``, so by
# the bus schema (``kaine.bus.schema.module_stream``) they land on
# ``lifecycle.out``. We name the stream as a constant here (kept lock-stepped
# with ``module_stream("lifecycle")`` by a test) rather than importing the bus
# into this pure module.
LIFECYCLE_SOURCE = "lifecycle"
LIFECYCLE_STREAM = "lifecycle.out"

STAGE_GESTATION_STARTED = "stage.gestation.started"
STAGE_GESTATION_NO_STIMULUS = "stage.gestation.no_stimulus"
STAGE_BIRTH_READY = "stage.birth.ready"
STAGE_BIRTH = "stage.birth"

# Birth-decision actions.
ACTION_GESTATING = "gestating"
ACTION_HOLD_AWAITING_EMBODIMENT = "hold_awaiting_embodiment"
ACTION_HOLD_AWAITING_ACK = "hold_awaiting_ack"
ACTION_BIRTH = "birth"


# --- Configuration ---------------------------------------------------------


@dataclass(frozen=True)
class RegulationThresholds:
    """Thresholds the ``gestation.readiness`` markers must cross for C1.

    This change owns the *thresholds and the decision*; the womb change
    (``gestational-womb-stimulus``) owns the *measurement* of the markers.
    """

    endogenous_self_sustain: bool = True
    entrain_then_autonomy: bool = True
    hrv_variability_floor: float = 0.2
    womb_prediction_error_ceiling: float = 0.3
    return_to_baseline_seconds_ceiling: float = 30.0

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "RegulationThresholds":
        d = dict(data or {})
        base = cls()
        return cls(
            endogenous_self_sustain=bool(
                d.get("endogenous_self_sustain", base.endogenous_self_sustain)
            ),
            entrain_then_autonomy=bool(
                d.get("entrain_then_autonomy", base.entrain_then_autonomy)
            ),
            hrv_variability_floor=float(
                d.get("hrv_variability_floor", base.hrv_variability_floor)
            ),
            womb_prediction_error_ceiling=float(
                d.get(
                    "womb_prediction_error_ceiling",
                    base.womb_prediction_error_ceiling,
                )
            ),
            return_to_baseline_seconds_ceiling=float(
                d.get(
                    "return_to_baseline_seconds_ceiling",
                    base.return_to_baseline_seconds_ceiling,
                )
            ),
        )


@dataclass(frozen=True)
class MaturationConfig:
    """The ``[developmental_stage]`` config block. Ships ``enabled = false``
    (ship-inert, matching the Spot/Mundus convention): a false value runs the
    entity un-staged exactly as today. Defaults are conservative — a real
    gestation takes many sleep cycles and substantial lived time."""

    enabled: bool = False
    min_sleep_cycles: int = 5
    min_consolidation_passes: int = 3
    min_lived_seconds: float = 86400.0
    gate_cadence_seconds: float = 60.0
    require_operator_ack_for_birth: bool = False
    regulation_thresholds: RegulationThresholds = field(
        default_factory=RegulationThresholds
    )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "MaturationConfig":
        d = dict(data or {})
        base = cls()
        return cls(
            enabled=bool(d.get("enabled", base.enabled)),
            min_sleep_cycles=int(d.get("min_sleep_cycles", base.min_sleep_cycles)),
            min_consolidation_passes=int(
                d.get("min_consolidation_passes", base.min_consolidation_passes)
            ),
            min_lived_seconds=float(d.get("min_lived_seconds", base.min_lived_seconds)),
            gate_cadence_seconds=float(
                d.get("gate_cadence_seconds", base.gate_cadence_seconds)
            ),
            require_operator_ack_for_birth=bool(
                d.get(
                    "require_operator_ack_for_birth",
                    base.require_operator_ack_for_birth,
                )
            ),
            regulation_thresholds=RegulationThresholds.from_dict(
                d.get("regulation_thresholds")
            ),
        )


# --- Readiness (C1 ^ C2 ^ C3, fail-closed) ---------------------------------


@dataclass(frozen=True)
class ConditionResult:
    name: str
    met: bool
    detail: str


@dataclass(frozen=True)
class Readiness:
    c1: ConditionResult
    c2: ConditionResult
    c3: ConditionResult

    @property
    def ready(self) -> bool:
        return self.c1.met and self.c2.met and self.c3.met

    @property
    def unmet(self) -> tuple[str, ...]:
        return tuple(c.name for c in (self.c1, self.c2, self.c3) if not c.met)

    @property
    def passed_markers(self) -> tuple[str, ...]:
        return tuple(c.name for c in (self.c1, self.c2, self.c3) if c.met)


def _num(value: Any) -> float | None:
    """Best-effort numeric read; ``None`` (fail-closed) on a missing/bad value."""
    if isinstance(value, bool):  # guard: bool is an int subclass
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _evaluate_c1(
    readout: Mapping[str, Any] | None, t: RegulationThresholds
) -> ConditionResult:
    """C1 — every regulation marker crosses its threshold. Fail-closed: an
    absent/stale readout (``None``) or any missing marker is NOT met. The caller
    passes ``None`` for a stale readout so staleness fails closed here too."""
    if readout is None:
        return ConditionResult("C1_regulation_baseline", False, "readout absent/stale")

    if t.endogenous_self_sustain and not bool(readout.get("endogenous_self_sustain")):
        return ConditionResult(
            "C1_regulation_baseline", False, "endogenous rhythm not self-sustaining"
        )
    if t.entrain_then_autonomy and not bool(readout.get("entrain_then_autonomy")):
        return ConditionResult(
            "C1_regulation_baseline", False, "entrain-then-autonomy not demonstrated"
        )

    hrv = _num(readout.get("hrv_variability"))
    if hrv is None or hrv < t.hrv_variability_floor:
        return ConditionResult(
            "C1_regulation_baseline", False, "HRV-analog below floor"
        )

    pe = _num(readout.get("womb_prediction_error"))
    if pe is None or pe > t.womb_prediction_error_ceiling:
        return ConditionResult(
            "C1_regulation_baseline", False, "womb prediction error above ceiling"
        )

    rtb = _num(readout.get("return_to_baseline_seconds"))
    if rtb is None or rtb > t.return_to_baseline_seconds_ceiling:
        return ConditionResult(
            "C1_regulation_baseline", False, "return-to-baseline too slow"
        )

    return ConditionResult("C1_regulation_baseline", True, "all markers crossed")


def _evaluate_c2(
    sleep_count: int | None,
    consolidation_passes: int | None,
    cfg: MaturationConfig,
) -> ConditionResult:
    """C2 — sleep happened AND the world model actually trained. Fail-closed on
    a missing signal; BOTH the sleep count and the consolidation passes must
    reach their floor (an empty sleep does not count)."""
    if sleep_count is None or sleep_count < cfg.min_sleep_cycles:
        return ConditionResult(
            "C2_reality_model_consolidated",
            False,
            f"sleep cycles {sleep_count} < {cfg.min_sleep_cycles}",
        )
    if consolidation_passes is None or consolidation_passes < cfg.min_consolidation_passes:
        return ConditionResult(
            "C2_reality_model_consolidated",
            False,
            f"consolidation passes {consolidation_passes} "
            f"< {cfg.min_consolidation_passes}",
        )
    return ConditionResult(
        "C2_reality_model_consolidated", True, "sleep + consolidation evidence present"
    )


def _evaluate_c3(lived_seconds: float | None, cfg: MaturationConfig) -> ConditionResult:
    """C3 — the lived-subjective-time floor. Fail-closed on a missing value."""
    if lived_seconds is None or lived_seconds < cfg.min_lived_seconds:
        return ConditionResult(
            "C3_min_lived_time",
            False,
            f"lived {lived_seconds}s < {cfg.min_lived_seconds}s",
        )
    return ConditionResult("C3_min_lived_time", True, "lived-time floor reached")


def evaluate_readiness(
    *,
    readiness_readout: Mapping[str, Any] | None,
    sleep_count: int | None,
    consolidation_passes: int | None,
    lived_seconds: float | None,
    config: MaturationConfig,
) -> Readiness:
    """Evaluate C1 ^ C2 ^ C3, fail-closed. All signals are READ, never written —
    the gate measures readiness and imposes no development (see module docstring;
    warmed-up-signal precedent: paper §6.6, ``soma-coldstart-regulation-warmup``).

    Pass ``readiness_readout=None`` when the womb readout is absent OR stale so C1
    fails closed in both cases."""
    return Readiness(
        c1=_evaluate_c1(readiness_readout, config.regulation_thresholds),
        c2=_evaluate_c2(sleep_count, consolidation_passes, config),
        c3=_evaluate_c3(lived_seconds, config),
    )


# --- Embodiment-availability guard + birth decision ------------------------


def embodiment_available(
    *, mundus_enabled: bool, operator_approved: bool, reachable: bool
) -> bool:
    """Whether the entity can actually be born into an embodied world: Mundus's
    existing two-layer gate (``[mundus].enabled`` config layer AND
    ``KAINE_MUNDUS_OPERATOR_APPROVED=1`` operator layer) AND reachability. This
    is READ as a precondition; the gate never flips Mundus on."""
    return bool(mundus_enabled) and bool(operator_approved) and bool(reachable)


@dataclass(frozen=True)
class BirthDecision:
    action: str
    reason: str
    readiness: Readiness

    @property
    def should_birth(self) -> bool:
        return self.action == ACTION_BIRTH

    @property
    def holding(self) -> bool:
        return self.action in (
            ACTION_HOLD_AWAITING_EMBODIMENT,
            ACTION_HOLD_AWAITING_ACK,
        )


def decide_birth(
    *,
    readiness: Readiness,
    embodiment_ready: bool,
    operator_ack: bool = False,
    require_operator_ack: bool = False,
) -> BirthDecision:
    """Combine developmental readiness with the embodiment-availability guard.

    - not developmentally ready               -> keep gestating (report unmet Cn);
    - ready but embodiment unavailable        -> HOLD in the womb, loud repeated
      ``stage.birth.ready{awaiting_embodiment}`` (never born into an absent world,
      never a silent stall);
    - ready ^ available but an operator ack is required and absent (supervised
      shakedown) -> HOLD awaiting the ack;
    - ready ^ available ^ (ack not required or given) -> BIRTH.
    """
    if not readiness.ready:
        return BirthDecision(
            ACTION_GESTATING, "unmet: " + ",".join(readiness.unmet), readiness
        )
    if not embodiment_ready:
        return BirthDecision(
            ACTION_HOLD_AWAITING_EMBODIMENT, "awaiting_embodiment", readiness
        )
    if require_operator_ack and not operator_ack:
        return BirthDecision(ACTION_HOLD_AWAITING_ACK, "awaiting_operator_ack", readiness)
    return BirthDecision(ACTION_BIRTH, "ready_and_available", readiness)


# --- Stage-event payload builders ------------------------------------------
#
# The caller publishes these under ``source = LIFECYCLE_SOURCE`` (-> lifecycle.out).
# Payloads carry only operational/observability fields — never sensory content.


def gestation_started_payload(*, gestation_started_at: str | None) -> dict[str, Any]:
    return {"stage": "gestation", "gestation_started_at": gestation_started_at}


def gestation_no_stimulus_payload() -> dict[str, Any]:
    return {"stage": "gestation", "reason": "no_womb_feed_configured"}


def birth_ready_payload(decision: BirthDecision) -> dict[str, Any]:
    return {
        "reason": decision.reason,
        "passed_markers": list(decision.readiness.passed_markers),
        "unmet": list(decision.readiness.unmet),
    }


def birth_payload(
    *,
    readiness: Readiness,
    sleep_count: int | None,
    lived_seconds: float | None,
) -> dict[str, Any]:
    return {
        "stage": "embodied",
        "passed_markers": list(readiness.passed_markers),
        "sleep_count": sleep_count,
        "lived_seconds": lived_seconds,
    }
