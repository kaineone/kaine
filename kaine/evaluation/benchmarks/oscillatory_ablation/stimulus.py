# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Fixed, reproducible scripted stimulus batteries for the oscillatory ablation.

This module factors the determinism-keystone ``ScriptedBus`` pattern (a minimal
in-memory bus with caller-fixed entry ids, capturing broadcasts + intents) into
the runner package so the runner does not depend on the test module.

Two batteries are provided, built from the same ``_SourceSpec`` machinery so they
are directly comparable:

- **Engineered** (``ENGINEERED_STIMULUS``): two *phase-locked* sources carry
  LOWER raw salience than two *desynchronized* competitors. With the layer absent
  the desynchronized (higher-salience) events rank first; with the layer enabled
  at a sufficient precision gain the phase-locked events are boosted and the
  desynchronized ones attenuated, so selection re-ranks toward the coherent
  coalition — a controlled, measurable, directionally-*correct* effect. This is
  the positive-control battery.
- **Neutral / non-engineered** (``NEUTRAL_STIMULUS``): four sources with NO
  coherence *contrast* — every source shares one phase schedule, so all are
  equally phase-coherent and none is a low-salience coherent coalition waiting to
  be promoted. Precision-weighting by coherence has no discriminative signal
  here: an equal coherence factor multiplies every source, leaving the raw-salience
  ranking unchanged. This is the battery on which a real NULL ("the layer does
  essentially nothing here") is reachable and robust — it is NOT rigged to make
  the enabled arm re-rank. (Contrast the engineered battery, which deliberately
  hands the coherent coalition lower raw salience so the layer MUST re-rank to
  have an effect.)
- **Mislabeled / adversarial** (``MISLABELED_STIMULUS``): the ground-truth
  ``coherent=True`` label is deliberately put on a high-salience source that is
  NOT the most phase-locked, while the truly-synchronized source is labeled
  ``coherent=False``. The honest, monotone coherence layer tracks real PLV and
  promotes the truly-synchronized (labeled-False) source, so relative to the
  labels it re-ranks AWAY from the "coherent" source — the only way a genuinely
  NEGATIVE outcome is reachable through the real pipeline. With correctly-labeled
  coalitions the monotone layer can only WIN or NULL; NEGATIVE probes a
  label/reality mismatch (the layer tracking the wrong coherence).

Phases are fed to the cycle through a registry exposing ``all_modules()``: the
cycle's ``collect_phases=True`` path calls ``module.phase()`` per tick, so each
scripted source advances its own phase schedule. Phase-locked sources share one
schedule; desynchronized sources follow incommensurate schedules.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from kaine.bus.schema import Event
from kaine.cycle.engine import BASE_EPOCH


# ---------------------------------------------------------------------------
# Source specification: one scripted stream + its phase schedule.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _SourceSpec:
    """One scripted source: its raw salience and (offset, step) phase schedule.

    ``coherent`` is the ground-truth label — whether this source belongs to the
    phase-locked coalition the coherence layer is *hypothesized* to promote. It is
    used only by the runner's directional (WIN vs adverse) metric; it does not
    affect the cycle.
    """

    name: str
    salience: float
    offset: float
    step: float
    coherent: bool


# Engineered (positive-control) battery: two phase-locked sources at LOWER raw
# salience compete with two desynchronized sources at HIGHER raw salience, so an
# effective coherence layer must re-rank them once the PLV windows fill.
LOCKED_SALIENCE = 0.40
DRIFT_SALIENCE = 0.60
_LOCK_STEP = 0.5  # phase-locked sources share offset 0 + this step → PLV → 1

_ENGINEERED_SPECS: tuple[_SourceSpec, ...] = (
    _SourceSpec("lock_a", LOCKED_SALIENCE, 0.0, _LOCK_STEP, True),
    _SourceSpec("lock_b", LOCKED_SALIENCE, 0.0, _LOCK_STEP, True),
    _SourceSpec("drift_a", DRIFT_SALIENCE, 1.3, 0.91, False),
    _SourceSpec("drift_b", DRIFT_SALIENCE, 2.7, 2.17, False),
)

# Neutral (non-engineered) battery: NO coherence CONTRAST. Every source shares
# one phase schedule (offset 0, step _LOCK_STEP), so all are equally phase-
# coherent — precision-weighting produces the SAME coherence factor for each and
# cannot re-rank them. Saliences are slightly separated so the disabled-arm
# ranking is well-defined (not a tie-break), and no source is a coherence target
# (``coherent=False`` → empty ground-truth set), so a real NULL is reachable and
# robust. This is the falsification battery: an honest layer does essentially
# nothing here.
_NEUTRAL_SPECS: tuple[_SourceSpec, ...] = (
    _SourceSpec("src_a", 0.50, 0.0, _LOCK_STEP, False),
    _SourceSpec("src_b", 0.52, 0.0, _LOCK_STEP, False),
    _SourceSpec("src_c", 0.54, 0.0, _LOCK_STEP, False),
    _SourceSpec("src_d", 0.56, 0.0, _LOCK_STEP, False),
)

# Mislabeled / adversarial battery: the ground-truth coherence LABEL is put on
# the WRONG source. ``decoy`` carries the highest raw salience and the
# ``coherent=True`` label but is NOT phase-locked to its cohort; ``sync_a`` /
# ``sync_b`` ARE mutually phase-locked (the real coherent coalition) but are
# labeled ``coherent=False``. The honest, monotone coherence layer tracks real
# PLV, so it boosts the truly-synchronized ``sync_*`` sources over the decoy —
# which, against these labels, is a re-ranking AWAY from the "coherent" source, a
# genuinely NEGATIVE (adverse) coherence_alignment_delta produced through the
# real measurement pipeline (not a hand-fed classifier input).
#
# This is why NEGATIVE is a real, two-sided outcome: with CORRECTLY-labeled
# coalitions the monotone layer can only WIN or NULL (it can only push
# more-phase-locked sources up). NEGATIVE specifically probes a label/reality
# MISMATCH — the layer tracking a coherence the ground-truth label disagrees with.
_MISLABELED_SPECS: tuple[_SourceSpec, ...] = (
    _SourceSpec("decoy", 0.60, 1.30, 0.91, True),      # high salience, NOT locked, mislabeled coherent
    _SourceSpec("sync_a", 0.40, 0.0, _LOCK_STEP, False),  # truly locked, labeled non-coherent
    _SourceSpec("sync_b", 0.40, 0.0, _LOCK_STEP, False),  # locked to sync_a
    _SourceSpec("drift_x", 0.55, 2.70, 2.17, False),   # another non-locked competitor
)

# Backward-compatible source-name tuples (imported by tests + the docs prose).
LOCK_SOURCES = tuple(s.name for s in _ENGINEERED_SPECS if s.coherent)
DRIFT_SOURCES = tuple(s.name for s in _ENGINEERED_SPECS if not s.coherent)
ALL_SOURCES = tuple(s.name for s in _ENGINEERED_SPECS)


class ScriptedBus:
    """Minimal in-memory bus implementing exactly what the engine uses.

    Module streams are pre-seeded with caller-supplied, FIXED entry ids so that
    reading is reproducible across runs (unlike a time-based Redis id). Published
    events (workspace broadcasts and intents) are captured in order. This is the
    determinism-keystone bus, factored here so the runner is self-contained.
    """

    def __init__(self, streams: dict[str, list[tuple[str, Event]]]) -> None:
        self._streams: dict[str, list[tuple[str, Event]]] = {
            name: list(entries) for name, entries in streams.items()
        }
        self.workspace_broadcasts: list[dict[str, Any]] = []
        self.published: dict[str, list[Event]] = {}
        # The "now" gate: only events whose entry-id major component is <= this
        # are visible. A real Redis stream wouldn't contain future events yet;
        # offline we emulate that so each tick reads only its own events (one per
        # source per tick) instead of draining the whole script on tick 0.
        self._now_major = 0

    def advance(self) -> None:
        """Make the next tick's events (major == _now_major) readable."""
        self._now_major += 1

    async def read(
        self, stream: str, last_id: str = "0", count: int = 100, block_ms: int = 0
    ) -> list[tuple[str, Event]]:
        entries = self._streams.get(stream, [])
        out: list[tuple[str, Event]] = []
        for entry_id, event in entries:
            if _id_tuple(entry_id)[0] > self._now_major:
                break  # future event; not yet visible
            if _id_gt(entry_id, last_id):
                out.append((entry_id, event))
            if len(out) >= count:
                break
        return out

    async def publish(self, event: Event) -> str:
        self.published.setdefault(event.source, []).append(event)
        return f"{event.source}-pub"

    async def publish_workspace(
        self, snapshot: dict[str, Any], source: str = "syneidesis"
    ) -> str:
        self.workspace_broadcasts.append(snapshot)
        return "workspace-pub"

    async def close(self) -> None:
        return None


def _id_gt(entry_id: str, last_id: str) -> bool:
    if last_id in ("0", "0-0"):
        return True
    return _id_tuple(entry_id) > _id_tuple(last_id)


def _id_tuple(entry_id: str) -> tuple[int, int]:
    parts = entry_id.split("-")
    if len(parts) == 2:
        return int(parts[0]), int(parts[1])
    return int(parts[0]), 0


def _make_event(source: str, etype: str, salience: float, text: str, seq: int) -> Event:
    # Timestamp is irrelevant to selection; the engine re-stamps published events
    # from its own clock. Use the fixed base epoch for tidiness.
    return Event(
        source=source,
        type=etype,
        payload={"text": text, "seq": seq},
        salience=salience,
        timestamp=BASE_EPOCH,
    )


def _build_streams(
    specs: tuple[_SourceSpec, ...], n_ticks: int
) -> dict[str, list[tuple[str, Event]]]:
    """Build the module streams for ``specs`` with FIXED, reproducible entry ids.

    Each source emits ONE event PER TICK (so selection runs every tick and the
    coherence layer's phase windows accumulate enough samples). Entry ids must be
    unique ACROSS streams within a tick (Syneidesis keys salience_scores by
    entry_id) AND monotone within a stream. Ids are ``"<tick+1>-<source_index>"``
    — caller-fixed, so the run is reproducible (unlike a time-based Redis id).
    """
    streams: dict[str, list[tuple[str, Event]]] = {}
    for i, spec in enumerate(specs):
        label = "locked" if spec.coherent else "drift"
        entries: list[tuple[str, Event]] = []
        for t in range(n_ticks):
            entries.append(
                (
                    f"{t + 1}-{i}",
                    _make_event(spec.name, f"{spec.name}.signal", spec.salience, label, t),
                )
            )
        streams[f"{spec.name}.out"] = entries
    return streams


def scripted_streams(n_ticks: int) -> dict[str, list[tuple[str, Event]]]:
    """The engineered battery's module streams (backward-compatible entry point)."""
    return _build_streams(_ENGINEERED_SPECS, n_ticks)


class _ScriptedPhaseModule:
    """A phase provider with the minimal surface the cycle's phase collector uses.

    The cycle's ``_collect_module_phases`` reads ``module.name`` and calls
    ``module.phase()`` once per tick. Phase advances by a fixed step per call, so
    the schedule is a pure function of how many ticks have elapsed — fully
    deterministic. ``offset`` and ``step`` define the schedule; phase-locked
    sources share them, desynchronized sources use incommensurate steps.
    """

    def __init__(self, name: str, *, offset: float, step: float) -> None:
        self.name = name
        self._offset = float(offset)
        self._step = float(step)
        self._ticks = 0

    def phase(self) -> float:
        ph = (self._offset + self._ticks * self._step) % (2.0 * math.pi)
        self._ticks += 1
        return ph


class _SpecPhaseRegistry:
    """Registry exposing scripted streams AND scripted phase providers for specs.

    ``active_streams`` drives the engine's bus reads; ``all_modules`` drives the
    phase collector (only consulted when ``collect_phases=True``).
    """

    def __init__(self, specs: tuple[_SourceSpec, ...]) -> None:
        self._streams = sorted(f"{s.name}.out" for s in specs)
        self._modules = [
            _ScriptedPhaseModule(s.name, offset=s.offset, step=s.step) for s in specs
        ]

    def active_streams(self) -> list[str]:
        return list(self._streams)

    def all_modules(self) -> list[_ScriptedPhaseModule]:
        return list(self._modules)


class ScriptedPhaseRegistry(_SpecPhaseRegistry):
    """The engineered battery's phase registry (backward-compatible entry point).

    Both locked sources share one phase schedule (PLV → 1); the drift sources use
    mutually incommensurate schedules (PLV → low).
    """

    def __init__(self) -> None:
        super().__init__(_ENGINEERED_SPECS)


@dataclass(frozen=True)
class Stimulus:
    """A named stimulus battery: its source specs + derived coherence ground truth.

    The runner asks a ``Stimulus`` for its streams and phase registry and reads
    ``coherent_sources`` to score the directional (WIN vs adverse) metric.
    """

    name: str
    specs: tuple[_SourceSpec, ...]

    @property
    def coherent_sources(self) -> frozenset[str]:
        """Ground-truth set of phase-locked sources the layer should promote.

        Empty for a battery with no coherent coalition (the neutral battery), in
        which case a directional verdict is undefined and only WIN/NULL by
        magnitude applies.
        """
        return frozenset(s.name for s in self.specs if s.coherent)

    def streams(self, n_ticks: int) -> dict[str, list[tuple[str, Event]]]:
        return _build_streams(self.specs, n_ticks)

    def registry(self) -> _SpecPhaseRegistry:
        return _SpecPhaseRegistry(self.specs)


ENGINEERED_STIMULUS = Stimulus("engineered_phase_locked", _ENGINEERED_SPECS)
NEUTRAL_STIMULUS = Stimulus("neutral_unstructured", _NEUTRAL_SPECS)
MISLABELED_STIMULUS = Stimulus("mislabeled_adversarial", _MISLABELED_SPECS)

#: CLI / config name → battery.
STIMULUS_BY_NAME: dict[str, Stimulus] = {
    "engineered": ENGINEERED_STIMULUS,
    "neutral": NEUTRAL_STIMULUS,
    "mislabeled": MISLABELED_STIMULUS,
}


__all__ = [
    "ScriptedBus",
    "ScriptedPhaseRegistry",
    "Stimulus",
    "ENGINEERED_STIMULUS",
    "NEUTRAL_STIMULUS",
    "MISLABELED_STIMULUS",
    "STIMULUS_BY_NAME",
    "scripted_streams",
    "ALL_SOURCES",
    "LOCK_SOURCES",
    "DRIFT_SOURCES",
    "LOCKED_SALIENCE",
    "DRIFT_SALIENCE",
]
