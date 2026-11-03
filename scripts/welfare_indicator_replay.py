#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Offline replay of the welfare net's response to the A.4 indicators.

Runs archived research-event records (``affect.state`` and the sleep events,
and for the forward method the recorded perceptual reports) through the real
welfare monitor (``WelfareProtectiveMonitor``: the evaluator and the
three-stage state machine) with no entity, no bus server and no GPU. The
monitor runs on an in-memory bus, simulated clocks and a scratch control
file; a preservation is only recorded, never made.

A record replay cannot show what follows a reset it did not apply: after a
virtual rest, the recorded trajectory is the one in which no rest happened at
that moment. So the tool offers two methods and names the one it used:

``recorded-rest``
    The developmental welfare rest is the state cycle's next rest brought
    forward. The next recorded rest after the response's request, which did
    reset, stands as the response's rest, and the fresh span is read from the
    recorded trajectory after it. The rest's timing shifts; the reset is real.
    The rest-start and rest-completion bounds are not applied, because the
    stand-in rest starts when the recording's next rest did.

``forward``
    The real affect module (the current code, built from the configuration)
    runs over the recorded perceptual reports from the start of the run. When
    the net requests a rest, a rest of ``developmental_rest_s`` begins at once:
    perception is skipped for its length and it ends with the affective reset.
    The module then runs forward on the recorded reports after it. Recorded
    rests elsewhere are applied as they happened.

Records that predate the drive threshold flags (``drive_above``) get them from
the recorded drive levels and the configured thresholds; records without
crossing-end counts (``drive_ends``) leave the uncontrolled indicators
unevaluable. The output says so. Everything printed is content-free: times in
awake hours, fixed indicator names, counts and labels.

Encrypted records are read with the state key the cycle uses
(``KAINE_STATE_KEY`` or the OS keyring); lines that cannot be read are counted.

Usage::

    python scripts/welfare_indicator_replay.py --method recorded-rest \\
        --label testboot-2026-10-18a <research_events-*.jsonl ...>
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from kaine.bus.schema import Event, module_stream, validate_event  # noqa: E402

METHODS = ("recorded-rest", "forward")

#: Record kinds the forward method feeds the affect module, by the stream it reads.
_PERCEPTUAL_STREAMS = {
    "vision.report": "vision.out",
    "audition.perception": "audition.out",
    "audition.emotion": "audition.out",
    "interoception.report": "interoception.out",
    "sequence.report": "sequence.out",
    "episodic_memory.recall": "episodic_memory.out",
}
_META_FIELDS = {"event_type", "source", "run_id", "seq", "ts", "mono_ts", "tick_index", "entry_id", "incident_id"}

#: Polls of the monitor per second of record time (the shipped poll interval is 1 s).
_POLL_EVERY_S = 5.0


# --- reading the records ---------------------------------------------------------


def _parse_ts(value: Any) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        ts = datetime.fromisoformat(value)
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.timestamp()


@dataclass
class Trace:
    """One run's records, in time order."""

    run_index: int
    affect: list[tuple[float, dict[str, Any]]] = field(default_factory=list)
    sleeps: list[tuple[float, float | None, str | None]] = field(default_factory=list)
    perceptual: list[tuple[float, str, str, dict[str, Any]]] = field(default_factory=list)
    flags_derived: int = 0
    ends_present: int = 0

    @property
    def start(self) -> float:
        times = [t for t, _ in self.affect] + [t for t, *_ in self.perceptual]
        return min(times) if times else 0.0

    @property
    def end(self) -> float:
        times = [t for t, _ in self.affect] + [t for t, *_ in self.perceptual]
        return max(times) if times else 0.0


def _decrypt_lines(paths: Iterable[Path]) -> tuple[list[dict[str, Any]], int]:
    from kaine.security.crypto import (
        CryptoConfig,
        CryptoConfigError,
        StateEncryptor,
        get_state_encryptor,
        install_from_section,
        set_state_encryptor,
    )

    try:
        install_from_section({"enabled": True})
    except CryptoConfigError:
        set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))
    encryptor = get_state_encryptor()
    records: list[dict[str, Any]] = []
    unreadable = 0
    for path in paths:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                if not raw.strip():
                    continue
                try:
                    record = json.loads(encryptor.decrypt_text(raw.rstrip("\n")))
                except Exception:
                    unreadable += 1
                    continue
                if isinstance(record, dict):
                    records.append(record)
    return records, unreadable


