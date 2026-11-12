# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Stimulus control through the real playlist feed (stimulus-control-act).

Real media (synthetic clips written with PyAV), the real PyAV video decoder
and audio producer of the playlist feeds, and the boot's own feed factories. Each clip has
its own colour and tone, so a decoded frame or PCM block names its item.
"""
from __future__ import annotations

import asyncio
import time

import pytest

pytest.importorskip("av")

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
TONES = {300.0: "red", 500.0: "green", 800.0: "blue", 1200.0: "yellow"}


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
    # The container duration, the length both surfaces register.
    assert [clock.duration(i) for i in range(3)] == [pytest.approx(2.0, abs=0.05)] * 3
    assert clock.viewing_length == pytest.approx(6.0, abs=0.15)


def test_video_follows_next_previous_and_wraps(tmp_path):
    runtime = _runtime()
    clock = runtime.install_programme(str(_programme(tmp_path)), start=False)
    controller = runtime.controller
    source = PlaylistSource(runtime.programme.manifest, playlist_clock=clock)
    opened = source.open()
    assert opened
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
    source = PlaylistSource(runtime.programme.manifest, playlist_clock=clock)
    opened = source.open()
    assert opened
    try:
        source.read()
        time.sleep(0.45)
        source.read()
        before = source._shown.t
        assert before >= 0.3
        runtime.controller.apply("next")  # the only item: back to its start
        ok, _frame = source.read()
        assert ok
        # The decoder sought to the clock's offset (its base is the target).
        assert source._shown.t < before
        assert abs(source._shown.t - clock.locate()[1]) <= 0.15
    finally:
        source.release()


def _assert_paced(stream, clock, tolerance=0.15):
    """The delivered audio is on the clock's item and within ``tolerance`` of it."""
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        delivered = stream.delivered_position
        c_idx, c_off = clock.locate()
        if delivered is not None and delivered[0] == c_idx and abs(delivered[1] - c_off) <= tolerance:
            return
        time.sleep(0.02)
    raise AssertionError(f"audio not paced to the clock: {stream.delivered_position} vs {clock.locate()}")


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
    stream = PlaylistAudioStream(
        runtime.programme.manifest,
        callback=controller.wrap_audio_callback(captured.append),
        sample_rate=16000,
        channels=1,
        frames_per_block=480,
        playlist_clock=clock,
    )
    stream.start()
    try:
        blocks = _collect(captured, 6)
        assert {_tone(b) for b in blocks[1:]} == {"red"}
        level = sum(rms(b) for b in blocks[1:]) / len(blocks[1:])

        n_before = len(captured)
        controller.apply("next")
        time.sleep(0.3)
        blocks = _collect(captured, 6)
        heard = [_tone(b) for b in blocks]
        assert heard and set(heard) <= {"green"}, heard
        # At most the block already in flight is from before the jump.
        after_jump = [_tone(b) for b in captured[n_before + 1:]]
        assert "red" not in after_jump, after_jump
        _assert_paced(stream, clock)

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
        _assert_paced(stream, clock)
        assert stream._jumps == 2 and stream._skips == 0
    finally:
        stream.stop()
        runtime.close()


