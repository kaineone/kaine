# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Regression tests for the pre-boot correctness batch, Phases 1-2.

Covers, with fake clocks and tmp_path control files only (no real bus, no
sleeps):

- C1  freeze/resume restores the desired perception flags (the freeze path
      saves them; the resume path writes back exactly what was saved).
- C2  stacked freeze sources: a welfare pause survives a Spot recovery
      (Spot pops only its own entry), a pre-existing stack is restored intact,
      and only an operator or welfare stand-down lifts a welfare freeze.
- M3  the welfare ``notify`` rate limit (``_welfare_notify_allowed``).
- C3  the refractory-scaled guard timeout clears speak/think in-flight guards
      without any realization event, and the ``realization_failed`` audit
      event schema is content-free.
- H4  same-signature suppression expires after ``sig_expiry_s``.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from kaine.cycle import control_state
from kaine.cycle.control_state import (
    CycleControl,
    freeze,
    pop_freeze,
    push_freeze,
    read_control,
    stand_down,
    unfreeze,
)
from kaine.cycle.preservation_monitor import _welfare_notify_allowed
from kaine.workspace import report_policy as rp
from kaine.workspace import volition as vt


# --------------------------------------------------------------------------
# Shared test doubles
# --------------------------------------------------------------------------


class FakeClock:
    """A plain float clock the tests advance by hand."""

    def __init__(self, start: float = 0.0) -> None:
        self.t = float(start)

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += float(dt)


class _Evt:
    """Duck-typed workspace event (source, type, payload)."""

    def __init__(
        self,
        source: str,
        type_: str,
        payload: dict | None = None,
        surprise: float = 0.0,
    ):
        self.source = source
        self.type = type_
        self.payload = payload or {}
        self.surprise = float(surprise)


class _Snap:
    """Duck-typed WorkspaceSnapshot: only what the policies touch."""

    def __init__(self, events, scores, inhibited: bool = False):
        self.selected_events = list(events)
        self.salience_scores = dict(scores)
        self.inhibited = inhibited


def _report_policy(clock, **kw):
    """Build the REAL report policy (SelfInitiatedReportPolicy), passing
    only the kwargs its ctor actually accepts."""
    cls = rp.SelfInitiatedReportPolicy
    params = set(inspect.signature(cls.__init__).parameters)
    kwargs: dict = {"clock": clock}
    for key, value in kw.items():
        if key in params:
            kwargs[key] = value
    return cls(**kwargs)


def _mark_realized(policy) -> None:
    """Clear the report policy's in-flight guard if it exposes one."""
    mark = getattr(policy, "mark_realized", None)
    if mark is not None:
        mark()


SPEAK = getattr(vt, "SPEAK", "speak")
THINK = getattr(vt, "THINK", "think")
OWN_SRC = getattr(vt, "OWN_EXTERNAL_SPEECH_SOURCE", "lingua")
OWN_EXT_TYPE = getattr(vt, "OWN_EXTERNAL_SPEECH_TYPE", "lingua.external")
OWN_INT_TYPE = getattr(vt, "OWN_INTERNAL_SPEECH_TYPE", "lingua.internal")


# --------------------------------------------------------------------------
# C1 — freeze/resume restores desired perception flags
# --------------------------------------------------------------------------


