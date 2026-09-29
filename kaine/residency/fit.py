# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Sequence

from kaine.residency.budget import ResidencyBudget
from kaine.residency.catalogue import FootprintCatalogue

_MiB = 1 << 20


def _mib(value: int | None) -> str:
    """Format bytes as whole MiB for human-readable output."""
    if value is None:
        return "unknown"
    return f"{value / _MiB:.1f}"


def _footprint(
    catalogue: FootprintCatalogue,
    component: str,
    rung: Rung,
    host_class: str,
) -> int | None:
    """Return the peak system-memory footprint for a rung, or None."""
    entry = catalogue.get(component, rung.backend, rung.model_id, host_class)
    if entry is None:
        return None
    return entry.peak_bytes


@dataclass(frozen=True)
class Rung:
    """One model/backend rung on a speech ladder."""

    backend: str
    model_id: str

    @property
    def label(self) -> str:
        return f"{self.backend}/{self.model_id}"


SPEECH_LADDERS: dict[str, tuple[Rung, ...]] = {
    "vox.tts": (
        Rung("chatterbox", "chatterbox"),
        Rung("sherpa_onnx", "kokoro-en"),
    ),
    "audition.stt": (
        Rung("speaches", "medium.en"),
        Rung("sherpa_onnx", "moonshine-base-en"),
        Rung("sherpa_onnx", "moonshine-tiny-en"),
    ),
}


@dataclass(frozen=True)
class Demand:
    """A requested component, its configured rung, and what is installed."""

    component: str
    configured: Rung
    installed: tuple[Rung, ...]
    interactive: bool


