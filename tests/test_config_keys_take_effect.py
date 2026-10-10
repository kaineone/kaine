# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests that accepted configuration keys actually take effect (or are refused)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest

from kaine.boot import _resolve_job_queue_trainer, make_hypnos, make_mundus, make_topos
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.cycle.__main__ import _apply_log_level
from kaine.modules.hypnos.voice_alignment import VoiceAlignmentConfig
from kaine.modules.topos.internvideo_next_loader import PINNED_REVISION


def _bus() -> AsyncBus:
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    return AsyncBus(BusConfig(password="x", audit_required=False), client=client)


@pytest.fixture
def bus() -> AsyncBus:
    return _bus()


def _voice_cfg(tmp_path: Path, **over: Any) -> VoiceAlignmentConfig:
    probe = tmp_path / "probe.jsonl"
    probe.write_text(
        json.dumps({"prompt": "p", "deflection_patterns": ["I cannot"]}) + "\n",
        encoding="utf-8",
    )
    base = dict(
        intent_log_path=tmp_path / "intent.jsonl",
        adapter_output_dir=tmp_path / "adapters",
        enabled=True,
        base_model_path=str(tmp_path / "base"),
        trainer_backend="job_queue",
        trainer_jobs_dir=str(tmp_path / "jobs"),
        trainer_timeout_s=300.0,
        abliteration_probe_path=str(probe),
        hot_swap_mode="organ_adapter",
        organ_url="http://organ:8080",
        organ_adapters_dir=str(tmp_path / "organ_adapters"),
    )
    base.update(over)
    return VoiceAlignmentConfig(**base)


def test_make_hypnos_honours_requested_rest_min_interval_s(bus: AsyncBus) -> None:
    hypnos = make_hypnos(bus, {"requested_rest_min_interval_s": 600})
    assert hypnos._requested_rest_min_interval_s == 600.0


def test_make_hypnos_rejects_non_positive_requested_rest_interval_s(
    bus: AsyncBus,
) -> None:
    with pytest.raises(ValueError, match="must be a number greater than 0"):
        make_hypnos(bus, {"requested_rest_min_interval_s": 0})


def test_resolve_job_queue_trainer_reads_lingua_api_key_from_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("KAINE_MODEL_SERVER_API_KEY", raising=False)
    cfg = _voice_cfg(tmp_path)
    trainer = _resolve_job_queue_trainer(
        cfg,
        {"lingua": {"api_key": "cfg-key", "chat_url": "http://organ:8080/v1"}},
    )
    assert trainer._organ_api_key == "cfg-key"


def test_resolve_job_queue_trainer_falls_back_to_env_when_config_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KAINE_MODEL_SERVER_API_KEY", "env-key")
    cfg = _voice_cfg(tmp_path, organ_url="")
    trainer = _resolve_job_queue_trainer(
        cfg,
        {"lingua": {"api_key": "", "chat_url": ""}},
    )
    assert trainer._organ_api_key == "env-key"


def test_make_topos_honours_habituation_window(bus: AsyncBus) -> None:
    topos = make_topos(bus, {"habituation_window": 8})
    assert topos._habituator.window == 8


def test_make_topos_rejects_too_small_habituation_window(bus: AsyncBus) -> None:
    with pytest.raises(ValueError, match="must be an integer of at least 2"):
        make_topos(bus, {"habituation_window": 1})


def test_make_topos_rejects_non_pinned_encoder_revision(bus: AsyncBus) -> None:
    with pytest.raises(ValueError, match="does not match the pinned"):
        make_topos(bus, {"encoder_revision": "not-the-pin"})


def test_make_topos_accepts_pinned_encoder_revision(bus: AsyncBus) -> None:
    topos = make_topos(bus, {"encoder_revision": PINNED_REVISION})
    assert topos.name == "topos"


def test_apply_log_level_sets_root_logger() -> None:
    root = logging.getLogger()
    previous = root.level
    try:
        _apply_log_level({"logging": {"level": "debug"}})
        assert root.level == logging.DEBUG
    finally:
        root.setLevel(previous)


def test_apply_log_level_rejects_invalid_level() -> None:
    with pytest.raises(ValueError, match="must be one of"):
        _apply_log_level({"logging": {"level": "LOUD"}})


def test_make_mundus_routes_expose_keys_by_capabilities(bus: AsyncBus) -> None:
    m = make_mundus(
        bus,
        {
            "adapter": "stub",
            "stub": {"expose_drive": True, "expose_say": False},
        },
    )
    assert m._continuous_expose["drive"] is True
    assert m._continuous_expose["yaw_rate"] is False
    assert m._expose["say"] is False


def test_make_mundus_rejects_unknown_expose_key(bus: AsyncBus) -> None:
    with pytest.raises(ValueError, match="expose_drvie"):
        make_mundus(
            bus,
            {"adapter": "stub", "stub": {"expose_drvie": True}},
        )


@pytest.mark.parametrize("bad", [float("nan"), True, "600", -5])
def test_make_hypnos_rejects_non_numeric_or_non_finite_interval(
    bus: AsyncBus, bad: Any
) -> None:
    with pytest.raises(ValueError, match="must be a number greater than 0"):
        make_hypnos(bus, {"requested_rest_min_interval_s": bad})
