# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for womb perception-feed boot wiring."""
from __future__ import annotations

import numpy as np
import pytest

from kaine.boot import (
    _build_perception_feed_audio_factory,
    _build_perception_feed_video_factory,
    _install_shared_womb_clock,
    gather_perception_feed_descriptor,
)
from kaine.lifecycle.stage import StageState, write_stage
from kaine.modules.topos.feed import WombClock


def test_womb_video_factory_returns_readable_bgr_frame():
    feed = {"mode": "womb", "seed": 1}
    factory = _build_perception_feed_video_factory("womb", feed, width=64, height=48)
    src = factory("ignored", width=64, height=48)
    src.open()
    ok, frame = src.read()
    assert ok is True
    assert frame is not None
    assert frame.dtype == np.uint8
    assert frame.shape == (48, 64, 3)


def test_womb_audio_factory_pcm_at_zero_has_expected_shape():
    feed = {"mode": "womb", "seed": 1, "audio": {"sample_rate": 16000, "channels": 1}}
    factory = _build_perception_feed_audio_factory(
        "womb", feed, sample_rate=16000, channels=1, frames_per_block=480
    )
    stream = factory(
        device="ignored",
        sample_rate=16000,
        channels=1,
        frames_per_block=480,
        callback=lambda b: None,
    )
    pcm = stream.pcm_at(0)
    samples = np.frombuffer(pcm, dtype=np.int16)
    assert samples.shape == (480 * 1,)


def test_womb_factories_share_clock_when_installed():
    clock = WombClock(lived_offset_seconds=0.0)
    lived = lambda: clock.womb_seconds()  # noqa: E731
    feed = {
        "mode": "womb",
        "seed": 1,
        "_shared_womb_clock": clock,
        "_womb_lived_seconds": lived,
    }
    vf = _build_perception_feed_video_factory("womb", feed, width=64, height=48)
    af = _build_perception_feed_audio_factory(
        "womb", feed, sample_rate=16000, channels=1, frames_per_block=480
    )
    src = vf("x", width=64, height=48)
    stream = af(
        device="x",
        sample_rate=16000,
        channels=1,
        frames_per_block=480,
        callback=lambda b: None,
    )
    assert src._clock is clock
    assert stream._clock is clock


def test_womb_factories_build_private_clock_without_shared_objects(tmp_path, monkeypatch):
    from kaine.lifecycle import stage as stage_mod

    monkeypatch.setattr(stage_mod, "STAGE_PATH", tmp_path / "stage.json")
    feed = {"mode": "womb", "seed": 1}
    vf = _build_perception_feed_video_factory("womb", feed, width=64, height=48)
    af = _build_perception_feed_audio_factory(
        "womb", feed, sample_rate=16000, channels=1, frames_per_block=480
    )
    src = vf("x", width=64, height=48)
    stream = af(
        device="x",
        sample_rate=16000,
        channels=1,
        frames_per_block=480,
        callback=lambda b: None,
    )
    assert src._clock is not None
    assert stream._clock is not None
    assert "_shared_womb_clock" not in feed
    assert "_womb_lived_seconds" not in feed


def test_install_shared_womb_clock_reads_stage_and_tracks_entity_clock(tmp_path, monkeypatch):
    from kaine.lifecycle import stage as stage_mod

    monkeypatch.setattr(stage_mod, "STAGE_PATH", tmp_path / "stage.json")
    stage_path = tmp_path / "stage.json"
    write_stage(StageState(lived_seconds=500.0), stage_path)

    class FakeEntityClock:
        def __init__(self) -> None:
            self._t = 0.0

        def now(self) -> float:
            return self._t

        def advance(self, dt: float) -> None:
            self._t += dt

    entity_clock = FakeEntityClock()
    feed: dict[str, object] = {}
    cfg: dict[str, object] = {}
    _install_shared_womb_clock(feed, cfg, entity_clock, stage_path=stage_path)
    clock = feed["_shared_womb_clock"]
    lived = feed["_womb_lived_seconds"]
    assert isinstance(clock, WombClock)
    assert clock.womb_seconds() >= 500.0
    assert cfg["perception_feed"]["_shared_womb_clock"] is clock
    assert cfg["perception_feed"]["_womb_lived_seconds"] is lived
    entity_clock.advance(10.0)
    assert lived() == pytest.approx(510.0, abs=0.001)


def test_install_shared_womb_clock_without_stage_offset_zero(tmp_path, monkeypatch):
    from kaine.lifecycle import stage as stage_mod

    monkeypatch.setattr(stage_mod, "STAGE_PATH", tmp_path / "stage.json")
    feed: dict[str, object] = {}
    cfg: dict[str, object] = {}
    _install_shared_womb_clock(feed, cfg, None)
    assert feed["_womb_lived_seconds"]() == 0.0
    assert feed["_shared_womb_clock"].womb_seconds() >= 0.0


def test_womb_video_factory_raises_at_build_for_bad_config():
    feed = {"mode": "womb", "womb": {"heartbeat_bpm": 500}}
    with pytest.raises(ValueError):
        _build_perception_feed_video_factory("womb", feed, width=64, height=48)