def _thresholds(config: dict[str, Any]) -> dict[str, float]:
    from kaine.modules.affect.drives import DriveSet

    drives = DriveSet.from_config(((config.get("affect") or {}).get("drives")))
    return {d.name: float(d.threshold) for d in drives.all()}


def build_traces(
    records: Iterable[dict[str, Any]], thresholds: dict[str, float], *, with_perceptual: bool
) -> list[Trace]:
    """Group records by run and keep what the replay reads."""
    by_run: dict[str, Trace] = {}
    open_sleep: dict[str, tuple[float, str | None]] = {}
    for record in records:
        kind = record.get("event_type")
        ts = _parse_ts(record.get("ts"))
        if ts is None or not isinstance(kind, str):
            continue
        run = str(record.get("run_id") or "")
        trace = by_run.get(run)
        if trace is None:
            trace = by_run[run] = Trace(run_index=len(by_run))
        if kind == "affect.state":
            state = record.get("state") if isinstance(record.get("state"), dict) else {}
            payload: dict[str, Any] = {"state": dict(state)}
            above = record.get("drive_above")
            if isinstance(above, dict):
                payload["drive_above"] = dict(above)
            else:
                levels = record.get("drives") if isinstance(record.get("drives"), dict) else {}
                derived = {
                    name: bool(float(level) >= thresholds[name])
                    for name, level in levels.items()
                    if name in thresholds and isinstance(level, (int, float)) and not isinstance(level, bool)
                }
                if derived:
                    payload["drive_above"] = derived
                    trace.flags_derived += 1
            ends = record.get("drive_ends")
            if isinstance(ends, dict):
                payload["drive_ends"] = ends
                trace.ends_present += 1
            trace.affect.append((ts, payload))
        elif kind == "sleep.sleep.started":
            open_sleep[run] = (ts, record.get("trigger") if isinstance(record.get("trigger"), str) else None)
        elif kind == "sleep.sleep.completed":
            began = open_sleep.pop(run, None)
            if began is not None:
                trace.sleeps.append((began[0], ts, began[1]))
        elif with_perceptual and (kind in _PERCEPTUAL_STREAMS or kind.startswith("intent.")):
            stream = _PERCEPTUAL_STREAMS.get(kind, "action_selection.out")
            payload = {k: v for k, v in record.items() if k not in _META_FIELDS}
            source = record.get("source") if isinstance(record.get("source"), str) else kind.split(".")[0]
            trace.perceptual.append((ts, stream, kind, {"source": source, **payload}))
    for run, (began, trigger) in open_sleep.items():
        by_run[run].sleeps.append((began, None, trigger))
    traces = [t for t in by_run.values() if t.affect or t.perceptual]
    for trace in traces:
        trace.affect.sort(key=lambda item: item[0])
        trace.sleeps.sort(key=lambda item: item[0])
        trace.perceptual.sort(key=lambda item: item[0])
    return traces


# --- the in-memory bus and the monitor --------------------------------------------


class ReplayBus:
    """A minimal in-memory stream bus with the reads the monitor makes."""

    def __init__(self) -> None:
        self.streams: dict[str, list[tuple[int, Event]]] = {}
        self._seq = 0

    async def publish(self, event: Event) -> str:
        self._seq += 1
        self.streams.setdefault(module_stream(event.source), []).append((self._seq, event))
        return f"{self._seq}-0"

    async def read_entries(self, stream: str, last_id: str = "0", count: int = 100, block_ms: int = 0):
        after = int(str(last_id).split("-")[0] or 0)
        entries = [(f"{n}-0", e) for n, e in self.streams.get(stream, []) if n > after][:count]
        return entries, (entries[-1][0] if entries else None)

    async def last_entry_id(self, stream: str) -> str:
        entries = self.streams.get(stream)
        return f"{entries[-1][0]}-0" if entries else "0-0"


