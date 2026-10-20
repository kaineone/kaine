# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Tests for intent-log record_id to intent_entry_id links in the ignition audit."""

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from kaine.bus import Event
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.modules.sleep.corpus import intent_record_links


@dataclass
class _PhaseResult:
    success: bool = True
    name: str = ""
    message: str = ""


class _FakeClock:
    def __init__(self):
        self._now = 0.0

    def now(self):
        return self._now

    def advance(self, seconds):
        self._now += seconds


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


@pytest.fixture
def sleep(bus, monkeypatch, tmp_path):
    from kaine.modules.sleep.module import Sleep
    from kaine.modules.sleep.voice_alignment import VoiceAlignmentConfig

    clock = _FakeClock()
    h = Sleep(
        bus,
        entity_clock=clock,
        requested_rest_min_interval_s=1800.0,
        fatigue_triggered=False,
        voice_alignment_config=VoiceAlignmentConfig(
            intent_log_path=tmp_path / "language" / "intent_expression.jsonl",
            adapter_output_dir=tmp_path / "adapters",
        ),
    )
    h._sleep_pending = False
    h._baseline_salience = 0.5
    h._sleep_count = 0
    h._broadcast_cursor = "0"
    h._audit_cursors = {}
    h._scheduler = SimpleNamespace(mark_completed=lambda: None)

    def _phase(name):
        async def _run(*args, **kwargs):
            return _PhaseResult(success=True, name=name, message="ok")

        return _run

    monkeypatch.setattr("kaine.modules.sleep.module.light_consolidation", _phase("light"))
    monkeypatch.setattr("kaine.modules.sleep.module.deep_consolidation", _phase("deep"))
    monkeypatch.setattr(
        "kaine.modules.sleep.module.associative_replay", _phase("associative")
    )
    monkeypatch.setattr(
        "kaine.modules.sleep.module.affective_reset", _phase("affective")
    )

    async def _fake_voice_alignment():
        return (
            SimpleNamespace(
                accepted=False,
                adapter_path=None,
                capability_loss=None,
                reason="skipped",
                samples_used=0,
                dpo_loss=None,
                capability_score_before=None,
                capability_score_after=None,
                mean_intent_expression_similarity_before=None,
                mean_intent_expression_similarity_after=None,
            ),
            _PhaseResult(success=True, name="voice_alignment", message="skipped"),
        )

    monkeypatch.setattr(h, "_run_voice_alignment", _fake_voice_alignment)
    return h


def test_intent_record_links_maps_record_id_to_intent_entry_id(tmp_path):
    a = tmp_path / "a.jsonl"
    a.write_text(
        "\n"
        "{bad json\n"
        '{"record_id": "R0"}\n'
        '{"record_id": "R1", "intent_entry_id": "E1"}\n'
        '{"record_id": "", "intent_entry_id": "E0"}\n'
        '{"record_id": "R2", "intent_entry_id": "E2"}\n'
        '"not a dict"\n'
    )
    b = tmp_path / "b.jsonl"
    b.write_text('{"record_id": "R1", "intent_entry_id": "E1B"}\n')
    missing = tmp_path / "missing.jsonl"
    assert intent_record_links([a, b, missing]) == {"R1": "E1B", "R2": "E2"}


def test_intent_record_links_logs_and_skips_oserror(tmp_path, monkeypatch):
    from kaine.persistence.encrypted_jsonl import iter_records as real_iter

    a = tmp_path / "a.jsonl"
    a.write_text('{"record_id": "R1", "intent_entry_id": "E1"}\n')
    bad = tmp_path / "bad.jsonl"

    def _fake_iter(path):
        if path == bad:
            raise OSError("boom")
        return real_iter(path)

    monkeypatch.setattr(
        "kaine.persistence.encrypted_jsonl.iter_records", _fake_iter
    )
    assert intent_record_links([bad, a]) == {"R1": "E1"}


