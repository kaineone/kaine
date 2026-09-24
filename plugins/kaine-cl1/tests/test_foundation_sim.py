# SPDX-License-Identifier: LicenseRef-CAL-0.2
"""Foundation integration tests against the vendored CL simulator.

These use the deterministic, stim-responsive ReferenceCulture source so the whole
closed loop is exercised and reproducible. They open the simulator (subprocesses),
so they are a little slower than the pure tests.
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("CL_SDK_ACCELERATED_TIME", "1")
os.environ.setdefault("CL_SDK_VISUALISATION", "0")

import cl.sim as clsim  # noqa: E402
from kaine_cl1.substrate.broker import SubstrateBroker  # noqa: E402
from kaine_cl1.substrate.codec import StimRequest, SurpriseDecoder  # noqa: E402
from kaine_cl1.substrate.session import SubstrateConfig, SubstrateSession  # noqa: E402

_SOURCE = "kaine_cl1.substrate.sources:make_reference_culture"
_CONFIG = {"seed": 42, "baseline_hz": 5.0, "evoked_spikes": 12, "response_ms": 20.0}


def _register():
    """(Re-)register the source. Re-registration resets the SDK singleton, so the
    substrate timeline restarts at t=0 — necessary because the SDK does NOT reset
    its frame clock on an in-process re-open (open 2 would otherwise continue the
    timeline and read a different, non-comparable region). Each 'run' below calls
    this first so runs are directly comparable and reproducible."""
    clsim.set_simulator_data_source(_SOURCE, config=_CONFIG)


@pytest.fixture
def reference_source():
    _register()
    yield
    clsim.clear_simulator_data_source()


def _session():
    _register()  # reset timeline to t=0 for this run
    return SubstrateSession(
        SubstrateConfig(accelerated_time=True, random_seed=42, ticks_per_second=100)
    )


def _collect_loop_spikes(limit_ts=6000):
    """Collect spikes with timestamp < limit_ts. Comparing over a fixed timestamp
    span (not a fixed tick count) is what makes the deterministic source's output
    reproducible — accelerated `loop()` chunks frames-per-tick nondeterministically."""
    out = []
    with _session() as s:
        for tick in s.neurons.loop(ticks_per_second=100):
            for sp in tick.analysis.spikes:
                if sp.timestamp < limit_ts:
                    out.append((sp.channel, sp.timestamp))
            if tick.analysis.stop_timestamp >= limit_ts:
                break
    return sorted(out)


def test_reference_source_is_deterministic(reference_source):
    a = _collect_loop_spikes()
    b = _collect_loop_spikes()
    assert a == b
    assert len(a) > 0


def _run_broker(nesting, ticks, stim=False, stim_tick=1):
    b = SubstrateBroker(channel_count=64, ticks_per_second=100, nesting_factor=nesting)
    ta = b.allocate("A", 4)  # channels 1..4 (channel 0 reserved)
    tb = b.allocate("B", 4)  # channels 5..8
    totals = {"A": 0, "B": 0}
    b_channels_seen: set[int] = set()
    with _session() as s:
        b.open(s.neurons)
        for t in range(ticks):
            if stim and t == stim_tick:
                b.queue_stim("A", [StimRequest(channel=ta.channels[0], amplitude_uA=2.0)])
            obs = b.run_cognitive_tick()
            totals["A"] += len(obs["A"].spikes)
            totals["B"] += len(obs["B"].spikes)
            b_channels_seen.update(sp.channel for sp in obs["B"].spikes)
    return totals, b_channels_seen, set(ta.channels), set(tb.channels)


def test_broker_territory_isolation_and_stim_response(reference_source):
    base, _, _, _ = _run_broker(nesting=5, ticks=6)
    stimmed, b_channels, a_ch, b_ch = _run_broker(nesting=5, ticks=6, stim=True)
    # Stimulating module A's channel raises A's spike count materially.
    assert stimmed["A"] > base["A"] + 5
    # Module B, on disjoint channels, never sees A's channels and stays ~baseline.
    assert b_channels <= b_ch
    assert not (b_channels & a_ch)
    assert stimmed["B"] <= base["B"] + 3


def test_broker_is_deterministic(reference_source):
    a, _, _, _ = _run_broker(nesting=5, ticks=5, stim=True)
    b, _, _, _ = _run_broker(nesting=5, ticks=5, stim=True)
    assert a == b


def test_channel_zero_is_unstimulable(reference_source):
    """Documents the SDK quirk the broker guards against: stims on channel 0 are
    silently dropped by the simulator (never recorded, never evoked), so the
    broker reserves channel 0 out of every territory."""
    from cl import ChannelSet, StimDesign

    recorded = {0: [], 1: []}
    for ch in (0, 1):
        _register()
        with _session() as s:
            for tick in s.neurons.loop(ticks_per_second=100, stop_after_ticks=12):
                if tick.iteration == 2:
                    s.neurons.stim(ChannelSet(ch), StimDesign(200, -2.0, 200, 2.0))
                recorded[ch].extend(st.channel for st in tick.analysis.stims)
    assert recorded[0] == []       # channel 0 stim never commits
    assert 1 in recorded[1]        # channel 1 stim does


def test_cognitive_tick_aggregates_subticks(reference_source):
    b = SubstrateBroker(channel_count=64, ticks_per_second=100, nesting_factor=5)
    b.allocate("A", 8)
    with _session() as s:
        b.open(s.neurons)
        obs = b.run_cognitive_tick()["A"]
    # 5 sub-ticks at 100 Hz over a 25 kHz clock ≈ 5 * 250 = 1250 frames.
    assert 1000 <= obs.frame_count <= 1500


def test_surprise_decoder_on_live_response(reference_source):
    """Surprise is higher for a stimulated (evoked, scattered) response than for
    quiet baseline, using real simulator spikes."""
    b = SubstrateBroker(channel_count=64, ticks_per_second=100, nesting_factor=6)
    b.allocate("A", 8)
    dec = SurpriseDecoder(channels=b.territory("A").channels, bins=16, baseline_window=8)
    with _session() as s:
        b.open(s.neurons)
        # baseline ticks
        quiet_vals = []
        for _ in range(8):
            obs = b.run_cognitive_tick()["A"]
            quiet_vals.append(dec.decode(obs.spikes, obs.from_timestamp, obs.frame_count))
        # stimulate across the territory and measure surprise
        for ch in b.territory("A").channels:
            b.queue_stim("A", [StimRequest(channel=ch, amplitude_uA=2.5)])
        obs = b.run_cognitive_tick()["A"]
        evoked = dec.decode(obs.spikes, obs.from_timestamp, obs.frame_count)
    assert evoked >= quiet_vals[-1]
