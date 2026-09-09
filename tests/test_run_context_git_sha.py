# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Tests for compute_git_sha's KAINE_GIT_SHA env fallback.

Covers: (a) a successful git lookup ignores the env var, (b) a failed git
lookup falls back to KAINE_GIT_SHA, (c) a failed git lookup with unset or
empty/invalid env returns None. compute_git_sha must never raise.
"""

import subprocess
from unittest import mock

import pytest

from kaine.experiment.run_context import compute_git_sha


def _fake_run(returncode=0, stdout=""):
    proc = mock.Mock(returncode=returncode)
    proc.stdout = stdout
    return proc


def test_git_success_ignores_env(monkeypatch):
    monkeypatch.setenv("KAINE_GIT_SHA", "feedfee")
    with mock.patch.object(
        subprocess, "run", return_value=_fake_run(0, "abc1234\n")
    ) as run:
        assert compute_git_sha() == "abc1234"
    assert run.called


def test_git_failure_falls_back_to_env(monkeypatch):
    monkeypatch.setenv("KAINE_GIT_SHA", "deadbee")
    with mock.patch.object(
        subprocess, "run", return_value=_fake_run(128, "")
    ):
        assert compute_git_sha() == "deadbee"


def test_git_exception_falls_back_to_env(monkeypatch):
    monkeypatch.setenv("KAINE_GIT_SHA", "deadbee")

    def _raise(*a, **k):
        raise OSError("no git")

    with mock.patch.object(subprocess, "run", side_effect=_raise):
        assert compute_git_sha() == "deadbee"


def test_git_failure_unset_env_returns_none(monkeypatch):
    monkeypatch.delenv("KAINE_GIT_SHA", raising=False)
    with mock.patch.object(
        subprocess, "run", return_value=_fake_run(128, "")
    ):
        assert compute_git_sha() is None


@pytest.mark.parametrize("bad", ["", "   ", "zz12345", "abc123", "x" * 41])
def test_git_failure_invalid_env_returns_none(monkeypatch, bad):
    monkeypatch.setenv("KAINE_GIT_SHA", bad)
    with mock.patch.object(
        subprocess, "run", return_value=_fake_run(128, "")
    ):
        assert compute_git_sha() is None


def test_git_empty_stdout_falls_back_to_env(monkeypatch):
    monkeypatch.setenv("KAINE_GIT_SHA", "deadbee")
    with mock.patch.object(
        subprocess, "run", return_value=_fake_run(0, "\n")
    ):
        assert compute_git_sha() == "deadbee"
