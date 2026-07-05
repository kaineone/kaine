# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the turnkey model-server launch/supervision core
(kaine.setup.model_server).

The non-trivial logic (binary discovery, launch-command construction,
supervision-mode selection, health-gating, start/status/stop dispatch) is
unit-tested here with mocked subprocess / mocked /v1/models — no real binary,
no real network, no real systemd. The bootstrap shell is a thin wrapper over
``python -m kaine.setup.model_server <cmd>``, so this is the real test surface.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from kaine.setup import model_server as ms
from kaine.setup.model_server import (
    SERVER_BIN_ENV,
    build_launch_cmd,
    choose_supervision,
    health_check,
    locate_binary,
    render_systemd_unit,
)
from kaine.setup.organ import ServedAliasResult


# --- binary discovery --------------------------------------------------------


def test_locate_binary_honors_override(tmp_path):
    binary = tmp_path / "llama-server"
    binary.write_text("#!/bin/sh\n")
    found = locate_binary("cuda", override=str(binary))
    assert found == binary


def test_locate_binary_override_missing_returns_none(tmp_path):
    assert locate_binary("cuda", override=str(tmp_path / "nope")) is None


def test_locate_binary_env_override(tmp_path, monkeypatch):
    binary = tmp_path / "llama-server"
    binary.write_text("#!/bin/sh\n")
    monkeypatch.setenv(SERVER_BIN_ENV, str(binary))
    assert locate_binary("cuda") == binary


def test_locate_binary_absent_returns_none(monkeypatch):
    monkeypatch.delenv(SERVER_BIN_ENV, raising=False)
    monkeypatch.setattr(ms, "STUDIO_LLAMA_SERVER", Path("/nonexistent/llama-server"))
    monkeypatch.setattr(ms.shutil, "which", lambda _x: None)
    assert locate_binary("cuda") is None


# --- launch command ----------------------------------------------------------


def test_build_launch_cmd_flags_and_port():
    cmd = build_launch_cmd(
        Path("/bin/llama-server"),
        gguf="kaineone/Qwen3.5-4B-abliterated-GGUF",
        alias="kaineone/Qwen3.5-4B-abliterated-GGUF",
        chat_url="http://127.0.0.1:11434/v1",
    )
    assert cmd[0] == "/bin/llama-server"
    assert "-m" in cmd and "kaineone/Qwen3.5-4B-abliterated-GGUF" in cmd
    # served alias is exactly [lingua].model_id
    i = cmd.index("--alias")
    assert cmd[i + 1] == "kaineone/Qwen3.5-4B-abliterated-GGUF"
    # port parsed from chat_url
    p = cmd.index("--port")
    assert cmd[p + 1] == "11434"
    # CoT suppressed
    rb = cmd.index("--reasoning-budget")
    assert cmd[rb + 1] == "0"
    assert "--jinja" in cmd


def test_build_launch_cmd_custom_port():
    cmd = build_launch_cmd(
        Path("/bin/srv"), gguf="g", alias="a", chat_url="http://127.0.0.1:9999/v1"
    )
    assert cmd[cmd.index("--port") + 1] == "9999"


# --- supervision mode selection ----------------------------------------------


def test_choose_supervision_systemd_when_available(monkeypatch):
    monkeypatch.setattr(ms.shutil, "which", lambda _x: "/usr/bin/systemctl")

    def fake_run(cmd, **kwargs):
        import subprocess

        return subprocess.CompletedProcess(cmd, 0, stdout="running\n", stderr="")

    assert choose_supervision(runner=fake_run) == "systemd"


def test_choose_supervision_background_without_user_bus(monkeypatch):
    monkeypatch.setattr(ms.shutil, "which", lambda _x: "/usr/bin/systemctl")

    def fake_run(cmd, **kwargs):
        import subprocess

        # No user bus → empty stdout, non-zero exit.
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="Failed to connect to bus")

    assert choose_supervision(runner=fake_run) == "background"


def test_choose_supervision_background_without_systemctl(monkeypatch):
    monkeypatch.setattr(ms.shutil, "which", lambda _x: None)
    assert choose_supervision() == "background"


# --- systemd unit ------------------------------------------------------------


