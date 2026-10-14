# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for AsyncJsonlSink retention across module-name aliases."""

from __future__ import annotations

import os
import time

from kaine import legacy_aliases
from kaine.persistence.jsonl_sink import AsyncJsonlSink

OLD_TABLE = next(form for form in legacy_aliases.name_forms("dashboard") if form != "dashboard")
OLD_PREFIX = f"{OLD_TABLE}_record"


def test_retention_prunes_old_and_new_dashboard_record_prefixes(tmp_path):
    old_file = tmp_path / f"{OLD_PREFIX}-2020-01-01.jsonl"
    new_file = tmp_path / "dashboard_record-2020-01-01.jsonl"
    other_file = tmp_path / "other-2020-01-01.jsonl"
    for p in (old_file, new_file, other_file):
        p.write_text("{}\n")
    old_mtime = time.time() - (400 * 86400)
    for p in (old_file, new_file, other_file):
        os.utime(p, (old_mtime, old_mtime))

    sink = AsyncJsonlSink(
        tmp_path,
        name="dashboard_record",
        retention_days=30,
        retention_prefixes=[OLD_PREFIX],
    )
    sink._enforce_retention()

    assert not old_file.exists()
    assert not new_file.exists()
    assert other_file.exists()


def test_registry_dashboard_record_sink_prunes_both_prefixes(tmp_path):
    from kaine.evaluation.config import (
        DashboardRecordConfig,
        EvaluationConfig,
        ResearchEventLogConfig,
    )
    from kaine.evaluation.registry import SidecarRegistry

    log_dir = tmp_path / "record"
    log_dir.mkdir()
    old_file = log_dir / f"{OLD_PREFIX}-2020-01-01.jsonl"
    new_file = log_dir / "dashboard_record-2020-01-01.jsonl"
    other_file = log_dir / "research_events-2020-01-01.jsonl"
    old_mtime = time.time() - (400 * 86400)
    for p in (old_file, new_file, other_file):
        p.write_text("{}\n")
        os.utime(p, (old_mtime, old_mtime))

    research = ResearchEventLogConfig(
        dashboard_record=DashboardRecordConfig(
            enabled=True, log_dir=str(log_dir), retention_days=30
        )
    )
    registry = SidecarRegistry(
        bus=object(),
        config=EvaluationConfig.from_mapping({"enabled": False}),
        research_event_log_config=research,
    )
    registry.build()
    sinks = [s for s in registry._sinks if s._name == "dashboard_record"]
    assert len(sinks) == 1
    sinks[0]._enforce_retention()

    assert not old_file.exists()
    assert not new_file.exists()
    assert other_file.exists()