def test_womb_video_factory_raises_for_non_dict_video_section():
    feed = {"mode": "womb", "womb": {"video": "not-a-table"}}
    with pytest.raises(ValueError):
        _build_perception_feed_video_factory("womb", feed, width=64, height=48)


def test_womb_audio_factory_rejects_short_frames_per_block():
    feed = {"mode": "womb", "audio": {"sample_rate": 16000, "channels": 1}}
    with pytest.raises(ValueError):
        _build_perception_feed_audio_factory(
            "womb", feed, sample_rate=16000, channels=1, frames_per_block=64
        )


def test_gather_womb_descriptor():
    config = {"perception_feed": {"mode": "womb", "seed": 3}}
    desc = gather_perception_feed_descriptor(config)
    assert desc["mode"] == "womb"
    assert desc["regime"] == "womb"
    assert desc["seed"] == 3
    assert "heartbeat_bpm" in desc["womb"]
    assert "video" in desc
    assert "audio" in desc
    assert isinstance(desc["lived_offset_seconds"], float)
    assert "path" not in desc
    assert "playlist_manifest" not in desc


def test_gather_womb_descriptor_invalid_config_best_effort():
    config = {"perception_feed": {"mode": "womb", "womb": {"heartbeat_bpm": 500}}}
    desc = gather_perception_feed_descriptor(config)
    assert desc["mode"] == "womb"
    assert desc["regime"] == "womb"
    assert desc["womb"] == {"invalid": True}


@pytest.mark.asyncio
async def test_check_perception_womb_passes():
    from kaine.preboot import check_perception

    config = {
        "perception_feed": {"mode": "womb", "seed": 7},
        "modules": {"topos": True, "audition": True},
    }
    rows = await check_perception(config)
    video_rows = [r for r in rows if "video" in r.name]
    audio_rows = [r for r in rows if "audio" in r.name]
    assert video_rows and video_rows[0].status == "PASS"
    assert audio_rows and audio_rows[0].status == "PASS"


def test_build_registry_womb_mode_shares_one_clock_and_selects_virtual(
    monkeypatch, tmp_path
):
    """The real boot path: womb mode installs ONE shared womb clock (offset by
    the lived gestation time) that Topos and Audition both receive, and binds
    the senses to the virtual locus."""
    import asyncio

    import fakeredis.aioredis

    from kaine import perception_state
    from kaine.boot import SIMPLE_FACTORIES, build_registry
    from kaine.bus.client import AsyncBus
    from kaine.bus.config import BusConfig
    from kaine.entity_clock import EntityClock
    from kaine.lifecycle import stage as stage_mod

    stage_path = tmp_path / "stage.json"
    write_stage(StageState(lived_seconds=200.0), stage_path)
    monkeypatch.setattr(stage_mod, "STAGE_PATH", stage_path)
    monkeypatch.setattr(perception_state, "DESIRED_PATH", tmp_path / "desired.json")
    monkeypatch.setattr(perception_state, "RUNTIME_PATH", tmp_path / "runtime.json")

    captured: dict[str, dict] = {}

    class _Fake:
        def __init__(self, name: str) -> None:
            self.name = name

    def _recorder(name: str):
        def factory(bus_, section, *, entity_clock=None, intent_secret=None, injections=None):  # noqa: ANN001
            captured[name] = dict(section)
            return _Fake(name)

        return factory

    for name in ("topos", "audition"):
        monkeypatch.setitem(SIMPLE_FACTORIES, name, _recorder(name))
    monkeypatch.setattr("kaine.boot.install_state_encryption", lambda cfg: None)
    monkeypatch.setattr("kaine.boot._wire_self_hearing_gate", lambda reg: None)
    monkeypatch.setattr("kaine.boot._wire_lingua_self_model", lambda reg: None)
    monkeypatch.setattr("kaine.boot._wire_eidolon_capabilities", lambda reg: None)
    monkeypatch.setattr("kaine.boot._log_device_assignments", lambda reg, cfg: None)
    monkeypatch.setattr("kaine.boot._wire_oscillators", lambda reg, cfg: None)

    kaine_config = {
        "modules": {"topos": True, "audition": True},
        "perception_feed": {"mode": "womb", "seed": 5},
    }
    bus = AsyncBus(
        BusConfig(password="x", audit_required=False),
        client=fakeredis.aioredis.FakeRedis(decode_responses=True),
    )
    try:
        build_registry(bus, kaine_config, entity_clock=EntityClock(scale=1.0))
    finally:
        asyncio.run(bus.close())

    clock = kaine_config["perception_feed"]["_shared_womb_clock"]
    assert isinstance(clock, WombClock)
    assert captured["topos"]["perception_feed"]["_shared_womb_clock"] is clock
    assert captured["audition"]["perception_feed"]["_shared_womb_clock"] is clock
    assert clock.womb_seconds() >= 200.0
    assert kaine_config["perception_feed"]["_womb_lived_seconds"]() >= 200.0
    assert perception_state.read_desired().locus == "virtual"
