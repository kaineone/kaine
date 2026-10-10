# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Revive through KAINE's loader: the CL1 wrapper passes the restored
posterior to KAINE's engine (OpenSpec nous-revive-seeding).
"""

import os

import pytest

pytest.importorskip("kaine", reason="kaine boot tests require kaine package")
pytest.importorskip("fakeredis", reason="kaine boot tests require fakeredis")
pytest.importorskip("pymdp", reason="KAINE's Nous engine needs pymdp")

os.environ.setdefault("CL_SDK_ACCELERATED_TIME", "1")
os.environ.setdefault("CL_SDK_VISUALISATION", "0")

import logging  # noqa: E402

import cl.sim as clsim  # noqa: E402
import fakeredis.aioredis  # noqa: E402

from kaine.boot import build_registry, known_module_names, make_nous  # noqa: E402
from kaine.bus.client import AsyncBus  # noqa: E402
from kaine.bus.config import BusConfig  # noqa: E402
from kaine.plugins import load_plugins  # noqa: E402


def _config(*, territory=10, mode=None):
    cl1 = {
        "substrate": {"target": "simulator", "accelerated_time": True, "territories": {"nous": territory}},
        "backends": {"nous": "cl1"},
    }
    if mode is not None:
        cl1["nous"] = {"mode": mode}
    return {
        "modules": {"nous": True},
        "nous": {"efe_timeout_ms": 60000.0},
        "plugins": {"enabled": ["cl1"], "cl1": cl1},
    }


def _bus():
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    return AsyncBus(BusConfig(password="x", audit_required=False), client=client)


def _load(cfg):
    return load_plugins(cfg, known_modules=known_module_names())


def _close_cl1(plugins):
    for info in getattr(plugins, "_plugins", {}).values():
        obj = info.get("plugin")
        if obj is not None and hasattr(obj, "close"):
            obj.close()


@pytest.fixture
def reference_culture():
    clsim.set_simulator_data_source(
        "kaine_cl1.substrate.sources:make_reference_culture",
        config={
            "seed": 7,
            "baseline_hz": 2.0,
            "evoked_spikes": 16,
            "response_ms": 20.0,
        },
    )
    try:
        yield
    finally:
        clsim.clear_simulator_data_source()


async def test_revive_seeds_kaines_engine_through_the_wrapper(reference_culture, caplog):
    bus = _bus()
    cfg = _config()
    plugins = _load(cfg)

    try:
        reg = build_registry(bus, cfg, plugins=plugins)
        nous = reg.get("nous")

        posterior = []
        for num in nous.engine._inner._model.num_states:
            factor = [0.0] * num
            factor[-1] = 1.0
            posterior.append(factor)

        with caplog.at_level(logging.INFO, logger="kaine.modules.nous.module"):
            nous.deserialize({"posterior": posterior})

        assert nous.engine._inner._last_posterior == posterior
        assert not any("cannot take the restored posterior" in r.getMessage() for r in caplog.records)
        assert not any("does not match the model" in r.getMessage() for r in caplog.records)
    finally:
        await bus.close()
        _close_cl1(plugins)


async def test_a_non_forwarding_wrapper_is_reported(caplog):
    class Opaque:
        def __init__(self, inner):
            self._inner = inner

        @property
        def actions(self):
            return self._inner.actions

        def step(self, snapshot):
            return self._inner.step(snapshot)

    bus = _bus()
    try:
        nous = make_nous(
            bus, {"efe_timeout_ms": 60000.0}, injections={"engine_wrapper": Opaque}
        )

        posterior = []
        for num in nous.engine._inner._model.num_states:
            factor = [0.0] * num
            factor[-1] = 1.0
            posterior.append(factor)

        with caplog.at_level(logging.INFO, logger="kaine.modules.nous.module"):
            nous.deserialize({"posterior": posterior})

        assert any("cannot take the restored posterior" in r.getMessage() for r in caplog.records)
    finally:
        await bus.close()
