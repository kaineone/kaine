# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import pytest

from kaine.bus.schema import Event
from kaine.dashboard.app import create_app
from kaine.dashboard.bridge import BusBridge
from kaine.dashboard.config import DashboardConfig
from kaine.dashboard.conversation import ConversationState
from kaine.dashboard.health.blocks import welfare_block
from kaine.dashboard.privacy import PrivacyFilter
from kaine.evaluation.observers import welfare_observer
from kaine.experiment.welfare_counts import (
    AFFECT_DEFICIT_DRIVES,
    AFFECT_INTEREST_DRIVES,
    AFFECT_WELFARE_KEYS,
    affect_welfare_from_jsonl,
)
from kaine.lifecycle.welfare_signal import ADVISORY_RESET


def _event(source, type_, payload):
    return Event(
        source=source,
        type=type_,
        payload=payload,
        salience=0.1,
        timestamp=datetime.now(timezone.utc),
    )


def _write_jsonl(path: Path, lines: list[dict[str, Any]]) -> None:
    path.write_text(
        "\n".join(json.dumps(line, default=str) for line in lines) + "\n",
        encoding="utf-8",
    )


def _valid_record(**overrides):
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "record": "affect_welfare",
    }
    for key in AFFECT_WELFARE_KEYS:
        record[key] = 1.0
    record.update(overrides)
    return record


def test_affect_drive_constants_match_observer():
    assert AFFECT_DEFICIT_DRIVES == welfare_observer._DEFICIT_DRIVES
    assert AFFECT_INTEREST_DRIVES == welfare_observer._INTEREST_DRIVES


def test_affect_welfare_newest_record_wins(tmp_path: Path):
    logs = tmp_path / "logs"
    welfare_dir = logs / "welfare"
    welfare_dir.mkdir(parents=True)
    _write_jsonl(
        welfare_dir / "welfare-1.jsonl",
        [_valid_record(awake_seconds=10.0), _valid_record(awake_seconds=20.0)],
    )
    result = affect_welfare_from_jsonl(logs)
    assert result is not None
    assert result["awake_seconds"] == 20.0
    assert result["current_run"] is True


def test_affect_welfare_reset_after_record_marks_not_current_run(tmp_path: Path):
    logs = tmp_path / "logs"
    welfare_dir = logs / "welfare"
    welfare_dir.mkdir(parents=True)
    _write_jsonl(
        welfare_dir / "welfare-1.jsonl",
        [_valid_record(awake_seconds=10.0), {"advisory": ADVISORY_RESET}],
    )
    result = affect_welfare_from_jsonl(logs)
    assert result is not None
    assert result["awake_seconds"] == 10.0
    assert result["current_run"] is False


def test_affect_welfare_reset_before_record_marks_current_run(tmp_path: Path):
    logs = tmp_path / "logs"
    welfare_dir = logs / "welfare"
    welfare_dir.mkdir(parents=True)
    _write_jsonl(
        welfare_dir / "welfare-1.jsonl",
        [{"advisory": ADVISORY_RESET}, _valid_record(awake_seconds=10.0)],
    )
    result = affect_welfare_from_jsonl(logs)
    assert result is not None
    assert result["current_run"] is True


def test_affect_welfare_drops_extra_fields_and_returns_all_keys(tmp_path: Path):
    logs = tmp_path / "logs"
    welfare_dir = logs / "welfare"
    welfare_dir.mkdir(parents=True)
    _write_jsonl(
        welfare_dir / "welfare-1.jsonl",
        [_valid_record(text="x")],
    )
    result = affect_welfare_from_jsonl(logs)
    assert result is not None
    assert "text" not in result
    assert "record" not in result
    for key in AFFECT_WELFARE_KEYS:
        assert key in result
    assert result["ts"] is not None


def test_affect_welfare_non_finite_values_become_none(tmp_path: Path):
    logs = tmp_path / "logs"
    welfare_dir = logs / "welfare"
    welfare_dir.mkdir(parents=True)
    _write_jsonl(
        welfare_dir / "welfare-1.jsonl",
        [
            _valid_record(
                awake_seconds=True,
                negative_valence_bar="not a number",
                negative_valence_share=float("nan"),
            )
        ],
    )
    result = affect_welfare_from_jsonl(logs)
    assert result is not None
    assert result["awake_seconds"] is None
    assert result["negative_valence_bar"] is None
    assert result["negative_valence_share"] is None
    assert result["curiosity_interest_share"] == 1.0


