# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""tests for beat mode, where KAINE's cycle hook closes one substrate window per processing tick."""

import os  # noqa: E402

os.environ.setdefault("CL_SDK_ACCELERATED_TIME", "1")
os.environ.setdefault("CL_SDK_VISUALISATION", "0")

import logging  # noqa: E402
import time  # noqa: E402
import types  # noqa: E402

import cl.sim as clsim  # noqa: E402
import pytest  # noqa: E402
from kaine_cl1.plugin import Cl1Plugin  # noqa: E402
from kaine_cl1.substrate.broker import SubstrateBroker  # noqa: E402
from kaine_cl1.substrate.codec import StimRequest  # noqa: E402
from kaine_cl1.substrate.session import SubstrateConfig, SubstrateSession  # noqa: E402


def _wait_for(pred, timeout=3.0):
    deadline = time.perf_counter() + timeout
    ok = False
    while time.perf_counter() < deadline:
        ok = pred()
        if ok:
            break
        time.sleep(0.01)
    return ok


def _count_windows(monkeypatch, broker):
    original = broker._run_window

    counter = [0]

    def wrapper(frames):
        counter[0] += 1
        return original(frames)

    monkeypatch.setattr(broker, "_run_window", wrapper)
    return counter


def _strong(broker, name):
    return [StimRequest(ch, 3.0) for ch in broker.territory(name).channels]


@pytest.fixture
def accel():
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
    broker.allocate("a", 4)
    broker.allocate("b", 4)
    broker.allocate("c", 4)
    broker.open(session.neurons)
    try:
        yield broker
    finally:
        broker.stop_beat()
        session.close()
        clsim.clear_simulator_data_source()


def test_standalone_exchange_runs_one_window_per_call(accel, monkeypatch):
    counter = _count_windows(monkeypatch, accel)
    for name in ("a", "b", "c"):
        obs = accel.exchange(name, [])
        assert obs.module == name
    assert counter[0] == 3
    assert accel.beat_mode is False


def test_three_consumers_one_beat_one_window(accel, monkeypatch):
    counter = _count_windows(monkeypatch, accel)
    accel.start_beat(accelerated=True)
    for name in ("a", "b", "c"):
        accel.exchange(name, [])
    assert counter[0] == 0
    accel.beat(0.1)
    assert _wait_for(lambda: counter[0] == 1)
    time.sleep(0.2)
    assert counter[0] == 1
    for name in ("a", "b", "c"):
        obs = accel.exchange(name, [])
        assert obs.module == name
        assert obs.frame_count > 0


def test_stimulus_response_arrives_one_tick_later(accel):
    accel.start_beat(accelerated=True)
    accel.beat(0.1)
    assert _wait_for(lambda: accel.exchange("a", []).frame_count > 0)
    baseline = accel.exchange("a", [])
    baseline_ts = baseline.from_timestamp
    accel.exchange("a", _strong(accel, "a"))
    accel.exchange("b", [])
    accel.beat(0.1)
    assert _wait_for(
        lambda: (la := accel._latest.get("a")) is not None
        and la.from_timestamp > baseline_ts
    )
    a_obs = accel.exchange("a", [])
    b_obs = accel.exchange("b", [])
    assert len(a_obs.spikes) > len(b_obs.spikes)


def test_hook_returns_quickly_accelerated(accel):
    p = Cl1Plugin()
    p._broker = accel
    p._accelerated = True
    t0 = time.perf_counter()
    p.on_cycle_tick({"processing_rate_hz": 10.0})
    elapsed = time.perf_counter() - t0
    assert elapsed < 0.005
    assert accel.beat_mode is True
    p._broker = None


def test_real_time_beat_never_blocks():
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
        SubstrateConfig(accelerated_time=False, ticks_per_second=100)
    )
    session.open()
    broker = SubstrateBroker(
        channel_count=64, ticks_per_second=100, nesting_factor=6
    )
    broker.allocate("a", 4)
    broker.open(session.neurons)
    try:
        broker.start_beat(accelerated=False)
        for _ in range(5):
            t0 = time.perf_counter()
            broker.exchange("a", _strong(broker, "a"))
            broker.beat(0.1)
            assert time.perf_counter() - t0 < 0.005
            time.sleep(0.1)
        assert _wait_for(lambda: broker.exchange("a", []).frame_count > 0)
    finally:
        broker.stop_beat()
        session.close()
        clsim.clear_simulator_data_source()


