# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The womb-to-world transition (womb-to-world-transition).

Covers the pure crossfade functions, the bloom-peak womb field, the shared
controller's single release of the ``transition`` holder, the video and audio
surfaces, the boot conditions (and their logged reasons), the run-manifest
covariate, and zero persistence. No real camera, microphone or media decoder:
decoding goes through small in-memory fakes of cv2 and PyAV.
"""
from __future__ import annotations

import hashlib
import logging
import math
import sys
import time
from pathlib import Path

import numpy as np
import pytest

from kaine.boot import (
    _build_perception_feed_audio_factory,
    _build_perception_feed_video_factory,
    _build_womb_world_transition,
    _install_womb_world_transition,
    _plan_womb_world_transition,
    _womb_params,
    gather_perception_feed_descriptor,
)
from kaine.cycle.ignition_log import playlist_position_provider
from kaine.lifecycle import stage as lifecycle_stage
from kaine.modules.audition.feed import PlaylistAudioStream
from kaine.modules.perception_transition import (
    TRANSITION_HOLDER,
    TransitionAudioStream,
    TransitionController,
    TransitionVideoSource,
    apply_audio_fade,
    audio_fade_gain,
    blend_frames,
    render_birth_field,
    resize_bilinear,
    smoothstep,
    transition_alpha,
)
from kaine.modules.topos.feed import (
    PlaylistClock,
    PlaylistSource,
    WombClock,
    WombProceduralSource,
    WombSchedule,
    load_playlist_manifest,
)

FILM_H, FILM_W = 20, 30
FPS = 30
WOMB_W, WOMB_H = 32, 24

# ---------------------------------------------------------------------------
# Fakes and fixtures
# ---------------------------------------------------------------------------


class _FakeClock:
    """Manually advanced monotonic clock."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


class _FakeTimer:
    def __init__(self, interval: float, fn) -> None:  # noqa: ANN001
        self.interval = interval
        self.fn = fn
        self.started = False
        self.cancelled = False

    def start(self) -> None:
        self.started = True

    def cancel(self) -> None:
        self.cancelled = True


class _TimerFactory:
    def __init__(self) -> None:
        self.timers: list[_FakeTimer] = []

    def __call__(self, interval: float, fn) -> _FakeTimer:  # noqa: ANN001
        timer = _FakeTimer(interval, fn)
        self.timers.append(timer)
        return timer

    def fire_last(self) -> None:
        self.timers[-1].fn()


class _CountingClock(PlaylistClock):
    """A real PlaylistClock that counts releases of the transition holder."""

    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        super().__init__(*args, **kwargs)
        self.transition_resumes = 0

    def resume(self, holder: str = "default") -> None:
        if holder == TRANSITION_HOLDER:
            self.transition_resumes += 1
        super().resume(holder)


def _film_frame(i: int) -> np.ndarray:
    ys = np.arange(FILM_H, dtype=np.int64).reshape(FILM_H, 1, 1)
    xs = np.arange(FILM_W, dtype=np.int64).reshape(1, FILM_W, 1)
    cs = np.arange(3, dtype=np.int64).reshape(1, 1, 3)
    return ((ys * 5 + xs * 3 + cs * 40 + i * 11) % 256).astype(np.uint8)


class _FakeCap:
    def __init__(self, frame_count: int) -> None:
        self._n = frame_count
        self._i = 0

    def isOpened(self) -> bool:  # noqa: N802 — mirrors cv2 API
        return True

    def get(self, prop) -> float:  # noqa: ANN001
        return float(self._n)

    def read(self):  # noqa: ANN201
        if self._i >= self._n:
            return False, None
        frame = _film_frame(self._i)
        self._i += 1
        return True, frame

    def release(self) -> None:
        return None


class _FakeCv2:
    CAP_PROP_FRAME_COUNT = 7

    def __init__(self, frame_count: int = 600) -> None:
        self._n = frame_count

    def VideoCapture(self, path: str) -> _FakeCap:  # noqa: N802 — mirrors cv2 API
        return _FakeCap(self._n)


