# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Launch-name log lines: preflight instances stay quiet (openspec preflight-launch-name-quiet)."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from kaine.cycle.research_gate import _NullBus, run_preflight_self_check
from kaine.modules.self_model import SelfModel


def _init(path: Path, **kw) -> SelfModel:
    module = SelfModel(_NullBus(), persistence_path=path, save_interval_s=60, **kw)
    asyncio.run(module.initialize())
    return module


def _name_lines(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if "self-model" in r.getMessage()
            and ("name" in r.getMessage())]


def test_preflight_construction_logs_no_surname(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    module = _init(tmp_path / "sm.json", preflight=True)
    surname = module.model.name.split()[-1]
    assert surname
    assert surname not in caplog.text
    assert "preflight check: launch name generation ok" in caplog.text
    assert "minted" not in caplog.text


def test_real_preflight_self_check_logs_no_surname(caplog):
    caplog.set_level(logging.INFO)
    ok, reason = run_preflight_self_check()
    assert ok, reason
    assert "self-model name minted" not in caplog.text
    assert "assigned launch name" not in caplog.text
    assert "adopted from identity" not in caplog.text


def test_identity_name_logs_one_adopted_line(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    _init(tmp_path / "sm.json", identity_name="Kaine Whipple")
    lines = [m for m in _name_lines(caplog) if "adopted from identity" in m]
    assert lines == ["self-model name adopted from identity: Kaine Whipple"]
    assert "minted" not in caplog.text


def test_no_identity_name_logs_one_minted_line(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    module = _init(tmp_path / "sm.json")
    lines = [m for m in _name_lines(caplog) if "minted" in m]
    assert lines == [f"self-model name minted: {module.model.name}"]
    assert "adopted" not in caplog.text
