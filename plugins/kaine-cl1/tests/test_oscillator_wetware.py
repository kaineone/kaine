# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""tests for the wetware oscillatory-binding oscillator and its plugin wiring."""

import logging
import os

os.environ.setdefault("CL_SDK_ACCELERATED_TIME", "1")
os.environ.setdefault("CL_SDK_VISUALISATION", "0")

import math  # noqa: E402
import types  # noqa: E402

import cl.sim as clsim  # noqa: E402
import numpy as np  # noqa: E402
import pytest  # noqa: E402
from kaine_cl1.backends.chronos import WetwareTimingModel  # noqa: E402
from kaine_cl1.backends.oscillator import (  # noqa: E402
    MIN_PLV_WINDOW,
    WetwareOscillator,
    _hilbert_phase,
)
from kaine_cl1.plugin import Cl1Plugin  # noqa: E402
from kaine_cl1.substrate.broker import SubstrateBroker  # noqa: E402
from kaine_cl1.substrate.session import SubstrateConfig, SubstrateSession  # noqa: E402


@pytest.fixture
def substrate():
    clsim.set_simulator_data_source(
        "kaine_cl1.substrate.sources:make_reference_culture",
        config={
            "seed": 7,
            "baseline_hz": 2.0,
            "evoked_spikes": 16,
            "response_ms": 20.0,
        },
    )
    session = SubstrateSession(
        SubstrateConfig(accelerated_time=True, ticks_per_second=100)
    )
    session.open()

    broker = SubstrateBroker(
        channel_count=64, ticks_per_second=100, nesting_factor=6
    )
    for name in ("osc.a", "osc.b", "osc.c", "osc.d"):
        broker.allocate(name, 4)
    broker.open(session.neurons)

    territories = {name: broker.territory(name) for name in ("osc.a", "osc.b", "osc.c", "osc.d")}
    yield broker, territories

    session.close()
    clsim.clear_simulator_data_source()


def _plv(pa: list[float], pb: list[float]) -> float:
    return abs(np.mean(np.exp(1j * (np.asarray(pa) - np.asarray(pb)))))


def _cfg(**overrides):
    base = {
        "substrate": {
            "target": "simulator",
            "accelerated_time": True,
            "ticks_per_second": 100,
            "cognitive_rate": 3.333,
            "territories": {},
        },
        "backends": {},
        "oscillators": {
            "modules": ["chronos"],
            "channels_per_module": 4,
        },
    }
    base.update(overrides)
    return base


def test_hilbert_matches_scipy():
    signal = pytest.importorskip("scipy.signal")
    for n in (10, 11, 20, 37):
        x = np.random.default_rng(n).normal(size=n)
        x -= x.mean()
        expected = float(np.angle(signal.hilbert(x)[-1]))
        assert _hilbert_phase(x) == pytest.approx(expected, abs=1e-9)


def test_neutral_phase_before_window(substrate):
    broker, terrs = substrate
    osc = WetwareOscillator(broker, terrs["osc.a"])
    for k in range(MIN_PLV_WINDOW - 1):
        osc.step(1.0 if k % 2 == 0 else 0.0)
    assert osc.phase() == 0.0
    assert osc.samples == MIN_PLV_WINDOW - 1


def test_phase_is_a_finite_angle(substrate):
    broker, terrs = substrate
    osc = WetwareOscillator(broker, terrs["osc.a"])
    for k in range(3 * MIN_PLV_WINDOW):
        drive = 0.5 + 0.5 * math.sin(2 * math.pi * k / 8)
        osc.step(drive)
    phase = osc.phase()
    assert math.isfinite(phase)
    assert -math.pi <= phase <= math.pi
    assert osc.samples == 2 * MIN_PLV_WINDOW


def test_plv_window_minimum():
    b = SubstrateBroker(channel_count=64)
    t = b.allocate("x", 4)
    with pytest.raises(ValueError, match="plv_window"):
        WetwareOscillator(b, t, plv_window=5)


