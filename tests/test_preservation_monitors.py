# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""PR-2: autonomous safety-net monitors + research boot gate
(entity-preservation-on-divergence).

Covers:
* DivergenceMonitor — rising-edge crossing preserves once (rate-limited);
  sub-threshold does nothing; preserve is read-only (entity untouched).
* WelfareProtectiveMonitor — sustained-distress crossing → preserve THEN pause
  (default); transient sub-threshold does not interrupt; action recorded;
  config selects pause/end/notify.
* The shared SustainedThresholdTracker (rising-edge + transient reset).
* Research boot gate — refuse/allow over the four conditions + the dry
  preserve→revive self-check (passing and failing).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import validate_event
from kaine.cycle import control_state
from kaine.cycle.incident_log import IncidentLog
from kaine.cycle.preservation_monitor import (
    DivergenceMonitor,
    DivergenceMonitorConfig,
    PreservationConfig,
    PreservationRetentionConfig,
    WelfareProtectiveMonitor,
    WelfareResponseConfig,
)
from kaine.experiment.run_context import RunContext, set_run_context
from kaine.lifecycle.divergence import DivergenceAssessment
from kaine.lifecycle.manager import ForkManager
from kaine.lifecycle.welfare_signal import (
    SustainedThresholdTracker,
    WindowedEventCounter,
)
from kaine.modules.eidolon import Eidolon, SelfModel
from kaine.modules.registry import ModuleRegistry
from kaine.security.crypto import CryptoConfig, StateEncryptor, set_state_encryptor


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    b = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield b
    await b.close()


@pytest.fixture(autouse=True)
def _plaintext_encryptor():
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))
    yield
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))


@pytest.fixture(autouse=True)
def _run_context():
    set_run_context(
        RunContext(
            run_id="prtworun01234567",
            seed=7,
            started_at=datetime.now(timezone.utc).isoformat(),
            git_sha=None,
        )
    )
    yield
    set_run_context(None)


@pytest.fixture(autouse=True)
def _control_to_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(control_state, "CONTROL_PATH", tmp_path / "control.json")
    yield


async def _entity(bus: AsyncBus, tmp_path: Path, *, name="Aria"):
    reg = ModuleRegistry()
    eid = Eidolon(bus, persistence_path=tmp_path / "sm.json", save_interval_s=60)
    await eid.initialize()
    eid._model = SelfModel(name=name, values=["honesty"])
    reg.register(eid)
    return reg, eid


# ---------------------------------------------------------------------------
# Shared tracker primitives
# ---------------------------------------------------------------------------


def test_sustained_tracker_rising_edge_fires_once():
    t = SustainedThresholdTracker(threshold=0.5, duration_s=1.0)
    assert t.observe(0.9, now=0.0) is False  # onset
    assert t.observe(0.9, now=0.5) is False  # still within duration
    assert t.observe(0.9, now=1.1) is True   # sustained → fire once
    assert t.observe(0.9, now=1.2) is False  # cleared; no immediate re-fire


def test_sustained_tracker_transient_resets():
    t = SustainedThresholdTracker(threshold=0.5, duration_s=1.0)
    assert t.observe(0.9, now=0.0) is False
    assert t.observe(0.1, now=0.5) is False  # dropped below → reset
    # Even long after, no fire because the sustain timer was reset.
    assert t.observe(0.9, now=5.0) is False
    assert t.active_since == 5.0


def test_sustained_tracker_fires_at_exact_threshold():
    """The crossing test is ``>=`` (inclusive): a magnitude EXACTLY equal to the
    threshold counts as above and a sustained run of exactly-threshold samples
    fires."""
    t = SustainedThresholdTracker(threshold=0.5, duration_s=1.0)
    assert t.observe(0.5, now=0.0) is False  # exactly threshold → onset (not below)
    assert t.active_since == 0.0
    assert t.observe(0.5, now=0.9) is False  # still within duration
    assert t.observe(0.5, now=1.0) is True   # elapsed == duration → fire (>=)
    # Just-below the threshold would NOT have started an episode.
    t2 = SustainedThresholdTracker(threshold=0.5, duration_s=1.0)
    assert t2.observe(0.4999, now=0.0) is False
    assert t2.active_since is None


def test_windowed_counter_fires_on_threshold():
    c = WindowedEventCounter(window_s=10.0, threshold=3)
    assert c.record(0.0) is False
    assert c.record(1.0) is False
    assert c.record(2.0) is True   # 3 within window → fire
    assert c.record(3.0) is False  # window cleared


# ---------------------------------------------------------------------------
# DivergenceMonitor
# ---------------------------------------------------------------------------


class _StubFM:
    """ForkManager double recording preserve_live calls without touching disk."""

    def __init__(self):
        self.calls: list[dict] = []

    async def preserve_live(
        self, registry, *, reason, label, out_root, entity_name, require_encryption=False
    ):
        self.calls.append(
            {
                "reason": reason,
                "label": label,
                "entity_name": entity_name,
                "require_encryption": require_encryption,
            }
        )
        from kaine.lifecycle.preservation import PreservationResult

        return PreservationResult(
            ok=True,
            preservation_id=f"pid{len(self.calls)}",
            snapshot_id=f"snap{len(self.calls)}",
            reason=reason,
            label=label,
            run_id="prtworun01234567",
            world_model_captured=False,
        )