def _write_manifest(root: Path) -> Path:
    data = b"film-media-0"
    (root / "film.mp4").write_bytes(data)
    manifest = root / "programme.toml"
    manifest.write_text(
        "[[item]]\n"
        'path = "film.mp4"\n'
        f'sha256 = "{hashlib.sha256(data).hexdigest()}"\n'
        f"fps = {FPS}\n"
        "order = 0\n",
        encoding="utf-8",
    )
    return manifest


def _feed(manifest: Path | None = None, **overrides) -> dict:  # noqa: ANN003
    feed = {
        "mode": "playlist",
        "playlist_manifest": str(manifest) if manifest is not None else "",
        "transition_seconds": 4.0,
        "transition_audio_fade_seconds": 1.0,
    }
    feed.update(overrides)
    return feed


def _born_stage(feed: dict, **overrides) -> lifecycle_stage.StageState:  # noqa: ANN003
    fields = {
        "stage": lifecycle_stage.EMBODIED,
        "gestation_started_at": "2026-09-01T00:00:00+00:00",
        "born_at": "2026-09-02T00:00:00+00:00",
        "lived_seconds": 5000.0,
        "womb_t_at_birth": 5003.2,
        "womb_seed": 7,
        "womb_params_digest": lifecycle_stage.womb_params_digest(_womb_params(feed)),
    }
    fields.update(overrides)
    return lifecycle_stage.StageState(**fields)


def _build(feed: dict, stage, clock: _FakeClock, timers: _TimerFactory, n_items: int = 1):  # noqa: ANN001, ANN202
    pclock = _CountingClock(n_items, clock=clock)
    transition = _build_womb_world_transition(
        feed,
        pclock,
        stage_state=stage,
        width=WOMB_W,
        height=WOMB_H,
        clock=clock,
        timer_factory=timers,
    )
    return transition, pclock


def _video(tmp_path: Path, feed: dict, clock: _FakeClock, timers: _TimerFactory):  # noqa: ANN202
    transition, pclock = _build(feed, _born_stage(feed), clock, timers)
    assert transition is not None
    manifest = load_playlist_manifest(feed["playlist_manifest"])
    inner = PlaylistSource(manifest, playlist_clock=pclock, cv2_module=_FakeCv2())
    source = TransitionVideoSource(inner, transition)
    assert source.open()
    return source, transition, pclock, manifest


# ---------------------------------------------------------------------------
# Pure functions
# ---------------------------------------------------------------------------


def test_smoothstep_endpoints_exact_and_monotonic():
    assert smoothstep(0.0) == 0.0
    assert smoothstep(1.0) == 1.0
    assert smoothstep(0.5) == 0.5
    assert smoothstep(-3.0) == 0.0
    assert smoothstep(7.0) == 1.0
    assert smoothstep(float("nan")) == 0.0
    xs = np.linspace(0.0, 1.0, 1001)
    ys = [smoothstep(float(x)) for x in xs]
    assert all(b >= a for a, b in zip(ys, ys[1:]))
    assert transition_alpha(0.0, 20.0) == 0.0
    assert transition_alpha(20.0, 20.0) == 1.0
    assert transition_alpha(25.0, 20.0) == 1.0
    assert transition_alpha(3.0, 0.0) == 1.0


def test_blend_bounds_dtype_and_exact_endpoints():
    rng = np.random.default_rng(3)
    a = rng.integers(0, 256, size=(6, 5, 3), dtype=np.uint8)
    b = rng.integers(0, 256, size=(6, 5, 3), dtype=np.uint8)
    assert np.array_equal(blend_frames(a, b, 0.0), a)
    assert np.array_equal(blend_frames(a, b, 1.0), b)
    assert np.array_equal(blend_frames(a, b, -1.0), a)
    assert np.array_equal(blend_frames(a, b, 2.0), b)
    for alpha in (0.1, 0.5, 0.9):
        out = blend_frames(a, b, alpha)
        assert out.dtype == np.uint8
        assert out.shape == a.shape
        lo = np.minimum(a, b)
        hi = np.maximum(a, b)
        assert np.all(out >= lo) and np.all(out <= hi)
    with pytest.raises(ValueError):
        blend_frames(a, b[:5], 0.5)


