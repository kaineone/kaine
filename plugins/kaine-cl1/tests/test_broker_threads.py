# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""tests that synchronous substrate windows run one at a time across threads (nous-on-wetware)."""

import threading
import time

from kaine_cl1.substrate.broker import SubstrateBroker, TerritoryObservation
from kaine_cl1.substrate.codec import StimRequest


def _instrumented_broker():
    broker = SubstrateBroker(channel_count=64, ticks_per_second=100, nesting_factor=6)
    broker.allocate("nous", 10)
    broker.allocate("chronos", 12)
    broker._loop_it = object()

    state = {"active": 0, "max_active": 0, "windows": []}
    counter_lock = threading.Lock()

    def fake_window(frames):
        with counter_lock:
            state["active"] += 1
            state["max_active"] = max(state["max_active"], state["active"])
        time.sleep(0.02)
        with counter_lock:
            state["active"] -= 1
            state["windows"].append(frames)
        return {
            name: TerritoryObservation(
                module=name,
                channels=broker.territory(name).channels,
                spikes=[],
                from_timestamp=0,
                frame_count=frames,
            )
            for name in ("nous", "chronos")
        }

    broker._run_window = fake_window
    return broker, state


def test_concurrent_exchanges_never_overlap():
    broker, state = _instrumented_broker()
    barrier = threading.Barrier(2)

    def run_exchanges(module_name, channel):
        barrier.wait()
        for _ in range(10):
            broker.exchange(module_name, [StimRequest(channel, 1.0)])

    threads = [
        threading.Thread(
            target=run_exchanges,
            args=("nous", broker.territory("nous").channels[0]),
        ),
        threading.Thread(
            target=run_exchanges,
            args=("chronos", broker.territory("chronos").channels[0]),
        ),
    ]

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert state["max_active"] == 1
    assert len(state["windows"]) == 20


def test_start_beat_waits_for_an_inflight_window():
    broker, state = _instrumented_broker()
    beat_started = threading.Event()

    def fake_beat_loop():
        beat_started.set()

    broker._beat_loop = fake_beat_loop

    exchange_thread = threading.Thread(target=broker.exchange, args=("nous", []))
    exchange_thread.start()

    deadline = time.monotonic() + 1.0
    while state["active"] == 0:
        if time.monotonic() > deadline:
            raise AssertionError("in-flight window did not start")
        time.sleep(0.001)

    try:
        broker.start_beat(accelerated=True)
        assert len(state["windows"]) == 1
        assert beat_started.wait(1.0)
    finally:
        exchange_thread.join()
        try:
            broker.stop_beat()
        except Exception:
            pass