def _div_monitor(bus, registry, fm, cfg, monkeypatch, *, assessments, warmed=True):
    """Build a DivergenceMonitor whose assess_divergence yields `assessments`.

    ``warmed`` defaults True so the monitor-side warm-up gate is satisfied
    (the lived-experience floor is exercised in its own dedicated tests). It
    sets warmup floors to 0 and supplies an observations provider above 0.
    """
    seq = iter(assessments)
    last = {"v": assessments[-1]}

    def _fake_assess(*, state_root, eval_root):
        try:
            last["v"] = next(seq)
        except StopIteration:
            pass
        return last["v"]

    import kaine.cycle.preservation_monitor as pm

    monkeypatch.setattr(pm, "assess_divergence", _fake_assess)
    if warmed:
        cfg.warmup_observations = 0
        cfg.warmup_lived_time_s = 0.0
    return DivergenceMonitor(
        registry=registry,
        fork_manager=fm,
        config=cfg,
        bus=bus,
        incident_log=IncidentLog(enabled=False, path="unused"),
        observations_provider=lambda: 10_000,
    )


def _diverged(p=None, fd=None, warmed_up=True):
    return DivergenceAssessment(
        diverged=True,
        signals={
            "individuation_p_value": p,
            "fork_divergence": fd,
            "individuation_warmed_up": warmed_up,
        },
        summary="",
    )


def _not_diverged():
    return DivergenceAssessment(diverged=False, signals={}, summary="")


@pytest.mark.asyncio
async def test_divergence_rising_edge_preserves_once(bus, tmp_path, monkeypatch):
    reg, eid = await _entity(bus, tmp_path)
    fm = _StubFM()
    cfg = DivergenceMonitorConfig(enabled=True, min_interval_s=0.0)
    # below, below, ABOVE, ABOVE(stay), below, ABOVE(new edge)
    mon = _div_monitor(
        bus, reg, fm, cfg, monkeypatch,
        assessments=[
            _not_diverged(), _not_diverged(),
            _diverged(), _diverged(),
            _not_diverged(), _diverged(),
        ],
    )
    stop = asyncio.Event()
    for _ in range(6):
        await mon._poll_once(stop)
    # Two rising edges → two preservations (the stay-high poll did NOT re-fire).
    assert len(fm.calls) == 2
    assert all(c["reason"] == "individuation" for c in fm.calls)
    # Read-only: the live entity identity is untouched.
    assert reg.get("eidolon").model.name == "Aria"
    await eid.shutdown()


@pytest.mark.asyncio
async def test_divergence_sub_threshold_does_nothing(bus, tmp_path, monkeypatch):
    reg, eid = await _entity(bus, tmp_path)
    fm = _StubFM()
    cfg = DivergenceMonitorConfig(enabled=True, min_interval_s=0.0)
    mon = _div_monitor(
        bus, reg, fm, cfg, monkeypatch,
        assessments=[_not_diverged(), _not_diverged(), _not_diverged()],
    )
    stop = asyncio.Event()
    for _ in range(3):
        await mon._poll_once(stop)
    assert fm.calls == []
    await eid.shutdown()


@pytest.mark.asyncio
async def test_divergence_rate_limited(bus, tmp_path, monkeypatch):
    reg, eid = await _entity(bus, tmp_path)
    fm = _StubFM()
    # Large min interval; a clock that does not advance → second crossing is
    # rate-limited.
    cfg = DivergenceMonitorConfig(enabled=True, min_interval_s=10_000.0)
    mon = _div_monitor(
        bus, reg, fm, cfg, monkeypatch,
        assessments=[
            _diverged(), _not_diverged(), _diverged(),
        ],
    )
    mon._clock = lambda: 100.0  # frozen clock
    stop = asyncio.Event()
    for _ in range(3):
        await mon._poll_once(stop)
    # First crossing preserves; second crossing is within min_interval → skipped.
    assert len(fm.calls) == 1
    await eid.shutdown()


@pytest.mark.asyncio
async def test_divergence_numeric_threshold_gates(bus, tmp_path, monkeypatch):
    reg, eid = await _entity(bus, tmp_path)
    fm = _StubFM()
    cfg = DivergenceMonitorConfig(
        enabled=True, min_interval_s=0.0, individuation_p_value_max=0.01
    )
    # diverged but p-value 0.5 > 0.01 → does NOT cross; then p=0.005 crosses.
    mon = _div_monitor(
        bus, reg, fm, cfg, monkeypatch,
        assessments=[_diverged(p=0.5), _diverged(p=0.005)],
    )
    stop = asyncio.Event()
    await mon._poll_once(stop)
    assert fm.calls == []  # p-value too high
    await mon._poll_once(stop)
    assert len(fm.calls) == 1  # tighter p-value crosses
    await eid.shutdown()