def test_affect_welfare_newer_file_wins(tmp_path: Path):
    logs = tmp_path / "logs"
    welfare_dir = logs / "welfare"
    welfare_dir.mkdir(parents=True)
    _write_jsonl(
        welfare_dir / "welfare-2026-01-01.jsonl",
        [_valid_record(awake_seconds=10.0)],
    )
    _write_jsonl(
        welfare_dir / "welfare-2026-01-02.jsonl",
        [_valid_record(awake_seconds=20.0)],
    )
    result = affect_welfare_from_jsonl(logs)
    assert result is not None
    assert result["awake_seconds"] == 20.0


def test_affect_welfare_missing_directory_returns_none(tmp_path: Path):
    assert affect_welfare_from_jsonl(tmp_path / "no_such_dir") is None


def test_affect_welfare_missing_record_returns_none(tmp_path: Path):
    logs = tmp_path / "logs"
    welfare_dir = logs / "welfare"
    welfare_dir.mkdir(parents=True)
    _write_jsonl(
        welfare_dir / "welfare-1.jsonl",
        [{"advisory": ADVISORY_RESET}],
    )
    assert affect_welfare_from_jsonl(logs) is None


def test_welfare_block_includes_affect_welfare(tmp_path: Path):
    logs = tmp_path / "logs"
    welfare_dir = logs / "welfare"
    welfare_dir.mkdir(parents=True)
    _write_jsonl(
        welfare_dir / "welfare-1.jsonl",
        [_valid_record(awake_seconds=55.0)],
    )
    result = welfare_block(logs)
    assert result["source"] == "jsonl"
    assert result["affect_welfare"] is not None
    assert result["affect_welfare"]["awake_seconds"] == 55.0


def test_welfare_block_without_rollup_has_none_affect_welfare(tmp_path: Path):
    result = welfare_block(tmp_path / "missing")
    assert result["source"] == "none"
    assert result["affect_welfare"] is None


def _sleep_event(type_, payload):
    return _event("sleep", type_, payload)


def test_developmental_rest_details():
    state = ConversationState()
    state.observe(
        _sleep_event(
            "sleep.sleep.started",
            {"trigger": "developmental_rest", "started_at": 1000.0},
        )
    )
    state.observe(
        _sleep_event(
            "sleep.sleep.completed",
            {
                "trigger": "developmental_rest",
                "rest_seconds": 1260.0,
                "total_elapsed_ms": 1265000.0,
            },
        )
    )
    snap = state.sleep_snapshot()
    assert snap["sleep"]["trigger"] == "developmental_rest"
    assert snap["sleep"]["rest_seconds"] == 1260.0
    assert snap["sleep"]["duration_s"] == 1265.0
    assert snap["sleep"]["started_at"] == 1000.0
    assert snap["sleep"]["asleep"] is False
    assert snap["sleeping"] is False


def test_requested_sleep_uses_start_trigger():
    state = ConversationState()
    state.observe(
        _sleep_event("sleep.sleep.started", {"trigger": "requested"})
    )
    state.observe(_sleep_event("sleep.sleep.completed", {}))
    assert state.sleep_snapshot()["sleep"]["trigger"] == "requested"

    other = ConversationState()
    other.observe(
        _sleep_event("sleep.sleep.started", {"trigger": "requested"})
    )
    other.observe(_sleep_event("sleep.sleep.completed", {"fatigue_triggered": True}))
    assert other.sleep_snapshot()["sleep"]["trigger"] == "requested"


def test_fatigue_sleep_trigger():
    state = ConversationState()
    state.observe(_sleep_event("sleep.sleep.started", {}))
    state.observe(
        _sleep_event(
            "sleep.sleep.completed", {"fatigue_triggered": True, "total_elapsed_ms": 5000.0}
        )
    )
    assert state.sleep_snapshot()["sleep"]["trigger"] == "fatigue_or_backstop"


def test_interval_sleep_trigger_is_backstop():
    state = ConversationState()
    state.observe(_sleep_event("sleep.sleep.started", {}))
    state.observe(
        _sleep_event(
            "sleep.sleep.completed",
            {"fatigue_triggered": False, "total_elapsed_ms": 3600000.0},
        )
    )
    assert state.sleep_snapshot()["sleep"]["trigger"] == "backstop"


def test_completed_without_start_or_trigger_has_no_trigger():
    state = ConversationState()
    state.observe(_sleep_event("sleep.sleep.completed", {}))
    assert state.sleep_snapshot()["sleep"]["trigger"] is None


def test_aborted_completion_flag():
    state = ConversationState()
    state.observe(_sleep_event("sleep.sleep.started", {}))
    state.observe(
        _sleep_event("sleep.sleep.completed", {"aborted": True, "total_elapsed_ms": 1000.0})
    )
    assert state.sleep_snapshot()["sleep"]["aborted"] is True


