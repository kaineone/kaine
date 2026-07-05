# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the operator config-override layer (kaine.config)."""
from __future__ import annotations

from pathlib import Path

from kaine.config import deep_merge, load_kaine_config


def test_deep_merge_override_scalar_wins():
    base = {"modules": {"soma": False}, "lingua": {"model_id": "a"}}
    override = {"lingua": {"model_id": "b"}}
    merged = deep_merge(base, override)
    assert merged["lingua"]["model_id"] == "b"
    # base untouched
    assert base["lingua"]["model_id"] == "a"


def test_deep_merge_nested_tables_merge_not_replace():
    base = {"hypnos": {"voice_alignment": {"training_device": "cpu", "lora_rank": 8}}}
    override = {"hypnos": {"voice_alignment": {"training_device": "cuda:0"}}}
    merged = deep_merge(base, override)
    va = merged["hypnos"]["voice_alignment"]
    assert va["training_device"] == "cuda:0"  # override wins
    assert va["lora_rank"] == 8  # sibling preserved


def test_deep_merge_lists_are_replaced_not_concatenated():
    base = {"t": {"xs": [1, 2, 3]}}
    override = {"t": {"xs": [9]}}
    assert deep_merge(base, override)["t"]["xs"] == [9]


def test_deep_merge_does_not_mutate_inputs():
    base = {"a": {"x": 1}}
    override = {"a": {"y": 2}}
    deep_merge(base, override)
    assert base == {"a": {"x": 1}}
    assert override == {"a": {"y": 2}}


def test_load_returns_shipped_when_no_operator_file(tmp_path: Path):
    shipped = tmp_path / "kaine.toml"
    shipped.write_text("[modules]\nsoma = false\n")
    op = tmp_path / "kaine.operator.toml"  # does not exist
    cfg = load_kaine_config(shipped, op)
    assert cfg["modules"]["soma"] is False


def test_load_merges_operator_over_shipped(tmp_path: Path):
    shipped = tmp_path / "kaine.toml"
    shipped.write_text("[modules]\nsoma = false\nlingua = false\n")
    op = tmp_path / "kaine.operator.toml"
    op.write_text("[modules]\nsoma = true\n")
    cfg = load_kaine_config(shipped, op)
    assert cfg["modules"]["soma"] is True
    # sibling key from shipped preserved
    assert cfg["modules"]["lingua"] is False


def test_operator_file_does_not_mutate_shipped_on_disk(tmp_path: Path):
    shipped = tmp_path / "kaine.toml"
    shipped_text = "[modules]\nsoma = false\n"
    shipped.write_text(shipped_text)
    op = tmp_path / "kaine.operator.toml"
    op.write_text("[modules]\nsoma = true\n")
    load_kaine_config(shipped, op)
    assert shipped.read_text() == shipped_text


def test_load_tolerates_malformed_operator_file(tmp_path: Path):
    shipped = tmp_path / "kaine.toml"
    shipped.write_text("[modules]\nsoma = false\n")
    op = tmp_path / "kaine.operator.toml"
    op.write_text("this is not = = valid toml [[[")
    cfg = load_kaine_config(shipped, op)
    # falls back to shipped, does not raise
    assert cfg["modules"]["soma"] is False
