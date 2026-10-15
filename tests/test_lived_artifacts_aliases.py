# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Lived-artifact recognition under old and new directory names."""

from __future__ import annotations

from pathlib import Path

from kaine.lifecycle.identity import OWN_LIVED_ARTIFACTS, own_lived_artifacts, tree_digest


def test_own_lived_artifacts_includes_old_and_new_paths() -> None:
    assert Path("lifecycle/stage.json") in OWN_LIVED_ARTIFACTS
    assert Path("sleep/consolidation_divergence.json") in OWN_LIVED_ARTIFACTS
    assert Path("sleep/consolidation_divergence.json") in OWN_LIVED_ARTIFACTS
    assert Path("world_model/world_model.ckpt") in OWN_LIVED_ARTIFACTS
    assert Path("world_model/world_model.ckpt") in OWN_LIVED_ARTIFACTS
    assert Path("perception/desired.json") in OWN_LIVED_ARTIFACTS
    assert Path("perceptual_locus/desired.json") in OWN_LIVED_ARTIFACTS


def test_own_lived_artifacts_finds_new_layout_tree(tmp_path: Path) -> None:
    (tmp_path / "sleep").mkdir()
    (tmp_path / "sleep" / "consolidation_divergence.json").write_text("{}")
    assert own_lived_artifacts(tmp_path) == [tmp_path / "sleep" / "consolidation_divergence.json"]


def test_own_lived_artifacts_finds_old_layout_tree(tmp_path: Path) -> None:
    (tmp_path / "sleep").mkdir()
    (tmp_path / "sleep" / "consolidation_divergence.json").write_text("{}")
    assert own_lived_artifacts(tmp_path) == [tmp_path / "sleep" / "consolidation_divergence.json"]


def test_own_lived_artifacts_empty_tree(tmp_path: Path) -> None:
    assert own_lived_artifacts(tmp_path) == []


def test_tree_digest_stable_across_rename(tmp_path: Path) -> None:
    old_root = tmp_path / "old"
    new_root = tmp_path / "new"
    other_root = tmp_path / "other"
    old_root.mkdir()
    new_root.mkdir()
    other_root.mkdir()

    (old_root / "world_model" / "world_model.ckpt").mkdir(parents=True)
    (old_root / "world_model" / "world_model.ckpt" / "w.bin").write_bytes(b"wm")
    (old_root / "sleep").mkdir()
    (old_root / "sleep" / "consolidation_divergence.json").write_text("{}")

    (new_root / "world_model" / "world_model.ckpt").mkdir(parents=True)
    (new_root / "world_model" / "world_model.ckpt" / "w.bin").write_bytes(b"wm")
    (new_root / "sleep").mkdir()
    (new_root / "sleep" / "consolidation_divergence.json").write_text("{}")

    (other_root / "world_model" / "world_model.ckpt").mkdir(parents=True)
    (other_root / "world_model" / "world_model.ckpt" / "w.bin").write_bytes(b"other")
    (other_root / "sleep").mkdir()
    (other_root / "sleep" / "consolidation_divergence.json").write_text("{}")

    old_digest = tree_digest(old_root, own_lived_artifacts(old_root))
    new_digest = tree_digest(new_root, own_lived_artifacts(new_root))
    other_digest = tree_digest(other_root, own_lived_artifacts(other_root))
    assert old_digest == new_digest
    assert old_digest != other_digest
