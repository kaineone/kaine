# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Fit report: does the enabled module set co-reside or must it multiplex?"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from kaine.residency.budget import GIB, Domain

GiB = GIB


@dataclass(frozen=True)
class Need:
    component: str
    domain: str
    footprint_bytes: int | None = None
    estimate_bytes: int | None = None
    interactive: bool = False
    rung: str = ""


@dataclass(frozen=True)
class DomainFit:
    domain: str
    budget_bytes: int | None
    need_bytes: int
    status: str
    # How far the whole set is from co-residing (need - budget); 0 when it
    # co-resides.
    shortfall_bytes: int
    pinned: str | None
    multiplexed: tuple[str, ...]
    rungs: dict[str, str]
    feel: str
    # For "does-not-fit": how far the largest single organ is from fitting on
    # its own (largest - budget). 0 otherwise.
    single_shortfall_bytes: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "budget_bytes": self.budget_bytes,
            "need_bytes": self.need_bytes,
            "status": self.status,
            "shortfall_bytes": self.shortfall_bytes,
            "pinned": self.pinned,
            "multiplexed": list(self.multiplexed),
            "rungs": dict(self.rungs),
            "feel": self.feel,
            "single_shortfall_bytes": self.single_shortfall_bytes,
        }


@dataclass(frozen=True)
class FitReport:
    domains: tuple[DomainFit, ...]
    co_resides: bool
    uncalibrated: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "domains": [d.to_dict() for d in self.domains],
            "co_resides": self.co_resides,
            "uncalibrated": list(self.uncalibrated),
        }

    def lines(self) -> list[str]:
        out: list[str] = []
        if self.co_resides:
            out.append("Everything co-resides; no multiplexing needed.")
        for fit in self.domains:
            out.append(
                f"{fit.domain}: {fit.status} "
                f"(budget {_fmt_gib(fit.budget_bytes)} GiB, "
                f"need {_fmt_gib(fit.need_bytes)} GiB, "
                f"shortfall {_fmt_gib(fit.shortfall_bytes)} GiB)"
            )
            if fit.pinned:
                out.append(f"  pinned: {fit.pinned}")
            if fit.multiplexed:
                out.append(f"  multiplexed: {', '.join(fit.multiplexed)}")
            out.append(f"  feel: {fit.feel}")
        if self.uncalibrated:
            out.append("Uncalibrated components: " + ", ".join(self.uncalibrated))
        return out


def _fmt_gib(n: int | None) -> str:
    if n is None:
        return "unknown"
    return f"{n / GiB:.2f}"


def _group_needs_by_domain(needs: tuple[Need, ...] | list[Need]) -> dict[str, list[Need]]:
    groups: dict[str, list[Need]] = {}
    for need in needs:
        groups.setdefault(need.domain, []).append(need)
    return groups


def _effective_bytes(need: Need) -> tuple[int, bool, bool]:
    """Return (bytes, used_footprint, used_estimate)."""
    if need.footprint_bytes is not None:
        return need.footprint_bytes, True, False
    if need.estimate_bytes is not None:
        return need.estimate_bytes, False, True
    return 0, False, False


