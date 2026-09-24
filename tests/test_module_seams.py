# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for boot-time module seams and the parity between registry boot,
individual construction, and Spot's heavy-restart rebuild path.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from kaine.boot import (
    SIMPLE_FACTORIES,
    ConfigurationError,
    build_registry,
    construct_module,
    make_chronos,
    make_nous,
    make_soma,
)
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.cycle.types import WorkspaceSnapshot
from kaine.entity_clock import EntityClock
from kaine.modules.chronos.featurizer import SnapshotFeaturizer
from kaine.modules.chronos.module import Chronos
from kaine.modules.nous import FakeEngine, Nous
from kaine.modules.registry import ModuleRegistry
from kaine.modules.soma.forward import SubstrateForwardModel
from kaine.modules.soma.module import Soma


def _bus() -> AsyncBus:
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    return AsyncBus(BusConfig(password="x", audit_required=False), client=client)


@pytest.fixture
async def bus() -> AsyncBus:
    bus = _bus()
    yield bus
    await bus.close()


def _empty_snapshot(tick: int = 0) -> WorkspaceSnapshot:
    return WorkspaceSnapshot(tick_index=tick, selected_events=[], inhibited=False)


def _head_units(head: Any) -> int:
    if hasattr(head, "units"):
        return int(head.units)
    import torch.nn as nn

    for module in head.modules():
        if isinstance(module, nn.Linear):
            return int(module.out_features)
    raise AssertionError("cannot determine prediction-head width")


class _FailingCallable:
    """Callable that fails the test if it is ever invoked."""

    def __init__(self, name: str) -> None:
        self.name = name

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError(f"{self.name} should not have been called")


class _FakeModule:
    def __init__(self, name: str) -> None:
        self.name = name


# ---------------------------------------------------------------------------
# Chronos network / forward-prediction seam
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chronos_injected_network_sizes_forward_prediction_head(bus: AsyncBus) -> None:
    network_mod = pytest.importorskip("kaine.modules.chronos.network")
    CfCNetwork = network_mod.CfCNetwork

    featurizer = SnapshotFeaturizer()
    net = CfCNetwork(input_size=featurizer.feature_dim, units=12)
    chronos = Chronos(
        bus,
        featurizer=featurizer,
        network=net,
        forward_prediction=True,
        prediction_error_window=4,
    )
    await chronos.initialize()
    try:
        assert chronos._pred_head is not None
        assert _head_units(chronos._pred_head) == 12

        # Drive the real tick path twice so a prediction is compared.
        await chronos.on_workspace(_empty_snapshot(0))
        await chronos.on_workspace(_empty_snapshot(1))
    finally:
        await chronos.shutdown()


@pytest.mark.asyncio
async def test_chronos_default_network_head_width_equals_cfc_units(bus: AsyncBus) -> None:
    pytest.importorskip("kaine.modules.chronos.network")
    chronos = Chronos(
        bus,
        forward_prediction=True,
        cfc_units=47,
        prediction_error_window=4,
    )
    await chronos.initialize()
    try:
        assert chronos._pred_head is not None
        assert _head_units(chronos._pred_head) == 47
    finally:
        await chronos.shutdown()


@pytest.mark.asyncio
async def test_chronos_injected_network_without_units_rejects_forward_prediction(
    bus: AsyncBus,
) -> None:
    # The chronos spec requires a construction error, so a bad plugin network
    # stops boot before any module starts.
    featurizer = SnapshotFeaturizer()
    with pytest.raises(ValueError, match="units"):
        Chronos(
            bus,
            featurizer=featurizer,
            network=object(),  # injected, but no `units` attribute
            forward_prediction=True,
            prediction_error_window=4,
        )


# ---------------------------------------------------------------------------
# Soma forward-model seam
# ---------------------------------------------------------------------------


def test_make_soma_default_builds_substrate_forward_model() -> None:
    bus = _bus()
    try:
        soma = make_soma(bus, {})
        assert isinstance(soma._forward_model, SubstrateForwardModel)
    finally:
        asyncio.run(bus.close())