@pytest.mark.asyncio
async def test_divergence_fork_divergence_min_gates(bus, tmp_path, monkeypatch):
    """fork_divergence_min floor: a diverged assessment with fd below the floor
    does NOT cross; a later rising edge with fd at/above the floor preserves
    once."""
    reg, eid = await _entity(bus, tmp_path)
    fm = _StubFM()
    cfg = DivergenceMonitorConfig(
        enabled=True, min_interval_s=0.0, fork_divergence_min=0.5
    )
    # fd=0.2 (< floor) → no cross; below (clear edge); fd=0.7 (>= floor) → cross.
    mon = _div_monitor(
        bus, reg, fm, cfg, monkeypatch,
        assessments=[_diverged(fd=0.2), _not_diverged(), _diverged(fd=0.7)],
    )
    stop = asyncio.Event()
    await mon._poll_once(stop)
    assert fm.calls == []          # fd below the floor → not a crossing
    await mon._poll_once(stop)     # drops below → clears the rising-edge latch
    await mon._poll_once(stop)
    assert len(fm.calls) == 1      # fd at/above the floor → one preserve
    await eid.shutdown()


@pytest.mark.asyncio
async def test_divergence_secondary_signal_only_passes_p_value_tightener(
    bus, tmp_path, monkeypatch
):
    """Secondary-signal divergence (drift/adapters: p_value is None, diverged
    True) has NO numeric p-value, so the individuation_p_value_max tightener does
    not veto it — it still preserves."""
    reg, eid = await _entity(bus, tmp_path)
    fm = _StubFM()
    cfg = DivergenceMonitorConfig(
        enabled=True, min_interval_s=0.0, individuation_p_value_max=0.01
    )
    # diverged=True but p_value is None (drift/adapter signal, no significance
    # test) → the p-value ceiling is only enforced when a number is present.
    mon = _div_monitor(
        bus, reg, fm, cfg, monkeypatch, assessments=[_diverged(p=None)]
    )
    stop = asyncio.Event()
    await mon._poll_once(stop)
    assert len(fm.calls) == 1
    await eid.shutdown()


@pytest.mark.asyncio
async def test_divergence_preserve_failure_recorded_and_monitor_continues(
    bus, tmp_path, monkeypatch
):
    """When preserve_live raises, the DivergenceMonitor records a
    preservation.failed event (no crash) and keeps running across a second
    crossing."""

    class _FailingFM:
        def __init__(self):
            self.attempts = 0

        async def preserve_live(
            self, registry, *, reason, label, out_root, entity_name,
            require_encryption=False,
        ):
            self.attempts += 1
            raise RuntimeError("capture blew up")

    reg, eid = await _entity(bus, tmp_path)
    fm = _FailingFM()
    cfg = DivergenceMonitorConfig(enabled=True, min_interval_s=0.0)
    # Two rising edges (below between them) → two preserve attempts, both fail.
    mon = _div_monitor(
        bus, reg, fm, cfg, monkeypatch,
        assessments=[_diverged(), _not_diverged(), _diverged()],
    )
    stop = asyncio.Event()
    for _ in range(3):
        await mon._poll_once(stop)  # must not raise
    assert fm.attempts == 2  # monitor kept running across the second crossing
    failed = [
        e for e in (await _drain(bus, "preservation.out"))
        if e.type == "preservation.failed"
    ]
    assert len(failed) == 2
    assert failed[0].payload.get("transition") == "preserve_failed"
    assert "capture blew up" in failed[0].payload.get("error", "")
    # Live entity untouched.
    assert reg.get("eidolon").model.name == "Aria"
    await eid.shutdown()


@pytest.mark.asyncio
async def test_divergence_preserve_is_read_only_real_forkmanager(bus, tmp_path, monkeypatch):
    """End-to-end with a REAL ForkManager: a real bundle is written and the live
    entity is untouched (read-only)."""
    reg, eid = await _entity(bus, tmp_path, name="Iris")
    fm = ForkManager(tmp_path / "forks")
    cfg = DivergenceMonitorConfig(
        enabled=True, min_interval_s=0.0, out_root=str(tmp_path / "backups"),
        entity_name="iris",
    )
    mon = _div_monitor(bus, reg, fm, cfg, monkeypatch, assessments=[_diverged()])
    stop = asyncio.Event()
    await mon._poll_once(stop)
    backups = list((tmp_path / "backups").iterdir())
    assert backups, "a real preservation bundle was written"
    # S5: entity-interior content is tarred (encryption disabled → bundle.tar);
    # the non-sensitive manifest stays loose.
    assert (backups[0] / "manifest.json").is_file()
    assert (backups[0] / "bundle.tar").is_file()
    # Read-only: identity intact, nothing deleted.
    assert reg.get("eidolon").model.name == "Iris"
    await eid.shutdown()


# ---------------------------------------------------------------------------
# individuation-instrument-gate — DivergenceMonitor warm-up gate (Defect B)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_divergence_warmup_blocks_crossing_at_t0(bus, tmp_path, monkeypatch):
    """A genuine crossing at t≈0 (no lived experience) does NOT preserve; it is
    recorded as a warming-up note (fail-closed)."""
    reg, eid = await _entity(bus, tmp_path)
    fm = _StubFM()
    cfg = DivergenceMonitorConfig(
        enabled=True, min_interval_s=0.0,
        warmup_observations=200, warmup_lived_time_s=1800.0,
    )
    # warmed=False so we keep the real warm-up floors; observations provider
    # returns 0 → floor unmet.
    mon = _div_monitor(
        bus, reg, fm, cfg, monkeypatch, assessments=[_diverged()], warmed=False
    )
    mon._observations_provider = lambda: 0
    mon._clock = lambda: 0.0
    stop = asyncio.Event()
    await mon._poll_once(stop)
    assert fm.calls == []  # warm-up not satisfied → no preserve
    skipped = [
        e for e in (await _drain(bus, "preservation.out"))
        if e.type == "preservation.skipped"
    ]
    assert skipped, "a warming-up note was recorded"
    assert skipped[-1].payload.get("transition") == "warming_up"
    await eid.shutdown()


