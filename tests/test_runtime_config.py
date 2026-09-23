# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the runtime configuration layering (module profile + deployment tier).

These tests cover the structural fix that separates module selection from
deployment-tier backend bounds, and the related preboot / hardware / wizard
defects.
"""
from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import pytest

from kaine.config import ProfileError, load_runtime_config
from kaine.hardware import TierRecommendation
from kaine.setup.wizard import ACK_PHRASE, MODULE_ORDER, run_wizard

REPO_ROOT = Path(__file__).resolve().parent.parent
SHIPPED = REPO_ROOT / "config" / "kaine.toml"


def _shipped() -> dict[str, Any]:
    with SHIPPED.open("rb") as fh:
        return tomllib.load(fh)


def _host(*, cuda: int) -> dict[str, Any]:
    cuda_devices = [
        {
            "index": i,
            "device": f"cuda:{i}",
            "name": f"GPU{i}",
            "total_vram_gb": 24.0,
            "free_vram_gb": 20.0,
        }
        for i in range(cuda)
    ]
    return {
        "backend": "cuda" if cuda else "cpu",
        "device": "cuda" if cuda else "cpu",
        "cuda_devices": cuda_devices,
        "gpu_count": cuda,
        "cpu_count": 16,
    }


def _collect_out() -> tuple[list[str], callable]:
    buf: list[str] = []
    return buf, buf.append


class _Answers:
    def __init__(self, answers: list[str]):
        self._answers = list(answers)

    def __call__(self, prompt: str) -> str:
        if self._answers:
            return self._answers.pop(0)
        return ""


def _write_minimal_configs(tmp_path: Path, monkeypatch: Any) -> tuple[Path, Path]:
    shipped = tmp_path / "kaine.toml"
    shipped.write_text(
        '[modules]\nall_off = false\n[lingua]\nbackend = "ollama"\nmodel_id = "base"\n'
    )
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    (profiles / "thesis_test.toml").write_text(
        '[modules]\nsoma = true\nchronos = true\nlingua = false\n[lingua]\nmodel_id = "thesis-model"\n'
    )
    (profiles / "tier0.toml").write_text(
        '[tier]\nname = "tier0"\nunsupported_modules = []\noscillator_supported = true\n'
    )
    (profiles / "tier1.toml").write_text(
        '[tier]\nname = "tier1"\nunsupported_modules = []\noscillator_supported = true\n[lingua]\nbackend = "http"\n'
    )
    (profiles / "tier2.toml").write_text(
        '[tier]\nname = "tier2"\nunsupported_modules = []\noscillator_supported = true\n[lingua]\nbackend = "llama_cpp"\n'
    )
    (profiles / "tier3.toml").write_text(
        '[tier]\nname = "tier3"\nunsupported_modules = []\noscillator_supported = true\n[lingua]\nbackend = "datacenter"\n'
    )
    monkeypatch.setattr("kaine.config.PROFILES_DIR", profiles)
    return shipped, profiles


def test_load_runtime_config_default_thesis_test_plus_tier(monkeypatch, tmp_path: Path):
    """No explicit profile/env uses thesis_test, and the operator tier overlays it."""
    shipped, _profiles = _write_minimal_configs(tmp_path, monkeypatch)
    op = tmp_path / "kaine.operator.toml"
    op.write_text('[deployment]\ntier = "tier2"\n')

    cfg = load_runtime_config(shipped, op)

    # thesis_test's module set survives...
    assert cfg["modules"]["soma"] is True
    assert cfg["modules"]["chronos"] is True
    # ...while the tier bounds backends.
    assert cfg["lingua"]["backend"] == "llama_cpp"
    # Siblings from the module profile survive where the tier is silent.
    assert cfg["lingua"]["model_id"] == "thesis-model"


def test_load_runtime_config_env_profile_with_tier_overlay(monkeypatch, tmp_path: Path):
    shipped, _profiles = _write_minimal_configs(tmp_path, monkeypatch)
    op = tmp_path / "kaine.operator.toml"
    op.write_text('[deployment]\ntier = "tier2"\n')

    cfg = load_runtime_config(shipped, op, env={"KAINE_PROFILE": "tier1"})

    # tier1 module profile applies, but tier2 backend bound wins on top.
    assert cfg["lingua"]["backend"] == "llama_cpp"


def test_load_runtime_config_kaine_tier_overrides_overlay(monkeypatch, tmp_path: Path):
    shipped, _profiles = _write_minimal_configs(tmp_path, monkeypatch)
    op = tmp_path / "kaine.operator.toml"
    op.write_text('[deployment]\ntier = "tier2"\n')

    cfg = load_runtime_config(shipped, op, env={"KAINE_TIER": "tier1"})

    assert cfg["lingua"]["backend"] == "http"


def test_load_runtime_config_kaine_tier_equal_profile_refused_if_not_tier(monkeypatch, tmp_path: Path):
    """KAINE_TIER=thesis_test must be refused, not silently skipped because tier==profile."""
    shipped, _profiles = _write_minimal_configs(tmp_path, monkeypatch)
    with pytest.raises(ProfileError, match="thesis_test is not a deployment tier"):
        load_runtime_config(shipped, tmp_path / "no-operator.toml", env={"KAINE_TIER": "thesis_test"})


def test_load_runtime_config_kaine_tier_module_profile_refused(monkeypatch, tmp_path: Path):
    """A module-selection profile used as a tier must be refused."""
    shipped, profiles = _write_minimal_configs(tmp_path, monkeypatch)
    (profiles / "module_profile.toml").write_text("[modules]\nlingua = true\n")
    with pytest.raises(ProfileError, match="module_profile is not a deployment tier"):
        load_runtime_config(shipped, tmp_path / "no-operator.toml", env={"KAINE_TIER": "module_profile"})


def test_load_runtime_config_invalid_tier_slug_raises(monkeypatch, tmp_path: Path):
    shipped, _profiles = _write_minimal_configs(tmp_path, monkeypatch)
    op = tmp_path / "kaine.operator.toml"
    op.write_text('[deployment]\ntier = "bad/slug"\n')

    with pytest.raises(ProfileError):
        load_runtime_config(shipped, op)


def test_real_thesis_test_plus_tier0_preserves_module_set(tmp_path: Path):
    """Recording a tier must never change which modules are enabled."""
    cfg_with_tier = load_runtime_config(
        SHIPPED,
        tmp_path / "no-operator.toml",
        env={"KAINE_TIER": "tier0"},
        profiles_dir=REPO_ROOT / "config" / "profiles",
    )
    cfg_thesis_only = load_runtime_config(
        SHIPPED,
        tmp_path / "no-operator-2.toml",
        env={},
        profiles_dir=REPO_ROOT / "config" / "profiles",
    )
    assert cfg_with_tier["modules"] == cfg_thesis_only["modules"]


def test_load_runtime_config_tier_with_modules_table_raises(monkeypatch, tmp_path: Path):
    """A tier file containing a [modules] table must raise ProfileError."""
    shipped, profiles = _write_minimal_configs(tmp_path, monkeypatch)
    (profiles / "tier0.toml").write_text(
        '[tier]\nname = "tier0"\nunsupported_modules = []\noscillator_supported = true\n[modules]\nlingua = false\n'
    )

    with pytest.raises(ProfileError, match="tier 'tier0' may not set module toggles"):
        load_runtime_config(
            shipped,
            tmp_path / "no-operator.toml",
            env={"KAINE_TIER": "tier0"},
        )


def test_load_runtime_config_tier_with_oscillator_enabled_raises(monkeypatch, tmp_path: Path):
    """A tier file containing [oscillator].enabled must raise ProfileError."""
    shipped, profiles = _write_minimal_configs(tmp_path, monkeypatch)
    (profiles / "tier0.toml").write_text(
        '[tier]\nname = "tier0"\nunsupported_modules = []\noscillator_supported = true\n[oscillator]\nenabled = false\n'
    )

    with pytest.raises(ProfileError, match="tier 'tier0' may not set module toggles"):
        load_runtime_config(
            shipped,
            tmp_path / "no-operator.toml",
            env={"KAINE_TIER": "tier0"},
        )


def test_preboot_uses_load_runtime_config(monkeypatch):
    """The pre-boot dry run loads the same config path the cycle boots with."""
    import kaine.preboot as preboot_mod

    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def fake_load_runtime_config(*args, **kwargs):
        calls.append((args, kwargs))
        return {
            "modules": {"soma": True},
            "preservation": {},
            "security": {"state_encryption": {"enabled": False}},
        }

    async def fake_checks(_config):
        return []

    monkeypatch.setattr(preboot_mod, "load_runtime_config", fake_load_runtime_config)
    monkeypatch.setattr(preboot_mod, "run_async_checks", fake_checks)
    monkeypatch.setattr(preboot_mod, "check_config_sanity", lambda _config: [])

    rc = preboot_mod.main([])
    assert rc == 0
    assert len(calls) == 1
    assert calls[0][0] == (preboot_mod.SHIPPED_CONFIG_PATH, preboot_mod.OPERATOR_CONFIG_PATH)
    # load_kaine_config is no longer imported here.
    assert not hasattr(preboot_mod, "load_kaine_config")


def test_classify_memory_discrete_without_vram_total_is_unknown(monkeypatch):
    """A discrete device that reports no VRAM total must not undercount to 0."""
    from kaine import hardware, hostmem

    def fake_classify(index, torch=None):
        return hostmem.MemoryClassification(
            state="discrete",
            pools=(
                hostmem.Pool(
                    kind="system",
                    total_bytes=int(64 * 1024 ** 3),
                    available_bytes=int(32 * 1024 ** 3),
                    provenance="mock",
                    unknown_reason=None,
                ),
            ),
            evidence="mock",
            unknown_reason=None,
        )

    monkeypatch.setattr(hostmem, "classify_accelerator_memory", fake_classify)
    state, vram = hardware._classify_memory(gpu_count=1)
    assert state == "unknown"
    assert vram is None


def test_recommend_tier_supplied_memory_state_does_not_probe_vram(monkeypatch):
    """When the caller supplies memory_state, the live VRAM probe is skipped."""
    from kaine import hardware, hostmem

    monkeypatch.setattr(
        hostmem,
        "classify_accelerator_memory",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("live probe called")),
    )
    rec = hardware.recommend_tier(
        torch_ok=True,
        ram_gb=16.0,
        gpu_count=1,
        accelerator="cuda",
        memory_state="discrete",
    )
    assert rec.memory_state == "discrete"
    assert rec.memory_budget_gb == 16.0
    assert rec.memory_budget_gb is not None
    assert rec.memory_budget_gb != 0


def _tier2_rec() -> TierRecommendation:
    return TierRecommendation(
        tier=2,
        reason="8 GB unified accelerator; module residency required",
        total_ram_gb=8.0,
        cpu_arch="aarch64",
        accelerator="cuda",
        torch_importable=True,
        gpu_count=1,
        memory_budget_gb=8.0,
        memory_state="unified",
        residency_required=True,
    )


def test_wizard_accepting_tier_writes_deployment_tier():
    answers = [ACK_PHRASE, "y", "y"] + ["n"] * len(MODULE_ORDER) + ["n", "n"]
    a = _Answers(answers)
    out, sink = _collect_out()
    result = run_wizard(
        input_fn=a,
        out=sink,
        host=_host(cuda=1),
        shipped_config=_shipped(),
        recommend_tier_fn=lambda: _tier2_rec(),
    )
    assert result.config["deployment"]["tier"] == "tier2"
    assert "profile" not in result.config.get("deployment", {})


def test_wizard_declining_tier_writes_nothing():
    answers = [ACK_PHRASE, "y", "n"] + ["n"] * len(MODULE_ORDER) + ["n", "n"]
    a = _Answers(answers)
    out, sink = _collect_out()
    result = run_wizard(
        input_fn=a,
        out=sink,
        host=_host(cuda=1),
        shipped_config=_shipped(),
        recommend_tier_fn=lambda: _tier2_rec(),
    )
    assert "deployment" not in result.config
