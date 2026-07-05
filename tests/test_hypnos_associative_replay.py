# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for Hypnos phase-3 associative cross-period replay.

Phase 3 selects traces from at least two distinct memory periods, cues
Phantasia for scenario extensions, consumes the resulting scenarios, and
re-injects the novel associations into the workspace. When Phantasia is
disabled/absent the cue degrades to a no-op.

All collaborators are tiny fakes — no real Mnemos / Phantasia / LLM.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from kaine.modules.hypnos.phases import associative_replay


@dataclass
class _Trace:
    point_id: str
    text: str


class FakeMnemos:
    """Yields traces grouped by memory period."""

    def __init__(self, by_period: dict[str, list[_Trace]]) -> None:
        self._by_period = by_period
        self.calls: list[tuple[int, int]] = []

    async def select_cross_period_traces(self, *, periods: int, per_period: int):
        self.calls.append((periods, per_period))
        return {
            name: traces[:per_period]
            for name, traces in self._by_period.items()
        }


class FakePhantasia:
    """Records cue seeds and returns scripted scenario payloads."""

    def __init__(self, *, scenarios_per_cue: int = 1) -> None:
        self.seeds: list[str] = []
        self._n = scenarios_per_cue

    async def generate_scenario(self, *, seed_memory_id: str = ""):
        self.seeds.append(seed_memory_id)
        return [
            {"seed_memory_id": seed_memory_id, "horizon": 3, "idx": i}
            for i in range(self._n)
        ]


@pytest.mark.asyncio
async def test_disabled_is_noop():
    result = await associative_replay(enabled=False)
    assert result.success is True
    assert result.phase == "associative_replay"
    assert "skipped" in result.metadata


@pytest.mark.asyncio
async def test_selects_cross_period_traces():
    mnemos = FakeMnemos(
        {
            "short_term": [_Trace("st:0", "a"), _Trace("st:1", "b")],
            "episodic": [_Trace("ep:0", "c")],
            "semantic": [_Trace("se:0", "d")],
        }
    )
    phantasia = FakePhantasia()
    result = await associative_replay(
        enabled=True, mnemos=mnemos, phantasia=phantasia
    )
    assert result.success is True
    # Traces span at least two distinct memory periods in the same batch.
    assert result.metadata["distinct_periods"] >= 2
    assert set(result.metadata["periods_selected"]) >= {"short_term", "episodic"}
    assert result.metadata["cross_period_traces"] == 4


@pytest.mark.asyncio
async def test_cues_phantasia_and_reinjects():
    mnemos = FakeMnemos(
        {
            "short_term": [_Trace("st:0", "a")],
            "episodic": [_Trace("ep:0", "c")],
        }
    )
    phantasia = FakePhantasia(scenarios_per_cue=2)
    reinjected: list[dict] = []

    async def _reinject(scenario):
        reinjected.append(scenario)

    result = await associative_replay(
        enabled=True, mnemos=mnemos, phantasia=phantasia, reinject=_reinject
    )
    assert result.success is True
    # Phantasia cued once per cross-period seed (2 seeds).
    assert phantasia.seeds == ["st:0", "ep:0"]
    # 2 seeds x 2 scenarios each = 4 consumed + re-injected.
    assert result.metadata["scenarios_consumed"] == 4
    assert result.metadata["associations_reinjected"] == 4
    assert len(reinjected) == 4


@pytest.mark.asyncio
async def test_phantasia_absent_is_noop_cue():
    mnemos = FakeMnemos({"short_term": [_Trace("st:0", "a")], "episodic": [_Trace("ep:0", "b")]})
    result = await associative_replay(enabled=True, mnemos=mnemos, phantasia=None)
    assert result.success is True
    assert "no-op" in result.metadata["phantasia_cue"]
    assert result.metadata["scenarios_consumed"] == 0
    # Cross-period selection still happened even with Phantasia absent.
    assert result.metadata["distinct_periods"] >= 2


@pytest.mark.asyncio
async def test_no_cross_period_surface_skips_cleanly():
    class BareMnemos:
        pass

    result = await associative_replay(enabled=True, mnemos=BareMnemos(), phantasia=None)
    assert result.success is True
    assert "cross_period_skipped" in result.metadata
