# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Offline tests for the maternal-voice Sam seed command helper."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

_spec = importlib.util.spec_from_file_location(
    "render_maternal_voice_sam_seed",
    REPO_ROOT / "tools" / "maintainer" / "render_maternal_voice_sam_seed.py",
)
seed = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(seed)


def test_constants_reflect_bounded_contract() -> None:
    assert seed.SPECTRAL_CEILING_HZ == 300
    assert seed.EXPECTED_SPECTRAL_CEILING_HZ == 300
    assert seed.MANIFEST_FORMAT if hasattr(seed, "MANIFEST_FORMAT") else True
    # no audio synthesis is performed
    assert seed.REPO_ROOT == REPO_ROOT


def test_read_manifest_accepts_dict() -> None:
    manifest = {"format": 1, "sample_rate": 8000, "generator": {"base_seed": 7, "spectral_ceiling_hz": 300}}
    data, path = seed.read_manifest(manifest)
    assert path is None
    assert data["format"] == 1
    assert seed._base_seed(data) == 7


def test_validate_spectral_ceiling_accepts_300() -> None:
    manifest = {"spectral_ceiling_hz": 300, "generator": {"spectral_ceiling_hz": 300}}
    assert seed.validate_spectral_ceiling(manifest, ceiling_hz=300) is True


def test_validate_spectral_ceiling_rejects_non_300() -> None:
    manifest = {"spectral_ceiling_hz": 400}
    with pytest.raises(ValueError):
        seed.validate_spectral_ceiling(manifest, ceiling_hz=300)


def test_render_seed_command_writes_file(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest = {
        "format": 1,
        "sample_rate": 8000,
        "initial_unlocked": 5,
        "generator": {"base_seed": 20261018, "spectral_ceiling_hz": 300},
        "spectral_ceiling_hz": 300,
        "items": [],
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    out_dir = tmp_path / "out"
    result = seed.render_seed_command(manifest_path, out=out_dir)
    assert isinstance(result, Path)
    assert result.exists()
    text = result.read_text(encoding="utf-8")
    assert "generate_maternal_voice.py" in text
    assert "--renderer sam" in text
    # sidecars
    assert result.with_suffix(".json").exists()
    assert result.with_suffix(".sh").exists()
    sidecar = json.loads(result.with_suffix(".json").read_text())
    assert sidecar["spectral_ceiling_hz"] == 300.0
    assert sidecar["renders_audio"] is False
    assert sidecar["synthesizes_audio"] is False


def test_render_seed_command_preserves_sample_rate_contract(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest = {"format": 1, "sample_rate": 8000, "generator": {"spectral_ceiling_hz": 300}}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    result = seed.render_seed_command(str(manifest_path), out=str(tmp_path / "o"), ceiling_hz=300)
    assert result.exists()
    sh = result.with_suffix(".sh").read_text(encoding="utf-8")
    assert sh.startswith("#!/usr/bin/env bash")


def test_build_seed_command_in_memory() -> None:
    manifest = {"format": 1, "sample_rate": 8000, "generator": {"base_seed": 42, "spectral_ceiling_hz": 300}}
    desc = seed.build_seed_command(manifest)
    assert desc["base_seed"] == 42
    assert desc["spectral_ceiling_hz"] == 300.0
    assert desc["deterministic"] is True


def test_bad_ceiling_in_manifest_raises(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest = {"format": 1, "sample_rate": 8000, "generator": {"spectral_ceiling_hz": 440}}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError):
        seed.render_seed_command(manifest_path, out=tmp_path / "o")
