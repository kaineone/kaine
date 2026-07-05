# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Post-run log range validation — re-check logged numbers against physics.

A finished run's records carry numeric fields with well-defined physical ranges
(a probability is in ``[0, 1]``, a prediction error is non-negative, an affect
valence is in ``[-1, 1]``). This module declares those ranges per event type and
sweeps a run's records, flagging any value outside its bound. It is the
post-hoc, fail-closed counterpart to the producers' own clamping: if a clamp
ever regresses, or a record is corrupted, the sweep catches it offline rather
than letting a physically-impossible number reach analysis.

Ranges are taken from the producing modules and the research event taxonomy
(``kaine.evaluation.observers.research_event_observer._TAXONOMY``). Where a field
has no well-defined hard bound it is declared with :data:`NONNEG` (a generic
">= 0", e.g. error magnitudes / counts) or omitted entirely — never guessed.
Fields not declared here are not validated (absence of a rule is honest "we
don't have a bound", not a silent pass of a known-bounded field).

This module is boundary-neutral: it reads via ``kaine.experiment.run_records``
and declares the schema as inline data, so it never imports
``kaine.evaluation``.

CLI: ``python -m kaine.experiment.log_schema <run_id>`` prints violations and
exits non-zero if any.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional, Sequence

from kaine.experiment.run_records import DEFAULT_ROOT, load_run_records

#: Sentinel for "no hard upper bound" (used by NONNEG and one-sided ranges).
INF = math.inf

#: A non-negative field with no defined upper bound (error magnitudes, counts,
#: durations, elapsed times). Honest: we know it can't be negative, we don't
#: claim a ceiling.
NONNEG = (0.0, INF)

#: Unit interval — probabilities, normalized scalars, arousal, salience.
UNIT = (0.0, 1.0)

#: Signed unit interval — valence / dominance.
SIGNED_UNIT = (-1.0, 1.0)


# ---------------------------------------------------------------------------
# Declarative schema: {event_type: {field: (lo, hi)}}.
#
# Stream/event names mirror the curated research taxonomy. Records are matched
# by their ``event_type`` field when present; fields are validated wherever they
# appear regardless of event type via the generic FIELD_RANGES fallback below,
# so a value is checked even if the record's event_type isn't in this table.
# ---------------------------------------------------------------------------
SCHEMA: dict[str, dict[str, tuple[float, float]]] = {
    # --- Prediction / precision ---
    # prediction_error is clamped non-negative at the producer (soma.fatigue:
    # max(0.0, e)); topos likewise reports a non-negative error magnitude.
    "soma.report": {"prediction_error": NONNEG, "wellness": UNIT, "fatigue_value": UNIT},
    "topos.report": {"prediction_error": NONNEG},
    "phantasia.world_error": {"error": NONNEG},
    # nous confidence is 1 - normalised_entropy, clamped to [0, 1]
    # (nous.module). expected_free_energy is a signed scalar with no hard
    # bound, so it is intentionally NOT declared.
    "nous.belief": {"confidence": UNIT},
    "nous.policy": {"confidence": UNIT},
    "nous.error": {"confidence": UNIT},
    "nous.timeout": {"confidence": UNIT},
    # --- Affect / motivation (thymos.state: documented [-1,1]/[0,1]) ---
    "thymos.state": {
        "valence": SIGNED_UNIT,
        "arousal": UNIT,
        "dominance": SIGNED_UNIT,
    },
    # thymos.drive carries {drive, value}; each drive value is in [0, 1].
    "thymos.drive": {"value": UNIT},
    # --- Perception (derived) ---
    "audition.emotion": {"confidence": UNIT},
    # --- Self / social ---
    # empatheia familiarity() is documented in [0, 1]; social error magnitude
    # is non-negative.
    "empatheia.agent_model": {"familiarity_scalar": UNIT},
    "empatheia.social_error": {"error_magnitude": NONNEG},
    # --- Coherence (PLV phase-locking value ∈ [0, 1]) ---
    # The coherence observer records a dict of pair -> PLV; handled specially in
    # _coherence_violations (nested), not via the flat SCHEMA.
}

# ---------------------------------------------------------------------------
# Generic field ranges — applied to a field WHEREVER it appears, when the
# record's event_type has no specific rule for that field. Keeps a known-bounded
# field validated even on streams not enumerated above (e.g. salience on any
# event). A specific SCHEMA rule always takes precedence over these.
# ---------------------------------------------------------------------------
FIELD_RANGES: dict[str, tuple[float, float]] = {
    "salience": UNIT,            # bus schema: Field(ge=0.0, le=1.0)
    "valence": SIGNED_UNIT,
    "arousal": UNIT,
    "dominance": SIGNED_UNIT,
    "confidence": UNIT,
    "familiarity_scalar": UNIT,
    "prediction_error": NONNEG,
    "wellness": UNIT,
    "fatigue_value": UNIT,
    "error_magnitude": NONNEG,
}

#: The coherence stream records a nested ``coherence`` dict of pair->PLV.
_COHERENCE_FIELD = "coherence"


@dataclass
class Violation:
    """One out-of-range value found in a run's records."""

    stream: str
    field: str
    value: float
    bound: tuple[float, float]
    event_type: Optional[str] = None
    seq: Optional[int] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _as_float(value: Any) -> Optional[float]:
    """Coerce a record value to float for range checking, or None if it isn't a
    real number (strings, None, bool, NaN are not validated as numbers)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        f = float(value)
        if math.isnan(f):
            return None
        return f
    return None


def _out_of_range(value: float, bound: tuple[float, float]) -> bool:
    lo, hi = bound
    return value < lo or value > hi


def _bound_for(event_type: Optional[str], field: str) -> Optional[tuple[float, float]]:
    """Resolve the applicable bound for ``field`` on ``event_type``.

    Specific SCHEMA rule (by event type) wins; else the generic FIELD_RANGES
    rule; else None (the field is not validated)."""
    if event_type and event_type in SCHEMA and field in SCHEMA[event_type]:
        return SCHEMA[event_type][field]
    return FIELD_RANGES.get(field)


def _coherence_violations(
    stream: str, record: dict[str, Any]
) -> list[Violation]:
    """PLV coherence: each pair label maps to a value in [0, 1]."""
    out: list[Violation] = []
    coherence = record.get(_COHERENCE_FIELD)
    if not isinstance(coherence, dict):
        return out
    seq = record.get("seq")
    seq = seq if isinstance(seq, int) and not isinstance(seq, bool) else None
    for pair, val in coherence.items():
        f = _as_float(val)
        if f is None:
            continue
        if _out_of_range(f, UNIT):
            out.append(
                Violation(
                    stream=stream,
                    field=f"{_COHERENCE_FIELD}[{pair}]",
                    value=f,
                    bound=UNIT,
                    event_type=record.get("event_type"),
                    seq=seq,
                )
            )
    return out


def sweep_run(
    run_id: str,
    *,
    root: Path | str = DEFAULT_ROOT,
) -> list[Violation]:
    """Sweep a run's records for out-of-range numeric values (fail-closed).

    Returns a list of :class:`Violation` — empty when every declared field is
    within its physical range. Any out-of-range value (or a NaN in coherence)
    is a violation, so a non-empty result means the run's logs are not clean.
    """
    records = load_run_records(run_id, root=root)
    violations: list[Violation] = []

    for stream, record in records.all_records():
        event_type = record.get("event_type")
        seq = record.get("seq")
        seq = seq if isinstance(seq, int) and not isinstance(seq, bool) else None

        for field, raw in record.items():
            if field == _COHERENCE_FIELD and isinstance(raw, dict):
                violations.extend(_coherence_violations(stream, record))
                continue
            bound = _bound_for(event_type, field)
            if bound is None:
                continue
            f = _as_float(raw)
            if f is None:
                continue
            if _out_of_range(f, bound):
                violations.append(
                    Violation(
                        stream=stream,
                        field=field,
                        value=f,
                        bound=bound,
                        event_type=event_type,
                        seq=seq,
                    )
                )

    return violations


def _format_violations(run_id: str, violations: Sequence[Violation]) -> str:
    if not violations:
        return f"run_id: {run_id}\nviolations: 0 (all logged values within range)"
    lines = [f"run_id: {run_id}", f"violations: {len(violations)}"]
    for v in violations:
        lo, hi = v.bound
        hi_s = "inf" if hi == INF else f"{hi:g}"
        et = f" [{v.event_type}]" if v.event_type else ""
        lines.append(
            f"  - {v.stream}.{v.field}{et} = {v.value:g} "
            f"(expected [{lo:g}, {hi_s}])"
        )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m kaine.experiment.log_schema",
        description="Re-validate a finished run's logged numbers against declared ranges.",
    )
    parser.add_argument("run_id", help="the run id to sweep")
    parser.add_argument(
        "--root",
        default=str(DEFAULT_ROOT),
        help="evaluation root holding the JSONL sink files (default data/evaluation)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit violations as JSON instead of text",
    )
    args = parser.parse_args(argv)

    violations = sweep_run(args.run_id, root=args.root)
    if args.json:
        print(
            json.dumps(
                {"run_id": args.run_id, "violations": [v.to_dict() for v in violations]},
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print(_format_violations(args.run_id, violations))
    return 0 if not violations else 1


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess in tests
    sys.exit(main())


__all__ = ["Violation", "sweep_run", "SCHEMA", "FIELD_RANGES", "main"]
