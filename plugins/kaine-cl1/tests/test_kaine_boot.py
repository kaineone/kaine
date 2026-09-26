# SPDX-License-Identifier: LicenseRef-CAL-0.2
"""These tests boot stock kaine through its own plugin loader
(`kaine.plugins.load_plugins` and `kaine.boot.build_registry`) with the
installed `cl1` entry point, proving the plugin works end to end without
any kaine-CL1 boot code. They skip where kaine or fakeredis is absent,
and a kaine without the plugin loader is an error because the KAINE in
this repository has it.
"""

import os

os.environ.setdefault("CL_SDK_ACCELERATED_TIME", "1")
os.environ.setdefault("CL_SDK_VISUALISATION", "0")

import pytest

pytest.importorskip("kaine", reason="requires the kaine stack")
pytest.importorskip("fakeredis", reason="requires fakeredis for the in-memory bus")

import math  # noqa: E402

import cl.sim as clsim  # noqa: E402
import fakeredis.aioredis  # noqa: E402
from kaine_cl1.backends.chronos import WetwareTimingModel  # noqa: E402

from kaine.boot import build_registry, known_module_names  # noqa: E402
from kaine.bus.client import AsyncBus  # noqa: E402
from kaine.bus.config import BusConfig  # noqa: E402
from kaine.cycle.types import WorkspaceSnapshot  # noqa: E402
from kaine.plugins import PluginError, load_plugins  # noqa: E402


def _config(backends=None, territories=None, chronos=None, enabled=("cl1",)):
    return {
        "modules": {"chronos": True},
        "chronos": dict(chronos or {}),
        "plugins": {
            "enabled": list(enabled),
            "cl1": {
                "substrate": {
                    "target": "simulator",
                    "accelerated_time": True,
                    "territories": dict(
                        territories if territories is not None else {"chronos": 12}
                    ),
                },
                "backends": dict(
                    backends if backends is not None else {"chronos": "cl1"}
                ),
            },
        },
    }


def _bus():
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    return AsyncBus(BusConfig(password="x", audit_required=False), client=client)


class _FakeMetricsReader:
    def __init__(self, metrics=None):
        self.metrics = dict(metrics or {"cpu_percent": 20.0, "ram_percent": 30.0})
    async def initialize(self):
        pass
    async def shutdown(self):
        pass
    async def read_metrics(self):
        return dict(self.metrics)
    def update_cycle_latency_sample(self, wall_duration_ms):
        pass


def _soma_config(*, soma_backend="cl1", with_chronos=False):
    modules = {"soma": True}
    cl1_backends = {"soma": soma_backend}
    cl1_territories = {"soma": 12}
    if with_chronos:
        modules["chronos"] = True
        cl1_backends["chronos"] = "cl1"
        cl1_territories["chronos"] = 12
    enabled = []
    if soma_backend == "silicon" and not with_chronos:
        enabled = []
    else:
        enabled = ["cl1"]
    return {
        "modules": dict(modules),
        "soma": {},
        "plugins": {
            "enabled": list(enabled),
            "cl1": {
                "substrate": {
                    "target": "simulator",
                    "accelerated_time": True,
                    "territories": dict(cl1_territories),
                },
                "backends": dict(cl1_backends),
            },
        },
    }


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


def test_manifest_records_the_substitution():
    p = _load(_config())
    try:
        assert p.manifest_entry()["cl1"]["distribution"] == "kaine-cl1"
        assert p.manifest_entry()["cl1"]["seams"] == ["chronos.network"]
    finally:
        _close_cl1(p)


async def test_not_enabled_loads_nothing():
    cfg = _config(enabled=())
    p = _load(cfg)
    assert not p
    bus = _bus()
    try:
        reg = build_registry(bus, cfg, plugins=p)
        assert reg.get("chronos").has_network is False
    finally:
        await bus.close()


def test_unimplemented_backend_fails_the_boot():
    cfg = _config(backends={"volition": "cl1"}, territories={"volition": 4})
    with pytest.raises(PluginError, match="hybrid-wetware-conversions"):
        _load(cfg)


def test_hardware_target_fails_the_boot():
    cfg = _config()
    cfg["plugins"]["cl1"]["substrate"]["target"] = "hardware"
    with pytest.raises(PluginError, match="simulator"):
        _load(cfg)


