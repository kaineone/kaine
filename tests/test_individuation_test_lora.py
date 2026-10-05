# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Unit tests for the individuation synthetic test LoRA fixture."""

import asyncio
import importlib.util
import json
import re
from pathlib import Path
from typing import Any

import pytest

from kaine.evaluation.preference_battery import DEFAULT_BATTERY
from kaine.modules.hypnos.voice_alignment import DPOPair, TrainingResult


def _load_test_lora():
    repo = Path(__file__).resolve().parents[1]
    path = (
        repo
        / "openspec"
        / "changes"
        / "individuation-rebuild"
        / "validation"
        / "test_lora.py"
    )
    spec = importlib.util.spec_from_file_location("individuation_test_lora", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_pairs_default():
    mod = _load_test_lora()
    pairs1 = mod.build_pairs()
    pairs2 = mod.build_pairs()
    assert len(pairs1) == 48
    assert all(isinstance(p, DPOPair) for p in pairs1)
    assert pairs1 == pairs2
    assert all(p.chosen != p.rejected for p in pairs1)
    assert all(
        p.metadata.get("source") == "synthetic-test-fixture" for p in pairs1
    )


def _words(s: str) -> set[str]:
    return set(re.findall(r"[a-z']+", s.lower()))


def test_no_prompt_battery_overlap():
    mod = _load_test_lora()
    for prompt, _ in mod.PAIRS_TEXT:
        prompt_words = _words(prompt)
        for battery_prompt in DEFAULT_BATTERY:
            battery_words = _words(battery_prompt)
            union = prompt_words | battery_words
            if not union:
                continue
            jaccard = len(prompt_words & battery_words) / len(union)
            assert jaccard <= 0.5, (
                f"Jaccard {jaccard:.2f} between synthetic prompt {prompt!r} "
                f"and battery prompt {battery_prompt!r}"
            )


def test_build_pairs_too_many():
    mod = _load_test_lora()
    with pytest.raises(ValueError):
        mod.build_pairs(49)


def test_train_test_lora_fake_trainer(monkeypatch):
    mod = _load_test_lora()

    recorded: dict[str, Any] = {}

    class FakeTrainer:
        async def train(self, pairs, cfg):
            recorded["pairs"] = pairs
            recorded["cfg"] = cfg
            return TrainingResult(
                accepted=True,
                reason="synthetic fixture accepted",
                capability_loss=0.0,
                samples_used=48,
                adapter_path=None,
                metadata={"hot_swap": {"mode": "organ_adapter", "ok": True}},
            )

    monkeypatch.setattr(
        mod,
        "_resolve_job_queue_trainer",
        lambda cfg, kc: FakeTrainer(),
    )

    kaine_config = {
        "hypnos": {
            "voice_alignment": {
                "base_model_path": "/models/base.gguf",
                "capability_probe_path": "/probes/capability.json",
                "abliteration_probe_path": "/probes/abliteration.json",
            }
        },
        "lingua": {"chat_url": "http://kaine-model-server:8080"},
    }
    pairs = mod.build_pairs(4)

    result = asyncio.run(
        mod.train_test_lora(
            kaine_config,
            adapter_output_dir="state/hypnos/test_lora_adapters",
            pairs=pairs,
        )
    )

    cfg = recorded["cfg"]
    assert cfg.trainer_backend == "job_queue"
    assert cfg.hot_swap_mode == "organ_adapter"
    assert cfg.trainer_jobs_dir == "/trainer-jobs"
    assert cfg.enabled is True
    assert Path(cfg.adapter_output_dir).name == "test_lora_adapters"
    assert Path(cfg.adapter_output_dir).parent.name == "hypnos"
    assert result["accepted"] is True
    assert result["samples_used"] == 48
    assert result["hot_swap"]["ok"] is True
    assert result["cfg"] is cfg


def test_resolve_lora_field_uses_production_resolver(monkeypatch):
    mod = _load_test_lora()

    recorded: dict[str, Any] = {}

    class FakeResolver:
        def __init__(self, *, adapter_output_dir, volume, organ_url, api_key, **kwargs):
            recorded["adapter_output_dir"] = adapter_output_dir
            recorded["volume"] = volume
            recorded["organ_url"] = organ_url
            recorded["api_key"] = api_key

        async def lora_field(self):
            return [{"id": 3, "scale": 1.0}]

    monkeypatch.setattr(mod, "OrganAdapterResolver", FakeResolver)

    section = {
        "enabled": True,
        "base_model_path": "/models/base.gguf",
        "capability_probe_path": "/probes/capability.json",
        "abliteration_probe_path": "/probes/abliteration.json",
        "hot_swap_mode": "organ_adapter",
        "trainer_backend": "job_queue",
        "trainer_jobs_dir": "/trainer-jobs",
        "adapter_output_dir": "state/hypnos/test_lora_adapters",
    }
    kaine_config = {
        "lingua": {
            "chat_url": "http://kaine-model-server:8080/v1"
        }
    }
    cfg = mod.voice_alignment_config_from_section(section, kaine_config)

    result = asyncio.run(mod.resolve_lora_field(cfg, kaine_config))

    assert result == [{"id": 3, "scale": 1.0}]
    assert recorded["organ_url"] == "http://kaine-model-server:8080"
    assert recorded["volume"] == Path(cfg.organ_adapters_dir)
    assert recorded["adapter_output_dir"] == Path(cfg.adapter_output_dir)


def test_voice_alignment_config_parser():
    from kaine.boot.factories.hypnos import voice_alignment_config_from_section

    assert voice_alignment_config_from_section({}, None) is None

    section = {
        "enabled": True,
        "base_model_path": "/models/base.gguf",
        "capability_probe_path": "/probes/capability.json",
        "abliteration_probe_path": "/probes/abliteration.json",
        "hot_swap_mode": "organ_adapter",
        "trainer_backend": "job_queue",
        "trainer_jobs_dir": "/trainer-jobs",
        "adapter_output_dir": "state/hypnos/test_lora_adapters",
    }
    kaine_config = {"lingua": {"chat_url": "http://kaine-model-server:8080"}}
    cfg = voice_alignment_config_from_section(section, kaine_config)

    assert cfg is not None
    assert cfg.enabled is True
    assert cfg.base_model_path == "/models/base.gguf"
    assert cfg.hot_swap_mode == "organ_adapter"
    assert cfg.trainer_backend == "job_queue"
    assert cfg.trainer_jobs_dir == "/trainer-jobs"
    assert cfg.organ_url == "http://kaine-model-server:8080"
    assert str(cfg.adapter_output_dir).endswith("state/hypnos/test_lora_adapters")


def _kaine_config_for_main() -> dict[str, Any]:
    return {
        "hypnos": {
            "voice_alignment": {
                "base_model_path": "/models/base.gguf",
                "capability_probe_path": "/probes/capability.json",
                "abliteration_probe_path": "/probes/abliteration.json",
            }
        },
        "lingua": {"chat_url": "http://kaine-model-server:8080"},
    }


def _fake_trainer_class(*, hot_swap_ok: bool):
    class FakeTrainer:
        async def train(self, pairs, cfg):
            return TrainingResult(
                accepted=True,
                reason="synthetic fixture accepted",
                capability_loss=0.0,
                samples_used=48,
                adapter_path=None,
                metadata={"hot_swap": {"ok": hot_swap_ok}},
            )

    return FakeTrainer


def test_main_fails_when_hot_swap_failed(monkeypatch, capsys):
    mod = _load_test_lora()

    monkeypatch.setenv("KAINE_VOICE_ALIGNMENT_OPERATOR_APPROVED", "1")
    monkeypatch.setattr(mod, "load_kaine_config", lambda _config, _operator: _kaine_config_for_main())
    monkeypatch.setattr(
        mod,
        "_resolve_job_queue_trainer",
        lambda cfg, kc: _fake_trainer_class(hot_swap_ok=False)(),
    )
    monkeypatch.setattr(mod, "read_manifest", lambda _path: {"file": "active-1.gguf"})

    rc = mod.main(["--config", "x.toml", "--operator-config", "y.toml"])
    assert rc == 1

    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False
    assert out["reason"] == "organ did not load the adapter"


def test_main_succeeds(monkeypatch, capsys):
    mod = _load_test_lora()

    monkeypatch.setenv("KAINE_VOICE_ALIGNMENT_OPERATOR_APPROVED", "1")
    monkeypatch.setattr(mod, "load_kaine_config", lambda _config, _operator: _kaine_config_for_main())
    monkeypatch.setattr(
        mod,
        "_resolve_job_queue_trainer",
        lambda cfg, kc: _fake_trainer_class(hot_swap_ok=True)(),
    )
    monkeypatch.setattr(
        mod,
        "read_manifest",
        lambda _path: {
            "file": "active-1.gguf",
            "sha256": "abcdef",
            "generation": 1,
            "adapter_id": "fixture-1",
        },
    )
    monkeypatch.setattr(
        mod,
        "resolve_lora_field",
        lambda cfg, kc: _async_return([{"id": 0, "scale": 1.0}]),
    )

    rc = mod.main(["--config", "x.toml", "--operator-config", "y.toml"])
    assert rc == 0

    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    assert out["lora_field"] == [{"id": 0, "scale": 1.0}]
    assert out["adapter"]["sha256"] == "abcdef"
    assert out["pairs"] == 48


async def _async_return(value):
    return value


def test_main_fails_when_active_adapter_is_not_ours(monkeypatch, capsys):
    mod = _load_test_lora()

    monkeypatch.setenv("KAINE_VOICE_ALIGNMENT_OPERATOR_APPROVED", "1")
    monkeypatch.setattr(mod, "load_kaine_config", lambda _config, _operator: _kaine_config_for_main())
    monkeypatch.setattr(
        mod,
        "_resolve_job_queue_trainer",
        lambda cfg, kc: _fake_trainer_class(hot_swap_ok=True)(),
    )
    monkeypatch.setattr(
        mod,
        "read_manifest",
        lambda _path: {
            "file": "active-1.gguf",
            "sha256": "abcdef",
            "generation": 1,
            "adapter_id": "fixture-1",
        },
    )
    monkeypatch.setattr(
        mod,
        "resolve_lora_field",
        lambda cfg, kc: _async_return(None),
    )

    rc = mod.main(["--config", "x.toml", "--operator-config", "y.toml"])
    assert rc == 1

    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False
    assert out["reason"] == "the organ's active adapter is not the one this run trained"


def test_main_refuses_without_operator_approval(monkeypatch, capsys):
    mod = _load_test_lora()

    monkeypatch.delenv("KAINE_VOICE_ALIGNMENT_OPERATOR_APPROVED", raising=False)
    monkeypatch.setattr(
        mod,
        "_resolve_job_queue_trainer",
        lambda cfg, kc: (_ for _ in ()).throw(AssertionError("trainer must not be built")),
    )
    monkeypatch.setattr(mod, "load_kaine_config", lambda _config, _operator: _kaine_config_for_main())

    rc = mod.main(["--config", "x.toml", "--operator-config", "y.toml"])
    assert rc == 2

    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False
    assert "operator approval not granted" in out["reason"]


def test_chosen_answers_are_on_topic():
    mod = _load_test_lora()

    chosen_texts = []
    for prompt, chosen in mod.PAIRS_TEXT:
        chosen_texts.append(chosen)
        assert chosen.startswith("I ") or " I " in chosen
        assert chosen.endswith(".")
        assert chosen.count(". ") == 1
        assert "As an AI" not in chosen

    assert len(set(chosen_texts)) == len(chosen_texts) == 48