def test_set_frequency_halves_the_drive(monkeypatch):
    b = SubstrateBroker(channel_count=64)
    t = b.allocate("x", 4)
    requests_log = []

    def queue_stim(module, requests):
        requests_log.append(requests)

    def run_tick():
        return {"x": types.SimpleNamespace(spikes=[])}

    monkeypatch.setattr(b, "queue_stim", queue_stim)
    monkeypatch.setattr(b, "run_cognitive_tick", run_tick)

    osc = WetwareOscillator(b, t)

    osc.step(1.0)
    assert len(requests_log) == 1
    assert all(req.amplitude_uA == pytest.approx(3.0) for req in requests_log[0])

    osc.set_frequency(0.5)
    osc.step(1.0)
    assert len(requests_log) == 2
    assert all(req.amplitude_uA == pytest.approx(1.75) for req in requests_log[1])

    osc.set_frequency(-1)
    assert osc.drive_scale == 0.0
    before = osc.samples
    osc.step(1.0)
    assert len(requests_log) == 2
    assert osc.samples == before + 1


def test_bad_drive_is_clamped(monkeypatch):
    b = SubstrateBroker(channel_count=64)
    t = b.allocate("x", 4)
    requests_log = []

    def queue_stim(module, requests):
        requests_log.append(requests)

    monkeypatch.setattr(b, "queue_stim", queue_stim)
    monkeypatch.setattr(
        b,
        "run_cognitive_tick",
        lambda: {"x": types.SimpleNamespace(spikes=[])},
    )

    osc = WetwareOscillator(b, t)

    osc.step(float("nan"))
    osc.step(-3.0)
    assert len(requests_log) == 0
    assert osc.samples == 2

    osc.step(7.0)
    assert len(requests_log) == 1
    assert all(req.amplitude_uA == pytest.approx(3.0) for req in requests_log[0])


def test_serialize_round_trip():
    b = SubstrateBroker(channel_count=64)
    t = b.allocate("x", 4)
    osc = WetwareOscillator(b, t)
    osc.set_frequency(0.25)
    state = osc.serialize()
    other = WetwareOscillator(b, t)
    other.deserialize(state)
    assert other.drive_scale == pytest.approx(0.25)


def test_shared_drive_is_more_coherent(substrate):
    broker, terrs = substrate
    oscs = {
        name: WetwareOscillator(broker, terrs[name])
        for name in ("osc.a", "osc.b", "osc.c", "osc.d")
    }
    phases = {name: [] for name in oscs}

    for k in range(120):
        drive_ab = 0.5 + 0.5 * math.sin(2 * math.pi * k / 12)
        oscs["osc.a"].step(drive_ab)
        oscs["osc.b"].step(drive_ab)
        oscs["osc.c"].step(0.5 + 0.5 * math.sin(2 * math.pi * k / 12))
        oscs["osc.d"].step(0.5 + 0.5 * math.sin(2 * math.pi * k / 5))

        if k >= 2 * MIN_PLV_WINDOW:
            for name in oscs:
                phases[name].append(oscs[name].phase())

    plv_ab = _plv(phases["osc.a"], phases["osc.b"])
    plv_cd = _plv(phases["osc.c"], phases["osc.d"])
    assert plv_ab > plv_cd


def test_plugin_declares_oscillator_seams():
    plugin = Cl1Plugin()
    assert plugin.seams(_cfg()) == {"oscillator.chronos"}

    cfg = _cfg(
        backends={"chronos": "cl1"},
        substrate={
            "target": "simulator",
            "accelerated_time": True,
            "ticks_per_second": 100,
            "cognitive_rate": 3.333,
            "territories": {"chronos": 12},
        },
    )
    assert plugin.seams(cfg) == {"chronos.network", "oscillator.chronos"}


def test_plugin_channel_budget():
    plugin = Cl1Plugin()
    cfg = _cfg(
        oscillators={"modules": ["chronos", "soma"], "channels_per_module": 32},
    )
    with pytest.raises(ValueError, match="channels"):
        plugin.seams(cfg)


def test_plugin_requires_accelerated_time_for_oscillators():
    plugin = Cl1Plugin()
    cfg = _cfg(
        substrate={
            "target": "simulator",
            "accelerated_time": False,
            "ticks_per_second": 100,
            "cognitive_rate": 3.333,
            "territories": {},
        },
    )
    with pytest.raises(ValueError, match="accelerated_time"):
        plugin.seams(cfg)


