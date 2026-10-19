# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The entity's first-class developmental stage (`developmental-maturation-gate`).

A persistent, one-way developmental arc: a mind spends its **developmental phase** in the stimulus source and
**matures** into the embodied world exactly once. The only legal transition is
``development -> embodied``; there is NO path back to the stimulus source (a mind matures
once and never regresses).

The stage is a small file-backed per-fork state (mirroring
``kaine.perception_state``'s desired/runtime split): it lives under the per-fork
state root at ``state/lifecycle/stage.json`` so a fork inherits its parent's
stage and only ever advances it. It is read at boot and written only by the
gate runner (first tick, when evidence changes, and at maturation).

Boot defaults encode a NORMATIVE invariant (spec: *A first-class, monotonic
developmental stage*):

  - a genuinely fresh entity (no stage file, no prior lived history) begins in
    ``development``;
  - an entity with prior lived history (an existing fork / preservation record)
    but no stage file defaults to ``embodied`` — a mind that has already lived
    is NEVER regressed into a stimulus source.

This module is deliberately pure: stdlib + the shared atomic JSON writer only.
It imports nothing from ``kaine.cycle`` or ``kaine.modules`` so the gate can be
wired anywhere without an import cycle.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable

from kaine import legacy_aliases, legacy_names
from kaine.lifecycle.stored_field_names import stimulus_source_params_record
from kaine.state_io import write_json_atomic

if TYPE_CHECKING:
    from kaine.lifecycle.identity import EntityIdentity
from kaine.storage import resolve

# Per-fork developmental-stage file. Under the per-fork state root, like other
# per-fork state, so a fork inherits the parent's stage.
DEFAULT_STAGE_PATH = Path("state/lifecycle/stage.json")
STAGE_PATH = DEFAULT_STAGE_PATH

DEVELOPMENT = "development"
EMBODIED = "embodied"
STAGES = (DEVELOPMENT, EMBODIED)


class StageValueError(Exception):
    """A stored stage value is not one this code recognizes.

    Deliberately not a ValueError: the stage reader's fail-safe for an unreadable
    file catches ValueError, and an unrecognized value must never be swallowed into
    a stage. The cycle refuses to boot on it.
    """

    def __init__(
        self, value: Any, path: Path | None = None, *, top_level: bool = False
    ) -> None:
        self.value = value
        self.path = path
        self.top_level = top_level
        self.value_repr = _stage_repr(value)
        if top_level:
            if path is not None:
                message = (
                    f"stage file {path} does not hold a JSON object ({self.value_repr}); "
                    "inspect it, then correct it or move it aside"
                )
            else:
                message = f"stage data is not a JSON object ({self.value_repr})"
        else:
            if path is not None:
                message = (
                    f"stage file {path} holds an unrecognized stage value {self.value_repr}; "
                    "inspect it, then correct it or move it aside"
                )
            else:
                message = f"unrecognized stage value {self.value_repr}"
        super().__init__(message)


def _stage_repr(value: Any) -> str:
    """Return a short, safe representation of a stage value for diagnostics."""
    r = repr(value)
    if len(r) > 64:
        return r[:61] + "..."
    return r


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def has_prior_lived_history(
    identity: "EntityIdentity | None" = None,
    state_root: Path | str = "state",
    bundle_roots: Iterable[Path | str] = (),
) -> bool:
    """Detect whether this entity has already lived.

    A genuinely fresh entity has a known identity, no own lived artifacts in
    this tree, and no fork/preservation/bundle record naming it or one of its
    ancestors.

    An entity is treated as already-lived when:

      * its identity is unknown (``None``) — lineage is unavailable, so the
        non-regressing answer is ``True``;
      * any of this tree's own lived artifacts exist (lifecycle stage file,
        the world model checkpoint, the sleep divergence record, perception
        desired-state) — these prove the *current* tree has lived regardless
        of sidecars;
      * a fork sidecar, preservation manifest, or configured bundle manifest
        records an entity ID that matches this entity or one of its ancestors.

    ``forks/`` and ``preservation/`` may hold other entities; they only count
    when their identity metadata names this lineage. The implementation is
    imported lazily from ``kaine.lifecycle.identity`` so this module stays
    free of an import cycle.
    """
    from kaine.lifecycle.identity import lived_before

    return lived_before(identity, state_root, bundle_roots)


def _coerce_stage(value: Any) -> str:
    """Coerce a persisted stage value.

    An unrecognized value stops the boot instead of reading as embodied.
    A stored ``development`` keeps reading as the developmental stage after the rename.
    """
    if not isinstance(value, str):
        raise StageValueError(value)
    original_value = value
    for entry in legacy_aliases.active(legacy_names.STAGE_VALUES):
        if value == entry["old"]:
            value = entry["new"]
    if value in STAGES:
        return value
    raise StageValueError(original_value)


def _coerce_lived_seconds(value: Any) -> float:
    """Defensive coerce: a corrupt value can only delay maturation."""
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
    """Defensive coerce: a corrupt value can only delay maturation."""
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    if value < 0:
        return 0
    return value


def _coerce_sleep_cursor(value: Any) -> str | None:
    """Defensive coerce: a corrupt cursor is treated as a fresh development."""
    if not isinstance(value, str):
        return None
    if not re.fullmatch(r"^\d+-\d+$", value):
        return None
    return value


def _coerce_stimulus_source_t_at_maturation(value: Any) -> float | None:
    """Defensive coerce: a corrupt stimulus source time is treated as unrecorded."""
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value) or value < 0:
        return None
    return value


