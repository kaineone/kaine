# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Stimulus control through the real playlist feed (stimulus-control-act).

Real media (synthetic clips written with PyAV), the real OpenCV video decode,
the real PyAV audio producer, and the boot's own feed factories. Each clip has
its own colour and tone, so a decoded frame or PCM block names its item.
"""
from __future__ import annotations

import asyncio
import time

import pytest

pytest.importorskip("av")
pytest.importorskip("cv2")

from kaine.boot.perception_feed import (  # noqa: E402
    _build_perception_feed_audio_factory,
    _build_perception_feed_video_factory,
)
from kaine.cycle.programme_end import ProgrammeEndWatcher  # noqa: E402
from kaine.entity_clock import EntityClock  # noqa: E402
from kaine.modules.audition.feed import PlaylistAudioStream  # noqa: E402
from kaine.modules.effectors.stimulus.config import StimulusControlConfig  # noqa: E402
from kaine.modules.effectors.stimulus.controller import ENTITY_HOLDER  # noqa: E402
from kaine.modules.effectors.stimulus.programme import ProgrammeClock  # noqa: E402
from kaine.modules.effectors.stimulus.runtime import StimulusControlRuntime  # noqa: E402
from kaine.modules.vision.feed import PlaylistClock, PlaylistSource  # noqa: E402
from tests.stimulus_media import dominant_bgr, rms, tone_of, write_manifest  # noqa: E402

RED, GREEN, BLUE = (255, 0, 0), (0, 255, 0), (0, 0, 255)
TONES = {300.0: "red", 500.0: "green", 800.0: "blue"}


def _programme(tmp_path, seconds=2.0):
    return write_manifest(
        tmp_path / "films",
        [("a.mkv", RED, 300.0, seconds), ("b.mkv", GREEN, 500.0, seconds), ("c.mkv", BLUE, 800.0, seconds)],
    )


def _runtime(**overrides):
    section = {"enabled": True, **overrides}
    return StimulusControlRuntime(
        StimulusControlConfig.from_section(section), now=time.monotonic, seed=7
    )


def _colour(frame):
    b, g, r = dominant_bgr(frame)
    if r > 150 and g < 100 and b < 100:
        return "red"
    if g > 150 and r < 100 and b < 100:
        return "green"
    if b > 150 and r < 100 and g < 100:
        return "blue"
    return f"?{(b, g, r)}"


def _tone(pcm):
    f = tone_of(pcm)
    if f == 0.0:
        return "silence"
    nearest = min(TONES, key=lambda t: abs(t - f))
    return TONES[nearest] if abs(nearest - f) < 60 else f"?{f:.0f}"


def test_probe_registers_every_items_real_duration(tmp_path):
    runtime = _runtime()
    clock = runtime.install_programme(str(_programme(tmp_path)), start=False)
    assert isinstance(clock, ProgrammeClock)
    assert [clock.duration(i) for i in range(3)] == [pytest.approx(2.0)] * 3
    assert clock.viewing_length == pytest.approx(6.0)


def test_video_follows_next_previous_and_wraps(tmp_path):
    runtime = _runtime()
    clock = runtime.install_programme(str(_programme(tmp_path)), start=False)
    controller = runtime.controller
    source = controller.wrap_video(PlaylistSource(runtime.programme.manifest, playlist_clock=clock))
    assert source.open()
    try:
        ok, frame = source.read()
        assert ok and _colour(frame) == "red"
        seen = []
        for action in ("next", "next", "next", "previous", "previous"):
            controller.apply(action)
            ok, frame = source.read()
            assert ok
            seen.append(_colour(frame))
        # next, next, next wraps to the first; previous wraps to the last.
        assert seen == ["green", "blue", "red", "blue", "green"]
        assert not clock.ended()
    finally:
        source.release()


def test_video_reopens_the_same_item_at_its_start(tmp_path):
    runtime = _runtime()
    clock = runtime.install_programme(
        str(write_manifest(tmp_path / "one", [("a.mkv", RED, 300.0, 3.0)])), start=False
    )
    source = runtime.controller.wrap_video(PlaylistSource(runtime.programme.manifest, playlist_clock=clock))
    assert source.open()
    try:
        source.read()
        time.sleep(0.35)
        source.read()
        before = source._inner._last_media_frame
        assert before >= 3
        runtime.controller.apply("next")  # the only item: back to its start
        ok, _frame = source.read()
        assert ok
        assert source._inner._last_media_frame < before
    finally:
        source.release()


def _collect(captured, n, timeout=4.0):
    deadline = time.monotonic() + timeout
    start = len(captured)
    while len(captured) - start < n and time.monotonic() < deadline:
        time.sleep(0.01)
    return captured[start:]


def test_audio_follows_a_seek_and_the_gain(tmp_path):
    runtime = _runtime()
    clock = runtime.install_programme(str(_programme(tmp_path, seconds=3.0)))
    controller = runtime.controller
    captured: list[bytes] = []
    stream = controller.wrap_audio(
        PlaylistAudioStream(
            runtime.programme.manifest,
            callback=controller.wrap_audio_callback(captured.append),
            sample_rate=16000,
            channels=1,
            frames_per_block=480,
            playlist_clock=clock,
        )
    )
    stream.start()
    try:
        blocks = _collect(captured, 6)
        assert {_tone(b) for b in blocks[1:]} == {"red"}
        level = sum(rms(b) for b in blocks[1:]) / len(blocks[1:])

        controller.apply("next")
        time.sleep(0.3)
        blocks = _collect(captured, 6)
        heard = [_tone(b) for b in blocks]
        assert heard and set(heard) <= {"green"}, heard

        for _ in range(3):
            controller.apply("louder")
        assert controller.gain_db == pytest.approx(6.0)
        time.sleep(0.1)
        blocks = _collect(captured, 6)
        louder = sum(rms(b) for b in blocks[1:]) / len(blocks[1:])
        assert louder / level == pytest.approx(10 ** (6 / 20), rel=0.05)

        controller.apply("previous")  # from the second item back to the first
        time.sleep(0.3)
        heard = [_tone(b) for b in _collect(captured, 6)]
        assert heard and set(heard) <= {"red"}, heard
    finally:
        stream.stop()
        runtime.close()


def test_entity_pause_holds_the_programme_and_releases_itself(tmp_path):
    runtime = _runtime(pause_max_s=0.6)
    clock = runtime.install_programme(str(_programme(tmp_path, seconds=3.0)))
    controller = runtime.controller
    captured: list[bytes] = []
    stream = controller.wrap_audio(
        PlaylistAudioStream(
            runtime.programme.manifest,
            callback=controller.wrap_audio_callback(captured.append),
            frames_per_block=480,
            playlist_clock=clock,
        )
    )
    stream.start()
    try:
        _collect(captured, 3)
        controller.apply("pause")
        assert ENTITY_HOLDER in clock.holders
        held_at = clock.elapsed()
        time.sleep(0.1)
        n = len(captured)
        time.sleep(0.25)
        assert len(captured) <= n + 1  # parked: at most the block in flight
        assert clock.elapsed() == pytest.approx(held_at, abs=1e-6)
        deadline = time.monotonic() + 2.0
        while ENTITY_HOLDER in clock.holders and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ENTITY_HOLDER not in clock.holders, "the entity pause did not release itself"
        assert runtime.tally.record()["auto_releases"] == 1
        assert len(_collect(captured, 3)) >= 3  # playback continues where it stopped
        assert clock.elapsed() == pytest.approx(held_at, abs=0.3)
    finally:
        stream.stop()
        runtime.close()


class _Mono:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def _fake_time_runtime(**overrides):
    mono = _Mono()
    section = {"enabled": True, **overrides}
    runtime = StimulusControlRuntime(StimulusControlConfig.from_section(section), now=mono, seed=1)
    return mono, runtime


def test_a_freeze_outlasting_the_entity_pause_keeps_the_programme_held(tmp_path):
    mono, runtime = _fake_time_runtime(pause_max_s=120.0)
    clock = runtime.install_programme(
        str(_programme(tmp_path)), probe=lambda item: 2.0, start=False
    )
    clock.start()
    controller = runtime.controller
    controller.apply("pause")
    clock.pause("freeze")
    mono.t = 121.0
    controller.poll_once()
    assert ENTITY_HOLDER not in clock.holders
    assert clock.paused and clock.holders == frozenset({"freeze"})
    clock.resume("freeze")
    assert not clock.paused


def test_skipping_never_ends_the_viewing_and_the_end_is_requested_once(tmp_path):
    mono = _Mono()
    runtime = StimulusControlRuntime(
        StimulusControlConfig.from_section({"enabled": True}), now=mono, seed=1
    )
    manifest = _programme(tmp_path)
    clock = runtime.install_programme(
        str(manifest), probe=lambda item: 2.0, start=False, monotonic=mono
    )
    clock.start()
    requests = []
    watcher = ProgrammeEndWatcher(
        clock,
        clock.item_count,
        write_request=requests.append,
        read_result=lambda: {"request_id": requests[-1].request_id, "ok": True} if requests else None,
        sleep=lambda s: asyncio.sleep(0),
    )
    for k in range(1, 12):
        mono.t = 0.5 * k
        runtime.controller.apply("next")
        assert not asyncio.run(watcher.step())
    assert requests == []
    mono.t = 6.0  # perceived programme time reaches the programme's 6 s length
    assert asyncio.run(watcher.step())
    assert asyncio.run(watcher.step())
    assert len(requests) == 1 and requests[0].stop is True


def test_boot_factories_wrap_both_surfaces_and_the_registry_wires_the_effector(tmp_path, monkeypatch):
    from kaine.boot.registry import SIMPLE_FACTORIES, build_registry
    from kaine.modules.effectors.stimulus.controller import (
        ControlledAudioStream,
        SeekAwareVideoSource,
    )

    manifest = _programme(tmp_path)
    captured: dict[str, dict] = {}

    class _Fake:
        relieves_drives: frozenset = frozenset()

        def __init__(self, name: str) -> None:
            self.name = name

    def _recorder(name: str):  # noqa: ANN202
        def factory(bus_, section, *, entity_clock=None, intent_secret=None, injections=None):  # noqa: ANN001
            captured[name] = dict(section)
            return _Fake(name)

        return factory

    for name in ("vision", "audition"):
        monkeypatch.setitem(SIMPLE_FACTORIES, name, _recorder(name))
    monkeypatch.setattr("kaine.boot.registry.install_state_encryption", lambda cfg: None)
    monkeypatch.setattr("kaine.boot.registry._wire_oscillators", lambda reg, cfg: None)
    monkeypatch.setattr("kaine.boot.registry._log_device_assignments", lambda reg, cfg: None)

    fakeredis = pytest.importorskip("fakeredis.aioredis")
    from kaine.bus.client import AsyncBus
    from kaine.bus.config import BusConfig

    bus = AsyncBus(
        BusConfig(password="x", audit_required=False),
        client=fakeredis.FakeRedis(decode_responses=True),
    )
    runtime = _runtime()
    kaine_config = {
        "modules": {"vision": True, "audition": True, "effectors": True, "affect": True},
        "perception_feed": {"mode": "playlist", "playlist_manifest": str(manifest), "transition_seconds": 0},
        "effectors": {
            "enabled_effectors": ["stimulus"],
            "sandbox_path": str(tmp_path / "sandbox"),
            "audit_log_path": str(tmp_path / "audit.log"),
            "notification_fallback_log": str(tmp_path / "notify.log"),
        },
    }
    try:
        registry = build_registry(
            bus, kaine_config, entity_clock=EntityClock(scale=1.0), stimulus_control=runtime
        )
        section = kaine_config["perception_feed"]
        pclock = section["_shared_playlist_clock"]
        assert isinstance(pclock, ProgrammeClock)
        assert section["_stimulus_controller"] is runtime.controller
        assert "stimulus" in registry.get("effectors").effectors
        assert registry.get("affect")._stimulus_credit_on
        video = _build_perception_feed_video_factory(
            "playlist", captured["vision"]["perception_feed"], width=64, height=48
        )(0, width=64, height=48)
        audio = _build_perception_feed_audio_factory(
            "playlist", captured["audition"]["perception_feed"],
            sample_rate=16000, channels=1, frames_per_block=480,
        )(device=None, sample_rate=16000, channels=1, frames_per_block=480, callback=lambda b: None)
        assert isinstance(video, SeekAwareVideoSource)
        assert isinstance(audio, ControlledAudioStream)
        assert video.clock is pclock and audio.clock is pclock
    finally:
        runtime.close()
        asyncio.run(bus.close())


def test_boot_with_stimulus_control_off_builds_the_plain_clock(tmp_path, monkeypatch):
    from kaine.boot.registry import SIMPLE_FACTORIES, build_registry

    manifest = _programme(tmp_path)
    captured: dict[str, dict] = {}

    def _recorder(name: str):  # noqa: ANN202
        def factory(bus_, section, *, entity_clock=None, intent_secret=None, injections=None):  # noqa: ANN001
            captured[name] = dict(section)
            return type("_Fake", (), {"name": name})()

        return factory

    for name in ("vision", "audition"):
        monkeypatch.setitem(SIMPLE_FACTORIES, name, _recorder(name))
    monkeypatch.setattr("kaine.boot.registry.install_state_encryption", lambda cfg: None)
    monkeypatch.setattr("kaine.boot.registry._wire_oscillators", lambda reg, cfg: None)
    monkeypatch.setattr("kaine.boot.registry._log_device_assignments", lambda reg, cfg: None)
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    from kaine.bus.client import AsyncBus
    from kaine.bus.config import BusConfig

    bus = AsyncBus(
        BusConfig(password="x", audit_required=False),
        client=fakeredis.FakeRedis(decode_responses=True),
    )
    kaine_config = {
        "modules": {"vision": True, "audition": True},
        "perception_feed": {"mode": "playlist", "playlist_manifest": str(manifest), "transition_seconds": 0},
        "stimulus_control": {"enabled": False},
    }
    try:
        registry = build_registry(bus, kaine_config, entity_clock=EntityClock(scale=1.0))
    finally:
        asyncio.run(bus.close())
    section = kaine_config["perception_feed"]
    assert type(section["_shared_playlist_clock"]) is PlaylistClock
    assert "_stimulus_controller" not in section and "_programme_manifest" not in section
    assert registry.stimulus_control is None
    video = _build_perception_feed_video_factory(
        "playlist", captured["vision"]["perception_feed"], width=64, height=48
    )(0, width=64, height=48)
    audio = _build_perception_feed_audio_factory(
        "playlist", captured["audition"]["perception_feed"],
        sample_rate=16000, channels=1, frames_per_block=480,
    )(device=None, sample_rate=16000, channels=1, frames_per_block=480, callback=lambda b: None)
    assert type(video) is PlaylistSource
    assert type(audio) is PlaylistAudioStream


def test_an_unmeasurable_item_or_missing_channel_stops_the_install(tmp_path):
    from kaine.modules.effectors.stimulus.config import StimulusControlError

    manifest = _programme(tmp_path)
    with pytest.raises(StimulusControlError):
        _runtime().install_programme(str(manifest), probe=lambda item: None, start=False)
    with pytest.raises(StimulusControlError):
        _runtime(channels=[str(tmp_path / "missing.toml")]).install_programme(
            str(manifest), start=False
        )


def test_the_registry_does_not_swallow_a_failed_install(tmp_path, monkeypatch):
    from kaine.boot.registry import SIMPLE_FACTORIES, build_registry
    from kaine.modules.effectors.stimulus.config import StimulusControlError

    monkeypatch.setitem(SIMPLE_FACTORIES, "vision", lambda *a, **k: None)
    monkeypatch.setattr("kaine.boot.registry.install_state_encryption", lambda cfg: None)
    runtime = _runtime(channels=[str(tmp_path / "missing.toml")])
    kaine_config = {
        "modules": {"vision": True},
        "perception_feed": {
            "mode": "playlist",
            "playlist_manifest": str(_programme(tmp_path)),
            "transition_seconds": 0,
        },
    }
    with pytest.raises(StimulusControlError):
        build_registry(
            object(), kaine_config, entity_clock=EntityClock(scale=1.0), stimulus_control=runtime
        )


def test_audio_from_before_a_jump_is_silent_until_the_producer_moves(tmp_path):
    import numpy as np

    mono, runtime = _fake_time_runtime()
    clock = runtime.install_programme(
        str(_programme(tmp_path)), probe=lambda item: 2.0, start=False, monotonic=mono
    )
    clock.start()
    heard: list[bytes] = []
    callback = runtime.controller.wrap_audio_callback(heard.append)
    block = (np.ones(480) * 5000).astype("<i2").tobytes()
    callback(block)
    runtime.controller.apply("next")
    callback(block)  # the producer has not been restarted yet
    runtime.controller.poll_once()  # no running stream: nothing to restart
    callback(block)
    assert heard[0] == block
    assert heard[1] == b"\x00" * len(block)
    assert heard[2] == block


def test_zero_gain_passes_the_samples_through_unchanged():
    from kaine.modules.effectors.stimulus.controller import apply_gain

    pcm = bytes(range(256)) * 4
    assert apply_gain(pcm, 0.0) is pcm
    louder = apply_gain(b"\x00\x10" * 8, 6.0)
    assert louder != b"\x00\x10" * 8
