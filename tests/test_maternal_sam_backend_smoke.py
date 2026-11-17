# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Smoke tests for the Sam-backend CLI/selector slice of maternal voice."""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

_spec = importlib.util.spec_from_file_location(
    "generate_maternal_voice",
    REPO_ROOT / "tools" / "maintainer" / "generate_maternal_voice.py",
)
generator = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(generator)


def test_renderer_default_is_chatterbox() -> None:
    args = generator.parse_args([])
    assert args.renderer == "chatterbox"


def test_renderer_accepts_chatterbox_and_sam() -> None:
    for choice in ("chatterbox", "sam"):
        args = generator.parse_args(["--renderer", choice])
        assert args.renderer == choice


@pytest.mark.parametrize("bad", ["foo", "SAM", "whisper", ""])
def test_renderer_rejects_invalid_choice(bad: str) -> None:
    with pytest.raises(SystemExit):
        generator.parse_args(["--renderer", bad])


def test_renderer_choices_constant() -> None:
    assert "chatterbox" in generator.VALID_RENDERERS
    assert "sam" in generator.VALID_RENDERERS
    assert generator.DEFAULT_RENDERER == "chatterbox"


def test_validate_renderer() -> None:
    assert generator.validate_renderer("chatterbox") == "chatterbox"
    assert generator.validate_renderer("sam") == "sam"
    with pytest.raises(ValueError):
        generator.validate_renderer("nope")


def test_chatterbox_path_keeps_text_flags() -> None:
    # Argparse-level: chatterbox default plus --verify flag remains recognized
    # and renderer validation does not disturb existing options.
    args = generator.parse_args(["--renderer", "chatterbox", "--verify"])
    assert args.renderer == "chatterbox"
    assert args.verify is True