@pytest.mark.asyncio
async def test_ignition_audit_links_via_intent_log(sleep, bus, tmp_path):
    now = datetime.now(timezone.utc)
    await bus.publish(
        Event(
            source="action_selection",
            type="intent.speak",
            payload={"kind": "speak", "about": "x", "entry_id": "E1"},
            salience=0.5,
            timestamp=now,
        )
    )
    await bus.publish(
        Event(
            source="action_selection",
            type="intent.speak",
            payload={"kind": "speak", "about": "y", "entry_id": "E2"},
            salience=0.5,
            timestamp=now,
        )
    )
    await bus.publish_workspace(
        {"selected": [{"entry_id": "E1", "type": "affect.drive", "salience": 0.9}]}
    )
    await bus.publish_workspace(
        {"selected": [{"entry_id": "E2", "type": "vision.report", "salience": 0.5}]}
    )
    await bus.client.xadd(
        "language.external",
        {
            "source": "language",
            "type": "external_speech",
            "salience": "0.5",
            "timestamp": now.isoformat(),
            "causal_parent": "",
            "payload": json.dumps(
                {"text": "hi", "mode": "external", "record_id": "R1"}
            ),
        },
    )
    await bus.client.xadd(
        "language.external",
        {
            "source": "language",
            "type": "external_speech",
            "salience": "0.5",
            "timestamp": now.isoformat(),
            "causal_parent": "",
            "payload": json.dumps(
                {"text": "ho", "mode": "external", "record_id": "R2"}
            ),
        },
    )

    corpus_dir = tmp_path / "language" / "intent_log"
    corpus_dir.mkdir(parents=True)
    (corpus_dir / "sleep-20261019T120000Z-0001.jsonl").write_text(
        json.dumps(
            {
                "record_id": "R1",
                "intent_entry_id": "E1",
                "mode": "external",
                "generated_text": "hi",
            }
        )
        + "\n"
    )
    (tmp_path / "language" / "intent_expression.jsonl").write_text(
        json.dumps(
            {
                "record_id": "R2",
                "intent_entry_id": "E2",
                "mode": "external",
                "generated_text": "ho",
            }
        )
        + "\n"
    )

    payload = await sleep._run_ignition_audit()
    assert payload["drive_triggered"] == 1
    assert payload["drive_triggered_entry_ids"] == ["E1"]
    assert payload["self_initiated"] == 1
    assert payload["self_initiated_entry_ids"] == ["E2"]
    assert "audit_error" not in payload


@pytest.mark.asyncio
async def test_ignition_audit_unlinked_counts_without_intent_log(sleep, bus):
    now = datetime.now(timezone.utc)
    await bus.publish(
        Event(
            source="action_selection",
            type="intent.speak",
            payload={"kind": "speak", "about": "x", "entry_id": "E1"},
            salience=0.5,
            timestamp=now,
        )
    )
    await bus.publish(
        Event(
            source="action_selection",
            type="intent.speak",
            payload={"kind": "speak", "about": "y", "entry_id": "E2"},
            salience=0.5,
            timestamp=now,
        )
    )
    await bus.publish_workspace(
        {"selected": [{"entry_id": "E1", "type": "affect.drive", "salience": 0.9}]}
    )
    await bus.publish_workspace(
        {"selected": [{"entry_id": "E2", "type": "vision.report", "salience": 0.5}]}
    )
    await bus.client.xadd(
        "language.external",
        {
            "source": "language",
            "type": "external_speech",
            "salience": "0.5",
            "timestamp": now.isoformat(),
            "causal_parent": "",
            "payload": json.dumps(
                {"text": "hi", "mode": "external", "record_id": "R1"}
            ),
        },
    )
    await bus.client.xadd(
        "language.external",
        {
            "source": "language",
            "type": "external_speech",
            "salience": "0.5",
            "timestamp": now.isoformat(),
            "causal_parent": "",
            "payload": json.dumps(
                {"text": "ho", "mode": "external", "record_id": "R2"}
            ),
        },
    )

    payload = await sleep._run_ignition_audit()
    assert payload["drive_triggered"] == 0
    assert payload["drive_triggered_entry_ids"] == []
    assert payload["self_initiated"] == 2
    assert payload["self_initiated_entry_ids"] == []
    assert "audit_error" not in payload


@pytest.mark.asyncio
async def test_ignition_audit_continues_when_link_read_fails(
    sleep, bus, tmp_path, monkeypatch
):
    now = datetime.now(timezone.utc)
    await bus.publish(
        Event(
            source="action_selection",
            type="intent.speak",
            payload={"kind": "speak", "about": "x", "entry_id": "E1"},
            salience=0.5,
            timestamp=now,
        )
    )
    await bus.publish(
        Event(
            source="action_selection",
            type="intent.speak",
            payload={"kind": "speak", "about": "y", "entry_id": "E2"},
            salience=0.5,
            timestamp=now,
        )
    )
    await bus.publish_workspace(
        {"selected": [{"entry_id": "E1", "type": "affect.drive", "salience": 0.9}]}
    )
    await bus.publish_workspace(
        {"selected": [{"entry_id": "E2", "type": "vision.report", "salience": 0.5}]}
    )
    await bus.client.xadd(
        "language.external",
        {
            "source": "language",
            "type": "external_speech",
            "salience": "0.5",
            "timestamp": now.isoformat(),
            "causal_parent": "",
            "payload": json.dumps(
                {"text": "hi", "mode": "external", "record_id": "R1"}
            ),
        },
    )
    await bus.client.xadd(
        "language.external",
        {
            "source": "language",
            "type": "external_speech",
            "salience": "0.5",
            "timestamp": now.isoformat(),
            "causal_parent": "",
            "payload": json.dumps(
                {"text": "ho", "mode": "external", "record_id": "R2"}
            ),
        },
    )

    def _broken_links(_paths):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "kaine.modules.sleep.corpus.intent_record_links", _broken_links
    )

    payload = await sleep._run_ignition_audit()
    assert payload["realized_total"] == 2
    assert "audit_error" not in payload