def test_aborted_completion_after_untriggered_start_has_no_trigger():
    state = ConversationState()
    state.observe(_sleep_event("sleep.sleep.started", {}))
    state.observe(
        _sleep_event("sleep.sleep.completed", {"aborted": True, "reason": "stop"})
    )
    sleep = state.sleep_snapshot()["sleep"]
    assert sleep["trigger"] is None
    assert sleep["aborted"] is True


def test_aborted_developmental_rest_keeps_its_trigger():
    state = ConversationState()
    state.observe(_sleep_event("sleep.sleep.started", {"trigger": "developmental_rest"}))
    state.observe(
        _sleep_event(
            "sleep.sleep.completed",
            {
                "aborted": True,
                "reason": "stop",
                "trigger": "developmental_rest",
                "rest_seconds": 1260.0,
            },
        )
    )
    sleep = state.sleep_snapshot()["sleep"]
    assert sleep["trigger"] == "developmental_rest"
    assert sleep["aborted"] is True


def test_false_fatigue_flag_after_untriggered_start_is_backstop():
    state = ConversationState()
    state.observe(_sleep_event("sleep.sleep.started", {}))
    state.observe(_sleep_event("sleep.sleep.completed", {"fatigue_triggered": False}))
    assert state.sleep_snapshot()["sleep"]["trigger"] == "backstop"


def test_completion_without_seen_start_does_not_reuse_previous_start_time():
    state = ConversationState()
    state.observe(_sleep_event("sleep.sleep.started", {"started_at": 1000.0}))
    state.observe(_sleep_event("sleep.sleep.completed", {"fatigue_triggered": False}))
    assert state.sleep_snapshot()["sleep"]["started_at"] == 1000.0
    state.observe(_sleep_event("sleep.sleep.completed", {"fatigue_triggered": False}))
    assert state.sleep_snapshot()["sleep"]["started_at"] is None


def test_while_asleep_snapshot_is_asleep():
    state = ConversationState()
    state.observe(
        _sleep_event("sleep.sleep.started", {"trigger": "requested", "started_at": 500.0})
    )
    snap = state.sleep_snapshot()
    assert snap["sleeping"] is True
    assert snap["sleep"]["asleep"] is True
    assert snap["sleep"]["trigger"] == "requested"


def test_invalid_sleep_label_becomes_none():
    state = ConversationState()
    state.observe(
        _sleep_event("sleep.sleep.started", {"trigger": "Bad Label!"})
    )
    assert state.sleep_snapshot()["sleep"]["trigger"] is None

    state2 = ConversationState()
    long_label = "a" * 60
    state2.observe(_sleep_event("sleep.sleep.started", {"trigger": long_label}))
    assert state2.sleep_snapshot()["sleep"]["trigger"] is None


def test_rest_request_recorded():
    state = ConversationState()
    ts = datetime(2026, 1, 2, 12, 0, 0, tzinfo=timezone.utc)
    event = Event(
        source="affect",
        type="affect.rest_request",
        payload={"reason": "stimulus_spent", "drive": "boredom", "stall_s": 612.0},
        salience=0.1,
        timestamp=ts,
    )
    state.observe(event)
    snap = state.sleep_snapshot()
    assert snap["rest_request"]["reason"] == "stimulus_spent"
    assert snap["rest_request"]["drive"] == "boredom"
    assert snap["rest_request"]["stall_s"] == 612.0
    assert snap["rest_request"]["at"] == ts.isoformat()


class FakeRecentBus:
    def __init__(self, recents: dict[str, list[tuple[str, Event]]], raise_on=None):
        self._recents = recents
        self._raise_on = raise_on or set()

    async def recent(self, stream: str, count: int = 100) -> list[tuple[str, Event]]:
        if stream in self._raise_on:
            raise RuntimeError("simulated failure")
        return list(self._recents.get(stream, []))


@pytest.mark.asyncio
async def test_backfill_completed_then_started():
    state = ConversationState()
    bus = FakeRecentBus(
        {
            "sleep.out": [
                (
                    "2-0",
                    _sleep_event(
                        "sleep.sleep.completed",
                        {
                            "trigger": "developmental_rest",
                            "rest_seconds": 1260.0,
                            "total_elapsed_ms": 1265000.0,
                        },
                    ),
                ),
                (
                    "1-0",
                    _sleep_event(
                        "sleep.sleep.started",
                        {"trigger": "developmental_rest", "started_at": 1000.0},
                    ),
                ),
            ]
        }
    )
    await state.backfill(bus)
    snap = state.sleep_snapshot()
    assert snap["sleep"]["trigger"] == "developmental_rest"
    assert snap["sleep"]["asleep"] is False