def test_resize_bilinear_is_deterministic_and_keeps_flat_fields():
    rng = np.random.default_rng(4)
    img = rng.integers(0, 256, size=(24, 32, 3), dtype=np.uint8)
    a = resize_bilinear(img, FILM_H, FILM_W)
    b = resize_bilinear(img, FILM_H, FILM_W)
    assert a.shape == (FILM_H, FILM_W, 3) and a.dtype == np.uint8
    assert np.array_equal(a, b)
    flat = np.full((24, 32, 3), 77, dtype=np.uint8)
    assert np.all(resize_bilinear(flat, 50, 70) == 77)
    assert np.array_equal(resize_bilinear(img, 24, 32), img)


def test_audio_fade_gain_is_exact_at_start_mid_and_end():
    assert audio_fade_gain(0, 48000) == 0.0
    assert audio_fade_gain(24000, 48000) == 0.5
    assert audio_fade_gain(48000, 48000) == 1.0
    assert audio_fade_gain(96000, 48000) == 1.0
    assert audio_fade_gain(0, 0) == 1.0


def test_apply_audio_fade_ramps_each_frame_and_passes_after_the_fade():
    fade = 8
    mono = np.full(12, 1000, dtype="<i2").tobytes()
    out = np.frombuffer(apply_audio_fade(mono, start_frame=0, channels=1, fade_frames=fade), dtype="<i2")
    expected = [round(1000 * min(1.0, n / fade)) for n in range(12)]
    assert out.tolist() == expected
    assert out[0] == 0 and out[4] == 500 and out[8] == 1000
    # Stereo: both channels of a frame share one gain.
    stereo = np.array([1000, -1000] * 6, dtype="<i2").tobytes()
    out2 = np.frombuffer(
        apply_audio_fade(stereo, start_frame=2, channels=2, fade_frames=fade), dtype="<i2"
    ).reshape(6, 2)
    assert np.array_equal(out2[:, 0], -out2[:, 1])
    assert out2[2, 0] == 500  # frame index 2 + 2 = 4 -> gain 0.5
    # Past the fade and with no fade, the block is untouched.
    assert apply_audio_fade(mono, start_frame=fade, channels=1, fade_frames=fade) == mono
    assert apply_audio_fade(mono, start_frame=0, channels=1, fade_frames=0) == mono


def test_birth_field_is_the_womb_bloom_peak_at_the_recorded_time():
    feed = _feed()
    params = _womb_params(feed)
    field = render_birth_field(
        seed=7, womb_t_at_birth=5003.2, lived_seconds=5000.0, params=params,
        width=WOMB_W, height=WOMB_H,
    )
    schedule = WombSchedule(seed=7, width=WOMB_W, height=WOMB_H)
    womb = WombProceduralSource(
        schedule, params=params,
        clock=WombClock(lived_offset_seconds=5000.0), lived_seconds=lambda: 5000.0,
    )
    i_birth = math.floor(5003.2 * schedule.frame_rate_hz)
    assert np.array_equal(field, womb.frame_at(i_birth, birth_progress=1.0))
    assert field.shape == (WOMB_H, WOMB_W, 3) and field.dtype == np.uint8
    # Bright bloom (well above the dim gestation field) and bounded.
    assert field.max() <= int(0.8 * 255) + 1
    assert field.mean() > womb.frame_at(i_birth).mean()


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_two_constructions_give_identical_transition_frames(tmp_path):
    feed = _feed(_write_manifest(tmp_path))
    frames = []
    for _ in range(2):
        clock, timers = _FakeClock(), _TimerFactory()
        source, transition, _pclock, _m = _video(tmp_path, feed, clock, timers)
        run = []
        for t in (0.0, 0.7, 2.0, 3.3, 3.99):
            clock.t = t
            ok, frame = source.read()
            assert ok
            run.append(frame.copy())
        frames.append(run)
    for a, b in zip(*frames):
        assert np.array_equal(a, b)
    # And the crossfade actually moves between its ends.
    assert not np.array_equal(frames[0][0], frames[0][2])