def test_c1_freeze_resume_restores_desired_perception_flags(monkeypatch):
    """Freeze suspends perception; resume restores exactly the pre-freeze
    desired perception flags (the freeze-watch loop in cycle ``__main__``)."""
    import kaine.cycle.__main__ as cycle_main

    writes: list[tuple[str, bool]] = []

    # Monkeypatch the desired-perception reader/writers the freeze-watch
    # loop uses (reader = the pre-existing desired flags, writers record).
    monkeypatch.setattr(
        cycle_main,
        "read_desired",
        lambda: SimpleNamespace(audio_live_desired=True, video_live_desired=True),
    )
    monkeypatch.setattr(
        cycle_main,
        "write_desired_audio",
        lambda v: writes.append(("audio", bool(v))),
        raising=False,
    )
    monkeypatch.setattr(
        cycle_main,
        "write_desired_video",
        lambda v: writes.append(("video", bool(v))),
        raising=False,
    )

    class _Cycle:
        def __init__(self) -> None:
            self.is_paused = False

        async def pause(self) -> None:
            self.is_paused = True

        async def resume(self) -> None:
            self.is_paused = False

    class _Control:
        def __init__(self, frozen: bool, reason: str | None = None) -> None:
            self.frozen = frozen
            self.reason = reason

    controls = [_Control(True, "repair")]
    monkeypatch.setattr(cycle_main, "read_control", lambda: controls[0])

    watch = getattr(cycle_main, "_freeze_watch_loop", None)
    if watch is None:
        watch = cycle_main._freeze_watch

    async def _run() -> None:
        stop = asyncio.Event()
        cycle = _Cycle()
        task = asyncio.create_task(watch(cycle, stop))

        # Freeze observed: perception desires are suspended.
        for _ in range(200):
            if writes:
                break
            await asyncio.sleep(0.02)
        assert cycle.is_paused is True
        assert ("audio", False) in writes and ("video", False) in writes

        suspended = list(writes)

        # Resume: the pre-freeze desired flags are written back verbatim.
        controls[0] = _Control(False)
        for _ in range(200):
            if len(writes) > len(suspended):
                break
            await asyncio.sleep(0.02)
        assert cycle.is_paused is False
        restored = writes[len(suspended):]
        assert ("audio", True) in restored
        assert ("video", True) in restored

        stop.set()
        await asyncio.wait_for(task, 5)

    asyncio.run(_run())


# --------------------------------------------------------------------------
# C2 — stacked freeze sources
# --------------------------------------------------------------------------


def test_c2_welfare_pause_survives_spot_recovery(tmp_path: Path):
    """A Spot recovery pops only Spot's own entry; the welfare freeze below
    it stays in force, so the cycle remains frozen."""
    path = tmp_path / "control.json"
    push_freeze(reason="operator repair", path=path, source="operator")
    push_freeze(reason="distress", path=path, source="welfare")
    push_freeze(reason="module fault", path=path, source="spot")

    state = read_control(path)
    assert state.frozen
    assert len(state.stack) == 3
    assert state.source == "spot"  # top of the stack

    # Spot recovers: it pops only its own entry.
    state = pop_freeze(path=path, source="spot")
    assert state.frozen, "welfare freeze must survive a Spot recovery"
    assert [e["source"] for e in state.stack] == ["operator", " welfare".strip()]
    assert state.source == "welfare"
    assert state.reason == "distress"

    # A Spot recovery repeated still never touches the welfare entry.
    state = pop_freeze(path=path, source="spot")
    assert state.frozen
    assert [e["source"] for e in state.stack] == ["operator", "welfare"]

    # On disk it is still frozen.
    on_disk = json.loads(path.read_text())
    assert on_disk["frozen"] is True


def test_c2_spot_recovery_restores_pre_existing_stack(tmp_path: Path):
    """Spot stacking its freeze and popping it restores any pre-existing
    stack byte-for-byte in structure (sources, reasons, timestamps)."""
    path = tmp_path / "control.json"
    base = push_freeze(reason="infra", path=path, source="operator")
    before = [dict(e) for e in base.stack]
    assert len(before) == 1

    push_freeze(reason="escalating", path=path, source="spot")
    assert read_control(path).frozen

    after = pop_freeze(path=path, source="spot")
    assert after.stack == tuple(before)
    assert after.frozen and after.source == "operator"
    assert after.frozen_at == before[-1]["frozen_at"]


