# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The world model module factory."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass
from kaine.boot.config_kwargs import config_kwargs
from kaine.boot.errors import ConfigurationError, _require_keys
from kaine.bus.client import AsyncBus
from kaine.modules.base import BaseModule


def make_world_model(bus: AsyncBus, section: dict[str, Any]) -> BaseModule:
    from kaine.modules.world_model.module import WorldModel

    allowed = {
        "backend",
        "engine",
        "training_enabled",
        "training_device",
        "trajectory_buffer_size",
        "rollout_horizon",
        "persist_weights",
        "checkpoint_path",
        "episodic_memory_stream",
        "sleep_stream",
        "salience",  # nested sub-table: baseline, alert
        "world_model",  # nested sub-table: real-backend hyperparams (extra-gated)
    }
    _require_keys(section, allowed)
    kwargs: dict[str, Any] = {}
    kwargs.update(
        config_kwargs(
            section,
            (
                "backend",
                "engine",
                "training_enabled",
                "training_device",
                "trajectory_buffer_size",
                "rollout_horizon",
                "persist_weights",
                "checkpoint_path",
                "episodic_memory_stream",
                "sleep_stream",
            ),
            WorldModel,
        )
    )
    salience = section.get("salience") or {}
    if "baseline" in salience:
        kwargs["baseline_salience"] = float(salience["baseline"])
    if "alert" in salience:
        kwargs["alert_salience"] = float(salience["alert"])
    world_model = section.get("world_model") or {}
    if world_model:
        kwargs["world_model_kwargs"] = dict(world_model)

    engine = section.get("engine", "jax")
    if engine not in {"jax", "numpy"}:
        raise ConfigurationError(
            f"[world_model].engine must be \"jax\" or \"numpy\", got {engine!r}"
        )
    return WorldModel(bus, **kwargs)
