# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""tests for tagged exchanges: a module reads the response to its own stimulation (nous-on-wetware)."""

import os  # noqa: E402

os.environ.setdefault("CL_SDK_ACCELERATED_TIME", "1")
os.environ.setdefault("CL_SDK_VISUALISATION", "0")

import dataclasses  # noqa: E402
import time  # noqa: E402
import types  # noqa: E402

import cl.sim as clsim  # noqa: E402
import pytest  # noqa: E402
from kaine_cl1.backends.nous import WetwarePolicyEngine  # noqa: E402
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


def test_tagged_exchange_before_beat_answers_this_call(accel):
    """A tagged exchange before beat mode answers immediately."""
    obs = accel.exchange("a", _strong(accel, "a"), tag="now")
    assert obs.tag == "now"
    assert obs.frame_count > 0
    latest = accel._latest_response["a"]
    assert latest is obs or latest == obs


def test_tagged_response_survives_quiet_windows(accel):
    """A tagged response is stored and can be retrieved across quiet windows."""
    accel.start_beat(accelerated=True)
    accel.beat(0.1)
    assert _wait_for(lambda: accel.exchange("a", []).frame_count > 0)

    first = accel.exchange("a", _strong(accel, "a"), tag="t1")
    assert first.tag is None

    accel.beat(0.1)
    assert _wait_for(
        lambda: (lr := accel._latest_response.get("a")) is not None and lr.tag == "t1"
    )
    evoked = accel._latest_response["a"]

    for _ in range(3):
        ts = accel._latest["a"].from_timestamp
        accel.exchange("b", [])
        accel.beat(0.1)
        assert _wait_for(lambda: accel._latest["a"].from_timestamp > ts)

    r = accel.exchange("a", [], tag="t2")
    assert r.tag == "t1"
    assert r.from_timestamp == evoked.from_timestamp
    assert len(r.spikes) == len(evoked.spikes)
    assert accel._latest["a"].from_timestamp > r.from_timestamp
    assert len(accel._latest["a"].spikes) < len(r.spikes)


def test_untagged_exchange_cancels_a_pending_tag(accel):
    """An untagged exchange cancels a pending tag."""
    accel.start_beat(accelerated=True)
    accel.exchange("a", _strong(accel, "a"), tag="x")
    accel.exchange("a", [])
    assert "a" not in accel._next_tags

    accel.beat(0.1)
    assert _wait_for(lambda: accel.exchange("a", []).frame_count > 0)
    ts = accel._latest["a"].from_timestamp

    accel.beat(0.1)
    assert _wait_for(lambda: accel._latest["a"].from_timestamp > ts)
    assert accel._latest_response.get("a") is None


def test_freeze_guard_discards_tags(accel):
    """The freeze guard discards queued stimulation and tags."""
    accel.start_beat(accelerated=True)
    accel.exchange("a", _strong(accel, "a"), tag="f")
    accel._last_beat_at = time.monotonic() - 10.0
    accel.beat(0.1)

    assert accel._next_tags == {}
    assert _wait_for(lambda: accel._latest.get("a") is not None)
    assert accel._latest_response.get("a") is None


def test_real_time_response_is_the_window_after_delivery():
    """In real time the response arrives in the window after delivery."""
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
        broker.exchange("a", _strong(broker, "a"), tag="rt")
        for _ in range(4):
            broker.beat(0.1)
            time.sleep(0.12)
        assert _wait_for(
            lambda: (r := broker._latest_response.get("a")) is not None
            and r.tag == "rt"
        )
        # The evoked response (about 60 spikes here), not a baseline window (about 1).
        assert len(broker._latest_response["a"].spikes) >= 16
    finally:
        broker.stop_beat()
        session.close()
        clsim.clear_simulator_data_source()


def test_nous_scores_the_answer_against_the_encoded_choice():
    """The wetware policy engine scores the substrate answer against the silicon choice."""
    @dataclasses.dataclass(frozen=True)
    class Result:
        posterior: object
        policy_efe: object
        action_index: int
        action: str
        timed_out: bool = False
        error: bool = False

    class SiliconEngine:
        def __init__(self, results):
            self.actions = ("a", "b", "c", "d")
            self._results = iter(results)

        def step(self, snapshot):
            return next(self._results)

    class LaggingBroker:
        def __init__(self):
            self._prev_tag = None

        def exchange(self, module, requests, tag=None):
            obs = types.SimpleNamespace(
                spikes=[types.SimpleNamespace(channel=c) for c in (1, 2)],
                tag=self._prev_tag,
            )
            self._prev_tag = tag
            return obs

    territory = types.SimpleNamespace(module="nous", channels=tuple(range(1, 11)))

    shadow_policy = SiliconEngine(
        [
            Result(None, [0, 1, 2, 3], 0, "a"),
            Result(None, [1, 0, 2, 3], 1, "b"),
        ]
    )
    shadow_broker = LaggingBroker()
    engine = WetwarePolicyEngine(
        shadow_policy, shadow_broker, territory, mode="shadow"
    )
    engine.step(None)
    assert engine.proposal_count == 0
    engine.step(None)
    assert engine.proposal_count == 1
    assert engine.agreement_rate == 1.0
    assert engine.last_proposal == 0

    drive_policy = SiliconEngine(
        [
            Result(None, [0, 1, 2, 3], 0, "a"),
            Result(None, [1, 0, 2, 3], 1, "b"),
        ]
    )
    drive_broker = LaggingBroker()
    drive_engine = WetwarePolicyEngine(
        drive_policy, drive_broker, territory, mode="drive"
    )
    drive_engine.step(None)
    driven = drive_engine.step(None)
    assert driven.action_index == 0
