# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Fail-closed tests for adapter-merge rejection/failure handling.

A rejected or failed real adapter merge must not be silently persisted,
and the dashboard diagnostics handler must not run the synchronous merger on
the async event-loop thread.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import httpx
import pytest

from kaine.dashboard.app import create_app
from kaine.dashboard.bridge import BusBridge
from kaine.dashboard.config import DashboardConfig
from kaine.dashboard.privacy import PrivacyFilter
from kaine.lifecycle.adapter_merge import TiesDareAdapterMerger
from kaine.lifecycle.manager import (
    FakeAdapterMerger,
    ForkManager,
    UnmergedAdaptersError,
    merger_from_name,
)


class _FakeModule:
    def __init__(self, name: str) -> None:
        self.name = name

    def serialize(self) -> dict[str, Any]:
        return {"v": 1}

    def deserialize(self, state: dict[str, Any]) -> None:
        pass


class _FakeRegistry:
    def __init__(self, modules: list[_FakeModule]) -> None:
        self._modules = list(modules)

    def all_modules(self):
        return iter(self._modules)


class _StubBus:
    async def read(self, stream, *, last_id, count, block_ms):
        return []

    async def current_workspace_id(self):
        return "0"


def _snapshot_dirs(root: Path) -> set[str]:
    return {p.name for p in root.iterdir() if p.is_dir()}


class _RejectedMerger:
    def __init__(self, key: str = "adapter_merge_rejected") -> None:
        self._key = key
        self._reason = "capability_loss=0.2000 > threshold=0.0500"

    def merge(self, adapters_a: list[str], adapters_b: list[str]):
        return (
            list(adapters_a) + list(adapters_b),
            {"adapter_merge": "ties_dare", self._key: self._reason},
        )


class _FailedMerger:
    def merge(self, adapters_a: list[str], adapters_b: list[str]):
        return (
            list(adapters_a) + list(adapters_b),
            {"adapter_merge": "ties_dare", "adapter_merge_failed": "RuntimeError: boom"},
        )


def _make_fork_manager(tmp_path: Path, merger) -> ForkManager:
    return ForkManager(tmp_path, adapter_merger=merger)


def test_merge_rejected_raises_before_writing(tmp_path: Path):
    mgr = _make_fork_manager(tmp_path, _RejectedMerger())
    reg = _FakeRegistry([_FakeModule("interoception")])
    a = mgr.snapshot(reg, adapters=["adapters/a"])
    b = mgr.snapshot(reg, adapters=["adapters/b"])

    before = _snapshot_dirs(mgr._root)
    with pytest.raises(UnmergedAdaptersError) as exc_info:
        mgr.merge(a.id, b.id)

    msg = str(exc_info.value)
    assert a.id in msg
    assert b.id in msg
    assert "capability_loss" in msg
    assert "merged adapter was not kept" in msg
    assert "allow_unmerged_adapters=True" in msg
    assert _snapshot_dirs(mgr._root) == before


def test_merge_failed_raises_before_writing(tmp_path: Path):
    mgr = _make_fork_manager(tmp_path, _FailedMerger())
    reg = _FakeRegistry([_FakeModule("interoception")])
    a = mgr.snapshot(reg, adapters=["adapters/a"])
    b = mgr.snapshot(reg, adapters=["adapters/b"])

    before = _snapshot_dirs(mgr._root)
    with pytest.raises(UnmergedAdaptersError) as exc_info:
        mgr.merge(a.id, b.id)

    msg = str(exc_info.value)
    assert a.id in msg
    assert b.id in msg
    assert "RuntimeError" in msg
    assert "merged adapter was not kept" in msg
    assert "allow_unmerged_adapters=True" in msg
    assert _snapshot_dirs(mgr._root) == before


def test_merge_rejected_allowed_keeps_parents_uncombined(tmp_path: Path):
    mgr = _make_fork_manager(tmp_path, _RejectedMerger())
    reg = _FakeRegistry([_FakeModule("interoception")])
    a = mgr.snapshot(reg, adapters=["adapters/a"])
    b = mgr.snapshot(reg, adapters=["adapters/b"])

    merged = mgr.merge(a.id, b.id, allow_unmerged_adapters=True)

    assert merged.metadata["adapter_merge_rejected"] == (
        "capability_loss=0.2000 > threshold=0.0500"
    )
    assert set(merged.adapters) == {"adapters/a", "adapters/b"}


