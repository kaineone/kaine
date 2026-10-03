# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Fail-closed tests for adapter-merge rejection/failure handling.

A rejected or failed real adapter merge must not be silently persisted,
and the Nexus diagnostics handler must not run the synchronous merger on
the async event-loop thread.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import httpx
import pytest

from kaine.lifecycle.adapter_merge import TiesDareAdapterMerger
from kaine.lifecycle.manager import (
    FakeAdapterMerger,
    ForkManager,
    UnmergedAdaptersError,
    merger_from_name,
)
from kaine.nexus.app import create_app
from kaine.nexus.bridge import BusBridge
from kaine.nexus.config import NexusConfig
from kaine.nexus.privacy import PrivacyFilter


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
    reg = _FakeRegistry([_FakeModule("soma")])
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
    reg = _FakeRegistry([_FakeModule("soma")])
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
    reg = _FakeRegistry([_FakeModule("soma")])
    a = mgr.snapshot(reg, adapters=["adapters/a"])
    b = mgr.snapshot(reg, adapters=["adapters/b"])

    merged = mgr.merge(a.id, b.id, allow_unmerged_adapters=True)

    assert merged.metadata["adapter_merge_rejected"] == (
        "capability_loss=0.2000 > threshold=0.0500"
    )
    assert set(merged.adapters) == {"adapters/a", "adapters/b"}


def test_merge_checks_not_called_for_fake_or_auto_fallback(monkeypatch):
    calls: list[bool] = []

    def factory():
        calls.append(True)
        return (object(), object())

    assert isinstance(merger_from_name("fake", merge_checks=factory), FakeAdapterMerger)
    assert calls == []

    monkeypatch.setattr(
        "kaine.lifecycle.adapter_merge.check_peft_available",
        lambda: "peft is unavailable",
    )
    assert isinstance(
        merger_from_name(
            "auto",
            config_section={"base_model_path": "/models/base"},
            merge_checks=factory,
        ),
        FakeAdapterMerger,
    )
    assert calls == []


def test_merge_checks_called_for_ties_dare_and_wires_deps():
    class _EvalMarker:
        pass

    class _ScorerMarker:
        pass

    def factory():
        return (_EvalMarker(), _ScorerMarker())

    m = merger_from_name(
        "ties_dare",
        config_section={"base_model_path": "/models/base"},
        merge_checks=factory,
    )
    assert isinstance(m, TiesDareAdapterMerger)
    assert isinstance(m._capability_eval, _EvalMarker)
    assert isinstance(m._abliteration_scorer, _ScorerMarker)
    assert callable(m._model_loader)


def test_merge_checks_without_base_model_path_leaves_loader_none():
    def factory():
        return (object(), object())

    m = merger_from_name("ties_dare", config_section={}, merge_checks=factory)
    assert isinstance(m, TiesDareAdapterMerger)
    assert m._model_loader is None


async def _make_nexus_client(*, fork_manager: ForkManager | None = None):
    config = NexusConfig(
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
    reg = _FakeRegistry([_FakeModule("soma")])
    a = mgr.snapshot(reg, adapters=[])
    b = mgr.snapshot(reg, adapters=[])

    client = await _make_nexus_client(fork_manager=mgr)
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
    reg = _FakeRegistry([_FakeModule("soma")])
    a = mgr.snapshot(reg, adapters=["adapters/a"])
    b = mgr.snapshot(reg, adapters=["adapters/b"])

    client = await _make_nexus_client(fork_manager=mgr)
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
