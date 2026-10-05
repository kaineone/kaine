# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for shared-service detection and integration guards."""

import os
from unittest.mock import MagicMock

import pytest

from kaine.boot import _effective_hot_swap_mode, make_hypnos
from kaine.config import ConfigShapeError, load_kaine_config
from kaine.organ_server.lifecycle import cmd_stop
from kaine.shared_services import (
    KNOWN_PROCESS_NAMES,
    is_shared,
    match_shared_service,
    shared_services,
)


def test_make_hypnos_without_voice_alignment_shared_model_server():
    """Regression: absent [hypnos.voice_alignment] must not crash make_hypnos."""
    bus = MagicMock()
    hypnos = make_hypnos(
        bus,
        {},
        kaine_config={"services": {"model_server": {"shared": True}}},
    )
    assert hypnos is not None


def test_shared_services_absent():
    assert shared_services({}) == {}


def test_shared_services_shared_false():
    assert shared_services({"services": {"model_server": {"shared": False}}}) == {}


def test_shared_services_shared_true_default_patterns():
    assert shared_services({"services": {"model_server": {"shared": True}}}) == {
        "model_server": KNOWN_PROCESS_NAMES["model_server"]
    }


def test_cmd_stop_loads_config_when_none_and_respects_shared(monkeypatch):
    monkeypatch.setattr(
        "kaine.organ_server.lifecycle._load_config",
        lambda: {"services": {"model_server": {"shared": True}}},
    )
    runner_calls = []
    kill_calls = []
    out_lines = []

    def fake_runner(*args, **kwargs):
        runner_calls.append((args, kwargs))
        return None

    monkeypatch.setattr(
        "kaine.organ_server.lifecycle.os.kill",
        lambda *args, **kwargs: kill_calls.append((args, kwargs)),
    )
    result = cmd_stop(
        out=lambda s: out_lines.append(s),
        runner=fake_runner,
    )
    assert result == 2
    assert any("shared" in line for line in out_lines)
    assert runner_calls == []
    assert kill_calls == []


def test_shared_services_custom_process_names():
    assert shared_services(
        {"services": {"model_server": {"shared": True, "process_names": ["foo", "bar"]}}}
    ) == {"model_server": ("foo", "bar")}


def test_shared_services_unknown_service_uses_name():
    assert shared_services({"services": {"custom": {"shared": True}}}) == {
        "custom": ("custom",)
    }


def test_is_shared():
    assert is_shared({"services": {"model_server": {"shared": True}}}, "model_server")
    assert not is_shared(
        {"services": {"model_server": {"shared": False}}}, "model_server"
    )


def test_match_shared_service_case_insensitive():
    shared = {"chatterbox": ("chatterbox",)}
    assert match_shared_service("ChatterBox-Daemon", shared) == "chatterbox"
    assert match_shared_service("llama-server", shared) is None


def _write_configs(tmp_path, operator_text):
    shipped = tmp_path / "shipped.toml"
    shipped.write_text("[modules]\n")
    operator = tmp_path / "operator.toml"
    operator.write_text(operator_text)
    return shipped, operator


def test_config_shape_services_not_table(tmp_path):
    shipped, operator = _write_configs(tmp_path, 'services = "not-table"\n')
    with pytest.raises(ConfigShapeError, match="services expected table"):
        load_kaine_config(shipped, operator, strict_operator=True)


def test_config_shape_service_value_not_table(tmp_path):
    shipped, operator = _write_configs(tmp_path, 'services = { model_server = "bad" }\n')
    with pytest.raises(ConfigShapeError, match="services.model_server expected table"):
        load_kaine_config(shipped, operator, strict_operator=True)


def test_config_shape_shared_not_bool(tmp_path):
    shipped, operator = _write_configs(
        tmp_path, '[services.model_server]\nshared = "yes"\n'
    )
    with pytest.raises(
        ConfigShapeError, match="services.model_server.shared expected bool"
    ):
        load_kaine_config(shipped, operator, strict_operator=True)


def test_config_shape_process_names_element_not_string(tmp_path):
    shipped, operator = _write_configs(
        tmp_path, '[services.model_server]\nshared = true\nprocess_names = [1]\n'
    )
    with pytest.raises(
        ConfigShapeError,
        match=r"services\.model_server\.process_names\[0\] expected string",
    ):
        load_kaine_config(shipped, operator, strict_operator=True)


def test_cmd_stop_shared_leaves_server_running(monkeypatch):
    emitted = []
    runner_calls = []

    def emit(msg):
        emitted.append(msg)

    def runner(*args, **kwargs):
        runner_calls.append((args, kwargs))
        return None

    def fail_kill(pid, sig):
        pytest.fail(f"os.kill called with pid={pid}, sig={sig}")

    monkeypatch.setattr(os, "kill", fail_kill)
    rc = cmd_stop(
        {"services": {"model_server": {"shared": True}}},
        out=emit,
        runner=runner,
    )
    assert rc == 2
    assert any("[services.model_server].shared = true" in m for m in emitted)
    assert runner_calls == []


def test_effective_hot_swap_mode_shared_becomes_manual():
    cfg = {"services": {"model_server": {"shared": True}}}
    assert _effective_hot_swap_mode("restart_service", cfg) == "manual"
    assert _effective_hot_swap_mode("manual", cfg) == "manual"


def test_effective_hot_swap_mode_not_shared_unchanged():
    assert _effective_hot_swap_mode("restart_service", {}) == "restart_service"
    assert _effective_hot_swap_mode("restart_service", None) == "restart_service"
