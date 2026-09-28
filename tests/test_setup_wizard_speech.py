# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Backend-aware wizard tests for speech organs and extras."""

from __future__ import annotations

import inspect
from typing import Any

import pytest

from kaine.setup import wizard


def _call_wizard(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
    host: dict[str, Any],
    *,
    defaults: bool = True,
) -> tuple[Any, list[str]]:
    lines: list[str] = []

    fn = getattr(wizard, "run_setup_wizard", None)
    if fn is None:
        pytest.skip("wizard.run_setup_wizard is not available")

    sig = inspect.signature(fn)
    kwargs: dict[str, Any] = {
        "input_fn": lambda prompt: "",
        "line": lines.append,
        "host": host,
        "defaults": defaults,
    }
    for name, default in (
        ("probe_services", None),
        ("probe_trainer", None),
        ("guidance_fn", None),
        ("operator_path", tmp_path / "operator.toml"),
    ):
        if name in sig.parameters:
            kwargs[name] = default

    result = fn(**kwargs)
    if isinstance(result, tuple):
        return result[0], lines
    return result, lines


@pytest.mark.parametrize(
    ("modules", "shipped", "expected"),
    [
        ({"nous": True}, {"nous": {"backend": "pymdp"}}, ["reasoning"]),
        ({"nous": True}, {"nous": {"backend": "numpy"}}, []),
        (
            {"phantasia": True},
            {"phantasia": {"backend": "dreamerv3", "engine": "jax"}},
            ["worldmodel"],
        ),
        (
            {"phantasia": True},
            {"phantasia": {"backend": "dreamerv3", "engine": "numpy"}},
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
        ({"vox": True}, {"vox": {"backend": "sherpa_onnx"}}, ["speech-edge"]),
        ({"vox": True}, {"vox": {"backend": "chatterbox"}}, []),
        (
            {"audition": True, "vox": True},
            {
                "audition": {
                    "backend": "sherpa_onnx",
                    "transcription_enabled": True,
                },
                "vox": {"backend": "sherpa_onnx"},
            },
            ["speech-edge"],
        ),
    ],
)
def test_implied_extras(modules: dict[str, bool], shipped: dict[str, Any], expected: list[str]) -> None:
    assert wizard.implied_extras(modules, shipped) == expected


def test_defaults_keeps_vox_enabled_with_sherpa_backend(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.setattr(wizard, "DEFAULT_MODULE_SET", {"vox": True})
    host = {
        "target": {"name": "desktop-cpu"},
        "shipped_config": {"vox": {"backend": "sherpa_onnx"}},
    }
    cfg, lines = _call_wizard(monkeypatch, tmp_path, host, defaults=True)
    assert cfg["modules"]["vox"] is True
    assert any("sherpa-onnx Kokoro" in line for line in lines)
    assert not any("no voice id available" in line for line in lines)
    assert "predefined_voice_id" not in cfg.get("vox", {})


def test_defaults_disables_vox_when_chatterbox_has_no_voice(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.setattr(wizard, "DEFAULT_MODULE_SET", {"vox": True})
    host = {
        "target": {"name": "desktop-cpu"},
        "shipped_config": {
            "vox": {"backend": "chatterbox", "predefined_voice_id": ""}
        },
    }
    cfg, lines = _call_wizard(monkeypatch, tmp_path, host, defaults=True)
    assert cfg["modules"]["vox"] is False
    assert any("no voice id available" in line for line in lines)
