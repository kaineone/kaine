# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Verify that each deployment-tier profile pins the expected speech rungs."""

from __future__ import annotations

import tomllib
from pathlib import Path

PROFILES_DIR = Path(__file__).resolve().parents[1] / "config" / "profiles"


def _load_tier(name: str) -> dict:
    with open(PROFILES_DIR / f"{name}.toml", "rb") as f:
        return tomllib.load(f)


# -- Tier 0: no speech ---------------------------------------------------


class TestTier0:
    """Tier 0 has no speech support (vocal and audition unsupported)."""

    def test_vocal_unsupported(self) -> None:
        cfg = _load_tier("tier0")
        assert "vocal" in cfg["tier"]["unsupported_modules"]

    def test_audition_unsupported(self) -> None:
        cfg = _load_tier("tier0")
        assert "audition" in cfg["tier"]["unsupported_modules"]


# -- Tier 1: sherpa_onnx -------------------------------------------------


class TestTier1:
    """Tier 1 pins sherpa_onnx with explicit model IDs."""

    def test_vocal_backend(self) -> None:
        cfg = _load_tier("tier1")
        assert cfg["vocal"]["backend"] == "sherpa_onnx"

    def test_vocal_model_id(self) -> None:
        cfg = _load_tier("tier1")
        assert cfg["vocal"]["sherpa_model_id"] == "kokoro-en"

    def test_audition_backend(self) -> None:
        cfg = _load_tier("tier1")
        assert cfg["audition"]["backend"] == "sherpa_onnx"

    def test_audition_model_id(self) -> None:
        cfg = _load_tier("tier1")
        assert cfg["audition"]["sherpa_model_id"] == "moonshine-base-en"


# -- Tier 2: service backends --------------------------------------------


class TestTier2:
    """Tier 2 pins the workstation-class service backends."""

    def test_vocal_backend(self) -> None:
        cfg = _load_tier("tier2")
        assert cfg["vocal"]["backend"] == "chatterbox"

    def test_audition_backend(self) -> None:
        cfg = _load_tier("tier2")
        assert cfg["audition"]["backend"] == "speaches"


# -- Tier 3: same service backends as Tier 2 -----------------------------


class TestTier3:
    """Tier 3 also pins the service backends (scale-up is operator-configured)."""

    def test_vocal_backend(self) -> None:
        cfg = _load_tier("tier3")
        assert cfg["vocal"]["backend"] == "chatterbox"

    def test_audition_backend(self) -> None:
        cfg = _load_tier("tier3")
        assert cfg["audition"]["backend"] == "speaches"