class _FakeMetricsReader:
    async def read_metrics(self) -> dict[str, float]:
        return {
            "cpu_percent": 10.0,
            "ram_percent": 10.0,
            "gpu_0_temp_c": 40.0,
            "gpu_0_vram_percent": 40.0,
            "cycle_latency_avg_ms": 10.0,
        }


class _FakeForwardModel:
    def __init__(self) -> None:
        self.step_called = 0
        self.last_suspended: bool | None = None
        self.suspended = False
        self.adaptation_steps = 0

    def step(self, feature_vec: list[float]) -> float:
        self.step_called += 1
        self.last_suspended = self.suspended
        return 0.05

    def prediction_error_to_salience(
        self,
        error: float,
        baseline_salience: float,
        alert_salience: float,
        error_window: list[float],
    ) -> float:
        return baseline_salience

    def state_dict(self) -> dict[str, Any]:
        return {}

    def load_state_dict(self, state: dict[str, Any]) -> None:
        pass


@pytest.mark.asyncio
async def test_soma_injected_forward_model_tick_never_builds_substrate(
    bus: AsyncBus, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "kaine.modules.soma.module.SubstrateForwardModel",
        _FailingCallable("SubstrateForwardModel"),
    )

    fake_reader = _FakeMetricsReader()
    fake_forward = _FakeForwardModel()
    soma = Soma(
        bus,
        reader=fake_reader,
        forward_model=fake_forward,
        entity_clock=EntityClock(),
    )
    await soma.tick_once()
    assert fake_forward.step_called == 1
    assert fake_forward.last_suspended is False


# ---------------------------------------------------------------------------
# Nous engine seam
# ---------------------------------------------------------------------------


def _engine_of(nous: Nous) -> Any:
    return getattr(nous, "engine", getattr(nous, "_engine", None))


def test_make_nous_injected_engine_bypasses_pymdp_build(monkeypatch: pytest.MonkeyPatch) -> None:
    bus = _bus()
    try:
        fake_engine = FakeEngine()
        monkeypatch.setattr(
            "kaine.modules.nous.engine.PymdpEngine",
            _FailingCallable("PymdpEngine"),
        )
        monkeypatch.setattr(
            "kaine.modules.nous.generative_model.build_generative_model",
            _FailingCallable("build_generative_model"),
        )

        nous = make_nous(
            bus,
            {"baseline_salience": 0.1, "alert_salience": 0.7},
            injections={"engine": fake_engine},
        )
        assert _engine_of(nous) is fake_engine
    finally:
        asyncio.run(bus.close())


def test_make_nous_rejects_oversized_envelope_even_with_injected_engine() -> None:
    bus = _bus()
    try:
        fake_engine = FakeEngine()
        with pytest.raises(ConfigurationError):
            make_nous(
                bus,
                {
                    "factors": 50,
                    "max_states_per_factor": 50,
                    "actions": 50,
                    "planning_horizon": 50,
                },
                injections={"engine": fake_engine},
            )
    finally:
        asyncio.run(bus.close())


def test_make_nous_rejects_unknown_injection() -> None:
    bus = _bus()
    try:
        with pytest.raises(ConfigurationError, match="does not accept injection"):
            make_nous(
                bus,
                {},
                injections={"engine": FakeEngine(), "lobes": 7},
            )
    finally:
        asyncio.run(bus.close())


# ---------------------------------------------------------------------------
# Boot factory injection validation
# ---------------------------------------------------------------------------


def test_make_chronos_rejects_unknown_injection() -> None:
    bus = _bus()
    try:
        section = {
            "cfc_units": 32,
            "baseline_salience": 0.1,
            "alert_salience": 0.7,
            "anomaly_alert_threshold": 3.0,
            "forward_prediction": False,
        }
        with pytest.raises(ConfigurationError, match="does not accept injection"):
            make_chronos(
                bus,
                section,
                injections={"network": object(), "unknown": 1},
            )
    finally:
        asyncio.run(bus.close())