# ---------------------------------------------------------------------------
# Controller and the video surface
# ---------------------------------------------------------------------------


def test_controller_releases_the_holder_once_after_transition_seconds():
    clock, timers = _FakeClock(), _TimerFactory()
    pclock = _CountingClock(1, clock=clock)
    pclock.set_duration(0, 100.0)
    controller = TransitionController(pclock, 4.0, clock=clock, timer_factory=timers)
    # Paused under `transition` before any read; not started, nothing armed.
    assert pclock.paused and not controller.started and timers.timers == []
    clock.t = 10.0
    controller.start()
    controller.start()  # idempotent
    assert len(timers.timers) == 1 and timers.timers[0].interval == 4.0
    assert pclock.started and pclock.locate() == (0, 0.0)
    # Never before transition_seconds: neither the read path nor an early timer.
    clock.t = 13.999
    assert controller.poll() is False
    timers.fire_last()
    assert not controller.released and pclock.transition_resumes == 0
    assert len(timers.timers) == 2  # re-armed for the remainder
    assert timers.timers[1].interval == pytest.approx(0.001)
    assert pclock.locate() == (0, 0.0)
    # At transition_seconds the timer releases, once; programme time is zero.
    clock.t = 14.0
    timers.fire_last()
    assert controller.released and pclock.transition_resumes == 1
    assert not pclock.paused
    assert pclock.locate() == (0, 0.0)
    assert timers.timers[-1].cancelled
    # Further polls, timer fires and aborts never release again.
    assert controller.poll() is True
    timers.fire_last()
    controller.abort("late")
    assert pclock.transition_resumes == 1
    # Programme time then runs from the release.
    clock.t = 15.5
    assert pclock.locate() == (0, pytest.approx(1.5))


def test_video_source_crossfades_then_plays_from_programme_zero(tmp_path):
    feed = _feed(_write_manifest(tmp_path))
    clock, timers = _FakeClock(), _TimerFactory()
    source, transition, pclock, manifest = _video(tmp_path, feed, clock, timers)
    position = playlist_position_provider(pclock, manifest)
    film0 = _film_frame(0)
    womb = resize_bilinear(transition.womb_frame, FILM_H, FILM_W)

    clock.t = 100.0
    ok, frame = source.read()  # first read starts the transition
    assert ok and np.array_equal(frame, womb)
    assert source.current_item is None
    assert position() == (0, 0, "film.mp4", 0.0, True)

    clock.t = 102.0
    ok, frame = source.read()
    assert np.array_equal(frame, blend_frames(womb, film0, 0.5))
    assert pclock.locate() == (0, 0.0)

    clock.t = 104.0  # transition_seconds elapsed: the read releases
    ok, frame = source.read()
    assert ok and np.array_equal(frame, film0)
    assert pclock.transition_resumes == 1
    assert pclock.locate() == (0, 0.0)
    assert position() == (0, 0, "film.mp4", 0.0, False)
    assert source.current_item.offset == 0.0

    clock.t = 105.0  # one second of programme time -> media frame 30
    ok, frame = source.read()
    assert np.array_equal(frame, _film_frame(FPS))
    # The timer arriving late does not release again.
    timers.fire_last()
    assert pclock.transition_resumes == 1


def test_first_frame_decode_leaves_the_programme_clock_untouched(tmp_path):
    manifest = load_playlist_manifest(_write_manifest(tmp_path))
    pclock = PlaylistClock(1, clock=_FakeClock())
    src = PlaylistSource(manifest, playlist_clock=pclock, cv2_module=_FakeCv2())
    assert src.first_frame() is None  # not verified yet
    assert src.open()
    assert np.array_equal(src.first_frame(), _film_frame(0))
    assert not pclock.started