@pytest.mark.asyncio
async def test_divergence_preserves_after_warmup(bus, tmp_path, monkeypatch):
    """Once BOTH lived-experience floors are met, a genuine crossing preserves."""
    reg, eid = await _entity(bus, tmp_path)
    fm = _StubFM()
    cfg = DivergenceMonitorConfig(
        enabled=True, min_interval_s=0.0,
        warmup_observations=100, warmup_lived_time_s=50.0,
    )
    obs = {"n": 0}
    clock = {"t": 0.0}
    mon = _div_monitor(
        bus, reg, fm, cfg, monkeypatch,
        assessments=[_diverged(), _diverged()], warmed=False,
    )
    mon._observations_provider = lambda: obs["n"]
    mon._clock = lambda: clock["t"]
    stop = asyncio.Event()
    # Poll 1: t=0, 0 observations → warming up, no preserve.
    await mon._poll_once(stop)
    assert fm.calls == []
    # Poll 2: floors met → genuine crossing preserves.
    obs["n"] = 500
    clock["t"] = 100.0
    await mon._poll_once(stop)
    assert len(fm.calls) == 1
    await eid.shutdown()


@pytest.mark.asyncio
async def test_divergence_unwarmed_report_is_fail_closed(bus, tmp_path, monkeypatch):
    """An individuation report carrying individuation_warmed_up == false never
    crosses, even past the monitor's own lived-experience floor (shared signal,
    fail-closed)."""
    reg, eid = await _entity(bus, tmp_path)
    fm = _StubFM()
    cfg = DivergenceMonitorConfig(enabled=True, min_interval_s=0.0)
    # Monitor floor satisfied (warmed=True), but the report's signal says the
    # instrument itself has not warmed up.
    mon = _div_monitor(
        bus, reg, fm, cfg, monkeypatch,
        assessments=[_diverged(p=0.001, warmed_up=False)],
    )
    stop = asyncio.Event()
    await mon._poll_once(stop)
    assert fm.calls == []  # un-warmed-up individuation report → no crossing
    await eid.shutdown()


# ---------------------------------------------------------------------------
# WelfareProtectiveMonitor
# ---------------------------------------------------------------------------


async def _push_soma_report(bus: AsyncBus, prediction_error: float):
    await bus.publish(
        validate_event(
            source="soma",
            type="soma.report",
            payload={"prediction_error": prediction_error},
            salience=0.5,
            timestamp=datetime.now(timezone.utc),
        )
    )


def _welfare_monitor(bus, registry, fm, cfg, *, on_end=None, clock=None, warmup_s=0.0):
    # Default warmup_s=0.0 so the cold-start window is disabled for the
    # crossing-behavior tests; the cold-start is exercised in its own tests.
    cfg.warmup_s = warmup_s
    mon = WelfareProtectiveMonitor(
        registry=registry,
        fork_manager=fm,
        config=cfg,
        bus=bus,
        incident_log=IncidentLog(enabled=False, path="unused"),
        on_end=on_end,
    )
    if clock is not None:
        mon._clock = clock
    return mon


@pytest.mark.asyncio
async def test_welfare_sustained_distress_preserves_then_pauses(bus, tmp_path):
    reg, eid = await _entity(bus, tmp_path)
    fm = _StubFM()
    cfg = WelfareResponseConfig(
        enabled=True, action="pause", distress_threshold=0.5,
        distress_duration_s=1.0, out_root=str(tmp_path / "backups"),
    )
    clock = {"t": 0.0}
    mon = _welfare_monitor(bus, reg, fm, cfg, clock=lambda: clock["t"])

    stop = asyncio.Event()
    # Onset.
    await _push_soma_report(bus, 0.9)
    clock["t"] = 0.0
    await mon._poll_once(stop)
    assert fm.calls == []  # not yet sustained
    assert control_state.read_control().frozen is False
    # Sustained beyond duration (timer-driven crossing, no new sample needed).
    clock["t"] = 2.0
    await mon._poll_once(stop)
    # Preserve happened FIRST, then the cycle was frozen (paused).
    assert len(fm.calls) == 1
    assert fm.calls[0]["reason"] == "welfare"
    control = control_state.read_control()
    assert control.frozen is True
    assert control.source == "welfare"
    await eid.shutdown()