def test_make_soma_rejects_unknown_injection() -> None:
    bus = _bus()
    try:
        section = {
            "read_interval_s": 1.0,
            "baseline_salience": 0.1,
            "alert_salience": 0.7,
        }
        with pytest.raises(ConfigurationError, match="does not accept injection"):
            make_soma(
                bus,
                section,
                injections={"forward_model": object(), "unknown": 1},
            )
    finally:
        asyncio.run(bus.close())


# ---------------------------------------------------------------------------
# construct_module parity with build_registry
# ---------------------------------------------------------------------------


def _recording_factory(name: str, capture: list[dict[str, Any]]) -> Any:
    def factory(
        bus_: AsyncBus,
        section: dict[str, Any],
        *,
        entity_clock: EntityClock | None = None,
        intent_secret: bytes | None = None,
        injections: dict[str, Any] | None = None,
    ) -> _FakeModule:
        capture.append(
            {
                "name": name,
                "section": dict(section),
                "entity_clock": entity_clock,
                "intent_secret": intent_secret,
                "injections": injections,
            }
        )
        return _FakeModule(name)

    return factory


def test_construct_module_matches_build_registry_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_registry: list[dict[str, Any]] = []
    captured_direct: list[dict[str, Any]] = []

    modules_under_test = ("topos", "soma", "praxis", "chronos")
    for name in modules_under_test:
        monkeypatch.setitem(
            SIMPLE_FACTORIES,
            name,
            _recording_factory(name, captured_registry),
        )

    monkeypatch.setattr("kaine.boot.install_state_encryption", lambda cfg: None)
    monkeypatch.setattr("kaine.boot._wire_self_hearing_gate", lambda reg: None)
    monkeypatch.setattr("kaine.boot._wire_lingua_self_model", lambda reg: None)
    monkeypatch.setattr("kaine.boot._wire_eidolon_capabilities", lambda reg: None)
    monkeypatch.setattr("kaine.boot._log_device_assignments", lambda reg, cfg: None)
    monkeypatch.setattr("kaine.boot._wire_oscillators", lambda reg, cfg: None)

    kaine_config = {
        "modules": {
            "topos": True,
            "soma": True,
            "praxis": True,
            "chronos": True,
            "hypnos": False,
            "audition": False,
            "nous": False,
            "mnemos": False,
            "thymos": False,
            "phantasia": False,
            "lingua": False,
            "eidolon": False,
            "empatheia": False,
            "vox": False,
        },
        "perception_feed": {"mode": "off", "seed": 42},
        "topos": {"encoder_model_id": "dummy", "device": "cpu"},
        "praxis": {"model_id": "dummy"},
        "soma": {"read_interval_s": 1.0},
        "chronos": {
            "cfc_units": 8,
            "baseline_salience": 0.1,
            "alert_salience": 0.7,
            "anomaly_alert_threshold": 3.0,
            "forward_prediction": False,
        },
    }

    bus = _bus()
    clock = EntityClock(scale=1.0)
    secret = b"intent-secret"
    try:
        registry = build_registry(
            bus,
            kaine_config,
            entity_clock=clock,
            intent_secret=secret,
        )

        # Swap in a second set of recorders for direct construct_module calls.
        for name in modules_under_test:
            monkeypatch.setitem(
                SIMPLE_FACTORIES,
                name,
                _recording_factory(name, captured_direct),
            )

        for name in modules_under_test:
            construct_module(
                name,
                bus,
                kaine_config,
                registry=registry,
                entity_clock=clock,
                intent_secret=secret,
            )
    finally:
        asyncio.run(bus.close())

    by_name_reg = {c["name"]: c for c in captured_registry}
    by_name_dir = {c["name"]: c for c in captured_direct}
    assert set(by_name_reg) == set(by_name_dir) == set(modules_under_test)

    for name in modules_under_test:
        reg_call = by_name_reg[name]
        dir_call = by_name_dir[name]
        assert reg_call["section"] == dir_call["section"]
        # Parity: both paths hand every module the same arguments. Which modules
        # receive the clock and the secret is pinned just below.
        assert reg_call["entity_clock"] is dir_call["entity_clock"]
        assert reg_call["intent_secret"] == dir_call["intent_secret"]
        assert reg_call["injections"] == dir_call["injections"]

    # Topos/Audition receive the shared perception feed.
    topos_call = by_name_dir["topos"]
    assert topos_call["section"]["perception_feed"] == kaine_config["perception_feed"]

    # Praxis receives the intent secret.
    assert by_name_dir["praxis"]["intent_secret"] is secret

    # Soma is clocked and receives the shared EntityClock instance.
    assert by_name_dir["soma"]["entity_clock"] is clock


