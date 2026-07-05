# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import json
import os
import stat
from pathlib import Path

import pytest

from kaine.modules.praxis.audit_log import GENESIS_HASH, ActionAuditLog


def _read_records(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _append(log: ActionAuditLog, **overrides) -> None:
    kw = dict(
        effector="file_write",
        request_summary={"name": "x.txt"},
        success=True,
        elapsed_ms=1.0,
        error=None,
    )
    kw.update(overrides)
    log.append(**kw)


def test_appends_one_jsonl_line(tmp_path: Path):
    p = tmp_path / "audit.log"
    log = ActionAuditLog(p)
    log.append(
        effector="file_write",
        request_summary={"name": "x.txt"},
        success=True,
        elapsed_ms=12.5,
        error=None,
    )
    records = _read_records(p)
    assert len(records) == 1
    assert records[0]["effector"] == "file_write"
    assert records[0]["success"] is True
    assert "timestamp" in records[0]


def test_content_keys_stripped(tmp_path: Path):
    p = tmp_path / "audit.log"
    log = ActionAuditLog(p)
    log.append(
        effector="file_write",
        request_summary={"name": "secret.txt", "content": "TOP SECRET"},
        success=True,
        elapsed_ms=1.0,
        error=None,
    )
    records = _read_records(p)
    request = records[0]["request"]
    assert "content" not in request
    # Make sure we still recorded non-content fields.
    assert request["name"] == "secret.txt"
    # No occurrence of the content anywhere in the line.
    raw = p.read_text()
    assert "TOP SECRET" not in raw


def test_failure_records_error(tmp_path: Path):
    p = tmp_path / "audit.log"
    log = ActionAuditLog(p)
    log.append(
        effector="shell",
        request_summary={"command": "ls"},
        success=False,
        elapsed_ms=2.0,
        error="ValueError: command not in whitelist",
    )
    records = _read_records(p)
    assert records[0]["success"] is False
    assert records[0]["error"].startswith("ValueError")


def test_multiple_appends_accumulate(tmp_path: Path):
    p = tmp_path / "audit.log"
    log = ActionAuditLog(p)
    for i in range(5):
        log.append(
            effector="file_write",
            request_summary={"name": f"f{i}"},
            success=True,
            elapsed_ms=1.0,
            error=None,
        )
    records = _read_records(p)
    assert len(records) == 5


def test_path_created_on_first_write(tmp_path: Path):
    p = tmp_path / "a" / "b" / "audit.log"
    log = ActionAuditLog(p)
    log.append(
        effector="x",
        request_summary={},
        success=True,
        elapsed_ms=0.0,
        error=None,
    )
    assert p.exists()


def test_body_and_stdout_keys_also_stripped(tmp_path: Path):
    p = tmp_path / "audit.log"
    log = ActionAuditLog(p)
    log.append(
        effector="notify",
        request_summary={"title": "x", "body": "PRIVATE", "urgency": "low"},
        success=True,
        elapsed_ms=1.0,
        error=None,
    )
    raw = p.read_text()
    assert "PRIVATE" not in raw


# ---------------------------------------------------------------------------
# Tamper-evident hash chain.
# ---------------------------------------------------------------------------


def test_records_carry_chained_hashes(tmp_path: Path):
    p = tmp_path / "audit.log"
    log = ActionAuditLog(p)
    for i in range(3):
        _append(log, request_summary={"name": f"f{i}"})
    records = _read_records(p)
    assert records[0]["prev_hash"] == GENESIS_HASH
    # Each record's prev_hash equals the previous record's this_hash.
    for prev, cur in zip(records, records[1:]):
        assert cur["prev_hash"] == prev["this_hash"]
    assert all(len(r["this_hash"]) == 64 for r in records)


def test_verify_ok_on_intact_and_absent_log(tmp_path: Path):
    p = tmp_path / "audit.log"
    log = ActionAuditLog(p)
    # Absent log verifies ok.
    assert log.verify().ok
    for i in range(4):
        _append(log, request_summary={"name": f"f{i}"})
    assert log.verify().ok


def test_verify_detects_edited_historical_record(tmp_path: Path):
    p = tmp_path / "audit.log"
    log = ActionAuditLog(p)
    for i in range(4):
        _append(log, request_summary={"name": f"f{i}"})
    # Tamper with the substance of an earlier record without fixing its hash.
    lines = p.read_text().splitlines()
    rec = json.loads(lines[1])
    rec["effector"] = "shell"  # forged history
    lines[1] = json.dumps(rec, sort_keys=True)
    p.write_text("\n".join(lines) + "\n")

    result = log.verify()
    assert not result.ok
    assert result.broken_index == 1
    assert "edited" in result.detail


def test_verify_detects_truncated_middle_record(tmp_path: Path):
    p = tmp_path / "audit.log"
    log = ActionAuditLog(p)
    for i in range(4):
        _append(log, request_summary={"name": f"f{i}"})
    # Remove a historical record from the middle: the following record's
    # prev_hash no longer chains.
    lines = p.read_text().splitlines()
    del lines[1]
    p.write_text("\n".join(lines) + "\n")

    result = log.verify()
    assert not result.ok
    assert result.broken_index == 1  # what is now at index 1 breaks the chain


# ---------------------------------------------------------------------------
# File permissions (P3): the audit log is owner-only (0600) under any umask.
# ---------------------------------------------------------------------------


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits")
def test_audit_log_file_and_dir_are_owner_only_under_permissive_umask(tmp_path: Path):
    old = os.umask(0o002)
    try:
        # A freshly-created parent directory must be hardened too (not just the
        # file), mirroring snapshot.py / effectors.py.
        parent = tmp_path / "praxis"
        p = parent / "audit.log"
        log = ActionAuditLog(p)
        _append(log)
        assert stat.S_IMODE(p.stat().st_mode) == 0o600, oct(p.stat().st_mode)
        assert stat.S_IMODE(parent.stat().st_mode) == 0o700, oct(parent.stat().st_mode)
    finally:
        os.umask(old)
