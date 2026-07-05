# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Presence test: SECURITY.md §4 enumerates the v4 at-rest state files.

Spec requirement (openspec/specs/state-encryption/spec.md §"SECURITY.md names
all v4 at-rest state files"): SECURITY.md §4 SHALL enumerate all new v4
at-rest state files alongside the v1 files, noting which gain application-layer
encryption and which remain OS-layer operator responsibility.

This test pins that the section exists and mentions each of the four v4 state
artifacts: the Eidolon self-model, the evaluation-observer JSONL, the Phantasia
checkpoints, and the Empatheia Qdrant store.
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
SECURITY_PATH = REPO_ROOT / "SECURITY.md"


@pytest.fixture(scope="module")
def security_text() -> str:
    return SECURITY_PATH.read_text(encoding="utf-8").lower()


def test_security_md_exists() -> None:
    assert SECURITY_PATH.exists(), "SECURITY.md not found at repo root"


def test_security_md_mentions_eidolon_self_model(security_text: str) -> None:
    """§4 must name the Eidolon self-model file."""
    assert "self_model" in security_text, (
        "SECURITY.md §4 does not mention the Eidolon self-model "
        "(expected substring 'self_model')"
    )


def test_security_md_mentions_observer_jsonl(security_text: str) -> None:
    """§4 must name the evaluation observer JSONL logs."""
    assert "observer" in security_text and "jsonl" in security_text, (
        "SECURITY.md §4 does not mention the sidecar observer JSONL "
        "(expected both 'observer' and 'jsonl')"
    )


def test_security_md_mentions_phantasia(security_text: str) -> None:
    """§4 must name the Phantasia world-model checkpoints."""
    assert "phantasia" in security_text, (
        "SECURITY.md §4 does not mention the Phantasia checkpoints "
        "(expected substring 'phantasia')"
    )


def test_security_md_mentions_empatheia(security_text: str) -> None:
    """§4 must name the Empatheia Qdrant store."""
    assert "empatheia" in security_text, (
        "SECURITY.md §4 does not mention the Empatheia Qdrant store "
        "(expected substring 'empatheia')"
    )
