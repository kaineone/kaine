# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for wizard module presets (base thesis / full entity)."""
from __future__ import annotations

import io
import tomllib
import types
from pathlib import Path

import pytest

from kaine import config as kaine_config
from kaine.setup.wizard import (
    ACK_PHRASE,
    FULL_ENTITY_MODULES,
    MODULE_ORDER,
    base_thesis_modules,
    recommend_preset,
    run_wizard,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
SHIPPED = REPO_ROOT / "config" / "kaine.toml"


def _shipped() -> dict:
    with SHIPPED.open("rb") as fh:
        return tomllib.load(fh)


def _host(*, cuda: int = 0) -> dict:
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
        if self._answers:
            return self._answers.pop(0)
        return ""


def _collect_out():
    buf = io.StringIO()

    def sink(text: str = "") -> None:
        buf.write(text + "\n")

    def getvalue() -> str:
        return buf.getvalue()

    return getvalue, sink


def test_full_entity_modules():
    for m in MODULE_ORDER:
        if m in ("perception", "mundus", "echo"):
            assert FULL_ENTITY_MODULES[m] is False
        else:
            assert FULL_ENTITY_MODULES[m] is True


def test_base_thesis_modules_matches_profile():
    path = kaine_config.profile_path("thesis_test")
    with path.open("rb") as fh:
        table = tomllib.load(fh).get("modules", {})
    expected = {m: bool(table.get(m, False)) for m in MODULE_ORDER}
    expected["echo"] = False
    assert base_thesis_modules() == expected


def test_recommend_preset():
    assert recommend_preset(None) == (
        "base",
        "no hardware recommendation is available",
    )

    tier3 = types.SimpleNamespace(tier=3, residency_required=False)
    assert recommend_preset(tier3) == (
        "full",
        "this host fits tier 3 without swapping modules in and out",
    )

    tier2_resident = types.SimpleNamespace(tier=2, residency_required=True)
    assert recommend_preset(tier2_resident) == (
        "base",
        "tier 2 needs modules swapped in and out to fit",
    )

    tier1 = types.SimpleNamespace(tier=1, residency_required=False)
    assert recommend_preset(tier1) == (
        "base",
        "tier 1 is too small to run every module at once",
    )


def _tier3_no_residency():
    return types.SimpleNamespace(
        tier=3,
        residency_required=False,
        profile="tier3",
        reason="test",
        memory_budget_gb=24.0,
    )


def test_interactive_default_full_entity():
    answers = [ACK_PHRASE, "", "", "y", "n", "", "n", "n"]
    a = _Answers(answers)
    out, sink = _collect_out()
    result = run_wizard(
        input_fn=a,
        out=sink,
        host=_host(cuda=2),
        shipped_config=_shipped(),
        recommend_tier_fn=_tier3_no_residency,
        probe_services=None,
    )
    assert result.acknowledged is True
    for m in MODULE_ORDER:
        if m in ("perception", "mundus", "echo"):
            assert result.config["modules"][m] is False
        else:
            assert result.config["modules"][m] is True
    assert result.config["modules"]["echo"] is False
    assert "Recommended: full entity" in out()
    assert "Module preset: full entity" in out()


def test_interactive_choose_base_thesis():
    answers = [ACK_PHRASE, "", "", "y", "n", "b", "n", "n"]
    a = _Answers(answers)
    out, sink = _collect_out()
    result = run_wizard(
        input_fn=a,
        out=sink,
        host=_host(cuda=2),
        shipped_config=_shipped(),
        recommend_tier_fn=_tier3_no_residency,
        probe_services=None,
    )
    assert result.config["modules"] == base_thesis_modules()
    assert "Recommended: full entity" in out()
    assert "Module preset: base thesis" in out()


@pytest.mark.parametrize(
    ("recommend", "expected"),
    [
        (_tier3_no_residency, FULL_ENTITY_MODULES),
        (None, None),  # no recommendation: the base thesis
    ],
)
def test_custom_starts_from_the_recommended_preset(recommend, expected):
    if expected is None:
        expected = base_thesis_modules()
    a = _Answers([ACK_PHRASE, "", "", "y", "n", "c"])
    out, sink = _collect_out()
    run_wizard(
        input_fn=a,
        out=sink,
        host=_host(cuda=2),
        shipped_config=_shipped(),
        recommend_tier_fn=recommend,
        probe_services=None,
    )
    for m in MODULE_ORDER:
        suffix = " [Y/n]: " if expected[m] else " [y/N]: "
        assert f"  enable {m}?{suffix}" in a.prompts, m


def test_defaults_with_tier_recommendation_full_entity():
    shipped = _shipped()
    shipped.setdefault("vox", {})["predefined_voice_id"] = "test-voice"
    out, sink = _collect_out()
    result = run_wizard(
        input_fn=_Answers([]),
        out=sink,
        host=_host(cuda=0),
        shipped_config=shipped,
        recommend_tier_fn=_tier3_no_residency,
        defaults=True,
    )
    assert result.acknowledged is True
    for m in MODULE_ORDER:
        if m in ("perception", "mundus", "echo"):
            assert result.config["modules"][m] is False
        else:
            assert result.config["modules"][m] is True
    assert "[--defaults] module preset: full entity" in out()
    assert "Module preset: full entity" in out()


def test_full_entity_without_a_voice_turns_vox_off():
    shipped = _shipped()
    shipped.setdefault("vox", {})["backend"] = "chatterbox"
    shipped["vox"]["predefined_voice_id"] = ""
    out, sink = _collect_out()
    result = run_wizard(
        input_fn=_Answers([]),
        out=sink,
        host=_host(cuda=0),
        shipped_config=shipped,
        recommend_tier_fn=_tier3_no_residency,
        defaults=True,
    )
    assert result.config["modules"]["vox"] is False
    assert result.config["modules"]["lingua"] is True
    assert "no voice id available; disabling vox." in out()


def test_defaults_without_recommendation_base_thesis():
    out, sink = _collect_out()
    result = run_wizard(
        input_fn=_Answers([]),
        out=sink,
        host=_host(cuda=0),
        shipped_config=_shipped(),
        defaults=True,
    )
    assert result.acknowledged is True
    assert result.config["modules"] == base_thesis_modules()
    assert "[--defaults] module preset: base thesis" in out()
    assert "Module preset: base thesis" in out()