def test_an_undecodable_first_frame_abandons_the_transition(tmp_path, caplog):
    feed = _feed(_write_manifest(tmp_path))
    clock, timers = _FakeClock(), _TimerFactory()
    transition, pclock = _build(feed, _born_stage(feed), clock, timers)
    caplog.set_level(logging.WARNING)
    assert transition.prepare(lambda: None) is False
    assert transition.released and not pclock.paused
    assert pclock.transition_resumes == 1
    assert "first frame could not be decoded" in caplog.text


# ---------------------------------------------------------------------------
# Audio surface
# ---------------------------------------------------------------------------


def _install_fake_av(monkeypatch) -> None:  # noqa: ANN001
    class _Plane:
        def __init__(self, d: bytes) -> None:
            self._d = d

        def __bytes__(self) -> bytes:
            return bytes(self._d)

    class _Frame:
        def __init__(self, d: bytes) -> None:
            self.planes = [_Plane(d)]

    class _AudioResampler:
        def __init__(self, **kwargs) -> None:  # noqa: ANN003
            pass

        def resample(self, frame):  # noqa: ANN001, ANN201
            yield frame

    class _Streams:
        audio = [object()]

    class _Container:
        duration = 8_000_000
        streams = _Streams()

        def decode(self, stream):  # noqa: ANN001, ANN201
            for _ in range(8):
                yield _Frame(b"\x01" * 32_000)

        def close(self) -> None:
            pass

    class _ResamplerNS:
        AudioResampler = _AudioResampler

    class _AudioNS:
        resampler = _ResamplerNS

    class _FakeAv:
        audio = _AudioNS

        @staticmethod
        def open(path):  # noqa: ANN001, ANN205
            return _Container()

    monkeypatch.setitem(sys.modules, "av", _FakeAv)


def _wait_for(predicate, timeout: float = 5.0) -> bool:  # noqa: ANN001
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def test_audio_is_silent_during_the_crossfade_then_fades_in(tmp_path, monkeypatch):
    _install_fake_av(monkeypatch)
    feed = _feed(_write_manifest(tmp_path))
    clock, timers = _FakeClock(), _TimerFactory()
    transition, pclock = _build(feed, _born_stage(feed), clock, timers)
    manifest = load_playlist_manifest(feed["playlist_manifest"])
    heard: list[bytes] = []
    stream = TransitionAudioStream(
        lambda cb: PlaylistAudioStream(
            manifest, callback=cb, sample_rate=16000, channels=1,
            frames_per_block=480, playlist_clock=pclock,
        ),
        callback=heard.append,
        transition=transition,
        sample_rate=16000,
        channels=1,
    )
    clock.t = 50.0
    stream.start()  # the audio surface starts the shared transition
    try:
        assert transition.controller.started
        time.sleep(0.2)
        assert heard == []  # the programme is held: nothing is heard
        assert stream.current_item is None
        clock.t = 54.0
        timers.fire_last()  # no video surface: the timer releases
        assert transition.released and pclock.transition_resumes == 1
        assert _wait_for(lambda: len(heard) >= 2)
    finally:
        stream.stop()
    fade_frames = 16000  # 1.0 s at 16 kHz
    first = np.frombuffer(heard[0], dtype="<i2")
    second = np.frombuffer(heard[1], dtype="<i2")
    assert first.tolist() == [round(257 * n / fade_frames) for n in range(480)]
    assert second.tolist() == [round(257 * n / fade_frames) for n in range(480, 960)]
    assert first[0] == 0


