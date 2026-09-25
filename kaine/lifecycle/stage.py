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
stage and only ever advances it. It is read at boot and written only by the
gate runner (first tick, when evidence changes, and at birth).

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

import json
import math
import re
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from kaine.state_io import write_json_atomic

# Per-fork developmental-stage file. Under the per-fork state root, like other
# per-fork state, so a fork inherits the parent's stage.
STAGE_PATH = Path("state/lifecycle/stage.json")

GESTATION = "gestation"
EMBODIED = "embodied"
STAGES = (GESTATION, EMBODIED)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def has_prior_lived_history(
    state_root: Path | str = "state",
    stage_path: Path | None = None,
) -> bool:
    """Detect whether a being has already lived on this fork.

    A genuinely fresh entity has no stage file and no other durable lived-state
    or preservation artifact. A being with any of the following is treated as
    already-lived and defaults to ``embodied`` (never regressed into a womb):

      - any fork snapshot under ``state/forks/``,
      - any preservation bundle under ``state/preservation/``,
      - a Phantasia world-model checkpoint,
      - a Hypnos consolidation-divergence record,
      - an operator-commanded perception desired-state.

    The stage file itself is excluded: its absence is the signal that lets
    :func:`resolve_boot_stage` apply the preserved-being invariant.
    """
    root = Path(state_root)
    if not root.exists():
        return False

    def _any_child(path: Path) -> bool:
        try:
            return any(path.iterdir())
        except OSError:
            return False

    indicators = [
        root / "forks",
        root / "preservation",
        root / "phantasia" / "world_model.ckpt",
        root / "hypnos" / "consolidation_divergence.json",
        root / "perception" / "desired.json",
    ]
    stage_target = Path(stage_path) if stage_path else STAGE_PATH
    excluded = {stage_target.resolve()}
    for indicator in indicators:
        try:
            if indicator.is_dir() and _any_child(indicator):
                return True
            if indicator.is_file() and indicator.resolve() not in excluded:
                return True
        except OSError:
            continue
    return False


def _coerce_stage(value: Any) -> str:
    """Coerce a persisted stage value. An UNKNOWN value is read as ``embodied``,
    never ``gestation``: a garbled or forward-versioned file must never regress a
    mind that has already lived into a womb (the load-bearing never-regress
    invariant fails safe toward born, not toward the womb)."""
    return value if value in STAGES else EMBODIED


def _coerce_lived_seconds(value: Any) -> float:
    """Defensive coerce: a corrupt value can only delay birth."""
    if isinstance(value, bool):
        return 0.0
    try:
        value = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(value) or value < 0:
        return 0.0
    return value


def _coerce_sleep_count(value: Any) -> int:
    """Defensive coerce: a corrupt value can only delay birth."""
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    if value < 0:
        return 0
    return value


def _coerce_hypnos_cursor(value: Any) -> str | None:
    """Defensive coerce: a corrupt cursor is treated as a fresh gestation."""
    if not isinstance(value, str):
        return None
    if not re.fullmatch(r"^\d+-\d+$", value):
        return None
    return value


@dataclass(frozen=True)
class StageState:
    """The persisted developmental stage.

    ``stage``               — ``gestation`` | ``embodied``.
    ``gestation_started_at``— ISO time gestation began (the C3 lived-time anchor).
    ``born_at``             — ISO time of the birth transition (None until born).
    ``lived_seconds``       — cumulative subjective lived time in gestation.
    ``sleep_count``         — cumulative Hypnos sleep completions.
    ``hypnos_cursor``       — last scanned ``hypnos.out`` stream id.
    """

    stage: str = GESTATION
    gestation_started_at: str | None = None
    born_at: str | None = None
    lived_seconds: float = 0.0
    sleep_count: int = 0
    hypnos_cursor: str | None = None

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
            lived_seconds=_coerce_lived_seconds(data.get("lived_seconds", 0.0)),
            sleep_count=_coerce_sleep_count(data.get("sleep_count", 0)),
            hypnos_cursor=_coerce_hypnos_cursor(data.get("hypnos_cursor")),
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


def advance_to_embodied(state: StageState, *, now_iso: str | None = None) -> StageState:
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