def test_make_oscillator_reuses_its_territory():
    clsim.set_simulator_data_source(
        "kaine_cl1.substrate.sources:make_reference_culture",
        config={
            "seed": 7,
            "baseline_hz": 2.0,
            "evoked_spikes": 16,
            "response_ms": 20.0,
        },
    )
    p = Cl1Plugin()
    try:
        o1 = p.make_oscillator("chronos", _cfg(), {"plv_window": 12})
        o2 = p.make_oscillator("chronos", _cfg(), {"plv_window": 12})
        assert isinstance(o1, WetwareOscillator)
        assert isinstance(o2, WetwareOscillator)
        assert list(p.territory_map()) == ["oscillator.chronos"]
        assert len(p.territory_map()["oscillator.chronos"]) == 4

        with pytest.raises(ValueError):
            p.make_oscillator("soma", _cfg(), {})
    finally:
        p.close()
        clsim.clear_simulator_data_source()


async def test_oscillator_attaches_through_kaines_loader():
    pytest.importorskip("kaine.plugins")
    pytest.importorskip("fakeredis")

    clsim.set_simulator_data_source(
        "kaine_cl1.substrate.sources:make_reference_culture",
        config={
            "seed": 7,
            "baseline_hz": 2.0,
            "evoked_spikes": 16,
            "response_ms": 20.0,
        },
    )

    import fakeredis.aioredis

    from kaine.boot import build_registry, known_module_names
    from kaine.bus.client import AsyncBus
    from kaine.bus.config import BusConfig
    from kaine.plugins import load_plugins

    cfg = {
        "modules": {"chronos": True},
        "oscillator": {"enabled": True},
        "plugins": {"enabled": ["cl1"], "cl1": _cfg()},
    }
    plugins = load_plugins(cfg, known_modules=known_module_names())
    assert plugins.manifest_entry()["cl1"]["seams"] == ["oscillator.chronos"]

    bus = AsyncBus(
        BusConfig(password="x", audit_required=False),
        client=fakeredis.aioredis.FakeRedis(decode_responses=True),
    )
    try:
        reg = build_registry(bus, cfg, plugins=plugins)
        osc = reg.get("chronos").oscillator
        assert type(osc).__name__ == "WetwareOscillator"
        for _ in range(3):
            osc.step(0.5)
        assert osc.samples == 3
    finally:
        await bus.close()
        for info in plugins._plugins.values():
            info["plugin"].close()
        clsim.clear_simulator_data_source()


def test_failure_is_logged_loudly_and_re_raised(caplog, monkeypatch):
    b = SubstrateBroker(channel_count=64)
    t = b.allocate("x", 4)

    def bad_tick():
        raise RuntimeError("substrate gone")

    monkeypatch.setattr(b, "run_cognitive_tick", bad_tick)

    osc = WetwareOscillator(b, t)

    with caplog.at_level(logging.WARNING, logger="kaine_cl1.backends.oscillator"):
        for _ in range(3):
            with pytest.raises(RuntimeError):
                osc.step(0.5)

    assert osc.failures == 3

    warnings = [
        r for r in caplog.records
        if r.levelno == logging.WARNING and r.name == "kaine_cl1.backends.oscillator"
    ]
    assert len(warnings) == 1
    msg = warnings[0].message
    assert "x" in msg
    assert "substrate gone" in msg


def test_two_consumers_each_see_their_own_stimulus(substrate):
    """Each consumer queues its stim and runs its own window, so it reads the response to its
    own stimulus even while another consumer shares the broker (second-review finding on
    kaine #197).
    """
    broker, terrs = substrate
    strong = WetwareTimingModel(broker, terrs["osc.a"])
    weak = WetwareTimingModel(broker, terrs["osc.b"])

    strong_vals = []
    weak_vals = []
    for _ in range(8):
        s = sum(strong.tick([10.0] * 4))
        w = sum(weak.tick([-10.0] * 4))
        strong_vals.append(s)
        weak_vals.append(w)

    assert np.mean(strong_vals) > np.mean(weak_vals)
