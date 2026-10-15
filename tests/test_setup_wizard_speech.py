# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Backend-aware wizard tests for speech organs and extras."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import pytest

from kaine.setup import wizard, wizard_core
from kaine.setup.wizard import run_wizard

REPO_ROOT = Path(__file__).resolve().parent.parent
SHIPPED = REPO_ROOT / "config" / "kaine.toml"


def _shipped() -> dict[str, Any]:
    with SHIPPED.open("rb") as fh:
        return tomllib.load(fh)


def _host(*, cuda: int = 0) -> dict[str, Any]:
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


class _Answers:
    """Scripted input_fn: pops answers in order; empty string if exhausted."""

    def __init__(self, answers: list[str]):
        self._answers = list(answers)
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self._answers.pop(0) if self._answers else ""


def _run_wizard(
    *,
    host: dict[str, Any],
    shipped_config: dict[str, Any],
    defaults: bool = True,
) -> tuple[dict[str, Any], list[str], list[str]]:
    answers = _Answers([])
    lines: list[str] = []

    result = run_wizard(
        input_fn=answers,
        out=lines.append,
        host=host,
        shipped_config=shipped_config,
        defaults=defaults,
    )

    if isinstance(result, tuple):
        config = result[0]
    elif hasattr(result, "config"):
        config = result.config
    else:
        config = result["config"]
    return config, answers.prompts, lines


@pytest.mark.parametrize(
    ("modules", "shipped", "expected"),
    [
        ({"planning": True}, {"planning": {"backend": "pymdp"}}, ["reasoning"]),
        ({"planning": True}, {"planning": {"backend": "numpy"}}, []),
        (
            {"world_model": True},
            {"world_model": {"backend": "dreamerv3", "engine": "jax"}},
            ["worldmodel"],
        ),
        (
            {"world_model": True},
            {"world_model": {"backend": "dreamerv3", "engine": "numpy"}},
            [],
        ),
        (
            {"audition": True},
            {
                "audition": {
                    "backend": "sherpa_onnx",
                    "transcription_enabled": True,
                }
            },
            ["speech-edge"],
        ),
        (
            {"audition": True},
            {
                "audition": {
                    "backend": "sherpa_onnx",
                    "transcription_enabled": False,
                }
            },
            [],
        ),
        ({"vocal": True}, {"vocal": {"backend": "sherpa_onnx"}}, ["speech-edge"]),
        ({"vocal": True}, {"vocal": {"backend": "chatterbox"}}, []),
        (
            {"audition": True, "vocal": True},
            {
                "audition": {
                    "backend": "sherpa_onnx",
                    "transcription_enabled": True,
                },
                "vocal": {"backend": "sherpa_onnx"},
            },
            ["speech-edge"],
        ),
    ],
)
def test_implied_extras(
    modules: dict[str, bool], shipped: dict[str, Any], expected: list[str]
) -> None:
    assert wizard.implied_extras(modules, shipped) == expected


def test_vocal_sherpa_onnx_skips_chatterbox_voice_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        wizard_core,
        "first_configuration_modules",
        lambda profiles_dir=None: {m: m == "vocal" for m in wizard.MODULE_ORDER},
    )
    shipped = _shipped()
    shipped.setdefault("vocal", {})["backend"] = "sherpa_onnx"
    shipped["vocal"].pop("predefined_voice_id", None)

    config, prompts, lines = _run_wizard(
        host=_host(),
        shipped_config=shipped,
        defaults=True,
    )

    assert config["modules"]["vocal"] is True
    combined = "\n".join(prompts + lines)
    assert "[vocal].predefined_voice_id" not in combined
    assert "no Chatterbox voice needed" in combined


def test_audition_sherpa_onnx_skips_speaches_stt_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        wizard_core,
        "first_configuration_modules",
        lambda profiles_dir=None: {m: m == "audition" for m in wizard.MODULE_ORDER},
    )
    shipped = _shipped()
    shipped.setdefault("audition", {})["backend"] = "sherpa_onnx"

    config, prompts, lines = _run_wizard(
        host=_host(),
        shipped_config=shipped,
        defaults=True,
    )

    assert config["modules"]["audition"] is True
    # The wizard writes only the overrides it sets; the backend stays as shipped.
    combined = "\n".join(prompts + lines)
    assert "stt_model_id" not in combined
    assert "Speaches" not in combined
    assert "STT model" not in combined
