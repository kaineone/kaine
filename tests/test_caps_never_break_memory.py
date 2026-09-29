# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Shipped defaults that keep entity memory and research records
(caps-never-break-memory): no infrastructure cap deletes them."""

from __future__ import annotations

import tomllib
from pathlib import Path

from kaine.evaluation.config import (
    EvaluationPaths,
    RawArchiveConfig,
    ResearchEventLogConfig,
)

_ROOT = Path(__file__).resolve().parents[1]


def _shipped() -> dict:
    with (_ROOT / "config" / "kaine.toml").open("rb") as fh:
        return tomllib.load(fh)


def test_shipped_research_retention_keeps_records():
    cfg = _shipped()
    assert cfg["evaluation"]["paths"]["retention_days"] == 0
    assert cfg["research_event_log"]["retention_days"] == 0
    assert cfg["research_event_log"]["raw_archive"]["retention_days"] == 0


def test_retention_dataclass_defaults_keep_records():
    assert EvaluationPaths.from_mapping({}).retention_days == 0
    assert ResearchEventLogConfig.from_mapping({}).retention_days == 0
    assert RawArchiveConfig.from_mapping({}).retention_days == 0


def test_positive_retention_is_still_honored():
    assert EvaluationPaths.from_mapping({"retention_days": 7}).retention_days == 7


def test_shipped_identity_history_is_uncapped():
    assert _shipped()["eidolon"]["identity_history_cap"] == 0


def test_shipped_config_has_no_snapshot_count_cap():
    assert "max_snapshots_retained" not in _shipped()["lifecycle"]
