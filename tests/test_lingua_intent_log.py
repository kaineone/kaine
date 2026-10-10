# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import json
from pathlib import Path

from kaine.modules.lingua.intent_log import IntentExpressionLog


def _records(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_append_creates_jsonl_record(tmp_path: Path):
    p = tmp_path / "log.jsonl"
    log = IntentExpressionLog(p)
    log.append(
        mode="external",
        prompt="hi",
        generated_text="hello",
        model="qwen",
    )
    recs = _records(p)
    assert len(recs) == 1
    assert recs[0]["mode"] == "external"
    assert recs[0]["prompt"] == "hi"
    assert recs[0]["generated_text"] == "hello"
    assert recs[0]["model"] == "qwen"
    assert "timestamp" in recs[0]


def test_append_writes_faithful_rendering(tmp_path: Path):
    p = tmp_path / "log.jsonl"
    log = IntentExpressionLog(p)
    log.append(
        mode="external",
        prompt="describe",
        generated_text="generated",
        model="m",
        faithful_rendering="ground truth",
    )
    recs = _records(p)
    assert recs[0]["faithful_rendering"] == "ground truth"


def test_append_omits_optional_fields_when_absent(tmp_path: Path):
    p = tmp_path / "log.jsonl"
    log = IntentExpressionLog(p)
    log.append(
        mode="internal",
        prompt="",
        generated_text="thought",
        model="m",
    )
    recs = _records(p)
    assert "faithful_rendering" not in recs[0]
    assert "snapshot_summary" not in recs[0]


def test_append_accumulates(tmp_path: Path):
    p = tmp_path / "log.jsonl"
    log = IntentExpressionLog(p)
    for i in range(5):
        log.append(mode="external", prompt=f"p{i}", generated_text=f"g{i}", model="m")
    assert len(_records(p)) == 5


def test_path_created_on_first_write(tmp_path: Path):
    p = tmp_path / "a" / "b" / "log.jsonl"
    log = IntentExpressionLog(p)
    log.append(mode="external", prompt="x", generated_text="y", model="m")
    assert p.exists()


def test_extra_field_included(tmp_path: Path):
    p = tmp_path / "log.jsonl"
    log = IntentExpressionLog(p)
    log.append(
        mode="external",
        prompt="x",
        generated_text="y",
        model="m",
        extra={"experiment": "abl-001"},
    )
    recs = _records(p)
    assert recs[0]["extra"] == {"experiment": "abl-001"}


def test_token_counts_recorded(tmp_path: Path):
    p = tmp_path / "log.jsonl"
    log = IntentExpressionLog(p)
    log.append(
        mode="external",
        prompt="x",
        generated_text="y",
        model="m",
        prompt_tokens=12,
        completion_tokens=8,
        latency_ms=120.5,
    )
    rec = _records(p)[0]
    assert rec["prompt_tokens"] == 12
    assert rec["completion_tokens"] == 8
    assert rec["latency_ms"] == 120.5


def test_append_records_all_new_fields(tmp_path: Path):
    p = tmp_path / "log.jsonl"
    log = IntentExpressionLog(p)
    log.append(
        mode="external",
        prompt="p",
        generated_text="g",
        model="m",
        record_id="rid",
        intent_entry_id="eid",
        intent_origin="nous",
        sleep_index=3,
        system_digest="digest",
        seed=42,
    )
    rec = _records(p)[0]
    assert rec["record_id"] == "rid"
    assert rec["intent_entry_id"] == "eid"
    assert rec["intent_origin"] == "nous"
    assert rec["sleep_index"] == 3
    assert rec["system_digest"] == "digest"
    assert rec["seed"] == 42


def test_append_records_new_fields_as_null_when_absent(tmp_path: Path):
    p = tmp_path / "log.jsonl"
    log = IntentExpressionLog(p)
    log.append(mode="external", prompt="p", generated_text="g", model="m")
    rec = _records(p)[0]
    assert "record_id" in rec and rec["record_id"] is None
    assert "intent_entry_id" in rec and rec["intent_entry_id"] is None
    assert "intent_origin" in rec and rec["intent_origin"] is None
    assert "sleep_index" in rec and rec["sleep_index"] is None
    assert "system_digest" in rec and rec["system_digest"] is None
    assert "seed" in rec and rec["seed"] is None
