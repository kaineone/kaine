# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import json
from pathlib import Path

import pytest

from kaine.modules.lingua.intent_log import IntentExpressionLog


def _records(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


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
        mode="external", prompt="x", generated_text="y", model="m",
        prompt_tokens=12, completion_tokens=8, latency_ms=120.5,
    )
    rec = _records(p)[0]
    assert rec["prompt_tokens"] == 12
    assert rec["completion_tokens"] == 8
    assert rec["latency_ms"] == 120.5
