# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import json

import pytest

from kaine.cycle.caretaker_state import (
    CaretakerAck,
    CaretakerStart,
    clear_start,
    is_acknowledged,
    read_ack,
    read_start,
    write_ack,
    write_start,
)


def test_round_trip_start(tmp_path):
    path = tmp_path / "start.json"
    start = CaretakerStart(start_id="a" * 32, started_at="2026-01-01T00:00:00+00:00")
    write_start(start, path=path)
    assert read_start(path=path) == start


def test_round_trip_ack(tmp_path):
    path = tmp_path / "ack.json"
    ack = CaretakerAck(start_id="a" * 32, acknowledged_at="2026-01-01T01:00:00+00:00")
    write_ack(ack, path=path)
    assert read_ack(path=path) == ack


def test_missing_file_returns_none(tmp_path):
    assert read_start(path=tmp_path / "missing.json") is None
    assert read_ack(path=tmp_path / "missing.json") is None


@pytest.mark.parametrize(
    "payload",
    [
        "not valid json",
        '{"start_id": "short", "started_at": "t"}',
        '{"started_at": "t"}',
        '{"start_id": "a" * 32}',
        '{"start_id": "a" * 32, "started_at": 123}',
        "[]",
        "{}",
    ],
)
def test_malformed_start_returns_none(tmp_path, payload):
    path = tmp_path / "start.json"
    path.write_text(payload)
    assert read_start(path=path) is None


@pytest.mark.parametrize(
    "payload",
    [
        "not valid json",
        '{"start_id": "short", "acknowledged_at": "t"}',
        '{"acknowledged_at": "t"}',
        '{"start_id": "a" * 32}',
        '{"start_id": "a" * 32, "acknowledged_at": 123}',
        "[]",
        "{}",
    ],
)
def test_malformed_ack_returns_none(tmp_path, payload):
    path = tmp_path / "ack.json"
    path.write_text(payload)
    assert read_ack(path=path) is None


def test_bad_start_id_length_returns_none(tmp_path):
    path = tmp_path / "start.json"
    path.write_text(json.dumps({"start_id": "b" * 33, "started_at": "t"}))
    assert read_start(path=path) is None


def test_uppercase_start_id_returns_none(tmp_path):
    path = tmp_path / "start.json"
    path.write_text(json.dumps({"start_id": "A" * 32, "started_at": "t"}))
    assert read_start(path=path) is None


def test_is_acknowledged_truth_table(tmp_path):
    start = CaretakerStart(start_id="a" * 32, started_at="t1")
    ack_match = CaretakerAck(start_id="a" * 32, acknowledged_at="t2")
    ack_mismatch = CaretakerAck(start_id="0" * 32, acknowledged_at="t2")
    assert is_acknowledged(None, None) is False
    assert is_acknowledged(start, None) is False
    assert is_acknowledged(None, ack_match) is False
    assert is_acknowledged(start, ack_mismatch) is False
    assert is_acknowledged(start, ack_match) is True


def test_clear_start_removes_file(tmp_path):
    path = tmp_path / "start.json"
    write_start(CaretakerStart(start_id="a" * 32, started_at="t"), path=path)
    assert path.exists()
    clear_start(path=path)
    assert not path.exists()
    clear_start(path=path)
