# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""tests that a wetware oscillator records the response to its own stimulation (oscillator-own-response)."""

import os  # noqa: E402

os.environ.setdefault("CL_SDK_ACCELERATED_TIME", "1")
os.environ.setdefault("CL_SDK_VISUALISATION", "0")

import time  # noqa: E402
import types  # noqa: E402

import cl.sim as clsim  # noqa: E402
import pytest  # noqa: E402
from kaine_cl1.backends.oscillator import WetwareOscillator  # noqa: E402
from kaine_cl1.substrate.broker import SubstrateBroker, TerritoryObservation  # noqa: E402
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


def _tick(broker, name):
    ts = broker._latest[name].from_timestamp
    broker.beat(0.1)
    assert _wait_for(lambda: broker._latest[name].from_timestamp > ts)


def test_rare_publisher_records_its_evoked_response(accel):
    accel.start_beat(accelerated=True)
    accel.beat(0.1)
    assert _wait_for(lambda: accel._latest.get("a") is not None)

    osc = WetwareOscillator(accel, accel.territory("a"))

    background = []
    territory_channels = set(accel.territory("a").channels)
    for _ in range(8):
        osc.step(1.0)
        for _ in range(4):
            _tick(accel, "a")
        latest = accel._latest["a"]
        active = {
            spike.channel
            for spike in latest.spikes
            if spike.channel in territory_channels
        }
        background.append(len(active) / 4)

    osc.step(1.0)
    assert osc.samples == 8
    assert min(osc._history) >= 0.75
    assert sum(background) / len(background) < 0.5


def test_first_step_records_nothing_and_each_response_once():
    class LaggingBroker:
        def __init__(self):
            self.answered = None
            self.queued = None

        def exchange(self, module, requests, tag=None):
            self.queued = tag
            return TerritoryObservation(
                module=module,
                channels=(1, 2, 3, 4),
                spikes=[types.SimpleNamespace(channel=1)],
                from_timestamp=0,
                frame_count=1,
                tag=self.answered,
            )

        def deliver(self):
            self.answered = self.queued

    broker = LaggingBroker()
    territory = types.SimpleNamespace(module="osc", channels=(1, 2, 3, 4))
    osc = WetwareOscillator(broker, territory)

    osc.step(1.0)
    assert osc.samples == 0

    broker.deliver()
    osc.step(1.0)
    assert osc.samples == 1
    assert osc._history[0] == 0.25

    osc.step(1.0)
    assert osc.samples == 1

    broker.deliver()
    osc.step(0.0)
    assert osc.samples == 2