@pytest.mark.asyncio
async def test_welfare_transient_does_not_interrupt(bus, tmp_path):
    reg, eid = await _entity(bus, tmp_path)
    fm = _StubFM()
    cfg = WelfareResponseConfig(
        enabled=True, action="pause", distress_threshold=0.5,
        distress_duration_s=9999.0, out_root=str(tmp_path / "backups"),
    )
    clock = {"t": 0.0}
    mon = _welfare_monitor(bus, reg, fm, cfg, clock=lambda: clock["t"])
    stop = asyncio.Event()
    await _push_soma_report(bus, 0.9)   # spike
    await _push_soma_report(bus, 0.1)   # drops below → resets
    await mon._poll_once(stop)
    clock["t"] = 100.0
    await mon._poll_once(stop)
    assert fm.calls == []
    assert control_state.read_control().frozen is False
    await eid.shutdown()


@pytest.mark.asyncio
async def test_welfare_action_end_calls_on_end(bus, tmp_path):
    reg, eid = await _entity(bus, tmp_path)
    fm = _StubFM()
    ended = {"v": False}
    cfg = WelfareResponseConfig(
        enabled=True, action="end", distress_threshold=0.5,
        distress_duration_s=1.0, out_root=str(tmp_path / "backups"),
    )
    clock = {"t": 0.0}
    mon = _welfare_monitor(
        bus, reg, fm, cfg, on_end=lambda: ended.__setitem__("v", True),
        clock=lambda: clock["t"],
    )
    stop = asyncio.Event()
    await _push_soma_report(bus, 0.9)
    await mon._poll_once(stop)
    clock["t"] = 5.0
    await mon._poll_once(stop)
    assert len(fm.calls) == 1
    assert ended["v"] is True            # run signalled to end
    # "end" does not freeze (the run is stopping).
    assert control_state.read_control().frozen is False
    await eid.shutdown()


@pytest.mark.asyncio
async def test_welfare_action_notify_preserves_and_continues(bus, tmp_path):
    reg, eid = await _entity(bus, tmp_path)
    fm = _StubFM()
    cfg = WelfareResponseConfig(
        enabled=True, action="notify", distress_threshold=0.5,
        distress_duration_s=1.0, out_root=str(tmp_path / "backups"),
    )
    clock = {"t": 0.0}
    mon = _welfare_monitor(bus, reg, fm, cfg, clock=lambda: clock["t"])
    stop = asyncio.Event()
    await _push_soma_report(bus, 0.9)
    await mon._poll_once(stop)
    clock["t"] = 5.0
    await mon._poll_once(stop)
    assert len(fm.calls) == 1
    assert control_state.read_control().frozen is False  # continues
    assert mon._acted is False  # notify does not latch
    await eid.shutdown()


@pytest.mark.asyncio
async def test_welfare_repeated_distress_arm_fires_and_latches_one_preserve(
    bus, tmp_path
):
    """The repeated_distress arm fires (the previously-dead
    `and crossing_reason is None` guard).

    Honest coupling note: the windowed-repeat counter is fed in the soma path
    ONLY when a sustained crossing fires, so "repeated_distress" is reachable only
    via a sustained crossing that ALSO crosses the windowed-repeat arm. We make
    the sustained arm fire by the timer (small distress_duration_s) and set
    repeat_threshold=1 so that single sustained episode immediately crosses the
    windowed-repeat arm and reclassifies the reason to 'repeated_distress'.
    action='pause' latches (_acted) so the response preserves EXACTLY once even as
    further crossings are attempted."""
    reg, eid = await _entity(bus, tmp_path)
    fm = _StubFM()
    cfg = WelfareResponseConfig(
        enabled=True, action="pause",
        distress_threshold=0.5,
        distress_duration_s=1.0,
        repeat_window_s=300.0,
        repeat_threshold=1,               # one sustained episode crosses the arm
        out_root=str(tmp_path / "backups"),
    )
    clock = {"t": 0.0}
    mon = _welfare_monitor(bus, reg, fm, cfg, clock=lambda: clock["t"])
    stop = asyncio.Event()
    # Onset, then a later poll past the duration → timer-driven sustained crossing
    # which (repeat_threshold=1) immediately reclassifies to repeated_distress.
    await _push_soma_report(bus, 0.9)
    clock["t"] = 0.0
    await mon._poll_once(stop)
    clock["t"] = 5.0
    await mon._poll_once(stop)
    # A further crossing attempt must NOT add a second preserve (pause latched).
    await _push_soma_report(bus, 0.9)
    clock["t"] = 10.0
    await mon._poll_once(stop)
    clock["t"] = 15.0
    await mon._poll_once(stop)
    assert len(fm.calls) == 1
    assert fm.calls[0]["reason"] == "welfare"
    welfare_events = [
        e for e in (await _drain(bus, "preservation.out"))
        if e.type == "welfare.protective_action"
    ]
    assert welfare_events, "a protective action was published"
    assert welfare_events[-1].payload.get("reason") == "repeated_distress"
    await eid.shutdown()