def _coerce_stimulus_source_seconds(value: Any) -> float | None:
    """Defensive coerce: a corrupt stimulus source time is treated as unrecorded."""
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value) or value < 0:
        return None
    return value


def _coerce_stimulus_source_seed(value: Any) -> int | None:
    """Defensive coerce: a corrupt stimulus source seed is treated as unrecorded."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _coerce_stimulus_source_params_digest(value: Any) -> str | None:
    """Defensive coerce: a corrupt digest is treated as unrecorded."""
    if not isinstance(value, str):
        return None
    if not re.fullmatch(r"^[0-9a-f]{64}$", value):
        return None
    return value


def _coerce_maturation_bloom_ends_at(value: Any) -> str | None:
    """Defensive coerce: a corrupt bloom end time is treated as unrecorded."""
    if not isinstance(value, str):
        return None
    return value


@dataclass(frozen=True)
class StageState:
    """The persisted developmental stage.

    ``stage``                — ``development`` | ``embodied``.
    ``development_started_at`` — ISO time the developmental phase began (the C3 lived-time anchor).
    ``born_at``              — ISO time of the maturation transition (None until born).
    ``lived_seconds``        — cumulative subjective lived time in the developmental phase.
    ``sleep_count``          — cumulative sleep completions.
    ``sleep_cursor``        — last scanned ``sleep.out`` stream id.
    ``stimulus_source_t_at_maturation``      — stimulus source time in seconds when the maturation bloom ended (None until recorded).
    ``stimulus_source_seed``            — procedural stimulus source seed active at maturation (None until recorded).
    ``stimulus_source_params_digest``   — sha256 hex digest of the stimulus source parameters active at maturation (None until recorded).
    ``maturation_bloom_ends_at``  — UTC wall time when the maturation bloom ends (ISO-8601, None until recorded).
    ``stimulus_source_seconds``: the stimulus source clock's own elapsed time, recorded by the gate runner each tick and at shutdown, so a restart resumes the stimulus where it stopped (None until recorded).
    """

    stage: str = DEVELOPMENT
    development_started_at: str | None = None
    born_at: str | None = None
    lived_seconds: float = 0.0
    sleep_count: int = 0
    sleep_cursor: str | None = None
    stimulus_source_t_at_maturation: float | None = None
    stimulus_source_seed: int | None = None
    stimulus_source_params_digest: str | None = None
    maturation_bloom_ends_at: str | None = None
    stimulus_source_seconds: float | None = None

    @property
    def is_developing(self) -> bool:
        return self.stage == DEVELOPMENT

    @property
    def is_embodied(self) -> bool:
        return self.stage == EMBODIED

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "StageState":
        if data is not None and not isinstance(data, dict):
            raise StageValueError(data, top_level=True)
        data = legacy_aliases.map_stage_record(dict(data or {}))
        if "stage" in data:
            stage = _coerce_stage(data["stage"])
        else:
            stage = DEVELOPMENT
        return cls(
            stage=stage,
            development_started_at=data.get("development_started_at"),
            born_at=data.get("born_at"),
            lived_seconds=_coerce_lived_seconds(data.get("lived_seconds", 0.0)),
            sleep_count=_coerce_sleep_count(data.get("sleep_count", 0)),
            sleep_cursor=_coerce_sleep_cursor(data.get("sleep_cursor")),
            stimulus_source_t_at_maturation=_coerce_stimulus_source_t_at_maturation(data.get("stimulus_source_t_at_maturation")),
            stimulus_source_seed=_coerce_stimulus_source_seed(data.get("stimulus_source_seed")),
            stimulus_source_params_digest=_coerce_stimulus_source_params_digest(data.get("stimulus_source_params_digest")),
            maturation_bloom_ends_at=_coerce_maturation_bloom_ends_at(data.get("maturation_bloom_ends_at")),
            stimulus_source_seconds=_coerce_stimulus_source_seconds(data.get("stimulus_source_seconds")),
        )


def read_stage(path: Path | None = None) -> StageState | None:
    """Read the persisted stage, or ``None`` if no stage file exists.

    Returning ``None`` (rather than a default) lets :func:`resolve_boot_stage`
    apply the preserved-entity invariant: the *absence* of a file is the signal,
    and it means different things for a fresh entity versus one with prior lived
    history."""
    target = resolve(path or STAGE_PATH)
    try:
        exists = target.exists()
    except OSError:
        # If we cannot verify whether the stage file exists, we must fail safe
        # toward `embodied` rather than return `None` and risk regressing a
        # possibly-lived mind into the stimulus source.
        return StageState(stage=EMBODIED)
    if not exists:
        return None
    try:
        data = json.loads(target.read_text())
    except (json.JSONDecodeError, OSError, ValueError, TypeError):
        # A corrupt, malformed or unreadable stage file must fail safe toward
        # `embodied` (never regress a possibly-lived mind into the stimulus source), not
        # crash boot.
        return StageState(stage=EMBODIED)
    if not isinstance(data, dict):
        raise StageValueError(data, path=target, top_level=True) from None
    try:
        return StageState.from_dict(data)
    except StageValueError as exc:
        raise StageValueError(exc.value, path=target, top_level=exc.top_level) from None
    except (ValueError, TypeError):
        # A corrupt, malformed or unreadable stage file must fail safe toward
        # `embodied` (never regress a possibly-lived mind into the stimulus source), not
        # crash boot.
        return StageState(stage=EMBODIED)


def write_stage(state: StageState, path: Path | None = None) -> None:
    target = resolve(path or STAGE_PATH)
    write_json_atomic(target, state.to_dict())


def resolve_boot_stage(
    *,
    has_prior_lived_history: bool,
    path: Path | None = None,
    now_iso: str | None = None,
) -> StageState:
    """Resolve the developmental stage at boot, enforcing the boot invariants.

    - An existing stage file is authoritative (a fork inherits it verbatim).
    - No stage file + prior lived history => ``embodied`` (NEVER ``development``):
      a mind that has already lived is never regressed into a stimulus source.
    - No stage file + genuinely fresh => ``development``, anchoring the lived-time
      clock at ``now``.

    This function does not write; the caller persists the resolved stage.
    """
    existing = read_stage(path)
    if existing is not None:
        return existing
    if has_prior_lived_history:
        # Preserved-entity invariant (NORMATIVE): never regress a lived mind.
        return StageState(stage=EMBODIED)
    return StageState(stage=DEVELOPMENT, development_started_at=now_iso or _now_iso())


def advance_to_embodied(state: StageState, *, now_iso: str | None = None) -> StageState:
    """Return the state transitioned to ``embodied`` (the maturation transition).

    Monotonic and one-shot: an already-``embodied`` state is returned UNCHANGED
    (idempotent — maturation fires at most once), and there is no inverse. The
    caller checks :func:`maturation_is_new` to decide whether to fire the maturation event.
    """
    if state.is_embodied:
        return state
    return replace(state, stage=EMBODIED, born_at=now_iso or _now_iso())


def maturation_is_new(before: StageState, after: StageState) -> bool:
    """True iff ``after`` represents a fresh development->embodied transition of
    ``before`` — the one-shot guard the maturation event/handoff keys off."""
    return before.is_developing and after.is_embodied


def record_maturation_stimulus_source(
    state: StageState,
    *,
    stimulus_source_t_at_maturation: float | None,
    stimulus_source_seed: int | None,
    stimulus_source_params_digest: str | None,
    bloom_ends_at: str | None,
) -> StageState:
    """Record the stimulus-source-state snapshot taken at maturation.

    Raises:
        ValueError: if ``state`` is not already ``embodied``.
    """
    if not state.is_embodied:
        raise ValueError("record_maturation_stimulus_source: state must be embodied")
    return replace(
        state,
        stimulus_source_t_at_maturation=stimulus_source_t_at_maturation,
        stimulus_source_seed=stimulus_source_seed,
        stimulus_source_params_digest=stimulus_source_params_digest,
        maturation_bloom_ends_at=bloom_ends_at,
    )


def stimulus_source_params_digest(params: object) -> str:
    """Return a stable sha256 hex digest of a stimulus source parameters object.

    ``params`` must be a dataclass instance (e.g. ``StimulusSourceParams``); its fields are
    serialised under their stored names (see :mod:`kaine.lifecycle.stored_field_names`) as a
    compact sorted JSON object before hashing.
    """
    payload = json.dumps(
        stimulus_source_params_record(params), sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
