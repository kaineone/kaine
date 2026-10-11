# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from datetime import datetime, timezone

import pytest

from kaine.bus.schema import Event
from kaine.evaluation.ab_divergence import ABDivergenceObserver


class FakeBus:
    pass


class FakeEmbedder:
    kind = "fake"

    async def load(self) -> None:
        pass

    async def embed(self, text: str) -> list[float]:
        return [1.0, 0.0]


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def complete(self, user_text: str) -> str:
        self.calls.append(user_text)
        return "bare reply"

    async def close(self) -> None:
        pass


class FakeSink:
    def __init__(self) -> None:
        self.records: list[dict] = []

    async def write(self, record: dict) -> None:
        self.records.append(record)


@pytest.mark.asyncio
async def test_ab_divergence_records_skip_for_heard_reply(monkeypatch):
    monkeypatch.setattr(
        "kaine.organ_window_state.organ_unloaded",
        lambda: False,
    )
    sink = FakeSink()
    client = FakeClient()
    obs = ABDivergenceObserver(
        bus=FakeBus(),
        sink=sink,
        embedder=FakeEmbedder(),
        client=client,
    )
    event = Event(
        source="lingua",
        type="external_speech",
        payload={"text": "hello"},
        salience=0.6,
        timestamp=datetime.now(timezone.utc),
    )
    await obs.handle("lingua.external", "1-0", event)

    assert len(sink.records) == 1
    record = sink.records[0]
    assert record["entry_id"] == "1-0"
    assert record["skipped"] == "no_user_input_heard_reply"
    assert "user_text_len" not in record
    assert "real_text_len" not in record
    assert "bare_text_len" not in record
    assert "cosine_similarity" not in record
    assert "divergence" not in record
    assert obs.skipped_no_input_count == 1
    assert client.calls == []