def fit_report(
    budgets: tuple[Domain, ...] | list[Domain],
    needs: tuple[Need, ...] | list[Need],
    *,
    pin: str = "lingua",
) -> FitReport:
    """Build a fit report from budgets and per-domain needs."""
    budget_by_domain = {b.name: b for b in budgets}
    groups = _group_needs_by_domain(needs)

    domain_fits: list[DomainFit] = []
    uncalibrated: list[str] = []
    co_resides = True

    for domain_name, domain_needs in groups.items():
        budget = budget_by_domain.get(domain_name)
        budget_bytes = budget.budget_bytes if budget is not None else None

        # Determine effective bytes and calibration status per need.
        effective: list[tuple[Need, int, bool, bool]] = []  # (need, bytes, footprint?, estimate?)
        for need in domain_needs:
            b, used_fp, used_est = _effective_bytes(need)
            effective.append((need, b, used_fp, used_est))
            if not used_fp:
                uncalibrated.append(need.component)

        # Any uncalibrated need with no figure makes the domain unplannable.
        has_missing_figure = any(not fp and not est for _, _, fp, est in effective)

        rungs = {need.component: need.rung for need in domain_needs}

        if has_missing_figure:
            missing = [n.component for n, _, fp, est in effective if not fp and not est]
            feel = (
                "cannot plan: "
                + ", ".join(missing)
                + " is uncalibrated and has no estimate; run the calibration command"
            )
            domain_fits.append(
                DomainFit(
                    domain=domain_name,
                    budget_bytes=budget_bytes,
                    need_bytes=0,
                    status="unknown-budget",
                    shortfall_bytes=0,
                    pinned=None,
                    multiplexed=tuple(n.component for n in domain_needs),
                    rungs=rungs,
                    feel=feel,
                )
            )
            co_resides = False
            continue

        need_bytes = sum(b for _, b, _, _ in effective)

        if budget_bytes is None:
            domain_fits.append(
                DomainFit(
                    domain=domain_name,
                    budget_bytes=None,
                    need_bytes=need_bytes,
                    status="unknown-budget",
                    shortfall_bytes=0,
                    pinned=None,
                    multiplexed=tuple(n.component for n in domain_needs),
                    rungs=rungs,
                    feel="cannot plan: budget for this domain is unknown",
                )
            )
            co_resides = False
            continue

        if need_bytes <= budget_bytes:
            domain_fits.append(
                DomainFit(
                    domain=domain_name,
                    budget_bytes=budget_bytes,
                    need_bytes=need_bytes,
                    status="co-resides",
                    shortfall_bytes=0,
                    pinned=None,
                    multiplexed=(),
                    rungs=rungs,
                    feel="everything stays loaded; no swaps",
                )
            )
            continue

        co_resides = False
        shortfall_bytes = need_bytes - budget_bytes

        # Pin the first candidate that leaves room for the largest other need:
        # the configured pin, then interactive needs, largest first.
        sizes = {n.component: b for n, b, _, _ in effective}
        candidates = [pin] if pin in sizes else []
        candidates += [
            n.component
            for n, b, _, _ in sorted(effective, key=lambda e: e[1], reverse=True)
            if n.interactive and n.component != pin
        ]
        pinned_component: str | None = None
        for candidate in candidates:
            other_max = max(
                (b for c, b in sizes.items() if c != candidate), default=0
            )
            if sizes[candidate] + other_max <= budget_bytes:
                pinned_component = candidate
                break

        multiplexed = [
            n.component for n, _, _, _ in effective if n.component != pinned_component
        ]
        largest = max(sizes.values(), default=0)

        if pinned_component is not None:
            status = "multiplex"
            turn_bytes = sizes[pinned_component] + max(
                (b for c, b in sizes.items() if c != pinned_component), default=0
            )
            feel = (
                f"{pinned_component} stays loaded; "
                f"{len(multiplexed)} organ(s) take turns in {_fmt_gib(turn_bytes)} GiB; "
                "each turn that needs a swapped-out organ waits for its load"
            )
        elif largest <= budget_bytes:
            status = "multiplex"
            feel = (
                "no organ can stay loaded beside the others; every organ takes turns, "
                "and each turn waits for its load"
            )
        else:
            status = "does-not-fit"
            single_shortfall = largest - budget_bytes
            feel = (
                "even one at a time this domain is short by "
                f"{_fmt_gib(single_shortfall)} GiB"
            )

        domain_fits.append(
            DomainFit(
                domain=domain_name,
                budget_bytes=budget_bytes,
                need_bytes=need_bytes,
                status=status,
                shortfall_bytes=shortfall_bytes,
                pinned=pinned_component,
                multiplexed=tuple(multiplexed),
                rungs=rungs,
                feel=feel,
                single_shortfall_bytes=(
                    largest - budget_bytes if status == "does-not-fit" else 0
                ),
            )
        )

    return FitReport(
        domains=tuple(domain_fits),
        co_resides=co_resides,
        uncalibrated=tuple(uncalibrated),
    )
