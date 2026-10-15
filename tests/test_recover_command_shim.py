# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Tests for the deprecated recovery-command shim."""

import importlib
import io
import os
import subprocess
import sys

from kaine import legacy_names

_SHIM = next(e for e in legacy_names.PACKAGING if e["kind"] == "module_shim")
OLD_MODULE = _SHIM["old"]
NEW_MODULE = _SHIM["new"]
shim = importlib.import_module(OLD_MODULE)


def test_shim_warns_and_delegates(monkeypatch):
    """The shim emits a deprecation line and forwards argv, streams, and the return code."""
    calls = []

    def fake_main(argv, *, out, err):
        calls.append((argv, out, err))
        return 7

    monkeypatch.setattr(shim, "_main", fake_main)

    out = io.StringIO()
    err = io.StringIO()
    result = shim.main(["--confirm-keep-current-store"], out=out, err=err)

    assert result == 7
    assert len(calls) == 1
    assert calls[0][0] == ["--confirm-keep-current-store"]
    assert calls[0][1] is out
    assert calls[0][2] is err
    assert err.getvalue() == (
        f"{OLD_MODULE} is deprecated; "
        f"run python -m {NEW_MODULE} instead\n"
    )
    assert out.getvalue() == ""


def test_shim_module_command_mentions_new_command():
    """Running the old module path forwards to the new command name."""
    repo_root = os.path.dirname(os.path.dirname(__file__))
    env = os.environ.copy()
    env["PYTHONPATH"] = repo_root

    proc = subprocess.run(
        [sys.executable, "-m", OLD_MODULE, "--help"],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
    )

    output = proc.stdout + proc.stderr
    assert proc.returncode == 0
    assert NEW_MODULE in output
