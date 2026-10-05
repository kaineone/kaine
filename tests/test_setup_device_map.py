# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the setup device-map helpers."""

import stat
from pathlib import Path

from kaine.organ_server.device_map import (
    check_agreement,
    compose_gpu_env,
    cuda_index,
    native_organ_env,
    write_env_values,
)
from kaine.setup import wizard as wizard_module
from kaine.setup.steps import Step


def test_cuda_index():
    assert cuda_index("cuda:0") == 0
    assert cuda_index("cuda:10") == 10
    assert cuda_index("xpu:0") is None
    assert cuda_index("cpu") is None
    assert cuda_index("rocm:0") is None
    assert cuda_index("") is None


def test_compose_gpu_env_basic():
    devmap = {"organ": "cuda:0", "vision": "cuda:1"}
    assert compose_gpu_env(devmap) == {
        "KAINE_ORGAN_GPU": "0",
        "KAINE_VISION_GPU": "1",
    }


def test_compose_gpu_env_ignores_non_cuda_roles():
    devmap = {"organ": "xpu:0", "vision": "cpu"}
    assert compose_gpu_env(devmap) == {}


def test_native_organ_env():
    assert native_organ_env({"organ": "cuda:2"}) == {"CUDA_VISIBLE_DEVICES": "2"}
    assert native_organ_env({"organ": "cpu", "vision": "cuda:0"}) == {}
    assert native_organ_env({}) == {}


def test_write_env_values_preserves_secrets_and_comments(tmp_path):
    path = tmp_path / ".env"
    path.write_text(
        "# comment line\n"
        "KAINE_REDIS_PASSWORD=s3cret\n"
        "KAINE_ORGAN_GPU=0\n",
        encoding="utf-8",
    )
    path.chmod(0o600)

    write_env_values(path, {"KAINE_ORGAN_GPU": "3", "KAINE_VISION_GPU": "1"})

    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "# comment line"
    assert lines[1] == "KAINE_REDIS_PASSWORD=s3cret"
    assert lines[2] == "KAINE_ORGAN_GPU=3"
    assert lines[3] == "KAINE_VISION_GPU=1"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_check_agreement_skip_without_map():
    assert check_agreement({}, env_path=Path("compose/.env")) == (
        "skip",
        "no [hardware.devices] device map",
    )


def test_check_agreement_pass(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "KAINE_ORGAN_GPU=0\n"
        "KAINE_VISION_GPU=1\n",
        encoding="utf-8",
    )
    config = {
        "hardware": {"devices": {"organ": "cuda:0", "vision": "cuda:1"}},
        "hypnos": {"voice_alignment": {"training_device": "cuda:0"}},
        "topos": {"device": "cuda:1"},
    }
    assert check_agreement(config, env_path=env_path) == (
        "pass",
        "device map agrees with compose and the cycle's device keys",
    )


def test_check_agreement_fail_env_mismatch(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("KAINE_ORGAN_GPU=1\n", encoding="utf-8")
    config = {"hardware": {"devices": {"organ": "cuda:0"}}}
    status, detail = check_agreement(config, env_path=env_path)
    assert status == "fail"
    assert "KAINE_ORGAN_GPU=1" in detail
    assert "[hardware.devices].organ = cuda:0" in detail


def test_check_agreement_fail_key_mismatch(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "KAINE_ORGAN_GPU=0\n"
        "KAINE_VISION_GPU=1\n",
        encoding="utf-8",
    )
    config = {
        "hardware": {"devices": {"organ": "cuda:0", "vision": "cuda:1"}},
        "topos": {"device": "cuda:2"},
    }
    status, detail = check_agreement(config, env_path=env_path)
    assert status == "fail"
    assert "topos.device = cuda:2" in detail
    assert "[hardware.devices].vision = cuda:1" in detail


def test_check_device_map_returns_named_row():
    from kaine.preboot import check_device_map

    rows = check_device_map({})
    assert len(rows) == 1
    assert rows[0].name == "Device map"


def _noop_step():
    return Step(
        id="noop",
        title="noop",
        explanation=lambda _ctx: [],
        fields=lambda _ctx: (),
        applies=lambda _ctx: False,
        apply=lambda _ctx, _answers: None,
    )


def test_wizard_records_device_map_and_shared_service():
    import tomllib

    from kaine.setup.wizard import ACK_PHRASE

    repo = Path(__file__).resolve().parents[1]
    with (repo / "config" / "kaine.toml").open("rb") as fh:
        shipped = tomllib.load(fh)
    host = {
        "backend": "cuda",
        "device": "cuda",
        "cpu_count": 16,
        "gpu_count": 2,
        "cuda_devices": [
            {"index": i, "device": f"cuda:{i}", "name": f"GPU{i}",
             "total_vram_gb": 24.0, "free_vram_gb": 20.0}
            for i in range(2)
        ],
    }
    prompts: list[str] = []

    def input_fn(prompt: str) -> str:
        prompts.append(prompt)
        assert len(prompts) < 200, "the wizard kept re-asking"
        if ACK_PHRASE in prompt:
            return ACK_PHRASE
        if "chatterbox" in prompt.lower() and "shared" in prompt.lower():
            return "y"
        return ""

    def out(_line):
        return None

    result = wizard_module.run_wizard(
        input_fn=input_fn,
        out=out,
        host=host,
        shipped_config=shipped,
        services_up_fn=lambda: {"chatterbox": True, "speaches": False, "model_server": False},
    )

    assert result.config["hardware"]["devices"] == {"organ": "cuda:0", "vision": "cuda:1"}
    assert result.config["services"]["chatterbox"]["shared"] is True
    assert "model_server" not in result.config.get("services", {})
    assert "speaches" not in result.config.get("services", {})
