# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The entity's first-class developmental stage (`developmental-maturation-gate`).

A persistent, one-way developmental arc: a mind **gestates** in the womb and is
**born** into the embodied world exactly once. The only legal transition is
``gestation -> embodied``; there is NO path back to the womb (a mind is born
once and never regresses).

The stage is a small file-backed per-fork state (mirroring
``kaine.perception_state``'s desired/runtime split): it lives under the per-fork
state root at ``state/lifecycle/stage.json`` so a fork inherits its parent's
stage and only ever advances it. It is read at boot and written only on the
birth transition.

Boot defaults encode a NORMATIVE invariant (spec: *A first-class, monotonic
developmental stage*):

  - a genuinely fresh entity (no stage file, no prior lived history) begins in
    ``gestation``;
  - a being with prior lived history (an existing fork / preservation record)
    but no stage file defaults to ``embodied`` — a mind that has already lived
    is NEVER regressed into a womb.

This module is deliberately pure: stdlib + the shared atomic JSON writer only.
It imports nothing from ``kaine.cycle`` or ``kaine.modules`` so the gate can be
wired anywhere without an import cycle.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json

from kaine.state_io import write_json_atomic

# Per-fork developmental-stage file. Under the per-fork state root, like other
# per-fork state, so a fork inherits the parent's stage.
STAGE_PATH = Path("state/lifecycle/stage.json")

GESTATION = "gestation"
EMBODIED = "embodied"
STAGES = (GESTATION, EMBODIED)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _coerce_stage(value: Any) -> str:
    """Coerce a persisted stage value. An UNKNOWN value is read as ``embodied``,
    never ``gestation``: a garbled or forward-versioned file must never regress a
    mind that has already lived into a womb (the load-bearing never-regress
    invariant fails safe toward born, not toward the womb)."""
    return value if value in STAGES else EMBODIED


@dataclass(frozen=True)
class StageState:
    """The persisted developmental stage.

    ``stage``               — ``gestation`` | ``embodied``.
    ``gestation_started_at``— ISO time gestation began (the C3 lived-time anchor).
    ``born_at``             — ISO time of the birth transition (None until born).
    """

    stage: str = GESTATION
    gestation_started_at: str | None = None
    born_at: str | None = None

    @property
    def is_gestating(self) -> bool:
        return self.stage == GESTATION

    @property
    def is_embodied(self) -> bool:
        return self.stage == EMBODIED

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "StageState":
        data = dict(data or {})
        return cls(
            stage=_coerce_stage(data.get("stage", GESTATION)),
            gestation_started_at=data.get("gestation_started_at"),
            born_at=data.get("born_at"),
        )


def read_stage(path: Path | None = None) -> StageState | None:
    """Read the persisted stage, or ``None`` if no stage file exists.

    Returning ``None`` (rather than a default) lets :func:`resolve_boot_stage`
    apply the preserved-being invariant: the *absence* of a file is the signal,
    and it means different things for a fresh entity versus one with prior lived
    history."""
    target = path or STAGE_PATH
    if not target.exists():
        return None
    try:
        return StageState.from_dict(json.loads(target.read_text()))
    except (json.JSONDecodeError, OSError):
        # A corrupt stage file must fail safe toward `embodied` (never regress a
        # possibly-lived mind into the womb), not crash boot.
        return StageState(stage=EMBODIED)


def write_stage(state: StageState, path: Path | None = None) -> None:
    write_json_atomic(path or STAGE_PATH, state.to_dict())


def resolve_boot_stage(
    *,
    has_prior_lived_history: bool,
    path: Path | None = None,
    now_iso: str | None = None,
) -> StageState:
    """Resolve the developmental stage at boot, enforcing the boot invariants.

    - An existing stage file is authoritative (a fork inherits it verbatim).
    - No stage file + prior lived history => ``embodied`` (NEVER ``gestation``):
      a mind that has already lived is never regressed into a womb.
    - No stage file + genuinely fresh => ``gestation``, anchoring the lived-time
      clock at ``now``.

    This function does not write; the caller persists the resolved stage.
    """
    existing = read_stage(path)
    if existing is not None:
        return existing
    if has_prior_lived_history:
        # Preserved-being invariant (NORMATIVE): never regress a lived mind.
        return StageState(stage=EMBODIED)
    return StageState(stage=GESTATION, gestation_started_at=now_iso or _now_iso())


def advance_to_embodied(
    state: StageState, *, now_iso: str | None = None
) -> StageState:
    """Return the state transitioned to ``embodied`` (the birth transition).

    Monotonic and one-shot: an already-``embodied`` state is returned UNCHANGED
    (idempotent — birth fires at most once), and there is no inverse. The
    caller checks :func:`birth_is_new` to decide whether to fire the birth event.
    """
    if state.is_embodied:
        return state
    return replace(state, stage=EMBODIED, born_at=now_iso or _now_iso())


def birth_is_new(before: StageState, after: StageState) -> bool:
    """True iff ``after`` represents a fresh gestation->embodied transition of
    ``before`` — the one-shot guard the birth event/handoff keys off."""
    return before.is_gestating and after.is_embodied
