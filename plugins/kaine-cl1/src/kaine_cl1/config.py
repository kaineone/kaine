# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Load the kaine-cl1 plugin configuration (TOML) into typed objects.

The overlay is a thin layer *over* the pure kaine config: it says, per module,
whether the forward model runs on silicon (upstream default) or on the CL1
substrate, plus the substrate session parameters and channel-territory budget.
The configuration comes either from the `[plugins.cl1]` table of the kaine config
or from a standalone file such as `config/kaine_cl1.example.toml`.
"""
from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from kaine_cl1.substrate.session import SubstrateConfig


@dataclass(frozen=True)
class OverlayConfig:
    """The fully-resolved overlay: substrate session + per-module selection."""

    substrate: SubstrateConfig
    #: module name -> "cl1" | "silicon"
    backends: dict[str, str] = field(default_factory=dict)
    #: module name -> electrode count leased on the shared array
    territories: dict[str, int] = field(default_factory=dict)
    #: KAINE's cognitive-cycle rate in Hz, used to nest substrate sub-ticks
    #: inside one cognitive tick
    cognitive_rate: float = 3.333

    def cl1_modules(self) -> list[str]:
        """Modules whose forward model is routed to the substrate, in config order."""
        return [name for name, sel in self.backends.items() if sel == "cl1"]

    def territory_for(self, module: str) -> int:
        try:
            return self.territories[module]
        except KeyError:
            raise KeyError(
                f"module {module!r} is set to 'cl1' but has no "
                f"[substrate.territories] channel budget"
            ) from None


def _substrate_from_raw(raw: dict[str, Any]) -> SubstrateConfig:
    sub = raw.get("substrate", {}) or {}
    target = str(sub.get("target", "simulator"))
    if target not in ("simulator", "cloud", "hardware"):
        raise ValueError(
            f"[substrate].target must be 'simulator', 'cloud' or 'hardware', got {target!r}"
        )
    data_source = str(sub.get("data_source", "reference_culture"))
    if data_source not in ("reference_culture", "sdk", "replay"):
        raise ValueError(
            "[substrate].data_source must be 'reference_culture', 'sdk' or 'replay', "
            f"got {data_source!r}"
        )
    if data_source == "replay" and not sub.get("replay_path"):
        raise ValueError("[substrate].data_source = 'replay' needs [substrate].replay_path")
    return SubstrateConfig(
        target=target,
        data_source=data_source,
        accelerated_time=bool(sub.get("accelerated_time", False)),
        replay_path=sub.get("replay_path"),
        random_seed=int(sub.get("random_seed", 42)),
        ticks_per_second=int(sub.get("ticks_per_second", 100)),
    )


def overlay_from_mapping(raw: Mapping[str, Any]) -> OverlayConfig:
    """Build an :class:`OverlayConfig` from an already-parsed overlay table.

    ``raw`` may be any Mapping (for example the dict kaine hands to plugins) and
    may be empty. It is not mutated.
    """
    substrate = _substrate_from_raw(raw)
    sub = raw.get("substrate", {}) or {}

    backends: dict[str, str] = {}
    for name, value in (raw.get("backends", {}) or {}).items():
        value_str = str(value)
        if value_str not in ("cl1", "silicon"):
            raise ValueError(
                f"module {name!r} backend must be 'cl1' or 'silicon', got {value!r}"
            )
        backends[str(name)] = value_str

    territories_raw = sub.get("territories", {}) or {}
    territories = {str(k): int(v) for k, v in territories_raw.items()}

    cognitive_rate = float(sub.get("cognitive_rate", 3.333))
    if not cognitive_rate > 0:
        raise ValueError(
            f"[substrate].cognitive_rate must be > 0, got {cognitive_rate!r}"
        )

    return OverlayConfig(
        substrate=substrate,
        backends=backends,
        territories=territories,
        cognitive_rate=cognitive_rate,
    )


def load_overlay(path: str | Path) -> OverlayConfig:
    """Parse a TOML file that holds the overlay either at top level (`[substrate]`,
    `[backends]`) or as the kaine config's `[plugins.cl1]` block."""
    raw = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    plugins_raw = raw.get("plugins", {})
    cl1_table = plugins_raw.get("cl1") if isinstance(plugins_raw, Mapping) else None
    if cl1_table is not None:
        if "substrate" in raw or "backends" in raw:
            raise ValueError(
                "overlay file must use one form or the other: "
                "top-level [substrate]/[backends] or [plugins.cl1], not both"
            )
        table = cl1_table
    else:
        table = raw
    return overlay_from_mapping(table)

