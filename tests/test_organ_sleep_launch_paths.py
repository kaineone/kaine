# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Launch-path regression tests for organ idle-sleep configuration."""
from __future__ import annotations

import os
import re
import subprocess
import tomllib
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]


def test_compose_command_defaults_sleep_idle_seconds():
    text = (REPO / "compose" / "kaine.yml").read_text()
    data = yaml.safe_load(text)
    command = data["services"]["kaine-model-server"]["command"]
    assert "${KAINE_MODEL_SERVER_SLEEP_IDLE_SECONDS:-600}" in command
    assert "--sleep-idle-seconds ${KAINE_MODEL_SERVER_SLEEP_IDLE_SECONDS:-600}" in command


def test_quadlet_has_entrypoint_and_env():
    text = (REPO / "quadlet" / "kaine-model-server.container").read_text()
    assert "PodmanArgs=--entrypoint=/bin/sh" in text
    assert "Environment=KAINE_MODEL_SERVER_SLEEP_IDLE_SECONDS=${KAINE_MODEL_SERVER_SLEEP_IDLE_SECONDS}" in text
    assert '--sleep-idle-seconds "$$s"' in text
    assert "exit 64" in text
    assert "EnvironmentFile=@KAINE_ROOT@/compose/.env" in text


def _extract_wrapper_script() -> str:
    text = (REPO / "quadlet" / "kaine-model-server.container").read_text()
    match = re.search(r"Exec=-c '(.+)'(?:\r?\n|$)", text)
    if not match:
        raise AssertionError("Could not find Exec=-c wrapper")
    script = match.group(1)
    script = script.replace("$$", "$")
    script = script.replace("exec /app/llama-server", "echo")
    return script


@pytest.mark.parametrize(
    "env_value,expected,rc",
    [
        (None, "--sleep-idle-seconds 600", 0),
        ("", "--sleep-idle-seconds 600", 0),
        ("120", "--sleep-idle-seconds 120", 0),
        ("-1", "--sleep-idle-seconds -1", 0),
        ("abc", "", 64),
        ("-5", "", 64),
    ],
)
def test_quadlet_wrapper_enforces_sleep_idle_seconds(env_value, expected, rc):
    script = _extract_wrapper_script()
    env = os.environ.copy()
    if env_value is not None:
        env["KAINE_MODEL_SERVER_SLEEP_IDLE_SECONDS"] = env_value
    else:
        env.pop("KAINE_MODEL_SERVER_SLEEP_IDLE_SECONDS", None)
    result = subprocess.run(["sh", "-c", script], env=env, capture_output=True, text=True)
    assert result.returncode == rc, result.stderr
    if expected:
        assert expected in result.stdout, result.stdout
    else:
        assert result.stdout == ""


def test_config_has_model_server_sleep_idle_seconds():
    with (REPO / "config" / "kaine.toml").open("rb") as f:
        config = tomllib.load(f)
    assert config["lingua"]["model_server_sleep_idle_seconds"] == 600