def test_entity_pause_holds_the_programme_and_releases_itself(tmp_path):
    runtime = _runtime(pause_max_s=0.6)
    clock = runtime.install_programme(str(_programme(tmp_path, seconds=3.0)))
    controller = runtime.controller
    captured: list[bytes] = []
    stream = PlaylistAudioStream(
        runtime.programme.manifest,
        callback=controller.wrap_audio_callback(captured.append),
        frames_per_block=480,
        playlist_clock=clock,
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
        collected = _collect(captured, 3)
        assert len(collected) >= 3  # playback continues where it stopped
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
        finished = asyncio.run(watcher.step())
        assert not finished
    assert requests == []
    mono.t = 6.0  # perceived programme time reaches the programme's 6 s length
    finished = asyncio.run(watcher.step())
    assert finished
    finished = asyncio.run(watcher.step())
    assert finished
    assert len(requests) == 1 and requests[0].stop is True


def test_boot_factories_wrap_both_surfaces_and_the_registry_wires_the_effector(tmp_path, monkeypatch):
    from kaine.boot.registry import SIMPLE_FACTORIES, build_registry

    manifest = _programme(tmp_path)
    captured: dict[str, dict] = {}

    class _Fake:
        relieves_drives: frozenset = frozenset()

        def __init__(self, name: str) -> None:
            self.name = name

    def _recorder(name: str):  # noqa: ANN202
        def factory(bus_, section, *, entity_clock=None, intent_secret=None, injections=None, router=None):  # noqa: ANN001
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
        assert type(video) is PlaylistSource and type(audio) is PlaylistAudioStream
        assert video.clock is pclock and audio.clock is pclock
        assert video.manifest is section["_programme_manifest"]
    finally:
        runtime.close()
        asyncio.run(bus.close())


def test_boot_with_stimulus_control_off_builds_the_plain_clock(tmp_path, monkeypatch):
    from kaine.boot.registry import SIMPLE_FACTORIES, build_registry

    manifest = _programme(tmp_path)
    captured: dict[str, dict] = {}

    def _recorder(name: str):  # noqa: ANN202
        def factory(bus_, section, *, entity_clock=None, intent_secret=None, injections=None, router=None):  # noqa: ANN001
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


def test_audio_follows_a_channel_switch_and_wraps_inside_it(tmp_path):
    second = write_manifest(
        tmp_path / "second", [("d.mkv", (255, 255, 0), 1200.0, 1.0)], name="second.toml"
    )
    runtime = _runtime(channels=[str(second)])
    clock = runtime.install_programme(str(_programme(tmp_path, seconds=3.0)))
    controller = runtime.controller
    captured: list[bytes] = []
    stream = PlaylistAudioStream(
        runtime.programme.manifest,
        callback=controller.wrap_audio_callback(captured.append),
        frames_per_block=480,
        playlist_clock=clock,
    )
    stream.start()
    try:
        _collect(captured, 4)
        controller.apply("channel:1")
        assert clock.locate()[0] == 3
        time.sleep(0.3)
        heard = [_tone(b) for b in _collect(captured, 6)]
        assert heard and set(heard) <= {"yellow"}, heard
        _assert_paced(stream, clock)
        # The one-second channel wraps inside itself: still channel 1 after it,
        # and its sound goes on (twenty blocks is 0.6 s of audio).
        time.sleep(1.2)
        assert clock.locate()[0] == 3
        later = _collect(captured, 20, timeout=2.0)
        assert len(later) == 20 and {_tone(b) for b in later[1:]} <= {"yellow", "silence"}
        time.sleep(1.0)
        again = _collect(captured, 20, timeout=2.0)
        assert len(again) == 20 and "yellow" in {_tone(b) for b in again}
        _assert_paced(stream, clock, tolerance=0.2)
        # Natural wraps past the channel's end are not lag (second review F5).
        assert stream._skips == 0, stream._skips
    finally:
        stream.stop()
        runtime.close()


def test_zero_gain_passes_the_samples_through_unchanged():
    from kaine.modules.effectors.stimulus.controller import apply_gain

    pcm = bytes(range(256)) * 4
    assert apply_gain(pcm, 0.0) is pcm
    louder = apply_gain(b"\x00\x10" * 8, 6.0)
    assert louder != b"\x00\x10" * 8


def test_no_path_reaches_the_logs(tmp_path, caplog):
    """Jumps, a failed install and the seek path log indices only, never a path."""
    import logging

    from kaine.modules.effectors.stimulus.config import StimulusControlError

    with caplog.at_level(logging.DEBUG):
        runtime = _runtime()
        clock = runtime.install_programme(str(_programme(tmp_path)), start=False)
        source = PlaylistSource(runtime.programme.manifest, playlist_clock=clock)
        opened = source.open()
        assert opened
        try:
            source.read()
            for action in ("next", "previous", "previous"):
                runtime.controller.apply(action)
                source.read()
        finally:
            source.release()
        with pytest.raises(StimulusControlError) as raised:
            _runtime(channels=[str(tmp_path / "missing.toml")]).install_programme(
                str(_programme(tmp_path / "again")), start=False
            )
        assert str(tmp_path) not in str(raised.value)
        assert raised.value.__cause__ is None and raised.value.__suppress_context__
        with pytest.raises(StimulusControlError) as unmeasured:
            _runtime().install_programme(
                str(_programme(tmp_path / "third")), probe=lambda item: None, start=False
            )
        assert str(tmp_path) not in str(unmeasured.value)
    for record in caplog.records:
        text = record.getMessage()
        if record.exc_info:
            text += logging.Formatter().formatException(record.exc_info)
        assert str(tmp_path) not in text, text


@pytest.mark.slow
@pytest.mark.skipif(
    not __import__("os").environ.get("KAINE_PROGRAMME_MEDIA"),
    reason="set KAINE_PROGRAMME_MEDIA to a directory holding programme.toml and its films",
)
def test_programme_films_under_stimulus_control(capsys):
    """The programme films: the probe registers each container duration, a
    seek shows the frame at or before the clock (through the decoder's seek),
    and the sound follows a jump paced against the clock."""
    import os
    from pathlib import Path as _Path

    from kaine.modules.vision.feed import container_duration_s

    manifest_path = _Path(os.environ["KAINE_PROGRAMME_MEDIA"]) / "programme.toml"
    mono = _Mono()
    runtime = StimulusControlRuntime(
        StimulusControlConfig.from_section({"enabled": True}), now=mono, seed=1
    )
    clock = runtime.install_programme(str(manifest_path), start=False, monotonic=mono)
    import av

    for i, item in enumerate(runtime.programme.manifest.items):
        container = av.open(item.path)
        assert clock.duration(i) == container_duration_s(container)
        container.close()
    source = PlaylistSource(runtime.programme.manifest, playlist_clock=clock)
    opened = source.open()
    assert opened
    leads = []
    try:
        clock.start(at=0.0)
        mono.t = 30.0
        source.read()
        for action in ("next", "next", "next", "next", "previous"):
            runtime.controller.apply(action)
            mono.t += 600.0  # ten minutes into the item: the source seeks
            ok, _frame = source.read()
            assert ok
            idx, offset = clock.locate()
            leads.append((action, idx, source._shown.t - offset))
    finally:
        source.release()
    for _action, _idx, lead in leads:
        assert -0.1 <= lead <= 0.0, leads
    # Sound: real time, a jump forward then back, paced to the clock.
    rt = _runtime()
    rclock = rt.install_programme(str(manifest_path))
    heard: list[bytes] = []
    stream = PlaylistAudioStream(
        rt.programme.manifest,
        callback=rt.controller.wrap_audio_callback(heard.append),
        frames_per_block=480,
        playlist_clock=rclock,
    )
    stream.start()
    try:
        _collect(heard, 10, timeout=10.0)
        rt.controller.apply("next")
        _assert_paced(stream, rclock, tolerance=0.2)
        rt.controller.apply("previous")
        _assert_paced(stream, rclock, tolerance=0.2)
        assert stream._jumps == 2 and stream._skips == 0
    finally:
        stream.stop()
        rt.close()
    with capsys.disabled():
        print("\nstimulus control over the films, frame minus clock after each seek: "
              + ", ".join(f"{a}->item {i}: {lead * 1000:+.0f} ms" for a, i, lead in leads))


def test_a_jump_goes_through_the_decoders_seek(tmp_path):
    """After a jump the reopened item's decoder seeks to the clock's offset."""
    from tests._playlist_fakes import FakeVideoDecoders

    mono, runtime = _fake_time_runtime()
    clock = runtime.install_programme(
        str(_programme(tmp_path)), probe=lambda item: 2.0, start=False, monotonic=mono
    )
    decoders = FakeVideoDecoders(20)
    source = PlaylistSource(
        runtime.programme.manifest, playlist_clock=clock, decoder_factory=decoders
    )
    opened = source.open()
    assert opened
    clock.start(at=0.0)
    mono.t = 0.5
    source.read()
    runtime.controller.apply("next")
    mono.t = 1.2  # 0.7 s into the next item, within the decoder's seek-behind span
    ok, frame = source.read()
    assert ok
    assert decoders.opened[-1].seeks == [pytest.approx(0.7)]
    assert frame == (decoders.opened[-1].path, 7)
