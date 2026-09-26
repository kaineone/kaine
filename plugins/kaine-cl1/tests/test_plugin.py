# SPDX-License-Identifier: LicenseRef-CAL-0.2
"""Tests for the kaine CL1 plugin entry point."""

import os

os.environ.setdefault("CL_SDK_ACCELERATED_TIME", "1")
os.environ.setdefault("CL_SDK_VISUALISATION", "0")

import logging
import math
import tomllib
from pathlib import Path

import cl.sim as clsim  # noqa: E402
import pytest
from kaine_cl1.plugin import Cl1Plugin, make_plugin
from kaine_cl1.substrate.session import SubstrateSession


def _cfg(**substrate_overrides):
    substrate = {
        "target": "simulator",
        "accelerated_time": True,
        "ticks_per_second": 100,
        "cognitive_rate": 3.333,
        "territories": {"chronos": 8},
    }
    substrate.update(substrate_overrides)
    return {"substrate": substrate, "backends": {"chronos": "cl1"}}


class _CountingFactory:
    def __init__(self):
        self.sessions = []

    def __call__(self, cfg):
        s = SubstrateSession(cfg)
        self.sessions.append(s)
        return s


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


@pytest.fixture
def plugin():
    p = Cl1Plugin()
    try:
        yield p
    finally:
        p.close()


def test_entry_point_is_declared():
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    with pyproject.open("rb") as f:
        data = tomllib.load(f)
    ep = data["project"]["entry-points"]["kaine.plugins"]["cl1"]
    assert ep == "kaine_cl1.plugin:make_plugin"

    p = make_plugin()
    assert isinstance(p, Cl1Plugin)
    assert p.name == "cl1"


def test_seams_for_chronos():
    assert Cl1Plugin().seams(_cfg()) == frozenset({"chronos.network"})


def test_seams_empty_when_nothing_converted_opens_no_session():
    factory = _CountingFactory()
    plugin = Cl1Plugin(session_factory=factory)

    assert plugin.seams({}) == frozenset()
    assert plugin.seams({"backends": {"chronos": "silicon"}}) == frozenset()
    assert plugin.injections("chronos", {}) == {}
    assert len(factory.sessions) == 0

    plugin.close()


def test_unimplemented_backend_rejected():
    config = {
        "substrate": {
            "target": "simulator",
            "accelerated_time": True,
            "ticks_per_second": 100,
            "cognitive_rate": 3.333,
            "territories": {"nous": 8},
        },
        "backends": {"nous": "cl1"},
    }
    with pytest.raises(ValueError) as excinfo:
        Cl1Plugin().seams(config)
    msg = str(excinfo.value)
    assert "nous" in msg
    assert "nous-on-wetware" in msg


def test_missing_territory_rejected():
    with pytest.raises(ValueError) as excinfo:
        Cl1Plugin().seams(_cfg(territories={}))
    msg = str(excinfo.value)
    assert "chronos" in msg
    assert not msg.startswith(('"', "'"))


def test_real_time_substrate_warns(caplog):
    """Real time is supported through KAINE's cycle hook, so it warns instead of refusing."""
    with caplog.at_level(logging.WARNING, logger="kaine_cl1.plugin"):
        assert Cl1Plugin().seams(_cfg(accelerated_time=False)) == frozenset({"chronos.network"})
    assert any("cycle hook" in r.getMessage() for r in caplog.records)


def test_hardware_target_rejected():
    with pytest.raises(ValueError) as excinfo:
        Cl1Plugin().seams(_cfg(target="hardware"))
    assert "simulator" in str(excinfo.value)


def test_bad_backend_value_rejected():
    config = {
        "substrate": {
            "target": "simulator",
            "accelerated_time": True,
            "ticks_per_second": 100,
            "cognitive_rate": 3.333,
            "territories": {"chronos": 8},
        },
        "backends": {"chronos": "wetware"},
    }
    with pytest.raises(ValueError):
        Cl1Plugin().seams(config)


def test_bad_cognitive_rate_rejected():
    with pytest.raises(ValueError) as excinfo:
        Cl1Plugin().seams(_cfg(cognitive_rate=0))
    assert "cognitive_rate" in str(excinfo.value)


def test_injections_for_unconverted_module_is_empty(plugin):
    assert plugin.injections("lingua", _cfg()) == {}
    assert plugin.territory_map() == {}


def test_repeated_injections_reuse_one_territory(reference_culture):
    factory = _CountingFactory()
    plugin = Cl1Plugin(session_factory=factory)

    try:
        networks = []
        for _ in range(3):
            injections = plugin.injections("chronos", _cfg())
            assert set(injections) == {"network"}
            networks.append(injections["network"])

        for net in networks:
            out = net.tick([0.1] * 8)
            assert len(out) == 8
            assert all(math.isfinite(float(v)) for v in out)

        assert networks[0] is not networks[1]
        assert networks[1] is not networks[2]

        territory = plugin.territory_map()
        assert set(territory) == {"chronos"}
        channels = territory["chronos"]
        assert len(channels) == 8

        for _ in range(3):
            assert plugin.territory_map()["chronos"] == channels

        assert len(factory.sessions) == 1
    finally:
        plugin.close()


def test_close_is_idempotent(reference_culture):
    plugin = Cl1Plugin()
    try:
        plugin.injections("chronos", _cfg())
        plugin.close()
        plugin.close()
    finally:
        plugin.close()
    assert plugin.territory_map() == {}


async def test_plugin_network_drives_real_chronos(reference_culture):
    pytest.importorskip("kaine")
    pytest.importorskip("fakeredis")

    import fakeredis.aioredis

    from kaine.bus.client import AsyncBus
    from kaine.bus.config import BusConfig
    from kaine.cycle.types import WorkspaceSnapshot
    from kaine.modules.chronos.anomaly import RollingZScoreAnomaly
    from kaine.modules.chronos.featurizer import SnapshotFeaturizer
    from kaine.modules.chronos.module import Chronos
    from kaine.modules.chronos.rumination import RecurrenceRuminationDetector

    plugin = Cl1Plugin()
    try:
        client = fakeredis.aioredis.FakeRedis(decode_responses=True)
        bus = AsyncBus(
            BusConfig(password="x", audit_required=False),
            client=client,
        )

        chronos = Chronos(
            bus,
            featurizer=SnapshotFeaturizer(clock=lambda: 0.0),
            anomaly=RollingZScoreAnomaly(window=4),
            rumination=RecurrenceRuminationDetector(window=4, threshold=4),
            **plugin.injections("chronos", _cfg()),
        )

        assert chronos.has_network is True

        for t in range(3):
            await chronos.on_workspace(
                WorkspaceSnapshot(tick_index=t, selected_events=[], inhibited=False)
            )

        entries = await bus.read("chronos.out", last_id="0")
        assert len(entries) == 3
        for _, event in entries:
            assert event.type == "chronos.report"

        await bus.close()
    finally:
        plugin.close()

