# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the birth request/acknowledgement state helpers."""

from __future__ import annotations

from datetime import datetime, timezone

from kaine.lifecycle.birth_ack import (
    BirthAck,
    clear_ack,
    clear_request,
    is_acknowledged,
    new_request,
    read_ack,
    read_request,
    write_ack,
    write_request,
)


def test_round_trip_and_acknowledgement(tmp_path):
    request_path = tmp_path / "birth_request.json"
    ack_path = tmp_path / "birth_ack.json"

    gestation_started = datetime.now(timezone.utc).isoformat()
    req = new_request(gestation_started)
    assert len(req.request_id) == 32
    assert req.requested_at is not None
    assert req.gestation_started_at == gestation_started

    write_request(req, path=request_path)
    read = read_request(request_path)
    assert read == req

    ack = BirthAck(
        request_id=req.request_id,
        acknowledged_at=datetime.now(timezone.utc).isoformat(),
    )
    write_ack(ack, path=ack_path)
    read_ack_ = read_ack(ack_path)
    assert read_ack_ == ack

    assert is_acknowledged(req, ack) is True
    assert is_acknowledged(req, None) is False
    assert is_acknowledged(None, ack) is False
    assert is_acknowledged(None, None) is False


def test_absent_and_malformed_read_as_none(tmp_path):
    request_path = tmp_path / "birth_request.json"
    ack_path = tmp_path / "birth_ack.json"

    assert read_request(request_path) is None
    assert read_ack(ack_path) is None

    request_path.write_text("not json", encoding="utf-8")
    ack_path.write_text("[]", encoding="utf-8")
    assert read_request(request_path) is None
    assert read_ack(ack_path) is None

    request_path.write_text('{"request_id": "a" * 32}', encoding="utf-8")
    assert read_request(request_path) is None

    ack_path.write_text(
        '{"request_id": "a" * 32, "acknowledged_at": 123}', encoding="utf-8"
    )
    assert read_ack(ack_path) is None


def test_non_hex_id_reads_as_none(tmp_path):
    request_path = tmp_path / "birth_request.json"
    bad_id = "A" * 32  # uppercase hex is invalid
    request_path.write_text(
        '{"request_id": "%s", "requested_at": "2024-01-01T00:00:00+00:00"}' % bad_id,
        encoding="utf-8",
    )
    assert read_request(request_path) is None


def test_clear_missing_is_fine(tmp_path):
    request_path = tmp_path / "birth_request.json"
    ack_path = tmp_path / "birth_ack.json"
    clear_request(request_path)
    clear_ack(ack_path)
    assert not request_path.exists()
    assert not ack_path.exists()


def test_invalid_gestation_started_at_type_reads_as_none(tmp_path):
    request_path = tmp_path / "birth_request.json"
    request_path.write_text(
        '{"request_id": "a" * 32, "requested_at": "2024-01-01T00:00:00+00:00", '
        '"gestation_started_at": 123}',
        encoding="utf-8",
    )
    assert read_request(request_path) is None