@pytest.mark.asyncio
async def test_welfare_still_pauses_when_preservation_fails(bus, tmp_path):
    """If preserve_live raises, the protective action still PAUSES (freezes) the
    run — the entity is not left suffering because the save failed — the incident
    records preserve_error, and the monitor does not die."""

    class _FailingFM:
        async def preserve_live(
            self, registry, *, reason, label, out_root, entity_name,
            require_encryption=False,
        ):
            raise RuntimeError("disk full")

    reg, eid = await _entity(bus, tmp_path)
    fm = _FailingFM()
    cfg = WelfareResponseConfig(
        enabled=True, action="pause", distress_threshold=0.5,
        distress_duration_s=1.0, out_root=str(tmp_path / "backups"),
    )
    clock = {"t": 0.0}
    mon = _welfare_monitor(bus, reg, fm, cfg, clock=lambda: clock["t"])
    stop = asyncio.Event()
    await _push_soma_report(bus, 0.9)
    clock["t"] = 0.0
    await mon._poll_once(stop)            # onset — not yet sustained
    clock["t"] = 5.0
    await mon._poll_once(stop)            # sustained crossing → preserve FAILS
    # Despite the preserve failure the run is frozen (paused) — humane fallback.
    control = control_state.read_control()
    assert control.frozen is True
    assert control.source == "welfare"
    welfare_events = [
        e for e in (await _drain(bus, "preservation.out"))
        if e.type == "welfare.protective_action"
    ]
    assert welfare_events, "a protective action was still published"
    ev = welfare_events[-1].payload
    assert ev.get("preserve_error") and "disk full" in ev["preserve_error"]
    assert ev.get("transition") == "protective_action_preserve_failed"
    assert mon._acted is True             # pause latched; monitor alive
    await eid.shutdown()


@pytest.mark.asyncio
async def test_welfare_action_end_without_on_end_falls_back_to_pause(bus, tmp_path):
    """action='end' with no on_end hook wired must degrade honestly to a pause
    (action_taken == 'pause_fallback') so the entity is not left suffering;
    freeze fires and _acted latches."""
    reg, eid = await _entity(bus, tmp_path)
    fm = _StubFM()
    cfg = WelfareResponseConfig(
        enabled=True, action="end", distress_threshold=0.5,
        distress_duration_s=1.0, out_root=str(tmp_path / "backups"),
    )
    clock = {"t": 0.0}
    mon = _welfare_monitor(bus, reg, fm, cfg, on_end=None, clock=lambda: clock["t"])
    stop = asyncio.Event()
    await _push_soma_report(bus, 0.9)
    clock["t"] = 0.0
    await mon._poll_once(stop)
    clock["t"] = 5.0
    await mon._poll_once(stop)
    assert len(fm.calls) == 1
    control = control_state.read_control()
    assert control.frozen is True            # fell back to pause/freeze
    assert control.source == "welfare"
    assert mon._acted is True
    welfare_events = [
        e for e in (await _drain(bus, "preservation.out"))
        if e.type == "welfare.protective_action"
    ]
    assert welfare_events[-1].payload.get("action") == "pause_fallback"
    await eid.shutdown()


# ---------------------------------------------------------------------------
# individuation-instrument-gate — welfare cold-start warm-up (Task 4.2)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_welfare_boot_transient_within_warmup_does_not_act(bus, tmp_path):
    """Sustained distress that occurs entirely within the cold-start warmup_s is
    observed + logged but does NOT preserve-then-pause."""
    reg, eid = await _entity(bus, tmp_path)
    fm = _StubFM()
    cfg = WelfareResponseConfig(
        enabled=True, action="pause", distress_threshold=0.5,
        distress_duration_s=1.0, out_root=str(tmp_path / "backups"),
    )
    clock = {"t": 0.0}
    mon = _welfare_monitor(bus, reg, fm, cfg, clock=lambda: clock["t"], warmup_s=120.0)
    stop = asyncio.Event()
    # Onset + sustained beyond duration, but all within the 120 s warm-up window.
    await _push_soma_report(bus, 0.9)
    clock["t"] = 1.0
    await mon._poll_once(stop)
    clock["t"] = 60.0
    await _push_soma_report(bus, 0.9)
    await mon._poll_once(stop)
    assert fm.calls == []  # no protective action during warm-up
    assert control_state.read_control().frozen is False
    # A warming-up note was recorded (events observed + logged, not counted).
    warming = [
        e for e in (await _drain(bus, "preservation.out"))
        if e.type == "welfare.warming_up"
    ]
    assert warming, "boot transients were observed + logged during warm-up"
    await eid.shutdown()


@pytest.mark.asyncio
async def test_welfare_sustained_distress_after_warmup_still_acts(bus, tmp_path):
    """After the warm-up window, genuine sustained distress preserves-then-pauses
    as before (the gate does not weaken the net)."""
    reg, eid = await _entity(bus, tmp_path)
    fm = _StubFM()
    cfg = WelfareResponseConfig(
        enabled=True, action="pause", distress_threshold=0.5,
        distress_duration_s=1.0, out_root=str(tmp_path / "backups"),
    )
    clock = {"t": 0.0}
    mon = _welfare_monitor(bus, reg, fm, cfg, clock=lambda: clock["t"], warmup_s=30.0)
    stop = asyncio.Event()
    # First poll stamps the warm-up origin at t=0; advance past warm-up.
    await mon._poll_once(stop)
    # Now (past warm-up) drive a genuine sustained crossing.
    clock["t"] = 40.0
    await _push_soma_report(bus, 0.9)
    await mon._poll_once(stop)
    clock["t"] = 45.0
    await mon._poll_once(stop)  # timer-driven sustained crossing
    assert len(fm.calls) == 1
    control = control_state.read_control()
    assert control.frozen is True
    assert control.source == "welfare"
    await eid.shutdown()


