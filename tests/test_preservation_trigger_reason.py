# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
# The bus fixture is imported from test_preservation_monitors and requested by name.
# ruff: noqa: F811

"""A divergence preservation names the arm that triggered it."""

import asyncio

import pytest

from kaine.cycle.preservation_monitor import DivergenceMonitorConfig
from kaine.lifecycle.divergence import DivergenceAssessment
from tests.test_preservation_monitors import (
    _control_to_tmp,  # noqa: F401
    _div_monitor,
    _entity,
    _not_diverged,
    _plaintext_encryptor,  # noqa: F401
    _run_context,  # noqa: F401
    _StubFM,
    bus,  # noqa: F401
)


def _armed(*arms):
    signals = {}
    if "individuation" in arms:
        signals["individuation_individuated"] = True
    if "consolidation" in arms:
        signals["consolidation_divergence_signal"] = True
    if "self_model_drift" in arms:
        signals["self_model_drift_signal"] = True
    if "adapters" in arms:
        signals["sleep_adapters_present"] = True
    if "voice" in arms:
        signals["voice_vote"] = "diverged"
    return DivergenceAssessment(diverged=True, signals=signals, summary="")


def _capture_records(mon):
    records = []
    orig = mon._record

    async def _rec(record, *, event_type):
        records.append((event_type, dict(record)))
        await orig(record, event_type=event_type)

    mon._record = _rec
    return records


class _BoomFM:
    async def preserve_live(
        self, registry, *, reason, label, out_root, entity_name, require_encryption=False
    ):
        raise RuntimeError("boom")


def _cfg():
    return DivergenceMonitorConfig(enabled=True, min_interval_s=0.0)


@pytest.mark.asyncio
async def test_voice_alone_reason_is_voice(bus, tmp_path, monkeypatch):
    fm = _StubFM()
    reg, eid = await _entity(bus, tmp_path)
    mon = _div_monitor(
        bus,
        reg,
        fm,
        _cfg(),
        monkeypatch,
        assessments=[_not_diverged(), _armed("voice")],
        tmp_state_root=tmp_path / "state",
    )
    records = _capture_records(mon)
    await mon._poll_once(asyncio.Event())
    await mon._poll_once(asyncio.Event())
    assert len(fm.calls) == 1
    assert fm.calls[0]["reason"] == "voice"
    assert fm.calls[0]["label"].startswith("divergence:")
    preserved = [payload for et, payload in records if et == "preservation.preserved"]
    assert len(preserved) == 1
    assert preserved[0]["reason"] == "voice"
    assert preserved[0]["arms"] == ["voice"]
    await eid.shutdown()


@pytest.mark.asyncio
async def test_consolidation_alone_reason_is_consolidation(bus, tmp_path, monkeypatch):
    fm = _StubFM()
    reg, eid = await _entity(bus, tmp_path)
    mon = _div_monitor(
        bus,
        reg,
        fm,
        _cfg(),
        monkeypatch,
        assessments=[_not_diverged(), _armed("consolidation")],
        tmp_state_root=tmp_path / "state",
    )
    await mon._poll_once(asyncio.Event())
    await mon._poll_once(asyncio.Event())
    assert len(fm.calls) == 1
    assert fm.calls[0]["reason"] == "consolidation"
    await eid.shutdown()


@pytest.mark.asyncio
async def test_individuation_alone_reason_is_individuation(bus, tmp_path, monkeypatch):
    fm = _StubFM()
    reg, eid = await _entity(bus, tmp_path)
    mon = _div_monitor(
        bus,
        reg,
        fm,
        _cfg(),
        monkeypatch,
        assessments=[_not_diverged(), _armed("individuation")],
        tmp_state_root=tmp_path / "state",
    )
    await mon._poll_once(asyncio.Event())
    await mon._poll_once(asyncio.Event())
    assert len(fm.calls) == 1
    assert fm.calls[0]["reason"] == "individuation"
    await eid.shutdown()


@pytest.mark.asyncio
async def test_two_arms_reason_is_sorted_joined(bus, tmp_path, monkeypatch):
    fm = _StubFM()
    reg, eid = await _entity(bus, tmp_path)
    mon = _div_monitor(
        bus,
        reg,
        fm,
        _cfg(),
        monkeypatch,
        assessments=[_not_diverged(), _armed("voice", "consolidation")],
        tmp_state_root=tmp_path / "state",
    )
    records = _capture_records(mon)
    await mon._poll_once(asyncio.Event())
    await mon._poll_once(asyncio.Event())
    assert len(fm.calls) == 1
    assert fm.calls[0]["reason"] == "consolidation+voice"
    preserved = [payload for et, payload in records if et == "preservation.preserved"]
    assert len(preserved) == 1
    assert preserved[0]["reason"] == "consolidation+voice"
    await eid.shutdown()


