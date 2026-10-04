# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The Mundus factory."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass
from kaine.bus.client import AsyncBus
from kaine.modules.base import BaseModule


def make_mundus(bus: AsyncBus, section: dict[str, Any]) -> BaseModule:
    from kaine.modules.mundus.module import Mundus

    # Body-agnostic control plane: select exactly one embodiment adapter and
    # build it from its own nested `[mundus.<adapter>]` table. Adapter-specific
    # settings (transport, per-family/channel exposure) live under that table,
    # never flat in `[mundus]`. An unknown adapter name fails closed at boot.
    adapter_name = str(section.get("adapter", "stub"))
    adapter_section = dict(section.get(adapter_name, {}) or {})

    if adapter_name == "stub":
        from kaine.modules.mundus.adapters.stub import StubAdapter

        adapter = StubAdapter()
    else:
        raise ValueError(
            f"mundus: unknown adapter {adapter_name!r}; no embodiment constructed "
            "(fail-closed). Set [mundus].adapter to a known adapter."
        )

    # `expose_<family>`/`expose_<channel>` keys under the adapter table →
    # operator exposure overrides on top of the descriptor defaults, routed by the
    # adapter's declared capabilities.
    caps = adapter.capabilities()
    expose: dict[str, bool] = {}
    continuous_expose: dict[str, bool] = {}
    for key, value in adapter_section.items():
        if not key.startswith("expose_"):
            continue
        name = key[len("expose_") :]
        if name in caps.continuous_channels:
            continuous_expose[name] = bool(value)
        elif name in caps.action_families:
            expose[name] = bool(value)
        else:
            raise ValueError(
                f"[mundus.{adapter_name}].{key}: {name!r} is neither a continuous "
                f"channel nor an action family of the {adapter_name!r} body "
                f"(channels: {', '.join(caps.continuous_channels) or 'none'}; "
                f"families: {', '.join(sorted(caps.action_families)) or 'none'})"
            )

    kwargs: dict[str, Any] = {}
    for key in ("mirror_speech", "speech_stream"):
        if key in section:
            kwargs[key] = section[key]

    # Continuous embodiment control surface (`intuitive-embodiment-control-surface`):
    # the entity's per-tick continuous motor producer + freeze-then-free curriculum
    # + closed-loop forward model. Off by default (ships conservative); constructed
    # only when [mundus.control_surface].enabled = true. The producer is held by the
    # control plane but its per-tick driving loop is the cycle's motor seam.
    cs_section = dict(section.get("control_surface", {}) or {})
    if bool(cs_section.get("enabled", False)):
        from kaine.modules.mundus.control_surface import (
            ContinuousMotorSurface,
            MotorCurriculum,
        )

        curriculum_kwargs: dict[str, Any] = {}
        for cfg_key, arg_key in (
            ("competence_threshold", "competence_threshold"),
            ("min_samples", "min_samples"),
            ("window", "window"),
        ):
            if cfg_key in cs_section:
                curriculum_kwargs[arg_key] = cs_section[cfg_key]
        curriculum = MotorCurriculum(**curriculum_kwargs) if curriculum_kwargs else None
        kwargs["control_surface"] = ContinuousMotorSurface(curriculum=curriculum)

    # Constructed only when [modules].mundus is on; the operational two-layer gate
    # is [mundus].enabled (default true here) AND KAINE_MUNDUS_OPERATOR_APPROVED=1.
    return Mundus(
        bus,
        adapter=adapter,
        enabled=bool(section.get("enabled", True)),
        expose=expose or None,
        continuous_expose=continuous_expose or None,
        **kwargs,
    )