def test_fade_continues_across_blocks_to_full_gain():
    clock, timers = _FakeClock(), _TimerFactory()
    pclock = PlaylistClock(1, clock=clock)
    feed = _feed()
    transition = _build_womb_world_transition(
        dict(feed, transition_audio_fade_seconds=0.001), pclock,
        stage_state=_born_stage(feed), width=8, height=6, clock=clock, timer_factory=timers,
    )
    block = np.full(10, 2000, dtype="<i2").tobytes()
    # Before release any block is silenced.
    assert transition.fade_block(block, sample_rate=16000, channels=1) == b"\x00" * 20
    transition.controller.start()
    clock.t = 4.0
    assert transition.controller.poll()
    a = np.frombuffer(transition.fade_block(block, sample_rate=16000, channels=1), dtype="<i2")
    b = np.frombuffer(transition.fade_block(block, sample_rate=16000, channels=1), dtype="<i2")
    fade = 16  # 0.001 s at 16 kHz
    assert a.tolist() == [round(2000 * n / fade) for n in range(10)]
    assert b.tolist() == [round(2000 * min(1.0, n / fade)) for n in range(10, 20)]
    assert transition.fade_block(block, sample_rate=16000, channels=1) == block


# ---------------------------------------------------------------------------
# Boot conditions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("case", "level", "fragment"),
    [
        ("mode", logging.INFO, "not 'playlist'"),
        ("disabled", logging.INFO, "transition_seconds is 0"),
        ("no_stage", logging.INFO, "no developmental stage"),
        ("gestating", logging.INFO, "not born yet"),
        ("never_born", logging.INFO, "never born from the womb"),
        ("missing_record", logging.WARNING, "no womb birth record"),
        ("digest_mismatch", logging.WARNING, "digest mismatch"),
    ],
)
def test_no_transition_logs_why(case, level, fragment, caplog):
    feed = _feed()
    stage = _born_stage(feed)
    if case == "mode":
        feed["mode"] = "seeded"
    elif case == "disabled":
        feed["transition_seconds"] = 0
    elif case == "no_stage":
        stage = None
    elif case == "gestating":
        stage = lifecycle_stage.StageState(stage=lifecycle_stage.GESTATION)
    elif case == "never_born":
        stage = lifecycle_stage.StageState(stage=lifecycle_stage.EMBODIED)
    elif case == "missing_record":
        stage = _born_stage(feed, womb_t_at_birth=None)
    elif case == "digest_mismatch":
        feed["womb"] = {"heartbeat_bpm": 90}
    clock, timers = _FakeClock(), _TimerFactory()
    caplog.set_level(logging.INFO, logger="kaine.boot")
    transition, pclock = _build(feed, stage, clock, timers)
    assert transition is None
    assert not pclock.paused and timers.timers == []
    records = [r for r in caplog.records if "no womb-to-world transition" in r.getMessage()]
    assert len(records) == 1
    assert records[0].levelno == level
    assert fragment in records[0].getMessage()


def test_the_conditions_hold_for_a_recorded_birth():
    feed = _feed()
    active, _reason, level = _plan_womb_world_transition(feed, _born_stage(feed))
    assert active and level == logging.INFO


@pytest.mark.parametrize("bad", [-1.0, float("nan"), float("inf"), "20", True])
def test_invalid_transition_settings_are_refused(bad):
    feed = _feed(transition_seconds=bad)
    with pytest.raises(ValueError):
        _plan_womb_world_transition(feed, _born_stage(_feed()))
    feed = _feed(transition_audio_fade_seconds=bad)
    with pytest.raises(ValueError):
        _plan_womb_world_transition(feed, _born_stage(_feed()))