async def test_booted_chronos_runs_on_the_substrate(reference_culture):
    cfg = _config()
    p = _load(cfg)
    bus = _bus()
    try:
        reg = build_registry(bus, cfg, plugins=p)
        chronos = reg.get("chronos")
        assert isinstance(chronos._network, WetwareTimingModel)
        assert chronos._network.units == 12

        await chronos.initialize()
        for t in range(4):
            await chronos.on_workspace(
                WorkspaceSnapshot(tick_index=t, selected_events=[], inhibited=False)
            )

        entries = await bus.read("chronos.out", last_id="0")
        assert len(entries) == 4
        for _id, ev in entries:
            assert ev.type == "chronos.report"
            assert math.isfinite(float(ev.payload["temporal_prediction_error"]))

        await chronos.shutdown()
    finally:
        await bus.close()
        _close_cl1(p)


async def test_forward_prediction_uses_the_substrate_width(reference_culture):
    pytest.importorskip("torch", reason="the forward-prediction head needs torch")
    cfg = _config(chronos={"forward_prediction": True})
    p = _load(cfg)
    bus = _bus()
    try:
        reg = build_registry(bus, cfg, plugins=p)
        chronos = reg.get("chronos")
        assert isinstance(chronos._network, WetwareTimingModel)
        assert chronos._network.units == 12

        await chronos.initialize()
        for t in range(3):
            await chronos.on_workspace(
                WorkspaceSnapshot(tick_index=t, selected_events=[], inhibited=False)
            )

        entries = await bus.read("chronos.out", last_id="0")
        assert len(entries) == 3
        for _id, ev in entries:
            assert ev.type == "chronos.report"
            assert math.isfinite(float(ev.payload["temporal_prediction_error"]))

        await chronos.shutdown()
    finally:
        await bus.close()
        _close_cl1(p)


async def test_booted_soma_runs_on_the_substrate(reference_culture):
    cfg = _soma_config()
    p = _load(cfg)
    bus = _bus()
    try:
        reg = build_registry(bus, cfg, plugins=p)
        soma = reg.get("soma")
        assert type(soma._forward_model).__name__ == "WetwareInteroceptiveModel"
        assert soma._forward_model.units == 12
        soma._reader = _FakeMetricsReader()
        await soma.tick_once()
        await soma.tick_once()
        await soma.tick_once()
        entries = await bus.read("soma.out", last_id="0")
        assert len(entries) >= 3
        assert soma._forward_model.adaptation_steps >= 1
    finally:
        await bus.close()
        _close_cl1(p)


async def test_chronos_and_soma_share_the_substrate(reference_culture):
    cfg = _soma_config(with_chronos=True)
    p = _load(cfg)
    assert p.manifest_entry()["cl1"]["seams"] == ["chronos.network", "soma.forward_model"]
    bus = _bus()
    try:
        reg = build_registry(bus, cfg, plugins=p)
        soma = reg.get("soma")
        chronos = reg.get("chronos")
        soma._reader = _FakeMetricsReader()
        await chronos.initialize()
        for t in range(3):
            await chronos.on_workspace(
                WorkspaceSnapshot(tick_index=t, selected_events=[], inhibited=False)
            )
            await soma.tick_once()
        chronos_entries = await bus.read("chronos.out", last_id="0")
        soma_entries = await bus.read("soma.out", last_id="0")
        assert len(chronos_entries) == 3
        assert len(soma_entries) >= 3
        assert set(chronos._network._channels).isdisjoint(soma._forward_model._channels)
        await chronos.shutdown()
    finally:
        await bus.close()
        _close_cl1(p)


async def test_soma_event_schema_matches_silicon(reference_culture):
    pytest.importorskip("torch", reason="the silicon Soma forward model needs torch")

    async def run(backend):
        cfg = _soma_config(soma_backend=backend)
        p = _load(cfg)
        bus = _bus()
        try:
            reg = build_registry(bus, cfg, plugins=p)
            soma = reg.get("soma")
            soma._reader = _FakeMetricsReader()
            await soma.tick_once()
            await soma.tick_once()
            await soma.tick_once()
            entries = await bus.read("soma.out", last_id="0")
            return [ev for _id, ev in entries]
        finally:
            await bus.close()
            _close_cl1(p)

    wet = await run("cl1")
    sil = await run("silicon")
    assert wet
    assert sil
    assert {e.type for e in wet} == {e.type for e in sil}
    wet_by_type = {e.type: e for e in wet}
    sil_by_type = {e.type: e for e in sil}
    for ev_type in wet_by_type:
        assert set(wet_by_type[ev_type].payload.keys()) == set(sil_by_type[ev_type].payload.keys())