def test_c2_only_operator_or_welfare_stand_down_lifts_welfare(tmp_path: Path):
    """A welfare freeze is liftable only by an operator stand-down or an
    explicit welfare stand-down — never by a Spot recovery or a plain pop."""
    path = tmp_path / "control.json"
    push_freeze(reason="distress", path=path, source="welfare")

    # Spot recovery cannot lift it.
    assert pop_freeze(path=path, source="spot").frozen
    # A plain pop of the top would lift it — but the API contract for welfare
    # entries is the stand-down paths; assert an unrelated source stand-down
    # (e.g. spot) does not lift the welfare freeze either.
    assert stand_down(path=path, source="spot").frozen

    # Operator stand-down lifts everything, including the welfare freeze.
    state = unfreeze(path=path)
    assert not state.frozen
    assert state.stack == ()

    # Re-arm welfare; an explicit welfare stand-down lifts it.
    push_freeze(reason="distress", path=path, source="welfare")
    state = stand_down(path=path, source="welfare")
    assert not state.frozen
    assert state.stack == ()

    # An operator stand-down (stand_down(source="operator")) also lifts it.
    push_freeze(reason="distress", path=path, source="welfare")
    push_freeze(reason="r", path=path, source="operator")
    state = stand_down(path=path, source="operator")
    assert state.frozen, "welfare entry must survive an operator stand-down"
    assert [e["source"] for e in state.stack] == ["welfare"]
    state = stand_down(path=path, source="welfare")
    assert not state.frozen


def test_c2_legacy_single_slot_file_promotes_to_stack(tmp_path: Path):
    """A legacy single-slot frozen file is read as a one-entry stack."""
    path = tmp_path / "control.json"
    path.write_text(json.dumps({"frozen": True, "reason": "old"}))
    state = read_control(path)
    assert state.frozen
    assert len(state.stack) == 1
    assert state.stack[0]["source"] == "operator"
    assert state.stack[0]["reason"] == "old"


# --------------------------------------------------------------------------
# M3 — welfare notify rate limit
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "last,now,interval,expected",
    [
        (0.0, 10.0, 30.0, False),  # well inside the window
        (0.0, 29.999, 30.0, False),  # just inside
        (0.0, 30.0, 30.0, True),  # boundary: >= interval allows
        (0.0, 45.0, 30.0, True),  # past the window
        (100.0, 100.0, 0.0, True),  # zero interval never suppresses
    ],
)
def test_m3_welfare_notify_rate_limit(last, now, interval, expected):
    assert _welfare_notify_allowed(last, now, interval) is expected


