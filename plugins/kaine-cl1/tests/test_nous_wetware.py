# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""tests for Nous on wetware: the substrate policy proposer (OpenSpec nous-on-wetware)."""

import logging
import os

os.environ.setdefault("CL_SDK_ACCELERATED_TIME", "1")
os.environ.setdefault("CL_SDK_VISUALISATION", "0")

import copy  # noqa: E402
import dataclasses  # noqa: E402
import math  # noqa: E402
import types  # noqa: E402

import cl.sim as clsim  # noqa: E402
import pytest  # noqa: E402
from kaine_cl1.backends.nous import (  # noqa: E402
    FEEDBACK_PULSE_UA,
    LOG_EVERY,
    WetwarePolicyEngine,
)
from kaine_cl1.boot import WETWARE_BACKENDS  # noqa: E402
from kaine_cl1.config import overlay_from_mapping  # noqa: E402
from kaine_cl1.plugin import Cl1Plugin  # noqa: E402
from kaine_cl1.substrate.broker import (  # noqa: E402
    ChannelTerritory,
    SubstrateBroker,
    TerritoryObservation,
)
from kaine_cl1.substrate.session import SubstrateConfig, SubstrateSession  # noqa: E402


@dataclasses.dataclass(frozen=True)
class FakeResult:
    posterior: list
    policy_efe: list
    action_index: int
    action: str
    timed_out: bool = False
    error: bool = False


class FakeEngine:
    def __init__(self, efe=(0.0, 1.0, 2.0, 3.0), actions=("a", "b", "c", "d")):
        self._efe = efe
        self._actions = actions
        self.next_result = None
        self.seeded = None
        self.closed = False
        self.model = "silicon-model"

    @property
    def actions(self):
        return self._actions

    def step(self, snapshot):
        if self.next_result is not None:
            return self.next_result
        finite = [(i, v) for i, v in enumerate(self._efe) if math.isfinite(v)]
        if finite:
            index = min(finite, key=lambda iv: iv[1])[0]
        else:
            index = 0
        return FakeResult(
            posterior=[[1.0]],
            policy_efe=list(self._efe),
            action_index=index,
            action=self._actions[index],
        )

    def seed_posterior(self, posterior):
        self.seeded = posterior

    def close(self):
        self.closed = True


class FakeBroker:
    def __init__(self, spike_channels=None):
        self.calls = []
        self.spike_channels = spike_channels or []

    def exchange(self, module, requests, tag=None):
        # Answers at once, like the broker before beat mode: the window carries this call's tag.
        self.calls.append((module, list(requests)))
        return TerritoryObservation(
            module=module,
            channels=(),
            spikes=[types.SimpleNamespace(channel=c) for c in self.spike_channels],
            from_timestamp=0,
            frame_count=1,
            tag=tag,
        )


TERRITORY = ChannelTerritory("nous", tuple(range(1, 11)))


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
    broker = SubstrateBroker(channel_count=64, ticks_per_second=100, nesting_factor=6)
    territory = broker.allocate("nous", 10)
    broker.open(session.neurons)
    try:
        yield broker, territory
    finally:
        session.close()
        clsim.clear_simulator_data_source()


def _cfg(nous=None):
    cfg = {
        "substrate": {
            "target": "simulator",
            "accelerated_time": True,
            "ticks_per_second": 100,
            "cognitive_rate": 3.333,
            "territories": {"nous": 10},
        },
        "backends": {"nous": "cl1"},
    }
    if nous is not None:
        cfg["nous"] = nous
    return cfg


def test_shadow_returns_inner_result_and_counts_proposal():
    engine = FakeEngine()
    broker = FakeBroker(spike_channels=[1, 2])
    wrapper = WetwarePolicyEngine(engine, broker, TERRITORY, mode="shadow")
    expected = FakeResult(
        posterior=[[1.0]],
        policy_efe=[0.0, 1.0, 2.0, 3.0],
        action_index=0,
        action="a",
    )
    engine.next_result = expected
    result = wrapper.step(None)
    assert result is expected
    assert wrapper.proposal_count == 1
    assert len(broker.calls) == 1


def test_drive_chooses_wetware_action():
    engine = FakeEngine()
    broker = FakeBroker(spike_channels=[5, 6, 5])
    wrapper = WetwarePolicyEngine(engine, broker, TERRITORY, mode="drive")
    result = wrapper.step(None)
    assert result.action_index == 2
    assert result.action == "c"
    assert result.posterior == [[1.0]]
    assert result.policy_efe == [0.0, 1.0, 2.0, 3.0]
    assert wrapper.agreement_rate == 0.0


def test_no_spikes_and_tie_fall_back_to_silicon():
    engine = FakeEngine()
    broker = FakeBroker(spike_channels=[])
    wrapper = WetwarePolicyEngine(engine, broker, TERRITORY, mode="shadow")
    wrapper.step(None)
    assert wrapper.last_proposal == 0
    # A silent window is not the tissue choosing: it counts as a disagreement.
    assert wrapper.proposal_count == 1
    assert wrapper.agreement_rate == 0.0

    broker = FakeBroker(spike_channels=[3, 7])
    wrapper = WetwarePolicyEngine(engine, broker, TERRITORY, mode="shadow")
    wrapper.step(None)
    assert wrapper.last_proposal == 0


