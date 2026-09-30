# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from kaine.evaluation.config import (
    ExternalUtterancesConfig,
    NexusRecordConfig,
    RawArchiveConfig,
    RawArchiveConfinementError,
    load_research_event_log_config,
)


@pytest.fixture(autouse=True)
def _drop_env_root(monkeypatch):
    monkeypatch.delenv("KAINE_DATA_ROOT", raising=False)


@pytest.mark.parametrize(
    "cls, key, default",
    [
        (RawArchiveConfig, "archive_dir", "state/research/raw_bus_archive"),
        (ExternalUtterancesConfig, "log_dir", "state/research/external_utterances"),
        (NexusRecordConfig, "log_dir", "data/nexus_record"),
    ],
)
def test_recorder_config_rejects_export_tree(cls, key, default, tmp_path):
    export_root = tmp_path / "eval"
    export_root.mkdir()
    bad = str(export_root / "local")
    good = str(tmp_path / "local")

    with pytest.raises(RawArchiveConfinementError) as exc_info:
        cls.from_mapping({key: bad}, export_roots=(str(export_root),))
    assert str(export_root) in str(exc_info.value)

    cfg = cls.from_mapping({key: good}, export_roots=(str(export_root),))
    assert getattr(cfg, key) == good
    assert cfg.export_roots == (str(export_root),)

    cfg_default = cls.from_mapping({key: default}, export_roots=(str(export_root),))
    assert getattr(cfg_default, key) == default


def test_default_export_root_uses_cwd(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(RawArchiveConfinementError) as exc_info:
        RawArchiveConfig.from_mapping({"archive_dir": "data/evaluation/raw"})
    assert "data/evaluation" in str(exc_info.value)


def test_load_research_event_log_config_eval_logs_absolute(tmp_path):
    eval_dir = tmp_path / "eval"
    eval_dir.mkdir()
    bad_nexus = eval_dir / "nexus"
    shipped = tmp_path / "kaine.toml"
    shipped.write_text(
        textwrap.dedent(
            f"""
            [evaluation.paths]
            evaluation_logs = "{eval_dir}"

            [research_event_log]
            enabled = true

            [research_event_log.nexus_record]
            log_dir = "{bad_nexus}"
            """
        ).strip()
        + "\n"
    )
    operator = tmp_path / "operator.toml"
    operator.write_text("")

    with pytest.raises(RawArchiveConfinementError) as exc_info:
        load_research_event_log_config(shipped, operator_path=operator)
    assert str(eval_dir) in str(exc_info.value)


def test_load_research_event_log_config_data_root_resolves_export_root(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    shipped = tmp_path / "kaine.toml"
    shipped.write_text(
        textwrap.dedent(
            f"""
            [storage]
            data_root = "{root}"

            [research_event_log]
            enabled = true

            [research_event_log.nexus_record]
            log_dir = "nexus"
            """
        ).strip()
        + "\n"
    )
    operator = tmp_path / "operator.toml"
    operator.write_text("")

    cfg = load_research_event_log_config(shipped, operator_path=operator)
    assert Path(cfg.nexus_record.log_dir) == root.resolve() / "nexus"
    expected_eval = (root / "data" / "evaluation").resolve()
    assert len(cfg.nexus_record.export_roots) == 1
    assert Path(cfg.nexus_record.export_roots[0]).resolve() == expected_eval