class _Clock:
    def __init__(self, value: float = 0.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


class _SleepStandIn:
    """The sleep module as the monitor sees it: running, with its rest length."""

    name = "sleep"

    def __init__(self, developmental_rest_s: float) -> None:
        self.developmental_rest_s = developmental_rest_s

    def welfare_rest_ready(self) -> bool:
        return True


class _Registry:
    def __init__(self, sleep: _SleepStandIn) -> None:
        self._sleep = sleep

    def __contains__(self, name: object) -> bool:
        return name == "sleep"

    def get(self, name: str):
        if name != "sleep":
            raise KeyError(name)
        return self._sleep


class _RecordingPreserver:
    """Records that the net would preserve; nothing is written."""

    def __init__(self) -> None:
        self.reasons: list[str] = []

    async def preserve_live(self, registry, *, reason, label, **_kwargs):
        from kaine.lifecycle.preservation import PreservationResult

        self.reasons.append(reason)
        return PreservationResult(
            ok=True, preservation_id="replay", snapshot_id="replay", reason=reason,
            label=label, run_id="replay", world_model_captured=False,
        )


@dataclass
class ReplayResult:
    method: str
    run_index: int
    awake_hours: float
    affect_states: int
    first_crossing_awake_h: float | None = None
    first_crossing_indicators: list[str] = field(default_factory=list)
    rest_start_awake_h: float | None = None
    rest_end_awake_h: float | None = None
    rest_kind: str | None = None
    second_stage_awake_h: float | None = None
    second_stage_reason: str | None = None
    rearmed: int = 0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {k: (round(v, 3) if isinstance(v, float) else v) for k, v in self.__dict__.items()}


class _Driver:
    """Runs the real welfare monitor over one trace on simulated clocks."""

    def __init__(self, *, params, config, developmental_rest_s: float, developing: bool, scratch: Path):
        from kaine.cycle import control_state
        from kaine.cycle.incident_log import IncidentLog
        from kaine.cycle.preservation_monitor import WelfareProtectiveMonitor
        from kaine.cycle.unfrozen_clock import UnfrozenClock

        self.bus = ReplayBus()
        self.u = _Clock(0.0)
        self.w = _Clock(0.0)
        self.preserver = _RecordingPreserver()
        self.records: list[tuple[float, dict[str, Any]]] = []
        self.awake_s = 0.0
        control_path = scratch / "control.json"
        self.monitor = WelfareProtectiveMonitor(
            registry=_Registry(_SleepStandIn(developmental_rest_s)),
            fork_manager=self.preserver,
            config=config,
            bus=self.bus,
            incident_log=IncidentLog(enabled=False, path=str(scratch / "unused")),
            clock=self.u,
            unfrozen_clock=UnfrozenClock(
                lambda: control_state.read_frozen_state(path=control_path),
                unknown_counts_as="unfrozen",
                monotonic=self.u,
            ),
            indicator_params=params,
            is_developing=lambda: developing,
            wall_time=self.w,
        )
        # The freeze goes to the scratch control file, never a real one.
        self.monitor._place_welfare_freeze = lambda reason: self._freeze(control_path, reason)
        self.monitor._read_holders = lambda: control_state.read_holder_sources(path=control_path)
        original = self.monitor._record

        async def capture(record: dict[str, Any], *, event_type: str) -> None:
            self.records.append((self.awake_s, dict(record)))
            await original(record, event_type=event_type)

        self.monitor._record = capture
        self.stop = asyncio.Event()

    @staticmethod
    def _freeze(path: Path, reason: str):
        from kaine.cycle import control_state
        from kaine.cycle.preservation_monitor import _FreezeOutcome

        control_state.freeze(reason=reason, path=path, source="welfare")
        return _FreezeOutcome(placed=True)

    def _ts(self, t: float) -> datetime:
        return datetime.fromtimestamp(t, timezone.utc)

    async def publish(self, source: str, type_: str, payload: dict[str, Any], t: float) -> None:
        await self.bus.publish(
            validate_event(source=source, type=type_, payload=payload, salience=0.1, timestamp=self._ts(t))
        )

    async def poll(self, t: float, t0: float) -> None:
        self.w.value = t
        self.u.value = t - t0
        await self.monitor._poll_once(self.stop)

    def pending_request(self) -> str | None:
        request = self.monitor._ind_request
        if request is None or request.started or request.standing:
            return None
        return request.request_id

    def summarize(self, result: ReplayResult) -> None:
        for awake, record in self.records:
            transition = record.get("transition")
            if transition == "indicator_rest_requested" and result.first_crossing_awake_h is None:
                result.first_crossing_awake_h = awake / 3600.0
                result.first_crossing_indicators = list(record.get("indicators") or [])
            elif transition == "indicator_rearmed":
                result.rearmed += 1
            elif str(transition).startswith("protective_action") and result.second_stage_awake_h is None:
                result.second_stage_awake_h = awake / 3600.0
                result.second_stage_reason = record.get("reason")


def _replay_config(method: str):
    from kaine.cycle.preservation_monitor import WelfareIndicatorConfig, WelfareResponseConfig

    indicators = WelfareIndicatorConfig()
    if method == "recorded-rest":
        # The stand-in rest begins when the recording's next rest did.
        indicators = WelfareIndicatorConfig(
            rest_start_timeout_s=1e12,
            rest_complete_developmental_s=1e12,
            rest_complete_matured_s=1e12,
        )
    return WelfareResponseConfig(enabled=True, action="pause", indicators=indicators)


async def replay_recorded_rest(trace: Trace, *, params, developmental_rest_s: float, developing: bool) -> ReplayResult:
    result = ReplayResult("recorded-rest", trace.run_index, 0.0, len(trace.affect))
    with tempfile.TemporaryDirectory(prefix="kaine-replay-") as tmp:
        driver = _Driver(
            params=params, config=_replay_config("recorded-rest"),
            developmental_rest_s=developmental_rest_s, developing=developing, scratch=Path(tmp),
        )
        t0 = trace.start
        events: list[tuple[float, int, str, Any]] = []
        for t, payload in trace.affect:
            events.append((t, 1, "affect", payload))
        for began, ended, trigger in trace.sleeps:
            events.append((began, 0, "sleep_start", trigger))
            if ended is not None:
                events.append((ended, 0, "sleep_end", trigger))
        events.sort(key=lambda e: (e[0], e[1]))
        await driver.poll(t0, t0)
        next_poll = t0 + _POLL_EVERY_S
        last_t = t0
        asleep = False
        standing: str | None = None
        for t, _order, kind, data in events:
            while t >= next_poll:
                await driver.poll(next_poll, t0)
                next_poll += _POLL_EVERY_S
                if driver.monitor._acted:
                    break
            if driver.monitor._acted:
                break
            if not asleep:
                driver.awake_s += max(0.0, t - last_t)
            last_t = t
            if kind == "affect":
                await driver.publish("affect", "affect.state", data, t)
            elif kind == "sleep_start":
                asleep = True
                request_id = driver.pending_request()
                if request_id is not None:
                    standing = request_id
                    result.rest_start_awake_h = driver.awake_s / 3600.0
                    result.rest_kind = f"the next recorded rest (trigger {data or 'unrecorded'})"
                    await driver.publish("sleep", "sleep.sleep.started", {"trigger": "welfare_rest"}, t)
                    await driver.publish(
                        "sleep", "sleep.rest_request",
                        {"accepted": True, "reason": "accepted", "origin": "welfare", "proposal_id": request_id}, t,
                    )
                else:
                    await driver.publish("sleep", "sleep.sleep.started", {"trigger": data or "state_cycle"}, t)
            elif kind == "sleep_end":
                asleep = False
                if standing is not None:
                    result.rest_end_awake_h = driver.awake_s / 3600.0
                    await driver.publish("sleep", "sleep.sleep.completed", {"trigger": "welfare_rest"}, t)
                    standing = None
                else:
                    await driver.publish("sleep", "sleep.sleep.completed", {"trigger": data or "state_cycle"}, t)
        if not driver.monitor._acted:
            await driver.poll(max(next_poll, last_t), t0)
        result.awake_hours = driver.awake_s / 3600.0
        driver.summarize(result)
        if result.first_crossing_awake_h is not None and result.rest_start_awake_h is None:
            result.notes.append("no recorded rest followed the first crossing; the second stage is not evaluable")
    return result


class _SimClock:
    def __init__(self) -> None:
        self.value = 0.0
        self.scale = 1.0

    def now(self) -> float:
        return self.value


class _CaptureBus:
    def __init__(self) -> None:
        self.states: list[dict[str, Any]] = []
        self._seq = 0

    async def publish(self, event: Event) -> str:
        self._seq += 1
        if event.type == "affect.state":
            self.states.append(dict(event.payload or {}))
        return f"{self._seq}-0"


async def replay_forward(
    trace: Trace, *, params, developmental_rest_s: float, developing: bool, affect_section: dict[str, Any]
) -> ReplayResult:
    from kaine.boot.factories.affect import make_affect

    result = ReplayResult("forward", trace.run_index, 0.0, 0)
    capture = _CaptureBus()
    clock = _SimClock()
    affect = make_affect(capture, affect_section, entity_clock=clock)
    period = float(params.publish_interval_s)
    with tempfile.TemporaryDirectory(prefix="kaine-replay-") as tmp:
        driver = _Driver(
            params=params, config=_replay_config("forward"),
            developmental_rest_s=developmental_rest_s, developing=developing, scratch=Path(tmp),
        )
        t0 = trace.start
        clock.value = 0.0
        affect._last_tick_at = 0.0
        events: list[tuple[float, int, str, Any]] = []
        for item in trace.perceptual:
            events.append((item[0], 1, "input", item))
        for began, ended, trigger in trace.sleeps:
            events.append((began, 0, "sleep_start", trigger))
            if ended is not None:
                events.append((ended, 0, "sleep_end", trigger))
        events.sort(key=lambda e: (e[0], e[1]))
        await driver.poll(t0, t0)
        next_poll = t0 + _POLL_EVERY_S
        next_tick = t0 + period
        last_t = t0
        asleep = False
        virtual_until: float | None = None

        async def advance_to(t: float) -> None:
            nonlocal next_tick, next_poll, last_t, virtual_until, asleep
            while True:
                step = min(next_tick, next_poll, t)
                awake_now = not asleep and virtual_until is None
                if awake_now:
                    driver.awake_s += max(0.0, step - last_t)
                last_t = step
                clock.value = step - t0
                if virtual_until is not None and step >= virtual_until:
                    # The virtual rest ends with the affective reset.
                    await affect.affective_reset()
                    virtual_until = None
                    result.rest_end_awake_h = driver.awake_s / 3600.0
                    await driver.publish("sleep", "sleep.sleep.completed", {"trigger": "welfare_rest"}, step)
                if step == next_tick:
                    if not asleep and virtual_until is None:
                        await affect._tick(own_update=True)
                        await affect._maybe_publish_state()
                        while capture.states:
                            await driver.publish("affect", "affect.state", capture.states.pop(0), step)
                            result.affect_states += 1
                    next_tick += period
                if step == next_poll:
                    await driver.poll(step, t0)
                    next_poll += _POLL_EVERY_S
                    request_id = driver.pending_request()
                    if request_id is not None and virtual_until is None and not asleep:
                        # The net's rest begins at once.
                        virtual_until = step + developmental_rest_s
                        result.rest_start_awake_h = driver.awake_s / 3600.0
                        result.rest_kind = f"virtual rest of {developmental_rest_s:.0f} s with the affective reset"
                        await driver.publish("sleep", "sleep.sleep.started", {"trigger": "welfare_rest"}, step)
                        await driver.publish(
                            "sleep", "sleep.rest_request",
                            {"accepted": True, "reason": "accepted", "origin": "welfare", "proposal_id": request_id},
                            step,
                        )
                if driver.monitor._acted or step >= t:
                    return

        for t, _order, kind, data in events:
            await advance_to(t)
            if driver.monitor._acted:
                break
            if kind == "input" and not asleep and virtual_until is None:
                _ts, stream, type_, payload = data
                source = payload.get("source", type_.split(".")[0])
                body = {k: v for k, v in payload.items() if k != "source"}
                await affect._handle_peer_event(
                    stream, Event(source=source, type=type_, payload=body, salience=0.1, timestamp=driver._ts(t))
                )
            elif kind == "sleep_start" and virtual_until is None:
                asleep = True
                await driver.publish("sleep", "sleep.sleep.started", {"trigger": data or "state_cycle"}, t)
            elif kind == "sleep_end" and asleep:
                asleep = False
                await affect.affective_reset()
                await driver.publish("sleep", "sleep.sleep.completed", {"trigger": data or "state_cycle"}, t)
        if not driver.monitor._acted:
            await advance_to(last_t + _POLL_EVERY_S)
        result.awake_hours = driver.awake_s / 3600.0
        driver.summarize(result)
        result.notes.append(
            "the affect module is the current code run on the recorded reports; workspace "
            "accesses and intent targets are not in the research log, so concern re-entry is "
            "not reproduced and every intent counts as engagement"
        )
    return result


def _parameters(config: dict[str, Any]):
    from kaine.boot.factories.affect import affect_indicator_parameters
    from kaine.cycle.preservation_monitor import WelfareIndicatorConfig
    from kaine.lifecycle.welfare_indicators import IndicatorParams

    affect = affect_indicator_parameters(config.get("affect") or {})
    bars = WelfareIndicatorConfig.from_section(
        ((config.get("preservation") or {}).get("welfare_response") or {}).get("indicators") or {}
    )
    return IndicatorParams(
        span_s=affect["learning_progress_span_s"],
        min_span_s=affect["goal_stall_s"],
        valence_bar=affect["regulation_set_point"],
        publish_interval_s=affect["publish_interval_s"],
        share_bar=bars.share_bar,
        posterior_bar=bars.posterior_bar,
    )


def _load_config(extra: Path | None) -> dict[str, Any]:
    from kaine.config import _load_merged_config

    operator = extra if extra is not None else Path("/nonexistent/kaine.operator.toml")
    return _load_merged_config(REPO / "config" / "kaine.toml", operator)


async def run(paths: list[Path], *, method: str, label: str, config_path: Path | None, matured: bool) -> dict[str, Any]:
    config = _load_config(config_path)
    params = _parameters(config)
    developmental_rest_s = float((config.get("sleep") or {}).get("developmental_rest_s", 1410.0))
    records, unreadable = _decrypt_lines(paths)
    traces = build_traces(records, _thresholds(config), with_perceptual=(method == "forward"))
    out: dict[str, Any] = {
        "label": label,
        "method": method,
        "unreadable_lines": unreadable,
        "runs": [],
        "parameters": {
            "span_s": params.span_s, "min_span_s": params.min_span_s,
            "share_bar": params.share_bar, "posterior_bar": params.posterior_bar,
            "valence_bar": params.valence_bar, "developmental_rest_s": developmental_rest_s,
        },
    }
    for trace in traces:
        if method == "recorded-rest":
            result = await replay_recorded_rest(
                trace, params=params, developmental_rest_s=developmental_rest_s, developing=not matured
            )
        else:
            result = await replay_forward(
                trace, params=params, developmental_rest_s=developmental_rest_s,
                developing=not matured, affect_section=config.get("affect") or {},
            )
        if trace.flags_derived:
            result.notes.append(
                f"{trace.flags_derived} affect states predate drive_above; the flags come "
                "from the recorded drive levels and the configured thresholds"
            )
        if trace.ends_present == 0:
            result.notes.append("no crossing-end counts recorded: the uncontrolled indicators are not evaluable")
        out["runs"].append(result.to_dict())
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("paths", nargs="+", type=Path, help="research-event JSONL files of one boot")
    parser.add_argument("--method", choices=METHODS, required=True)
    parser.add_argument("--label", default="replay", help="a content-free name for the boot")
    parser.add_argument("--config", type=Path, default=None, help="an operator overlay to layer on the shipped config")
    parser.add_argument("--matured", action="store_true", help="the boot ran after maturation")
    args = parser.parse_args(argv)
    result = asyncio.run(
        run(list(args.paths), method=args.method, label=args.label, config_path=args.config, matured=args.matured)
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