def test_stimulation_encoding():
    engine = FakeEngine()
    broker = FakeBroker(spike_channels=[])
    wrapper = WetwarePolicyEngine(
        engine, broker, TERRITORY, mode="shadow", min_uA=0.5, max_uA=3.0
    )
    wrapper.step(None)
    assert len(broker.calls) == 1
    module, requests = broker.calls[0]
    assert module == "nous"
    channels = {r.channel for r in requests}
    assert channels == set(range(1, 9))
    amplitudes = {r.channel: r.amplitude_uA for r in requests}
    assert amplitudes[1] == pytest.approx(3.0)
    assert amplitudes[2] == pytest.approx(3.0)
    for ch in range(1, 9):
        assert 0.5 <= amplitudes[ch] <= 3.0
    assert amplitudes[1] > amplitudes[3] > amplitudes[5] > amplitudes[7]


def test_non_finite_efe_gets_minimum_amplitude():
    engine = FakeEngine(efe=(math.inf, 0.0, math.nan, 1.0))
    broker = FakeBroker(spike_channels=[])
    wrapper = WetwarePolicyEngine(
        engine, broker, TERRITORY, mode="shadow", min_uA=0.5, max_uA=3.0
    )
    wrapper.step(None)
    amplitudes = {r.channel: r.amplitude_uA for r in broker.calls[0][1]}
    for ch in (1, 2, 5, 6):
        assert amplitudes[ch] == pytest.approx(0.5)
    for ch in range(1, 9):
        assert math.isfinite(amplitudes[ch])
    assert amplitudes[3] == pytest.approx(3.0)
    assert amplitudes[4] == pytest.approx(3.0)


def test_all_non_finite_efe_gets_minimum_everywhere():
    engine = FakeEngine(efe=(math.inf, math.inf, math.inf, math.inf))
    broker = FakeBroker(spike_channels=[])
    wrapper = WetwarePolicyEngine(
        engine, broker, TERRITORY, mode="shadow", min_uA=0.5, max_uA=3.0
    )
    wrapper.step(None)
    amplitudes = {r.channel: r.amplitude_uA for r in broker.calls[0][1]}
    for ch in range(1, 9):
        assert amplitudes[ch] == pytest.approx(0.5)


def test_feedback_after_agreement():
    engine = FakeEngine()
    broker = FakeBroker(spike_channels=[1, 2])
    wrapper = WetwarePolicyEngine(engine, broker, TERRITORY, mode="shadow")
    wrapper.step(None)
    first_feedback = [r for r in broker.calls[0][1] if r.channel in (9, 10)]
    assert first_feedback == []

    wrapper.step(None)
    second_feedback = [r for r in broker.calls[1][1] if r.channel in (9, 10)]
    assert len(second_feedback) == 2
    assert second_feedback[0].amplitude_uA == pytest.approx(FEEDBACK_PULSE_UA)
    assert second_feedback[1].amplitude_uA == pytest.approx(FEEDBACK_PULSE_UA)


def test_feedback_after_disagreement():
    engine = FakeEngine()
    broker = FakeBroker(spike_channels=[7, 8])
    wrapper = WetwarePolicyEngine(engine, broker, TERRITORY, mode="shadow", seed=42)
    wrapper.step(None)
    wrapper.step(None)
    second_feedback = [r for r in broker.calls[1][1] if r.channel in (9, 10)]
    assert len(second_feedback) == 2
    for r in second_feedback:
        assert 0.5 <= r.amplitude_uA < 3.0
    assert not all(r.amplitude_uA == FEEDBACK_PULSE_UA for r in second_feedback)

    def feedback_sequence(seed):
        br = FakeBroker(spike_channels=[7, 8])
        w = WetwarePolicyEngine(FakeEngine(), br, TERRITORY, mode="shadow", seed=seed)
        for _ in range(20):
            w.step(None)
        return [
            r.amplitude_uA
            for _, reqs in br.calls[1:]
            for r in reqs
            if r.channel in (9, 10)
        ]

    seq1 = feedback_sequence(42)
    seq2 = feedback_sequence(42)
    assert seq1 == seq2
    seq3 = feedback_sequence(43)
    assert seq3 != seq1


def test_timed_out_and_error_pass_through_without_exchange():
    engine = FakeEngine()
    broker = FakeBroker()
    wrapper = WetwarePolicyEngine(engine, broker, TERRITORY, mode="shadow")
    timed_out = FakeResult(
        posterior=[[1.0]],
        policy_efe=[0.0, 1.0, 2.0, 3.0],
        action_index=0,
        action="a",
        timed_out=True,
    )
    engine.next_result = timed_out
    assert wrapper.step(None) is timed_out
    assert len(broker.calls) == 0
    assert wrapper.proposal_count == 0

    engine.next_result = dataclasses.replace(timed_out, timed_out=False, error=True)
    result = wrapper.step(None)
    assert result.error is True
    assert len(broker.calls) == 0
    assert wrapper.proposal_count == 0


