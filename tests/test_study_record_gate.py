# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import json

import pytest

from kaine.persistence.jsonl_sink import AsyncJsonlSink
from kaine.persistence.study_record_gate import StudyRecordGate


def test_gate_suspend_resume_idempotent() -> None:
    gate = StudyRecordGate()
    assert not gate.suspended
    gate.suspend()
    assert gate.suspended
    gate.suspend()
    assert gate.suspended
    gate.resume()
    assert not gate.suspended
    gate.resume()
    assert not gate.suspended


@pytest.mark.asyncio
async def test_study_record_sink_emits_gap_markers(tmp_path) -> None:
    gate = StudyRecordGate()
    sink = AsyncJsonlSink(
        tmp_path,
        name="study",
        study_record=True,
        gate=gate,
        flush_interval_s=0.05,
    )
    await sink.start()

    await sink.write({"n": 1})
    await sink.write({"n": 2})
    # Let the queue flush before suspension.
    await asyncio.sleep(0.15)

    gate.suspend()
    await sink.write({"n": 3})
    await sink.write({"n": 4})
    await sink.write({"n": 5})
    await asyncio.sleep(0.15)

    gate.resume()
    await sink.write({"n": 6})
    await asyncio.sleep(0.15)

    await sink.stop()

    files = list(tmp_path.glob("*.jsonl"))
    assert len(files) == 1
    lines = files[0].read_text(encoding="utf-8").strip().splitlines()
    records = [json.loads(line) for line in lines]

    plain = [r for r in records if "record_gap" not in r]
    assert plain == [{"n": 1}, {"n": 2}, {"n": 6}]

    gaps = [r for r in records if "record_gap" in r]
    assert len(gaps) == 2
    assert gaps[0]["record_gap"] == "start"
    assert gaps[1]["record_gap"] == "end"
    assert gaps[1]["dropped"] == 3


@pytest.mark.asyncio
async def test_non_study_record_sink_ignores_suspended_gate(tmp_path) -> None:
    gate = StudyRecordGate()
    sink = AsyncJsonlSink(tmp_path, name="regular", study_record=False, gate=gate)
    gate.suspend()
    await sink.start()
    await sink.write({"a": 1})
    await sink.write({"a": 2})
    await sink.stop()
    lines = list(tmp_path.glob("*.jsonl"))[0].read_text(encoding="utf-8").strip().splitlines()
    assert [json.loads(line) for line in lines] == [{"a": 1}, {"a": 2}]


@pytest.mark.asyncio
async def test_study_record_write_sync_path(tmp_path) -> None:
    gate = StudyRecordGate()
    sink = AsyncJsonlSink(tmp_path, name="sync", study_record=True, gate=gate)
    gate.suspend()
    sink.write_sync({"x": 1})
    sink.write_sync({"x": 2})
    gate.resume()
    sink.write_sync({"x": 3})
    lines = list(tmp_path.glob("*.jsonl"))[0].read_text(encoding="utf-8").strip().splitlines()
    records = [json.loads(line) for line in lines]
    assert records[0]["record_gap"] == "start"
    assert records[1]["record_gap"] == "end"
    assert records[1]["dropped"] == 2
    assert records[2]["x"] == 3
    assert len(records) == 3
import asyncio  # noqa: E402
