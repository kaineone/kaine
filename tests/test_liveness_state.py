# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Unit tests for kaine.lifecycle.liveness cycle_process_state."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from kaine.lifecycle.liveness import cycle_process_running, cycle_process_state


def _running_as_root() -> bool:
    return getattr(os, "geteuid", lambda: 1)() == 0


def _fake_proc(root: Path, pids: dict[str, bytes]) -> str:
    root.mkdir(parents=True, exist_ok=True)
    for pid, cmdline in pids.items():
        d = root / pid
        d.mkdir()
        (d / "cmdline").write_bytes(cmdline)
    return str(root)


def test_cycle_process_state_finds_cycle(tmp_path):
    proc = _fake_proc(tmp_path / "proc", {"1": b"python\0-m\0kaine.cycle\0"})
    assert cycle_process_state(proc_root=proc) is True


def test_cycle_process_state_only_non_cycle(tmp_path):
    proc = _fake_proc(
        tmp_path / "proc",
        {"1": b"python\0-m\0something.else\0", "self": b"pytest\0"},
    )
    assert cycle_process_state(proc_root=proc) is False


@pytest.mark.skipif(_running_as_root(), reason="root bypasses file permissions")
def test_cycle_process_state_unreadable_cmdline_no_cycle_is_unknown(tmp_path):
    proc = _fake_proc(tmp_path / "proc", {"1": b"python\0script.py\0"})
    cmdline = Path(proc) / "1" / "cmdline"
    cmdline.chmod(0o000)
    try:
        assert cycle_process_state(proc_root=proc) is None
    finally:
        cmdline.chmod(0o600)


@pytest.mark.skipif(_running_as_root(), reason="root bypasses file permissions")
def test_cycle_process_state_unreadable_plus_cycle_is_true(tmp_path):
    proc = _fake_proc(
        tmp_path / "proc",
        {
            "1": b"python\0script.py\0",
            "2": b"python\0-m\0kaine.cycle\0",
        },
    )
    cmdline = Path(proc) / "1" / "cmdline"
    cmdline.chmod(0o000)
    try:
        assert cycle_process_state(proc_root=proc) is True
    finally:
        cmdline.chmod(0o600)


@pytest.mark.skipif(_running_as_root(), reason="root bypasses directory permissions")
def test_cycle_process_state_unlistable_root_is_unknown(tmp_path):
    proc = tmp_path / "proc"
    proc.mkdir(mode=0o000)
    try:
        assert cycle_process_state(proc_root=str(proc)) is None
    finally:
        proc.chmod(0o700)


def test_cycle_process_running_mirrors_state_true_case(monkeypatch):
    monkeypatch.setattr(
        "kaine.lifecycle.liveness.cycle_process_state", lambda **kwargs: True
    )
    assert cycle_process_running() is True


def test_cycle_process_running_mirrors_state_on_this_host():
    assert cycle_process_running() is (cycle_process_state() is True)