@pytest.mark.asyncio
async def test_backfill_backstop_from_start():
    state = ConversationState()
    bus = FakeRecentBus(
        {
            "sleep.out": [
                ("3-0", _sleep_event("sleep.sleep.completed", {"fatigue_triggered": False})),
                ("2-0", _event("other", "other.type", {})),
                ("1-0", _sleep_event("sleep.sleep.started", {})),
            ]
        }
    )
    await state.backfill(bus)
    snap = state.sleep_snapshot()
    assert snap["sleep"]["trigger"] == "backstop"
    assert snap["sleep"]["asleep"] is False


@pytest.mark.asyncio
async def test_backfill_newest_started_leaves_asleep():
    state = ConversationState()
    bus = FakeRecentBus(
        {"sleep.out": [("1-0", _sleep_event("sleep.sleep.started", {"trigger": "requested"}))]}
    )
    await state.backfill(bus)
    snap = state.sleep_snapshot()
    assert snap["sleep"]["asleep"] is True
    assert snap["sleep"]["trigger"] == "requested"


@pytest.mark.asyncio
async def test_backfill_affect_rest_request():
    state = ConversationState()
    bus = FakeRecentBus(
        {
            "affect.out": [
                ("2-0", _event("affect", "affect.state", {})),
                (
                    "1-0",
                    _event(
                        "affect",
                        "affect.rest_request",
                        {"reason": "stimulus_spent", "drive": "boredom", "stall_s": 612.0},
                    ),
                ),
            ]
        }
    )
    await state.backfill(bus)
    snap = state.sleep_snapshot()
    assert snap["rest_request"]["reason"] == "stimulus_spent"


@pytest.mark.asyncio
async def test_backfill_continues_when_one_stream_raises():
    state = ConversationState()
    bus = FakeRecentBus(
        {
            "self_model.out": [("1-0", _event("self_model", "self_model.document", {}))],
            "sleep.out": [
                (
                    "2-0",
                    _sleep_event(
                        "sleep.sleep.completed",
                        {"trigger": "developmental_rest", "total_elapsed_ms": 1000.0},
                    ),
                ),
                ("1-0", _sleep_event("sleep.sleep.started", {"trigger": "developmental_rest"})),
            ],
            "affect.out": [
                (
                    "1-0",
                    _event(
                        "affect",
                        "affect.rest_request",
                        {"reason": "stimulus_spent", "drive": "boredom", "stall_s": 10.0},
                    ),
                )
            ],
        },
        raise_on={"self_model.out"},
    )
    await state.backfill(bus)
    snap = state.sleep_snapshot()
    assert snap["sleep"]["trigger"] == "developmental_rest"
    assert snap["rest_request"]["reason"] == "stimulus_spent"


class StubBus:
    async def read(self, stream, *, last_id, count, block_ms):
        return []

    async def current_workspace_id(self):
        return "0"


async def _make_app_client(*, state: ConversationState):
    config = DashboardConfig(
        conversation_enabled=True,
        diagnostics_enabled=True,
        host_allowlist=("127.0.0.1", "localhost", "test"),
        operator_token="test-token",
    )
    bus = StubBus()
    privacy = PrivacyFilter()
    bridge = BusBridge(bus, privacy, streams=[], poll_interval_s=0.01)

    async def history_loader(n: int):
        return []

    app = create_app(
        config=config,
        bridge=bridge,
        history_loader=history_loader,
        metrics_snapshot=lambda: {"cycle_status": "not running"},
        conversation_state=state,
    )
    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(transport=transport, base_url="http://test")
    return client, app


@pytest.mark.asyncio
async def test_sleep_diagnostics_route():
    state = ConversationState()
    state.observe(
        _sleep_event(
            "sleep.sleep.started",
            {"trigger": "developmental_rest", "started_at": 1000.0},
        )
    )
    state.observe(
        _sleep_event(
            "sleep.sleep.completed",
            {
                "trigger": "developmental_rest",
                "rest_seconds": 1260.0,
                "total_elapsed_ms": 1265000.0,
            },
        )
    )

    client, app = await _make_app_client(state=state)
    try:
        resp = await client.get(
            "/diagnostics/sleep.json",
            headers={"Authorization": "Bearer test-token"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["sleep"]["trigger"] == "developmental_rest"
        assert data["sleep"]["rest_seconds"] == 1260.0
        assert resp.headers.get("cache-control") == "no-store"
    finally:
        await client.aclose()
