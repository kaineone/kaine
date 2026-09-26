# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Tests for the hardware target's welfare gate, freeze safety and real-time visibility.

No real device is used: hardware is represented by a fake SDK device.
"""

import os  # noqa: I001

os.environ.setdefault("CL_SDK_ACCELERATED_TIME", "1")
os.environ.setdefault("CL_SDK_VISUALISATION", "0")

import logging  # noqa: E402
import time  # noqa: E402
import types  # noqa: E402

import cl  # noqa: E402
import cl.sim as clsim  # noqa: E402
import pytest  # noqa: E402
from kaine_cl1.plugin import REQUIRED_ACKNOWLEDGEMENT, Cl1Plugin  # noqa: E402
from kaine_cl1.substrate.broker import SubstrateBroker  # noqa: E402
from kaine_cl1.substrate.codec import StimRequest  # noqa: E402
from kaine_cl1.substrate.session import SubstrateConfig, SubstrateSession  # noqa: E402


def _hw_cfg(**hardware_overrides):
    cfg = {
        "substrate": {
            "target": "hardware",
            "accelerated_time": False,
            "ticks_per_second": 100,
            "cognitive_rate": 3.333,
            "territories": {"chronos": 8},
        },
        "backends": {"chronos": "cl1"},
        "hardware": {
            "welfare_acknowledgement": REQUIRED_ACKNOWLEDGEMENT,
            "ethics_reference": "IRB-2026-001",
        },
    }
    cfg["hardware"].update(hardware_overrides)
    return cfg


class _FakeNeurons:
    def __init__(self, tick_frames=250, delay=0.005, spikes_per_tick=0):
        self.stims = []
        self._tick_frames = tick_frames
        self._delay = delay
        self._spikes_per_tick = spikes_per_tick

    def get_frames_per_second(self):
        return 25000

    def stim(self, channel_set, design):
        self.stims.append((channel_set, design))

    def loop(self, ticks_per_second=100):
        ts = 0
        while True:
            time.sleep(self._delay)
            spikes = [
                types.SimpleNamespace(channel=1, timestamp=ts + i)
                for i in range(self._spikes_per_tick)
            ]
            yield types.SimpleNamespace(
                analysis=types.SimpleNamespace(
                    start_timestamp=ts,
                    stop_timestamp=ts + self._tick_frames,
                    spikes=spikes,
                )
            )
            ts += self._tick_frames


class _FakeHardwareSession:
    def __init__(self, config):
        self.config = config
        self.neurons = _FakeNeurons()
        self.closed = False

    def open(self):
        return self.neurons

    def close(self):
        self.closed = True


def _wait_for(pred, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def accel():
    clsim.set_simulator_data_source(
        "kaine_cl1.substrate.sources:make_reference_culture",
        config={"seed": 7},
    )
    session = SubstrateSession(
        SubstrateConfig(accelerated_time=True, ticks_per_second=100)
    )
    session.open()
    broker = SubstrateBroker(channel_count=64, ticks_per_second=100, nesting_factor=6)
    broker.allocate("a", 4)
    broker.open(session.neurons)
    yield broker
    broker.stop_beat()
    session.close()
    clsim.clear_simulator_data_source()


def test_complete_gate_declares_seams_and_warns(caplog):
    with caplog.at_level(logging.WARNING, logger="kaine_cl1.plugin"):
        seams = Cl1Plugin().seams(_hw_cfg())
    assert seams == frozenset({"chronos.network"})
    assert any(
        "LIVING NEURAL CULTURE" in rec.message and "IRB-2026-001" in rec.message
        for rec in caplog.records
    )


def test_missing_hardware_table_names_both_statements():
    cfg = _hw_cfg()
    del cfg["hardware"]
    with pytest.raises(ValueError) as exc_info:
        Cl1Plugin().seams(cfg)
    msg = str(exc_info.value)
    assert "welfare_acknowledgement" in msg
    assert "ethics_reference" in msg


def test_wrong_acknowledgement_refused():
    with pytest.raises(ValueError, match="welfare_acknowledgement"):
        Cl1Plugin().seams(_hw_cfg(welfare_acknowledgement="I agree"))


def test_blank_ethics_reference_refused():
    with pytest.raises(ValueError, match="ethics_reference"):
        Cl1Plugin().seams(_hw_cfg(ethics_reference="   "))


def test_accelerated_time_refused_on_hardware():
    cfg = _hw_cfg()
    cfg["substrate"]["accelerated_time"] = True
    with pytest.raises(ValueError, match="accelerated_time"):
        Cl1Plugin().seams(cfg)


def test_data_source_refused_on_hardware():
    cfg = _hw_cfg()
    cfg["substrate"]["data_source"] = "sdk"
    with pytest.raises(ValueError, match="data_source"):
        Cl1Plugin().seams(cfg)


def test_all_problems_listed_together():
    cfg = _hw_cfg(welfare_acknowledgement="x", ethics_reference="")
    cfg["substrate"]["accelerated_time"] = True
    with pytest.raises(ValueError) as exc_info:
        Cl1Plugin().seams(cfg)
    msg = str(exc_info.value)
    assert "welfare_acknowledgement" in msg
    assert "ethics_reference" in msg
    assert "accelerated_time" in msg


def test_cloud_still_refused():
    cfg = _hw_cfg()
    cfg["substrate"]["target"] = "cloud"
    with pytest.raises(ValueError, match="Cortical Cloud"):
        Cl1Plugin().seams(cfg)


def test_hardware_session_refuses_the_simulator():
    session = SubstrateSession(SubstrateConfig(target="hardware"))
    with pytest.raises(RuntimeError, match="no real device"):
        session.open()


def test_hardware_session_opens_on_a_device(monkeypatch):
    class _FakeCtx:
        def __init__(self, neurons):
            self._neurons = neurons

        def __enter__(self):
            return self._neurons

        def __exit__(self, *args):
            return None

    fake = _FakeNeurons()
    monkeypatch.setattr(cl, "is_simulator", lambda: False)
    monkeypatch.setattr(cl, "open", lambda: _FakeCtx(fake))

    before = os.environ.get("CL_SDK_REPLAY_PATH")
    session = SubstrateSession(SubstrateConfig(target="hardware"))
    try:
        neurons = session.open()
        assert neurons is fake
    finally:
        session.close()
    after = os.environ.get("CL_SDK_REPLAY_PATH")
    assert after == before


def test_hardware_starts_in_beat_mode_and_stimulates_only_on_ticks():
    p = Cl1Plugin(session_factory=_FakeHardwareSession)
    try:
        net = p.injections("chronos", _hw_cfg())["network"]
        broker = p._broker
        assert broker.beat_mode is True

        net.tick([10.0] * 8)
        net.tick([10.0] * 8)
        time.sleep(0.1)
        fake = p._session.neurons
        assert fake.stims == []

        p.on_cycle_tick({"processing_rate_hz": 10.0})
        assert _wait_for(lambda: len(fake.stims) > 0)
    finally:
        p.close()


def test_frozen_cycle_discards_stale_stimulation(accel, caplog):
    with caplog.at_level(logging.WARNING, logger="kaine_cl1.substrate.broker"):
        accel.start_beat(accelerated=True)
        accel.beat(0.1)
        time.sleep(0.05)

        channels = accel.territory("a").channels
        accel.exchange("a", [StimRequest(ch, 3.0) for ch in channels])

        time.sleep(0.25)
        accel.beat(0.1)

    assert accel.discarded_stim == len(channels)
    assert any("discarded" in rec.message for rec in caplog.records)


def test_realtime_overrun_is_counted(caplog):
    b = SubstrateBroker(channel_count=64, ticks_per_second=100, nesting_factor=6)
    b.allocate("a", 4)
    neurons = _FakeNeurons(delay=0.2)
    b.open(neurons)
    b.start_beat(accelerated=False)
    try:
        with caplog.at_level(logging.WARNING, logger="kaine_cl1.substrate.broker"):
            b.beat(0.1)
            b.beat(0.1)
        assert b.realtime_overruns >= 1
        assert any("behind the cycle" in rec.message for rec in caplog.records)
    finally:
        b.stop_beat(timeout=2.0)


def test_realtime_window_is_capped_without_beats():
    b = SubstrateBroker(channel_count=64, ticks_per_second=100, nesting_factor=6)
    b.allocate("a", 4)
    neurons = _FakeNeurons(delay=0.001, spikes_per_tick=2)
    b.open(neurons)
    b.start_beat(accelerated=False)
    try:
        b.beat(0.1)
        time.sleep(0.5)
        b.beat(0.1)

        assert _wait_for(lambda: b.exchange("a", []).frame_count > 0)
        obs = b.exchange("a", [])
        cap = round(0.1 * 25000)
        assert obs.frame_count <= 2 * cap + 250
    finally:
        b.stop_beat(timeout=2.0)