@dataclass(frozen=True)
class Placement:
    """Selected rung and residency mode for one component."""

    component: str
    rung: Rung
    footprint_bytes: int | None
    mode: str
    reason: str

    def to_dict(self) -> dict:
        return {
            "component": self.component,
            "rung": self.rung.label,
            "footprint_bytes": self.footprint_bytes,
            "mode": self.mode,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class FitReport:
    """Residency fit verdict for a set of demands under a budget."""

    budget_bytes: int | None
    verdict: str
    total_bytes: int | None
    shortfall_bytes: int
    placements: tuple[Placement, ...]
    uncalibrated: tuple[str, ...]
    notes: tuple[str, ...]
    expected_feel: str

    def to_dict(self) -> dict:
        return json.loads(
            json.dumps(
                {
                    "budget_bytes": self.budget_bytes,
                    "verdict": self.verdict,
                    "total_bytes": self.total_bytes,
                    "shortfall_bytes": self.shortfall_bytes,
                    "placements": [p.to_dict() for p in self.placements],
                    "uncalibrated": list(self.uncalibrated),
                    "notes": list(self.notes),
                    "expected_feel": self.expected_feel,
                }
            )
        )

    def render(self) -> str:
        """Plain-text fit report for a terminal."""
        lines = ["Fit report"]
        lines.append(f"Budget: {_mib(self.budget_bytes)} MiB")
        lines.append(f"Verdict: {self.verdict}")
        lines.append(f"Total configured: {_mib(self.total_bytes)} MiB")
        lines.append(f"Shortfall: {_mib(self.shortfall_bytes)} MiB")
        lines.append("Placements:")
        if not self.placements:
            lines.append("  none")
        else:
            for placement in self.placements:
                size = _mib(placement.footprint_bytes)
                lines.append(
                    f"  {placement.component}/{placement.rung.label}: "
                    f"{placement.mode} ({placement.reason}) [{size} MiB]"
                )

        if self.uncalibrated:
            lines.append("Uncalibrated:")
            for label in self.uncalibrated:
                lines.append(f"  {label}")

        if self.notes:
            lines.append("Notes:")
            for note in self.notes:
                lines.append(f"- {note}")

        lines.append(f"Expected feel: {self.expected_feel}")
        return "\n".join(lines)


def fit_report(
    *,
    budget: ResidencyBudget,
    catalogue: FootprintCatalogue,
    demands: Sequence[Demand],
    host_class: str,
    pin: str | None = "lingua",
) -> FitReport:
    """Plan which speech organs can stay resident under ``budget``."""
    notes: list[str] = []

    if budget.topology == "discrete":
        notes.append(
            "Discrete host: device-domain planning is not yet implemented; planning system domain only."
        )

    # Look up configured rung footprints by input position.
    configured_fp: list[int | None] = []
    uncalibrated: list[str] = []
    for demand in demands:
        footprint = _footprint(
            catalogue,
            demand.component,
            demand.configured,
            host_class,
        )
        configured_fp.append(footprint)
        if footprint is None:
            uncalibrated.append(demand.component)

    # Unknown budget.
    if budget.system.budget_bytes is None:
        notes.append(budget.system.unknown_reason or "system budget unknown")
        return FitReport(
            budget_bytes=None,
            verdict="unknown",
            total_bytes=None,
            shortfall_bytes=0,
            placements=(),
            uncalibrated=tuple(uncalibrated),
            notes=tuple(notes),
            expected_feel="Unknown until budget is known.",
        )

    budget_bytes = budget.system.budget_bytes

    # Uncalibrated demands: report only the calibrated placements.
    if uncalibrated:
        placements: list[Placement] = []
        for index, demand in enumerate(demands):
            footprint = configured_fp[index]
            if footprint is not None:
                placements.append(
                    Placement(
                        component=demand.component,
                        rung=demand.configured,
                        footprint_bytes=footprint,
                        mode="unknown",
                        reason="Calibrated, but overall fit is unknown until all components are calibrated.",
                    )
                )
        notes.append("Run calibration: python -m kaine.setup.footprint")
        return FitReport(
            budget_bytes=budget_bytes,
            verdict="unknown",
            total_bytes=None,
            shortfall_bytes=0,
            placements=tuple(placements),
            uncalibrated=tuple(uncalibrated),
            notes=tuple(notes),
            expected_feel="Unknown until every enabled component is calibrated.",
        )

    total_configured = sum(configured_fp)

    pinned_index = next(
        (
            index
            for index, demand in enumerate(demands)
            if pin is not None and demand.component == pin
        ),
        None,
    )
    if pinned_index is None:
        notes.append("no pinned organ among the demands")

    # Co-residence: everything fits together.
    if total_configured <= budget_bytes:
        placements = []
        for index, demand in enumerate(demands):
            if index == pinned_index:
                mode = "pinned"
                reason = "Pinned organ, always resident."
            else:
                mode = "resident"
                reason = "Configured rung co-resides with all enabled organs."
            placements.append(
                Placement(
                    component=demand.component,
                    rung=demand.configured,
                    footprint_bytes=configured_fp[index],
                    mode=mode,
                    reason=reason,
                )
            )
        return FitReport(
            budget_bytes=budget_bytes,
            verdict="co_resides",
            total_bytes=total_configured,
            shortfall_bytes=0,
            placements=tuple(placements),
            uncalibrated=(),
            notes=tuple(notes),
            expected_feel="Everything stays loaded; no swaps.",
        )

    # Multiplex planning.
    pinned_footprint = configured_fp[pinned_index] if pinned_index is not None else 0

    # Pinned organ alone exceeds budget.
    if pinned_footprint > budget_bytes:
        shortfall = pinned_footprint - budget_bytes
        notes.append(
            f"Pinned {pin} needs {_mib(pinned_footprint)} MiB "
            f"but only {_mib(budget_bytes)} MiB is available."
        )
        return FitReport(
            budget_bytes=budget_bytes,
            verdict="does_not_fit",
            total_bytes=total_configured,
            shortfall_bytes=shortfall,
            placements=(),
            uncalibrated=(),
            notes=tuple(notes),
            expected_feel="The pinned organ alone exceeds the budget; nothing else can be scheduled.",
        )

    # Choose the heaviest installed and calibrated rung for each component that
    # fits beside the pinned organ.  Candidates are only rungs at or below the
    # configured rung in the ladder.
    chosen: list[tuple[Rung, int] | None] = [None] * len(demands)
    if pinned_index is not None:
        chosen[pinned_index] = (demands[pinned_index].configured, pinned_footprint)

    for index, demand in enumerate(demands):
        if index == pinned_index:
            continue

        ladder = SPEECH_LADDERS.get(demand.component, (demand.configured,))
        try:
            cfg_pos = ladder.index(demand.configured)
            candidates = list(ladder[cfg_pos:])
        except ValueError:
            candidates = [demand.configured]

        installed_set = set(demand.installed)
        candidates = [rung for rung in candidates if rung in installed_set]

        selected: tuple[Rung, int] | None = None
        for rung in candidates:
            footprint = _footprint(
                catalogue, demand.component, rung, host_class
            )
            if footprint is None:
                continue
            if pinned_footprint + footprint <= budget_bytes:
                selected = (rung, footprint)
                break

        if selected is None:
            calibrated: list[tuple[Rung, int]] = []
            for rung in candidates:
                footprint = _footprint(
                    catalogue, demand.component, rung, host_class
                )
                if footprint is not None:
                    calibrated.append((rung, footprint))

            if not calibrated:
                notes.append(
                    f"No calibrated installed rung for {demand.component}; fit unknown."
                )
                return FitReport(
                    budget_bytes=budget_bytes,
                    verdict="unknown",
                    total_bytes=total_configured,
                    shortfall_bytes=0,
                    placements=(),
                    uncalibrated=(),
                    notes=tuple(notes),
                    expected_feel="Unknown until every enabled component is calibrated.",
                )

            smallest_footprint = min(footprint for _, footprint in calibrated)
            if pinned_footprint + smallest_footprint > budget_bytes:
                shortfall = pinned_footprint + smallest_footprint - budget_bytes
                if pin is not None:
                    notes.append(
                        f"Pinned {pin} plus the smallest {demand.component} rung "
                        f"needs {_mib(pinned_footprint + smallest_footprint)} MiB "
                        f"but only {_mib(budget_bytes)} MiB is available."
                    )
                else:
                    notes.append(
                        f"The smallest {demand.component} rung "
                        f"needs {_mib(smallest_footprint)} MiB "
                        f"but only {_mib(budget_bytes)} MiB is available."
                    )
                return FitReport(
                    budget_bytes=budget_bytes,
                    verdict="does_not_fit",
                    total_bytes=total_configured,
                    shortfall_bytes=shortfall,
                    placements=(),
                    uncalibrated=(),
                    notes=tuple(notes),
                    expected_feel="Does not fit: even the pinned organ plus the smallest companion model exceeds the budget.",
                )

            selected = min(calibrated, key=lambda item: item[1])

        chosen[index] = selected

    # Greedy resident selection: interactive first, then descending footprint.
    resident_indices: set[int] = set()
    if pinned_index is not None:
        resident_indices.add(pinned_index)
    used = pinned_footprint

    others = [index for index in range(len(demands)) if index != pinned_index]
    others.sort(key=lambda index: (-int(demands[index].interactive), -chosen[index][1]))

    for index in others:
        footprint = chosen[index][1]
        if used + footprint <= budget_bytes:
            resident_indices.add(index)
            used += footprint

    # Build ordered placements: pinned, then resident, then multiplexed.
    placements = []
    for index, demand in enumerate(demands):
        rung, footprint = chosen[index]
        if index == pinned_index:
            mode = "pinned"
            reason = "Pinned organ, always resident."
        elif index in resident_indices:
            mode = "resident"
            if demand.configured == rung:
                reason = "Configured rung fits beside the pinned organ."
            else:
                if pin is not None:
                    reason = (
                        f"{demand.configured.model_id} does not fit beside the pinned {pin} "
                        f"(needs {_mib(configured_fp[index])} MiB, "
                        f"{_mib(budget_bytes - pinned_footprint)} MiB free)"
                    )
                else:
                    reason = (
                        f"{demand.configured.model_id} does not fit within the budget "
                        f"(needs {_mib(configured_fp[index])} MiB, "
                        f"{_mib(budget_bytes)} MiB free)"
                    )
        else:
            mode = "multiplexed"
            reason = "Does not fit concurrently with the resident set; scheduled on demand."

        placements.append(
            Placement(
                component=demand.component,
                rung=rung,
                footprint_bytes=footprint,
                mode=mode,
                reason=reason,
            )
        )

    shortfall = max(0, total_configured - budget_bytes)
    return FitReport(
        budget_bytes=budget_bytes,
        verdict="multiplexed",
        total_bytes=total_configured,
        shortfall_bytes=shortfall,
        placements=tuple(placements),
        uncalibrated=(),
        notes=tuple(notes),
        expected_feel="Multiplexed organs pause while their model loads; interactive organs are kept resident first.",
    )