# ---------------------------------------------------------------------------
# individuation-instrument-gate — shared signal: preserve + decommission agree
# (Task 5.2)
# ---------------------------------------------------------------------------


def test_shared_signal_consumers_agree_on_warmed_up_report(tmp_path):
    """A single warmed-up, significant individuation report makes BOTH
    consumers read individuated: assess_divergence() returns diverged AND the
    DivergenceMonitor crossing decision fires on the same report's signals."""
    from kaine.lifecycle.divergence import assess_divergence

    eval_dir = tmp_path / "eval" / "individuation"
    eval_dir.mkdir(parents=True)
    report = {
        "significant": True, "warmed_up": True,
        "p_value": 0.001, "fork_divergence": 0.6,
    }
    (eval_dir / "r.jsonl").write_text(__import__("json").dumps(report) + "\n")

    a = assess_divergence(state_root=tmp_path / "state", eval_root=tmp_path / "eval")
    assert a.diverged is True
    assert a.signals["individuation_warmed_up"] is True

    # The monitor's crossing decision, fed the SAME assessment, must agree.
    cfg = DivergenceMonitorConfig(individuation_p_value_max=0.05, fork_divergence_min=0.15)
    mon = DivergenceMonitor(
        registry=ModuleRegistry(), fork_manager=_StubFM(), config=cfg,
        bus=None, incident_log=IncidentLog(enabled=False, path="unused"),
    )
    assert mon._crosses_threshold(a) is True


def test_shared_signal_unwarmed_report_neither_consumer_individuates(tmp_path):
    """A report with warmed_up == false reads NOT diverged for decommission AND
    NOT crossed for preservation — the two never disagree (fail-closed)."""
    from kaine.lifecycle.divergence import assess_divergence

    eval_dir = tmp_path / "eval" / "individuation"
    eval_dir.mkdir(parents=True)
    # The instrument would already have forced significant=false when not warmed
    # up; assert the decommission gate is fail-closed even on a malformed report
    # that left significant=true but warmed_up=false.
    report = {
        "significant": True, "warmed_up": False,
        "p_value": 0.001, "fork_divergence": 0.6,
    }
    (eval_dir / "r.jsonl").write_text(__import__("json").dumps(report) + "\n")

    a = assess_divergence(state_root=tmp_path / "state", eval_root=tmp_path / "eval")
    assert a.diverged is False  # fail-closed: not warmed up
    assert a.signals["individuation_warmed_up"] is False
    assert "INSUFFICIENT LIVED EXPERIENCE" in a.summary

    cfg = DivergenceMonitorConfig()
    mon = DivergenceMonitor(
        registry=ModuleRegistry(), fork_manager=_StubFM(), config=cfg,
        bus=None, incident_log=IncidentLog(enabled=False, path="unused"),
    )
    assert mon._crosses_threshold(a) is False


# ---------------------------------------------------------------------------
# Config guards
# ---------------------------------------------------------------------------


def test_retention_refuses_auto_evict():
    with pytest.raises(ValueError, match="auto_evict=true is refused"):
        PreservationRetentionConfig.from_section({"auto_evict": True})


def test_welfare_config_rejects_unknown_action():
    with pytest.raises(ValueError, match="action must be one of"):
        WelfareResponseConfig.from_section({"action": "nuke"})


def test_preservation_config_ships_disabled():
    pc = PreservationConfig.from_section({})
    assert pc.divergence_monitor.enabled is False
    assert pc.welfare_response.enabled is False
    assert pc.welfare_response.action == "pause"
    assert pc.retention.auto_evict is False


# ---------------------------------------------------------------------------
# Batch 1 / A2 — distinct incident-log sink names → distinct files, seq holds
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_incident_logs_distinct_names_write_separate_files(tmp_path):
    """A2 — two IncidentLogs in the SAME dir with distinct names write separate
    files with their own contiguous per-sink seq counters, so the admissibility
    seq-contiguity scan stays clean (the bug: both named 'incidents' interleaved
    one file's seq counter and broke scan_run)."""
    from kaine.experiment.admissibility import scan_run

    incidents_dir = tmp_path / "preservation"
    log_div = IncidentLog(
        enabled=True, path=str(incidents_dir), name="preservation_divergence"
    )
    log_wel = IncidentLog(
        enabled=True, path=str(incidents_dir), name="preservation_welfare"
    )
    await log_div.start()
    await log_wel.start()
    # Interleave writes across the two logs (as the two monitors would).
    for i in range(3):
        await log_div.write({"monitor": "divergence", "i": i})
        await log_wel.write({"monitor": "welfare", "i": i})
    await log_div.stop()
    await log_wel.stop()

    files = sorted(p.name for p in incidents_dir.glob("*.jsonl"))
    # Two DISTINCT files (not a single shared 'incidents-*.jsonl').
    assert any(f.startswith("preservation_divergence-") for f in files)
    assert any(f.startswith("preservation_welfare-") for f in files)
    assert not any(f.startswith("incidents-") for f in files)

    # The run context fixture stamps run_id="prtworun01234567"; scan that run.
    report = scan_run(
        "prtworun01234567",
        root=tmp_path,
        expected_streams=["preservation_divergence", "preservation_welfare"],
    )
    # Each sink's seq is independently contiguous from 0 → no seq gaps.
    assert report.seq_gaps == {}, report.seq_gaps
    assert report.admissible is True