@pytest.mark.asyncio
async def test_construct_module_rejects_injections_for_non_seam_modules(
    bus: AsyncBus,
) -> None:
    registry = ModuleRegistry()
    with pytest.raises(ConfigurationError, match="does not accept injections"):
        construct_module(
            "topos",
            bus,
            {},
            registry=registry,
            injections={"network": object()},
        )


# ---------------------------------------------------------------------------
# Spot rebuild parity
# ---------------------------------------------------------------------------


def test_make_rebuild_module_passes_clock_and_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    import kaine.cycle.__main__ as cycle_main

    bus = _bus()
    kaine_config: dict[str, Any] = {"modules": {}}
    registry = ModuleRegistry()
    clock = EntityClock(scale=2.0)
    registry.entity_clock = clock
    secret = b"rebuild-secret"

    captured: list[dict[str, Any]] = []

    def recorder(
        name: str,
        bus_: AsyncBus,
        cfg: dict[str, Any],
        *,
        registry: ModuleRegistry,
        entity_clock: EntityClock | None = None,
        intent_secret: bytes | None = None,
        injections: dict[str, Any] | None = None,
    ) -> _FakeModule:
        captured.append(
            {
                "name": name,
                "bus": bus_,
                "cfg": cfg,
                "registry": registry,
                "entity_clock": entity_clock,
                "intent_secret": intent_secret,
                "injections": injections,
            }
        )
        return _FakeModule(name)

    monkeypatch.setattr(cycle_main, "construct_module", recorder)

    try:
        rebuild = cycle_main._make_rebuild_module(bus, kaine_config, registry, secret)
        result = rebuild("topos")
        assert isinstance(result, _FakeModule)
        assert result.name == "topos"
        assert len(captured) == 1
        call = captured[0]
        assert call["name"] == "topos"
        assert call["bus"] is bus
        assert call["cfg"] is kaine_config
        assert call["registry"] is registry
        assert call["entity_clock"] is clock
        assert call["intent_secret"] is secret
        assert call["injections"] is None
    finally:
        asyncio.run(bus.close())


# ---------------------------------------------------------------------------
# Chronos restart identity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chronos_restart_network_identity() -> None:
    network_mod = pytest.importorskip("kaine.modules.chronos.network")
    CfCNetwork = network_mod.CfCNetwork

    bus = _bus()
    feature_dim = SnapshotFeaturizer().feature_dim
    kaine_config = {
        "modules": {},
        "chronos": {
            "cfc_units": 16,
            "baseline_salience": 0.1,
            "alert_salience": 0.7,
            "anomaly_alert_threshold": 3.0,
            "forward_prediction": False,
        },
    }
    registry = ModuleRegistry()
    injected_nets: list[Any] = []

    for units in (11, 22, 33):
        net = CfCNetwork(input_size=feature_dim, units=units)
        injected_nets.append(net)
        chronos = construct_module(
            "chronos",
            bus,
            kaine_config,
            registry=registry,
            entity_clock=EntityClock(),
            intent_secret=None,
            injections={"network": net},
        )
        assert chronos._network is net

    default_chronos = construct_module(
        "chronos",
        bus,
        kaine_config,
        registry=registry,
        entity_clock=EntityClock(),
        intent_secret=None,
        injections=None,
    )
    await default_chronos.initialize()
    try:
        assert default_chronos._network is not None
        for net in injected_nets:
            assert default_chronos._network is not net
    finally:
        await default_chronos.shutdown()
        await bus.close()