def test_first_beat_switch_is_logged(accel, caplog):
    with caplog.at_level(logging.INFO, logger="kaine_cl1.substrate.broker"):
        accel.start_beat(accelerated=True)
    assert any("beat mode" in record.message for record in caplog.records)


def test_beat_requires_beat_mode(accel):
    with pytest.raises(RuntimeError):
        accel.beat(0.1)


def test_plugin_follows_kaines_cycle_through_the_loader(monkeypatch):
    pytest.importorskip("kaine.plugins")
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
        from kaine.boot import known_module_names
        from kaine.plugins import load_plugins

        cfg = {
            "modules": {"chronos": True},
            "plugins": {
                "enabled": ["cl1"],
                "cl1": {
                    "substrate": {
                        "target": "simulator",
                        "accelerated_time": True,
                        "territories": {"chronos": 8},
                    },
                    "backends": {"chronos": "cl1"},
                },
            },
        }
        plugins = load_plugins(cfg, known_modules=known_module_names())
        manifest = plugins.manifest_entry()
        assert manifest["cl1"]["observes_cycle"] is True
        observer = plugins.cycle_observer()
        assert observer is not None
        plugin_obj = plugins._plugins["cl1"]["plugin"]
        plugin_obj.injections("chronos", cfg["plugins"]["cl1"])
        counter = _count_windows(monkeypatch, plugin_obj._broker)
        try:
            # Real ticks are a processing period apart, so wait for each window before
            # the next tick; back-to-back beats are coalesced by design.
            for i in range(3):
                observer({"tick_index": i, "processing_rate_hz": 10.0}, 100.0)
                assert _wait_for(lambda n=i + 1: counter[0] == n)
            time.sleep(0.2)
            assert counter[0] == 3
        finally:
            plugin_obj.close()
    finally:
        clsim.clear_simulator_data_source()


def test_slow_substrate_coalesces_beats(accel, monkeypatch, caplog):
    original = accel._run_window

    def slow_run_window(frames):
        time.sleep(0.3)
        return original(frames)

    monkeypatch.setattr(accel, "_run_window", slow_run_window)
    accel.start_beat(accelerated=True)
    with caplog.at_level(logging.WARNING, logger="kaine_cl1.substrate.broker"):
        for _ in range(10):
            accel.beat(0.1)
    assert _wait_for(lambda: accel.coalesced_beats >= 1)
    assert accel.coalesced_beats <= 9
    assert any("coalesced" in record.message for record in caplog.records)
    assert accel._pending_frames is None or isinstance(accel._pending_frames, int)


def test_stop_that_times_out_marks_broken(accel, monkeypatch, caplog):
    accel.start_beat(accelerated=True)
    real_thread = accel._thread
    accel._thread = types.SimpleNamespace(
        join=lambda timeout=None: None, is_alive=lambda: True
    )
    try:
        with caplog.at_level(logging.WARNING, logger="kaine_cl1.substrate.broker"):
            accel.stop_beat(timeout=0.01)
        assert accel.broken is True
        assert any("did not stop" in record.message for record in caplog.records)
        with pytest.raises(RuntimeError):
            accel.exchange("a", [])
        with pytest.raises(RuntimeError):
            accel.run_cognitive_tick()
    finally:
        accel._thread = None
        accel._broken = False
        accel._beat_mode = False
        accel._stop.set()
        real_thread.join(timeout=2)


def test_stop_then_start_runs_a_new_thread(accel, monkeypatch):
    counter = _count_windows(monkeypatch, accel)
    accel.start_beat(accelerated=True)
    accel.beat(0.1)
    assert _wait_for(lambda: counter[0] == 1)
    accel.stop_beat()
    assert accel.beat_mode is False
    accel.start_beat(accelerated=True)
    assert accel.beat_mode is True
    accel.beat(0.1)
    assert _wait_for(lambda: counter[0] == 2)


def test_crashed_loop_makes_calls_raise(accel, monkeypatch):
    def die(frames):
        raise RuntimeError("substrate died")

    monkeypatch.setattr(accel, "_run_window", die)
    accel.start_beat(accelerated=True)
    accel.beat(0.1)
    assert _wait_for(lambda: accel.failed)
    with pytest.raises(RuntimeError):
        accel.beat(0.1)
    with pytest.raises(RuntimeError):
        accel.exchange("a", [])
    with pytest.raises(RuntimeError):
        accel.start_beat(accelerated=True)

