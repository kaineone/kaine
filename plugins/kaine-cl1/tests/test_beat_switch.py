# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""tests that switching to beat mode never blocks KAINE's event loop (nous-on-wetware)."""

import os  # noqa: E402

os.environ.setdefault("CL_SDK_ACCELERATED_TIME", "1")
os.environ.setdefault("CL_SDK_VISUALISATION", "0")

import threading  # noqa: E402
import time  # noqa: E402

import cl.sim as clsim  # noqa: E402
import pytest  # noqa: E402
from kaine_cl1.plugin import Cl1Plugin  # noqa: E402
from kaine_cl1.substrate.broker import SubstrateBroker  # noqa: E402
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


def _hold_sync_lock(broker):
    held = threading.Event()
    release = threading.Event()

    def _acquire():
        with broker._sync_lock:
            held.set()
            # Bounded, so a regression that blocks on the lock fails rather than hangs.
            release.wait(timeout=2.0)

    t = threading.Thread(target=_acquire, daemon=True)
    t.start()
    assert held.wait(timeout=2.0), "sync lock was not acquired in time"
    return release, t


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


def test_nonblocking_start_beat_returns_false_while_a_window_runs(accel):
    release, t = _hold_sync_lock(accel)
    try:
        t0 = time.perf_counter()
        ok = accel.start_beat(accelerated=True, blocking=False)
        elapsed = time.perf_counter() - t0
        assert elapsed < 0.05
        assert ok is False
        assert accel.beat_mode is False
    finally:
        release.set()
        t.join(timeout=2.0)

    ok = accel.start_beat(accelerated=True, blocking=False)
    assert ok is True
    assert accel.beat_mode is True


def test_first_tick_never_waits_for_a_window(accel):
    p = Cl1Plugin()
    p._broker = accel
    p._accelerated = True

    release, t = _hold_sync_lock(accel)
    try:
        t0 = time.perf_counter()
        p.on_cycle_tick({"processing_rate_hz": 10.0})
        elapsed1 = time.perf_counter() - t0
        assert elapsed1 < 0.005
        assert accel.beat_mode is False
        switcher = p._beat_switcher
        assert switcher is not None
        assert switcher.is_alive()

        t0 = time.perf_counter()
        p.on_cycle_tick({"processing_rate_hz": 10.0})
        elapsed2 = time.perf_counter() - t0
        assert elapsed2 < 0.005
        assert p._beat_switcher is switcher
        assert p._beat_switcher.is_alive()
    finally:
        release.set()
        t.join(timeout=2.0)

    assert _wait_for(lambda: accel.beat_mode) is True
    p.on_cycle_tick({"processing_rate_hz": 10.0})
    p._broker = None


def test_first_tick_switches_inline_when_free(accel):
    p = Cl1Plugin()
    p._broker = accel
    p._accelerated = True
    p.on_cycle_tick({"processing_rate_hz": 10.0})
    assert accel.beat_mode is True
    assert p._beat_switcher is None
    p._broker = None


def test_close_joins_a_pending_switch(accel):
    p = Cl1Plugin()
    p._broker = accel
    p._accelerated = True

    release, t = _hold_sync_lock(accel)
    try:
        p.on_cycle_tick({"processing_rate_hz": 10.0})
        assert p._beat_switcher is not None
    finally:
        release.set()
        t.join(timeout=2.0)

    p.close()
    assert p._beat_switcher is None
    assert p._broker is None