def test_attribute_forwarding_and_private_raised():
    engine = FakeEngine()
    wrapper = WetwarePolicyEngine(engine, FakeBroker(), TERRITORY, mode="shadow")

    wrapper.seed_posterior([[0.5]])
    assert engine.seeded == [[0.5]]

    wrapper.close()
    assert engine.closed is True

    assert wrapper.model == "silicon-model"
    assert wrapper.actions == engine.actions

    with pytest.raises(AttributeError):
        _ = wrapper._nonexistent

    # Without the private-name guard, a wrapper whose __init__ has not run (as during a
    # copy or unpickle) would recurse through __getattr__ looking up _inner.
    bare = WetwarePolicyEngine.__new__(WetwarePolicyEngine)
    with pytest.raises(AttributeError):
        _ = bare.model
    assert copy.copy(wrapper).model == "silicon-model"


def test_territory_and_mode_validation():
    small = ChannelTerritory("nous", tuple(range(1, 10)))
    with pytest.raises(ValueError, match=r"at least 10"):
        WetwarePolicyEngine(FakeEngine(), FakeBroker(), small, mode="shadow")

    with pytest.raises(ValueError):
        WetwarePolicyEngine(FakeEngine(), FakeBroker(), TERRITORY, mode="bogus")


def test_agreement_log(caplog):
    engine = FakeEngine()
    broker = FakeBroker(spike_channels=[1, 2])
    wrapper = WetwarePolicyEngine(engine, broker, TERRITORY, mode="shadow")
    with caplog.at_level(logging.INFO, logger="kaine_cl1.backends.nous"):
        for _ in range(LOG_EVERY):
            wrapper.step(None)
    relevant = [
        r for r in caplog.records if "agreed with the silicon policy" in r.message
    ]
    assert len(relevant) == 1
    assert "100 of 100" in relevant[0].message


def test_reference_culture_follows_the_stimulation(substrate):
    broker, territory = substrate
    engine = FakeEngine()
    # EFE favours action 2, but silicon reports action 0, so a proposal of 2 can only come
    # from evoked spikes: the no-spike and tie fallback would give 0.
    engine.next_result = FakeResult(
        posterior=[[1.0]], policy_efe=[5.0, 5.0, 0.0, 5.0], action_index=0, action="a"
    )
    wrapper = WetwarePolicyEngine(engine, broker, territory, mode="shadow", seed=7)
    proposals = []
    for _ in range(30):
        wrapper.step(None)
        proposals.append(wrapper.last_proposal)
    assert wrapper.proposal_count == 30
    assert proposals.count(2) > 15


def test_config_default_and_drive_modes():
    overlay = overlay_from_mapping(_cfg())
    assert overlay.nous_mode == "shadow"

    overlay = overlay_from_mapping(_cfg({"mode": "drive"}))
    assert overlay.nous_mode == "drive"


def test_config_invalid_mode_raises():
    with pytest.raises(ValueError, match=r"\[nous\]\.mode"):
        overlay_from_mapping(_cfg({"mode": "fast"}))

    with pytest.raises(ValueError, match=r"\[nous\]\.mode"):
        overlay_from_mapping(_cfg({"mode": 3}))


def test_config_backend_options():
    overlay = overlay_from_mapping(_cfg({"mode": "drive"}))
    assert overlay.backend_options("nous") == {
        "mode": "drive",
        "seed": overlay.substrate.random_seed,
    }
    assert overlay.backend_options("chronos") == {}


def test_boot_row():
    row = WETWARE_BACKENDS["nous"]
    assert row.inject_kwarg == "engine_wrapper"

    make = row.make(FakeBroker(), TERRITORY, mode="drive", seed=3)
    assert callable(make)
    engine = FakeEngine()
    wrapper = make(engine)
    assert isinstance(wrapper, WetwarePolicyEngine)

    broker = FakeBroker(spike_channels=[5, 6, 5])
    engine = FakeEngine()
    wrapper = row.make(broker, TERRITORY, mode="drive", seed=3)(engine)
    expected = FakeResult(
        posterior=[[1.0]],
        policy_efe=[0.0, 1.0, 2.0, 3.0],
        action_index=0,
        action="a",
    )
    engine.next_result = expected
    result = wrapper.step(None)
    assert result is not expected
    assert result.action_index == 2
    assert result.action == "c"


def test_plugin_seams(caplog):
    plugin = Cl1Plugin()
    try:
        with caplog.at_level(logging.INFO, logger="kaine_cl1.plugin"):
            seams = plugin.seams(_cfg())
        assert "nous.engine_wrapper" in seams
        assert any("shadow mode" in r.message for r in caplog.records)
        assert not any("DRIVE" in r.message for r in caplog.records)
    finally:
        plugin.close()

    caplog.clear()

    plugin = Cl1Plugin()
    try:
        with caplog.at_level(logging.WARNING, logger="kaine_cl1.plugin"):
            seams = plugin.seams(_cfg({"mode": "drive"}))
        assert "nous.engine_wrapper" in seams
        assert any("DRIVE mode" in r.message for r in caplog.records)
    finally:
        plugin.close()
