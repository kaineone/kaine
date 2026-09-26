# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the operator cycle CLI."""
from __future__ import annotations

from kaine.cycle.control import run_preserve
from kaine.cycle.preserve_watch import read_request, write_result


def test_run_preserve_success(tmp_path, capsys):
    request_path = tmp_path / "request.json"
    result_path = tmp_path / "result.json"

    def fake_sleep(seconds: float):
        req = read_request(request_path)
        if req:
            write_result(
                {
                    "request_id": req.request_id,
                    "ok": True,
                    "preservation_id": "pid1",
                    "bundle": "/backups/bundle-1",
                    "error": None,
                },
                result_path,
            )

    rc = run_preserve(
        "manual-backup",
        False,
        10.0,
        request_path=request_path,
        result_path=result_path,
        sleep=fake_sleep,
        clock=lambda: 0.0,
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "Preserved: /backups/bundle-1" in out


def test_run_preserve_failure(tmp_path, capsys):
    request_path = tmp_path / "request.json"
    result_path = tmp_path / "result.json"

    def fake_sleep(seconds: float):
        req = read_request(request_path)
        if req:
            write_result(
                {
                    "request_id": req.request_id,
                    "ok": False,
                    "preservation_id": None,
                    "bundle": None,
                    "error": "PreservationError: disk full",
                },
                result_path,
            )

    rc = run_preserve(
        "failing-backup",
        False,
        10.0,
        request_path=request_path,
        result_path=result_path,
        sleep=fake_sleep,
        clock=lambda: 0.0,
    )
    out = capsys.readouterr().out
    assert rc == 1
    assert "Preservation failed: PreservationError: disk full" in out


def test_run_preserve_timeout(tmp_path, capsys):
    request_path = tmp_path / "request.json"
    result_path = tmp_path / "result.json"
    t = [0.0]

    def fake_sleep(seconds: float):
        t[0] += 0.5

    def fake_clock():
        return t[0]

    rc = run_preserve(
        "slow-backup",
        False,
        2.0,
        request_path=request_path,
        result_path=result_path,
        sleep=fake_sleep,
        clock=fake_clock,
    )
    out = capsys.readouterr().out
    assert rc == 2
    assert "Timeout waiting for preservation result" in out