@pytest.mark.asyncio
async def test_edge_on_second_arm_preserves_only_new_reason(bus, tmp_path, monkeypatch):
    fm = _StubFM()
    reg, eid = await _entity(bus, tmp_path)
    mon = _div_monitor(
        bus,
        reg,
        fm,
        _cfg(),
        monkeypatch,
        assessments=[_armed("voice"), _armed("voice", "consolidation")],
        tmp_state_root=tmp_path / "state",
    )
    await mon._poll_once(asyncio.Event())
    await mon._poll_once(asyncio.Event())
    assert len(fm.calls) == 2
    assert fm.calls[0]["reason"] == "voice"
    assert fm.calls[1]["reason"] == "consolidation"
    await eid.shutdown()


@pytest.mark.asyncio
async def test_rate_limited_skip_record_carries_reason(bus, tmp_path, monkeypatch):
    fm = _StubFM()
    reg, eid = await _entity(bus, tmp_path)
    mon = _div_monitor(
        bus,
        reg,
        fm,
        DivergenceMonitorConfig(enabled=True, min_interval_s=3600.0),
        monkeypatch,
        assessments=[_armed("voice"), _armed("voice", "consolidation")],
        tmp_state_root=tmp_path / "state",
    )
    records = _capture_records(mon)
    await mon._poll_once(asyncio.Event())
    await mon._poll_once(asyncio.Event())
    assert len(fm.calls) == 1
    assert fm.calls[0]["reason"] == "voice"
    skipped = [payload for et, payload in records if et == "preservation.skipped"]
    assert len(skipped) == 1
    assert skipped[0]["reason"] == "consolidation"
    assert skipped[0]["new_arms"] == ["consolidation"]
    await eid.shutdown()


@pytest.mark.asyncio
async def test_fallback_reason_when_diverged_without_arms(bus, tmp_path, monkeypatch):
    fm = _StubFM()
    reg, eid = await _entity(bus, tmp_path)
    fallback = DivergenceAssessment(diverged=True, signals={}, summary="")
    mon = _div_monitor(
        bus,
        reg,
        fm,
        _cfg(),
        monkeypatch,
        assessments=[_not_diverged(), fallback],
        tmp_state_root=tmp_path / "state",
    )
    await mon._poll_once(asyncio.Event())
    await mon._poll_once(asyncio.Event())
    assert len(fm.calls) == 1
    assert fm.calls[0]["reason"] == "diverged"
    await eid.shutdown()


@pytest.mark.asyncio
async def test_failed_record_carries_reason(bus, tmp_path, monkeypatch):
    fm = _BoomFM()
    reg, eid = await _entity(bus, tmp_path)
    mon = _div_monitor(
        bus,
        reg,
        fm,
        _cfg(),
        monkeypatch,
        assessments=[_armed("consolidation")],
        tmp_state_root=tmp_path / "state",
    )
    records = _capture_records(mon)
    await mon._poll_once(asyncio.Event())
    failed = [payload for et, payload in records if et == "preservation.failed"]
    assert len(failed) == 1
    assert failed[0]["reason"] == "consolidation"
    await eid.shutdown()


@pytest.mark.parametrize("arm", ["voice", "consolidation", "self_model_drift", "adapters"])
@pytest.mark.asyncio
async def test_reason_is_not_individuation_unless_arm_fired(
    bus, tmp_path, monkeypatch, arm
):
    fm = _StubFM()
    reg, eid = await _entity(bus, tmp_path)
    mon = _div_monitor(
        bus,
        reg,
        fm,
        _cfg(),
        monkeypatch,
        assessments=[_not_diverged(), _armed(arm)],
        tmp_state_root=tmp_path / "state",
    )
    await mon._poll_once(asyncio.Event())
    await mon._poll_once(asyncio.Event())
    assert len(fm.calls) == 1
    assert fm.calls[0]["reason"] != "individuation"
    assert fm.calls[0]["reason"] == arm
    await eid.shutdown()