def test_m3_welfare_notify_bundles_bounded_over_duration():
    """A sustained distress run of duration D yields at most
    ceil(D / min_interval) allowed notify bundles."""
    interval, duration = 30.0, 100.0
    # Production starts with no prior notify, so the first eligible cycle
    # of the run may notify: last_notify_at begins at -inf, not at t=0
    # (which would silently swallow the first bundle).
    last = float("-inf")
    allowed = 0
    t = 0.0
    while t <= duration:
        if _welfare_notify_allowed(last, t, interval):
            allowed += 1
            last = t
        t += 1.0
    assert allowed == 4  # ceil(100/30)
    assert allowed <= -(-int(duration) // int(interval))


# --------------------------------------------------------------------------
# C3 — guard timeout clears in-flight guards without an event;
#      realization_failed is content-free
# --------------------------------------------------------------------------


def test_c3_guard_timeout_clears_speak_in_flight_without_event():
    """A speak guard armed longer than the refractory-scaled timeout is
    cleared on the next call with NO realization event in the coalition —
    a failed realization cannot permanently mute the entity. The guard and
    its timeout live on DefaultActionSelectionPolicy."""
    clock = FakeClock(0.0)
    policy = vt.DefaultActionSelectionPolicy(clock=clock)

    evt_a = _Evt(
        vt.USER_COMMUNICATION_SOURCE, vt.USER_COMMUNICATION_TYPE, {"text": "hello"}
    )
    intents = policy(_Snap([("e1", evt_a)], {"e1": 0.9}))
    assert [i.kind for i in intents] == [SPEAK]
    assert policy.speak_in_flight is True

    timeout = policy._GUARD_TIMEOUT_S

    # Well inside the timeout: no own-output event, so the guard holds and
    # nothing new fires.
    clock.advance(timeout * 0.5)
    evt_b = _Evt("vision", "vision.frame")
    assert policy(_Snap([("e2", evt_b)], {"e2": 0.9})) == []
    assert policy.speak_in_flight is True

    # Past the timeout: the guard is cleared WITHOUT any event, and a fresh
    # user utterance produces a new speak intent.
    clock.advance(timeout * 0.6)  # total > timeout
    evt_c = _Evt(
        vt.USER_COMMUNICATION_SOURCE, vt.USER_COMMUNICATION_TYPE, {"text": "again"}
    )
    intents = policy(_Snap([("e3", evt_c)], {"e3": 0.95}))
    assert [i.kind for i in intents] == [SPEAK]
    assert policy.speak_in_flight is True  # re-armed for the new utterance


def test_c3_guard_timeout_clears_think_in_flight_without_event():
    """The think guard gets the same refractory-scaled timeout, so a stuck
    think cannot permanently mute internal speech either. The think guard
    lives on the drive-biased policy (the default policy is speak-only)."""
    from kaine.workspace.drive_policy import DriveBiasedActionSelectionPolicy

    clock = FakeClock(0.0)
    policy = DriveBiasedActionSelectionPolicy(clock=clock)
    timeout = policy._GUARD_TIMEOUT_S

    # A think guard left armed by a failed realization (no own-output event
    # ever cleared it).
    policy._think_in_flight = True
    policy._think_armed_at = clock()
    assert policy.think_in_flight is True

    # Well inside the timeout the guard holds with no event in the coalition.
    clock.advance(timeout * 0.5)
    policy(_Snap([], {}))
    assert policy.think_in_flight is True

    # Past the timeout it is cleared WITHOUT any realization event.
    clock.advance(timeout * 0.6)
    policy(_Snap([], {}))
    assert policy.think_in_flight is False


def test_c3_volition_guard_timeout_constant_is_refractory_scaled():
    """The speak guard timeout is ~6x the 8s report speak refractory; the
    constant lives on the action-selection policy that owns the guards."""
    assert vt.DefaultActionSelectionPolicy._GUARD_TIMEOUT_S == pytest.approx(48.0)


def test_c3_volition_in_flight_guard_and_realization():
    """The action-selection policy arms one speak at a time and clears on
    the entity's own conscious external speech (the ordinary realization
    path)."""
    clock = FakeClock(0.0)
    policy = vt.DefaultActionSelectionPolicy(clock=clock)
    user_evt = _Evt(
        vt.USER_COMMUNICATION_SOURCE, vt.USER_COMMUNICATION_TYPE, {"text": "hi"}
    )
    snap = _Snap([("e1", user_evt)], {"e1": 0.5})
    intents = policy(snap)
    assert [i.kind for i in intents] == [vt.SPEAK]
    assert policy.speak_in_flight is True

    # While in flight, a second user utterance does not stack a speak.
    user_evt2 = _Evt(
        vt.USER_COMMUNICATION_SOURCE, vt.USER_COMMUNICATION_TYPE, {"text": "yo"}
    )
    assert policy(_Snap([("e2", user_evt2)], {"e2": 0.5})) == []

    # The entity's own external speech realizes the intent and clears it.
    own = _Evt(vt.OWN_EXTERNAL_SPEECH_SOURCE, OWN_EXT_TYPE, {"text": "..."})
    policy(_Snap([("e3", own)], {"e3": 0.5}))
    assert policy.speak_in_flight is False
    user_evt3 = _Evt(
        vt.USER_COMMUNICATION_SOURCE, vt.USER_COMMUNICATION_TYPE, {"text": "??"}
    )
    assert [i.kind for i in policy(_Snap([("e4", user_evt3)], {"e4": 0.5}))] == [
        vt.SPEAK
    ]


def test_c3_realization_failed_event_is_content_free():
    """The realization_failed audit event carries mode and reason class
    ONLY — never the text, the prompt, or any payload headed for
    generation."""
    try:
        from kaine.modules.lingua.module import Lingua
    except ImportError:  # the class lives directly on the package
        from kaine.modules.lingua import Lingua

    secret = "SECRET-PROMPT-CONTENT never to be audited"

    mod = object.__new__(Lingua)  # bypass heavy __init__
    mod.name = "lingua"
    mod._gen_task = None  # no held generation on this bare instance
    published: list[tuple[str, dict]] = []

    async def fake_publish(topic, payload):
        published.append((topic, dict(payload)))

    async def failing_speak(text):
        raise RuntimeError("boom " + text)

    mod._publish = fake_publish
    mod.speak = failing_speak
    mod.think = failing_speak

    asyncio.run(mod._realize_intent(vt.SPEAK, secret))

    assert len(published) == 1
    topic, payload = published[0]
    assert topic == "lingua.internal"
    assert payload["type"] == "realization_failed"
    assert payload["mode"] == vt.SPEAK
    assert payload["reason_class"] == "RuntimeError"
    # Schema is content-free: exactly these keys, nothing else.
    assert set(payload) == {"type", "mode", "reason_class"}
    assert secret not in json.dumps(payload)


# --------------------------------------------------------------------------
# H4 — same-signature suppression expires after sig_expiry_s
# --------------------------------------------------------------------------


def test_h4_same_signature_suppression_expires_after_sig_expiry_s():
    """Repeating the same (source, type) signature is suppressed until
    sig_expiry_s elapses, after which the same signature may report again."""
    clock = FakeClock(0.0)
    policy = rp.SelfInitiatedReportPolicy(
        clock=clock,
        report_threshold=0.6,
        sig_expiry_s=30.0,
        speak_refractory_s=0.0,
    )

    evt = _Evt("audition", "audition.transcription", {"text": "x"}, surprise=0.9)
    snap = _Snap([("e1", evt)], {"e1": 0.9})

    assert [i.kind for i in policy(snap)] == [SPEAK]  # first report fires
    policy.mark_realized()  # utterance completed; guard clear

    # Immediately again, same signature: suppressed (novelty guard).
    assert all(i.kind != "speak" for i in policy(snap))

    # 29s later — still inside sig_expiry_s: suppressed.
    clock.advance(29.0)
    assert all(i.kind != "speak" for i in policy(snap))

    # At/after 30s the signature has expired and the same content may
    # report again.
    clock.advance(1.0)
    intents = policy(snap)
    assert [i.kind for i in intents] == [SPEAK]
    policy.mark_realized()

    # A different signature is never blocked by the old one.
    clock.advance(1.0)
    evt2 = _Evt("vision", "vision.frame", surprise=0.9)
    assert [
        i.kind for i in policy(_Snap([("e2", evt2)], {"e2": 0.9}))
    ] == [SPEAK]


def test_h4_no_sig_expiry_means_permanent_novelty_suppression():
    """Without sig_expiry_s the same signature never repeats (the
    pre-existing behavior is unchanged)."""
    clock = FakeClock(0.0)
    policy = rp.SelfInitiatedReportPolicy(
        clock=clock, report_threshold=0.6, speak_refractory_s=0.0
    )
    evt = _Evt("audition", "audition.transcription", {"text": "x"}, surprise=0.9)
    snap = _Snap([("e1", evt)], {"e1": 0.9})

    assert [i.kind for i in policy(snap)] == [SPEAK]
    policy.mark_realized()
    clock.advance(10_000.0)
    assert all(i.kind != "speak" for i in policy(snap))
