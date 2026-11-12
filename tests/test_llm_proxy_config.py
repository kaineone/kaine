# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the llama-swap config generator."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from kaine.residency.llm_proxy import (
    UPSTREAM_BASE_PORT,
    LlamaSwapConfig,
    generate_llama_swap_config,
    write_llama_swap_config,
)

FAKE_BINARY = Path("/usr/bin/llama-server")
FAKE_GGUF = Path("/models/organ.Q4_K_M.gguf")


@pytest.fixture()
def _patch_deps(monkeypatch):
    monkeypatch.setattr(
        "kaine.organ_server.lifecycle.locate_binary",
        lambda backend, override=None: FAKE_BINARY,
    )
    monkeypatch.setattr(
        "kaine.organ_server.served.served_gguf_path",
        lambda: FAKE_GGUF,
    )
    monkeypatch.setattr(
        "kaine.organ_server.served.detect_organ_backend",
        lambda backend=None: SimpleNamespace(backend="cuda", available=True),
    )


def _base_config(**overrides) -> dict:
    cfg: dict = {
        "language": {"model_id": "kaineone/Qwen3.5-4B-abliterated-GGUF", "chat_url": "http://127.0.0.1:11434/v1"},
        "residency": {"llm_proxy": "llama-swap", "ttl_seconds": 300},
    }
    for k, v in overrides.items():
        if k in cfg and isinstance(v, dict):
            cfg[k].update(v)
        else:
            cfg[k] = v
    return cfg


def test_none_when_proxy_disabled():
    config = {"residency": {"llm_proxy": "none"}}
    assert generate_llama_swap_config(config) is None


def test_none_when_residency_absent():
    config = {}
    assert generate_llama_swap_config(config) is None


@pytest.mark.usefixtures("_patch_deps")
def test_generates_config_with_defaults():
    result = generate_llama_swap_config(_base_config())
    assert result is not None
    assert isinstance(result, LlamaSwapConfig)
    assert len(result.models) == 1


@pytest.mark.usefixtures("_patch_deps")
def test_model_alias_matches_config():
    result = generate_llama_swap_config(_base_config())
    assert result is not None
    assert result.models[0].alias == "kaineone/Qwen3.5-4B-abliterated-GGUF"


@pytest.mark.usefixtures("_patch_deps")
def test_ttl_from_residency():
    result = generate_llama_swap_config(_base_config())
    assert result is not None
    assert result.models[0].ttl == 300


@pytest.mark.usefixtures("_patch_deps")
def test_ttl_override_for_language():
    config = _base_config()
    config["residency"]["ttl_overrides"] = {"language": 60}
    result = generate_llama_swap_config(config)
    assert result is not None
    assert result.models[0].ttl == 60


@pytest.mark.usefixtures("_patch_deps")
def test_exclusive_group_contains_all_models():
    result = generate_llama_swap_config(_base_config())
    assert result is not None
    assert "llm" in result.groups
    aliases = {m.alias for m in result.models}
    assert set(result.groups["llm"]) == aliases


@pytest.mark.usefixtures("_patch_deps")
def test_upstream_port_from_base():
    result = generate_llama_swap_config(_base_config())
    assert result is not None
    assert str(UPSTREAM_BASE_PORT) in result.models[0].cmd


@pytest.mark.usefixtures("_patch_deps")
def test_cmd_includes_gguf_path():
    result = generate_llama_swap_config(_base_config())
    assert result is not None
    assert str(FAKE_GGUF) in result.models[0].cmd


@pytest.mark.usefixtures("_patch_deps")
def test_cmd_sleep_idle_minus_one():
    result = generate_llama_swap_config(_base_config())
    assert result is not None
    assert "--sleep-idle-seconds -1" in result.models[0].cmd


@pytest.mark.usefixtures("_patch_deps")
def test_listen_port_from_chat_url():
    result = generate_llama_swap_config(_base_config())
    assert result is not None
    assert result.listen_port == 11434


@pytest.mark.usefixtures("_patch_deps")
def test_to_dict_yaml_serializable():
    result = generate_llama_swap_config(_base_config())
    assert result is not None
    d = result.to_dict()
    text = yaml.safe_dump(d)
    loaded = yaml.safe_load(text)
    assert "models" in loaded
    assert "groups" in loaded
    alias = result.models[0].alias
    assert alias in loaded["models"]
    assert loaded["groups"]["llm"]["swap"] is True
    assert alias in loaded["groups"]["llm"]["members"]


@pytest.mark.usefixtures("_patch_deps")
def test_write_creates_file(tmp_path):
    result = generate_llama_swap_config(_base_config())
    assert result is not None
    out = write_llama_swap_config(result, path=tmp_path / "llama-swap.yaml")
    assert out.exists()
    loaded = yaml.safe_load(out.read_text())
    assert result.models[0].alias in loaded["models"]


@pytest.mark.usefixtures("_patch_deps")
def test_none_when_no_model_id():
    config = _base_config()
    del config["language"]["model_id"]
    assert generate_llama_swap_config(config) is None


def test_none_when_no_binary(monkeypatch):
    monkeypatch.setattr(
        "kaine.organ_server.lifecycle.locate_binary",
        lambda backend, override=None: None,
    )
    monkeypatch.setattr(
        "kaine.organ_server.served.served_gguf_path",
        lambda: FAKE_GGUF,
    )
    monkeypatch.setattr(
        "kaine.organ_server.served.detect_organ_backend",
        lambda backend=None: SimpleNamespace(backend="cuda", available=True),
    )
    assert generate_llama_swap_config(_base_config()) is None