# ---------------------------------------------------------------------------
# Batch 1 / A3 — windowed repeat correctly classifies repeated_distress
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_welfare_repeated_distress_classification(bus, tmp_path):
    """A3 — when a sustained-distress crossing ALSO crosses the windowed-repeat
    threshold, it classifies as 'repeated_distress' (the dead
    `and crossing_reason is None` guard previously made this unreachable)."""
    reg, eid = await _entity(bus, tmp_path)
    fm = _StubFM()
    # repeat_threshold=1 → the single sustained episode immediately crosses the
    # windowed-repeat arm, so the per-sample path must reclassify.
    cfg = WelfareResponseConfig(
        enabled=True, action="notify", distress_threshold=0.5,
        distress_duration_s=1.0, repeat_window_s=300.0, repeat_threshold=1,
        out_root=str(tmp_path / "backups"),
    )
    clock = {"t": 0.0}
    mon = _welfare_monitor(bus, reg, fm, cfg, clock=lambda: clock["t"])
    stop = asyncio.Event()
    # Onset then a later sample beyond duration so observe() fires on the sample.
    await _push_soma_report(bus, 0.9)
    clock["t"] = 0.0
    await mon._poll_once(stop)
    await _push_soma_report(bus, 0.9)
    clock["t"] = 2.0
    await mon._poll_once(stop)
    assert len(fm.calls) == 1
    # The recorded reason is repeated_distress (windowed-repeat reclassification).
    # Inspect the published bus event for the crossing reason.
    welfare_events = [
        e for e in (await _drain(bus, "preservation.out"))
        if e.type == "welfare.protective_action"
    ]
    assert welfare_events, "a protective action was published"
    assert welfare_events[-1].payload.get("reason") == "repeated_distress"
    await eid.shutdown()


async def _drain(bus_obj, stream):
    entries, _ = await bus_obj.read_entries(stream, last_id="0", count=256, block_ms=0)
    return [event for _eid, event in entries]


# ---------------------------------------------------------------------------
# Batch 1 / B2 — protective response acts on repeated gray-zone of any category
# ---------------------------------------------------------------------------


async def _push_gray_zone(bus_obj: AsyncBus, label: str) -> None:
    await bus_obj.publish(
        validate_event(
            source="welfare",
            type="welfare.gray_zone",
            payload={"gray_zone_event": label, "replay_overload_count": 1},
            salience=0.5,
            timestamp=datetime.now(timezone.utc),
        )
    )


@pytest.mark.asyncio
async def test_welfare_acts_on_repeated_gray_zone_non_distress(bus, tmp_path):
    """B2 — repeated welfare.gray_zone events of a NON-distress category
    (replay_overload) cross the windowed-repeat arm and trigger the protective
    response, closing the 'only sustained interoceptive distress' limitation."""
    reg, eid = await _entity(bus, tmp_path)
    fm = _StubFM()
    cfg = WelfareResponseConfig(
        enabled=True, action="pause",
        # Make the sustained-distress arm effectively never fire on its own.
        distress_threshold=0.5, distress_duration_s=9999.0,
        repeat_window_s=300.0, repeat_threshold=3,
        out_root=str(tmp_path / "backups"),
    )
    clock = {"t": 0.0}
    mon = _welfare_monitor(bus, reg, fm, cfg, clock=lambda: clock["t"])
    stop = asyncio.Event()
    # Three replay_overload gray-zone events within the window → crossing.
    for _ in range(3):
        await _push_gray_zone(bus, "replay_overload")
    await mon._poll_once(stop)
    # Preserve happened, then pause (freeze) for the repeated_gray_zone reason.
    assert len(fm.calls) == 1
    assert fm.calls[0]["reason"] == "welfare"
    control = control_state.read_control()
    assert control.frozen is True
    assert control.source == "welfare"
    welfare_events = [
        e for e in (await _drain(bus, "preservation.out"))
        if e.type == "welfare.protective_action"
    ]
    assert welfare_events[-1].payload.get("reason") == "repeated_gray_zone"
    await eid.shutdown()


@pytest.mark.asyncio
async def test_welfare_single_gray_zone_does_not_act(bus, tmp_path):
    """B2 — a single gray-zone event (below the repeat threshold) does NOT
    trigger the protective response."""
    reg, eid = await _entity(bus, tmp_path)
    fm = _StubFM()
    cfg = WelfareResponseConfig(
        enabled=True, action="pause",
        distress_threshold=0.5, distress_duration_s=9999.0,
        repeat_window_s=300.0, repeat_threshold=3,
        out_root=str(tmp_path / "backups"),
    )
    clock = {"t": 0.0}
    mon = _welfare_monitor(bus, reg, fm, cfg, clock=lambda: clock["t"])
    stop = asyncio.Event()
    await _push_gray_zone(bus, "unmaintained_fatigue")
    await mon._poll_once(stop)
    assert fm.calls == []
    assert control_state.read_control().frozen is False
    await eid.shutdown()
