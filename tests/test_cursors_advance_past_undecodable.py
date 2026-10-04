# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import Event
from kaine.cycle.gestation import GestationOwner, GestationReadoutConfig
from kaine.nexus.bridge import BusBridge
from kaine.privacy_filter import PrivacyFilter

fakeredis = pytest.importorskip("fakeredis.aioredis")


def _make_bus() -> AsyncBus:
    client = fakeredis.FakeRedis(decode_responses=True)
    return AsyncBus(BusConfig(password="x", audit_required=False), client=client)


def _event(source: str, type_: str, payload: dict[str, Any]) -> Event:
    return Event(
        source=source,
        type=type_,
        payload=payload,
        timestamp=datetime.now(timezone.utc),
        salience=0.5,
        causal_parent=None,
    )



def test_no_bus_read_calls_in_cursor_advancing_code() -> None:
    kaine_dir = Path(__file__).resolve().parent.parent / "kaine"
    exempt = {
        kaine_dir / "evaluation" / "benchmarks" / "workspace_mediation_ablation" / "inject.py",
        kaine_dir / "nexus" / "__main__.py",
    }
    pattern = re.compile(r"\b_?bus\.read\(")
    offenders: list[str] = []
    for path in kaine_dir.rglob("*.py"):
        if path.is_relative_to(kaine_dir / "bus"):
            continue
        if path in exempt:
            continue
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                offenders.append(
                    f"{path.relative_to(kaine_dir.parent)}:{lineno}: {line.strip()}"
                )
    assert not offenders, (
        "cursor-advancing code must use read_entries, not read:\n"
        + "\n".join(offenders)
    )


@pytest.mark.asyncio
async def test_nexus_bridge_advances_past_undecodable_batch() -> None:
    bus = _make_bus()
    stream = "topos.out"
    bridge = BusBridge(bus, PrivacyFilter(), streams=[stream], read_count=64)
    client = bridge.add_client("diagnostics")

    # The first tick resolves the cursor to the (empty) stream's tail.
    await bridge._tick_once()

    for _ in range(80):
        await bus.client.xadd(stream, {"junk": "x"})

    report = _event("topos", "topos.report", {"change_score": 0.2})
    await bus.publish(report)

    for _ in range(5):
        await bridge._tick_once()

    received: list[tuple[str, Event]] = []
    while not client.queue.empty():
        received.append(client.queue.get_nowait())

    assert any(ev.type == report.type for _entry_id, ev in received)


@pytest.mark.asyncio
async def test_gestation_soma_reader_advances_past_undecodable_batch(
    tmp_path: Path,
) -> None:
    bus = _make_bus()

    class FakeDrive:
        def __init__(self) -> None:
            self.scale = 0.0

    class FakeSoma:
        def self_rhythm_state(self) -> tuple[float, float] | None:
            return (0.0, 1.0)

    config = GestationReadoutConfig.from_dict(
        {
            "entrainment_replications": 1.0,
            "surrogate_count": 3.0,
            "readout_period_seconds": 10.0,
            "sample_hz": 10.0,
            "withdrawal_period_seconds": 10.0,
            "withdrawal_seconds": 5.0,
            "perturbation_period_seconds": 20.0,
            "perturbation_seconds": 2.0,
            "baseline_drive_fraction": 0.5,
            "hrv_window_seconds": 10.0,
            "recovery_tolerance": 0.25,
            "recovery_cap_seconds": 30.0,
            "probe_jitter_fraction": 0.0,
            "entrainment_window_seconds": 300.0,
            "entrainment_band_low_hz": 0.3,
            "entrainment_band_high_hz": 2.0,
            "edge_trim_seconds": 2.0,
            "frequency_pull_floor": 0.5,
            "baseline_withdrawals": 3.0,
        }
    )

    owner = GestationOwner(
        bus,
        soma=FakeSoma(),
        drive=FakeDrive(),
        beat_phase=lambda: 0.0,
        surrogate_beat_phases=None,
        is_paused=lambda: False,
        config=config,
        clock=lambda: 0.0,
        state_path=tmp_path / "gestation_readout.json",
    )
    owner._soma_cursor = "0-0"

    for _ in range(1100):
        await bus.client.xadd("soma.out", {"junk": "x"})

    await bus.publish(_event("soma", "soma.report", {"prediction_error": 0.5}))

    await owner._read_soma_reports(10.0)
    await owner._read_soma_reports(20.0)
    await owner._read_soma_reports(30.0)

    assert len(owner._soma_series) == 1
    assert math.isclose(owner._soma_series[0][1], 0.5)