def test_boot_hands_one_transition_to_both_surfaces(tmp_path):
    manifest = _write_manifest(tmp_path)
    feed = _feed(manifest)
    kaine_config = {"perception_feed": dict(feed), "topos": {"capture_width": 16, "capture_height": 12}}
    local = dict(feed)
    pclock = PlaylistClock(1)
    transition = _install_womb_world_transition(
        local, kaine_config, pclock, stage_state=_born_stage(feed)
    )
    assert transition is not None
    assert local["_womb_world_transition"] is transition
    assert kaine_config["perception_feed"]["_womb_world_transition"] is transition
    assert pclock.paused and transition.womb_frame.shape == (12, 16, 3)
    section = dict(kaine_config["perception_feed"], _shared_playlist_clock=pclock)
    video = _build_perception_feed_video_factory("playlist", section, width=16, height=12)(
        0, width=16, height=12
    )
    assert isinstance(video, TransitionVideoSource)
    audio = _build_perception_feed_audio_factory(
        "playlist", section, sample_rate=16000, channels=1, frames_per_block=480
    )(device=None, sample_rate=16000, channels=1, frames_per_block=480, callback=lambda b: None)
    assert isinstance(audio, TransitionAudioStream)
    assert audio.clock is pclock and video.clock is pclock
    # Without a transition the factories build the plain playlist sources.
    plain = dict(feed, _shared_playlist_clock=pclock)
    assert isinstance(
        _build_perception_feed_video_factory("playlist", plain, width=16, height=12)(
            0, width=16, height=12
        ),
        PlaylistSource,
    )


def test_run_manifest_records_the_transition(tmp_path, monkeypatch):
    monkeypatch.setattr(lifecycle_stage, "STAGE_PATH", tmp_path / "stage.json")
    feed = _feed(_write_manifest(tmp_path))
    config = {"perception_feed": feed}
    desc = gather_perception_feed_descriptor(config, stage_state=_born_stage(feed))
    assert desc["transition_seconds"] == 4.0
    assert desc["transition_audio_fade_seconds"] == 1.0
    assert desc["transition_active"] is True
    # Without a stage argument the stage file is read (absent here).
    assert gather_perception_feed_descriptor(config)["transition_active"] is False
    lifecycle_stage.write_stage(_born_stage(feed))
    assert gather_perception_feed_descriptor(config)["transition_active"] is True
    shipped = gather_perception_feed_descriptor(
        {"perception_feed": {"mode": "playlist", "playlist_manifest": ""}},
        stage_state=None,
    )
    assert shipped["transition_seconds"] == 20.0
    assert shipped["transition_audio_fade_seconds"] == 3.0
    bad = gather_perception_feed_descriptor({"perception_feed": dict(feed, transition_seconds=-1)})
    assert bad["transition_active"] is False and bad["transition_invalid"] is True


# ---------------------------------------------------------------------------
# Zero persistence
# ---------------------------------------------------------------------------


def test_no_frame_or_pcm_writers_in_the_transition_module():
    """Static guard: the transition module holds no call that could persist a
    frame or a sample (the same patterns the feed modules are held to)."""
    import re

    import kaine.modules.perception_transition as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    pattern = re.compile(
        r"(\.save\(|\.tofile\(|imwrite\(|imsave\(|np\.save\(|numpy\.save\(|"
        r"VideoWriter|wave\.open\(|soundfile\.|sf\.write\(|wavfile\.write\(|"
        r"open\([^)]*['\"][waxr]b?\+?['\"]|mode\s*=\s*['\"]w)"
    )
    assert pattern.findall(source) == []


def _snapshot(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_no_file_is_written_during_a_transition(tmp_path, monkeypatch):
    _install_fake_av(monkeypatch)
    monkeypatch.chdir(tmp_path)
    feed = _feed(_write_manifest(tmp_path))
    before = _snapshot(tmp_path)
    clock, timers = _FakeClock(), _TimerFactory()
    source, transition, pclock, manifest = _video(tmp_path, feed, clock, timers)
    heard: list[bytes] = []
    stream = TransitionAudioStream(
        lambda cb: PlaylistAudioStream(manifest, callback=cb, playlist_clock=pclock),
        callback=heard.append,
        transition=transition,
        sample_rate=16000,
        channels=1,
    )
    stream.start()
    try:
        for t in np.linspace(0.0, 5.0, 26):
            clock.t = float(t)
            assert source.read()[0]
        assert transition.released
        assert _wait_for(lambda: len(heard) >= 2)
    finally:
        stream.stop()
        source.release()
    assert _snapshot(tmp_path) == before