def test_real_merger_runs_merge_and_checks_in_a_child_process():
    """merger_from_name wires probe paths into the config and a child runner;
    it loads nothing (no evaluators, no loader, no backend) in this process."""
    from kaine.lifecycle.adapter_merge import ChildMergeRunner

    m = merger_from_name(
        "ties_dare",
        config_section={
            "base_model_path": "/models/base",
            "capability_probe_path": "/p/cap.jsonl",
            "abliteration_probe_path": "/p/abl.jsonl",
            "merge_timeout_s": 90,
        },
    )
    assert isinstance(m, TiesDareAdapterMerger)
    assert isinstance(m._runner, ChildMergeRunner)
    assert m._backend is None
    assert m._capability_eval is None
    assert m._abliteration_scorer is None
    assert m._model_loader is None
    assert m._config.capability_probe_path == "/p/cap.jsonl"
    assert m._config.abliteration_probe_path == "/p/abl.jsonl"
    assert m._config.merge_timeout_s == 90.0


def test_empty_probe_paths_select_the_bundled_sets():
    m = merger_from_name(
        "ties_dare",
        config_section={
            "base_model_path": "/models/base",
            "capability_probe_path": "",
            "abliteration_probe_path": "  ",
        },
    )
    assert m._config.capability_probe_path is None
    assert m._config.abliteration_probe_path is None


def test_fake_and_auto_fallback_build_no_real_merger(monkeypatch):
    assert isinstance(merger_from_name("fake"), FakeAdapterMerger)
    monkeypatch.setattr(
        "kaine.lifecycle.adapter_merge.check_peft_available",
        lambda: "peft is unavailable",
    )
    assert isinstance(
        merger_from_name("auto", config_section={"base_model_path": "/models/base"}),
        FakeAdapterMerger,
    )


async def _make_dashboard_client(*, fork_manager: ForkManager | None = None):
    config = DashboardConfig(
        conversation_enabled=True,
        host_allowlist=("127.0.0.1", "localhost", "test"),
        operator_token="test-token",
    )
    bus = _StubBus()
    privacy = PrivacyFilter(dev_content_override=None)
    bridge = BusBridge(bus, privacy, streams=[], poll_interval_s=0.01)

    async def history_loader(n: int):
        return []

    app = create_app(
        config=config,
        bridge=bridge,
        history_loader=history_loader,
        metrics_snapshot=lambda: {},
        fork_manager=fork_manager,
        conversation_state=None,
        health_prober=None,
        rate_control_publisher=None,
    )
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.asyncio
async def test_merge_handler_runs_merge_in_thread(tmp_path: Path):
    """The synchronous merger uses asyncio.run internally; this only works
    when the handler offloads merge() to a thread via asyncio.to_thread."""

    class _ThreadSafeMerger:
        def merge(self, adapters_a: list[str], adapters_b: list[str]):
            asyncio.run(asyncio.sleep(0))
            return ([], {})

    mgr = _make_fork_manager(tmp_path, _ThreadSafeMerger())
    reg = _FakeRegistry([_FakeModule("interoception")])
    a = mgr.snapshot(reg, adapters=[])
    b = mgr.snapshot(reg, adapters=[])

    client = await _make_dashboard_client(fork_manager=mgr)
    async with client:
        response = await client.post(
            "/diagnostics/merges",
            json={
                "snapshot_a_id": a.id,
                "snapshot_b_id": b.id,
                "label": "",
                "allow_unmerged_adapters": False,
                "world_model_from": None,
            },
            headers={"Authorization": "Bearer test-token"},
        )

    assert response.status_code == 200
    assert response.json()["id"] is not None


@pytest.mark.asyncio
async def test_merge_handler_reports_rejected_merge(tmp_path: Path):
    mgr = _make_fork_manager(tmp_path, _RejectedMerger())
    reg = _FakeRegistry([_FakeModule("interoception")])
    a = mgr.snapshot(reg, adapters=["adapters/a"])
    b = mgr.snapshot(reg, adapters=["adapters/b"])

    client = await _make_dashboard_client(fork_manager=mgr)
    async with client:
        response = await client.post(
            "/diagnostics/merges",
            json={
                "snapshot_a_id": a.id,
                "snapshot_b_id": b.id,
                "label": "",
                "allow_unmerged_adapters": False,
                "world_model_from": None,
            },
            headers={"Authorization": "Bearer test-token"},
        )

    assert response.status_code == 409
    assert "capability_loss" in response.text