def test_render_systemd_unit_restart_on_failure():
    unit = render_systemd_unit(["/bin/llama-server", "-m", "g", "--alias", "a"])
    assert "Restart=on-failure" in unit
    assert "ExecStart=/bin/llama-server -m g --alias a" in unit
    assert "WantedBy=default.target" in unit


# --- health gate -------------------------------------------------------------


def test_health_check_success_first_poll():
    def probe(chat_url, alias, *, api_key=None):
        return ServedAliasResult(listed=True, served=(alias,), detail="matches")

    ok, detail = health_check(
        "http://127.0.0.1:11434/v1", "alias", probe=probe, now=lambda: 0.0,
        sleep=lambda _s: None,
    )
    assert ok is True


def test_health_check_times_out():
    t = {"v": 0.0}

    def now():
        return t["v"]

    def sleep(s):
        t["v"] += 10.0

    def probe(chat_url, alias, *, api_key=None):
        return ServedAliasResult(listed=False, served=(), detail="not yet")

    ok, detail = health_check(
        "http://127.0.0.1:11434/v1", "alias", timeout_s=5.0, probe=probe,
        now=now, sleep=sleep,
    )
    assert ok is False
    assert "did not list" in detail


# --- start dispatch ----------------------------------------------------------


def _cfg():
    return {
        "lingua": {
            "chat_url": "http://127.0.0.1:11434/v1",
            "model_id": "kaineone/Qwen3.5-4B-abliterated-GGUF",
        }
    }


def test_cmd_start_binary_absent_prints_guide(monkeypatch):
    monkeypatch.setattr(ms, "locate_binary", lambda *a, **k: None)
    out_lines = []
    rc = ms.cmd_start(_cfg(), out=out_lines.append)
    assert rc == 2
    assert any("binary not found" in ln for ln in out_lines)
    assert any("NEVER silently installs" in ln for ln in out_lines)


def _cfg_with_gguf(tmp_path):
    """A config whose GGUF override points at a real file (the launch guard wants a
    real ``-m`` path)."""
    gguf = tmp_path / "organ.Q4_K_M.gguf"
    gguf.write_text("gguf")
    cfg = _cfg()
    cfg["lingua"]["model_gguf_path"] = str(gguf)
    return cfg


def test_cmd_start_idempotent_when_already_serving(monkeypatch, tmp_path):
    monkeypatch.setattr(ms, "locate_binary", lambda *a, **k: tmp_path / "srv")
    (tmp_path / "srv").write_text("x")
    monkeypatch.setattr(
        "kaine.setup.organ.verify_served_alias",
        lambda *a, **k: ServedAliasResult(listed=True, served=("x",), detail="matches"),
    )
    out_lines = []
    rc = ms.cmd_start(_cfg_with_gguf(tmp_path), out=out_lines.append)
    assert rc == 0
    assert any("already up" in ln for ln in out_lines)


def test_cmd_start_missing_gguf_fails_honestly(monkeypatch, tmp_path):
    """Binary present but the GGUF not downloaded → honest failure + guidance,
    never a faked launch (llama-server -m needs a real file path)."""
    monkeypatch.setattr(ms, "locate_binary", lambda *a, **k: tmp_path / "srv")
    (tmp_path / "srv").write_text("x")
    cfg = _cfg()
    cfg["lingua"]["model_gguf_path"] = str(tmp_path / "absent.gguf")  # does not exist
    out_lines = []
    rc = ms.cmd_start(cfg, out=out_lines.append)
    assert rc == 5
    assert any("GGUF not found" in ln for ln in out_lines)


def test_cmd_status_up(monkeypatch):
    monkeypatch.setattr(
        "kaine.setup.organ.verify_served_alias",
        lambda *a, **k: ServedAliasResult(listed=True, served=("x",), detail="ok"),
    )
    out_lines = []
    assert ms.cmd_status(_cfg(), out=out_lines.append) == 0
    assert any("[up]" in ln for ln in out_lines)


def test_cmd_status_down(monkeypatch):
    monkeypatch.setattr(
        "kaine.setup.organ.verify_served_alias",
        lambda *a, **k: ServedAliasResult(listed=False, served=(), detail="down"),
    )
    out_lines = []
    assert ms.cmd_status(_cfg(), out=out_lines.append) == 1
    assert any("[down]" in ln for ln in out_lines)
