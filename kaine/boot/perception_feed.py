# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The perception stimulus feed and the womb-to-world transition."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from kaine.modules.topos.feed import WombClock
    from kaine.modules.womb_signal import WombParams
from kaine.entity_clock import EntityClock

log = logging.getLogger(__name__)


def _womb_params(feed: dict[str, Any]) -> WombParams:
    from kaine.modules.womb_signal import WombParams

    womb = dict(feed.get("womb") or {})
    video = womb.pop("video", None)
    if video is not None and not isinstance(video, dict):
        raise ValueError("[perception_feed.womb.video] must be a table")
    audio = womb.pop("audio", None)
    if audio is not None and not isinstance(audio, dict):
        raise ValueError("[perception_feed.womb.audio] must be a table")
    # [perception_feed.womb.readout] belongs to the gestation owner, which
    # validates it itself (GestationReadoutConfig).
    readout = womb.pop("readout", None)
    if readout is not None and not isinstance(readout, dict):
        raise ValueError("[perception_feed.womb.readout] must be a table")
    return WombParams.from_sections(womb, video or {}, audio or {})


def _womb_lived_offset(stage_path: Path | None = None) -> float:
    import math

    from kaine.lifecycle.stage import read_stage

    state = read_stage(stage_path)
    if state is None:
        return 0.0
    value = float(state.lived_seconds)
    if not math.isfinite(value) or value < 0.0:
        return 0.0
    return value


def _shared_womb_objects(feed: dict[str, Any]) -> tuple[WombClock, Callable[[], float]]:
    from kaine.modules.topos.feed import WombClock

    clock = feed.get("_shared_womb_clock")
    lived = feed.get("_womb_lived_seconds")
    if clock is not None and lived is not None:
        return (clock, lived)
    offset = _womb_lived_offset()
    return (WombClock(lived_offset_seconds=offset), lambda: offset)


def _install_shared_womb_clock(
    perception_feed: dict[str, Any],
    kaine_config: dict[str, Any] | None,
    entity_clock: EntityClock | None,
    *,
    stage_path: Path | None = None,
    stage_state: Any | None = None,
) -> None:
    """Install one shared womb clock for both A/V surfaces.

    One clock for both surfaces so the beat is seen and heard together; the
    offset continues the maternal trajectory across boots; womb time runs on
    the real monotonic clock (the mother is external), while the colour schedule
    follows lived subjective time.
    """
    import math

    from kaine.lifecycle import stage as _lifecycle_stage
    from kaine.modules.topos.feed import WombClock

    if stage_state is not None:
        lived = float(stage_state.lived_seconds)
        offset = lived if math.isfinite(lived) and lived >= 0.0 else 0.0
    else:
        offset = _womb_lived_offset(stage_path)
    clock = WombClock(lived_offset_seconds=offset)

    if stage_state is not None:
        if stage_state.is_embodied:
            clock.mark_born()
            log.warning(
                "perception_feed mode is womb but the entity is already born; "
                "the womb delivers nothing. Choose another perception mode."
            )
    else:
        file_stage_state = _lifecycle_stage.read_stage(stage_path)
        if file_stage_state is not None and file_stage_state.is_embodied:
            clock.mark_born()
            log.warning(
                "perception_feed mode is womb but the entity is already born; "
                "the womb delivers nothing. Choose another perception mode."
            )

    if entity_clock is None:
        def lived_provider() -> float:
            return offset
    else:
        baseline_raw = entity_clock.now()
        baseline = float(baseline_raw) if math.isfinite(baseline_raw) else 0.0

        def lived_provider() -> float:
            reading = entity_clock.now()
            if not math.isfinite(reading):
                return offset
            return offset + max(0.0, reading - baseline)

    perception_feed["_shared_womb_clock"] = clock
    perception_feed["_womb_lived_seconds"] = lived_provider
    if kaine_config is not None:
        target = kaine_config.setdefault("perception_feed", {})
        target["_shared_womb_clock"] = clock
        target["_womb_lived_seconds"] = lived_provider


_TRANSITION_DEFAULT_SECONDS = 20.0
_TRANSITION_DEFAULT_AUDIO_FADE_SECONDS = 3.0


def _transition_setting(feed: dict[str, Any], key: str, default: float) -> float:
    """Read a non-negative, finite ``[perception_feed]`` transition setting."""
    import math

    raw = feed.get(key, default)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError(f"[perception_feed].{key} must be a number, got {raw!r}")
    value = float(raw)
    if not math.isfinite(value) or value < 0.0:
        raise ValueError(
            f"[perception_feed].{key} must be finite and non-negative, got {raw!r}"
        )
    return value


def _plan_womb_world_transition(
    feed: dict[str, Any], stage_state: Any | None
) -> tuple[bool, str, int]:
    """Decide whether this boot opens with the womb-to-world transition.

    Returns ``(active, reason, log_level)``. The transition runs when the mode
    is ``playlist``, ``transition_seconds`` is above zero, the stage is embodied
    with ``womb_t_at_birth``, ``womb_seed`` and the parameter digest recorded,
    and the configured womb parameters still have the recorded digest. An
    unstaged, unborn or disabled case is reported at info; a born being missing
    its record, or a parameter mismatch, at warning. Invalid settings raise
    ``ValueError``.
    """
    from kaine.lifecycle import stage as _lifecycle_stage

    mode = str(feed.get("mode", "off")).lower()
    if mode != "playlist":
        return False, f"the perception feed mode is {mode!r}, not 'playlist'", logging.INFO
    seconds = _transition_setting(feed, "transition_seconds", _TRANSITION_DEFAULT_SECONDS)
    _transition_setting(
        feed, "transition_audio_fade_seconds", _TRANSITION_DEFAULT_AUDIO_FADE_SECONDS
    )
    if seconds == 0.0:
        return False, "[perception_feed].transition_seconds is 0 (disabled)", logging.INFO
    if stage_state is None:
        return False, "no developmental stage is on record", logging.INFO
    if not stage_state.is_embodied:
        return False, "the being is not born yet", logging.INFO
    missing = [
        name
        for name in ("womb_t_at_birth", "womb_seed", "womb_params_digest")
        if getattr(stage_state, name, None) is None
    ]
    if missing:
        if getattr(stage_state, "born_at", None) is None:
            return (
                False,
                "the being was never born from the womb (no birth on record)",
                logging.INFO,
            )
        return (
            False,
            "the being is born but its stage has no womb birth record "
            f"(missing {', '.join(missing)})",
            logging.WARNING,
        )
    try:
        digest = _lifecycle_stage.womb_params_digest(_womb_params(feed))
    except Exception as exc:
        return (
            False,
            f"the womb parameters could not be read to check the birth record: {exc}",
            logging.WARNING,
        )
    if digest != stage_state.womb_params_digest:
        return (
            False,
            "the configured womb parameters differ from those recorded at birth "
            "(parameter digest mismatch), so the womb's last field cannot be "
            "reproduced",
            logging.WARNING,
        )
    return True, "the being was born from the womb and its birth state is recorded", logging.INFO


def _build_womb_world_transition(
    feed: dict[str, Any],
    playlist_clock: Any,
    *,
    stage_state: Any | None,
    width: int,
    height: int,
    clock: Callable[[], float] | None = None,
    timer_factory: Any | None = None,
    perceiving: Callable[[bool], bool] | None = None,
    video_present: bool = True,
    on_event: Callable[[str, dict[str, Any]], None] | None = None,
) -> Any | None:
    """Build this boot's womb-to-world transition, or return None and log why.

    The womb's bloom-peak field is rendered once, here, from the stage's
    recorded seed, womb time and lived time and the configured womb parameters.
    Constructing the controller pauses ``playlist_clock`` under ``transition``
    before any surface reads it. ``perceiving``, ``video_present`` and
    ``on_event`` pass through to the ``TransitionController``.
    """
    from kaine.modules.perception_transition import (
        TransitionController,
        WombWorldTransition,
        render_birth_field,
    )

    active, reason, level = _plan_womb_world_transition(feed, stage_state)
    if not active:
        log.log(level, "no womb-to-world transition: %s", reason)
        return None
    seconds = _transition_setting(feed, "transition_seconds", _TRANSITION_DEFAULT_SECONDS)
    fade = _transition_setting(
        feed, "transition_audio_fade_seconds", _TRANSITION_DEFAULT_AUDIO_FADE_SECONDS
    )
    try:
        womb_frame = render_birth_field(
            seed=int(stage_state.womb_seed),
            womb_t_at_birth=float(stage_state.womb_t_at_birth),
            lived_seconds=float(stage_state.lived_seconds),
            params=_womb_params(feed),
            width=int(width),
            height=int(height),
        )
    except Exception:
        log.warning(
            "no womb-to-world transition: the womb's birth field could not be "
            "rendered",
            exc_info=True,
        )
        return None
    controller_kwargs: dict[str, Any] = {
        "perceiving": perceiving,
        "video_present": bool(video_present),
        "on_event": on_event,
    }
    if clock is not None:
        controller_kwargs["clock"] = clock
    if timer_factory is not None:
        controller_kwargs["timer_factory"] = timer_factory
    controller = TransitionController(playlist_clock, seconds, **controller_kwargs)
    log.info(
        "womb-to-world transition armed: %.1f s crossfade from the womb's field "
        "at womb time %.3f s, then programme audio fades in over %.1f s",
        seconds,
        float(stage_state.womb_t_at_birth),
        fade,
    )
    return WombWorldTransition(
        womb_frame=womb_frame, controller=controller, audio_fade_seconds=fade
    )


def _transition_perceived(video_present: bool) -> bool:
    """Whether the being perceives the womb-to-world crossfade right now.

    Not while the cycle is frozen (any freeze source; this also covers a boot
    that revives a frozen being before the freeze watcher pauses the
    programme), and only while the primary surface is wanted on the virtual
    locus: video when a video surface exists, otherwise audio.
    """
    from kaine import perception_state as _ps
    from kaine.cycle.control_state import read_control

    if read_control().frozen:
        return False
    if video_present:
        return _ps.effective_virtual_video_capture()
    return _ps.effective_virtual_audio_capture()


def _transition_event_publisher(bus: Any) -> Callable[[str, dict[str, Any]], None]:
    """Publish the transition's content-free outcome as ``perception.transition``
    events on the perception stream (``perception.out``) through the bus.

    The controller reports from perception threads, so each event is handed to
    the event loop that was running when boot built the transition.
    """
    import asyncio
    from datetime import datetime, timezone

    from kaine.bus.schema import validate_event

    try:
        loop: Any = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    def _done(fut: Any) -> None:
        if fut.cancelled():
            return
        exc = fut.exception()
        if exc is not None:
            log.warning("could not publish perception.transition: %s", exc)

    def _emit(phase: str, payload: dict[str, Any]) -> None:
        target = loop
        if target is None:
            try:
                target = asyncio.get_running_loop()
            except RuntimeError:
                target = None
        if target is None or target.is_closed():
            log.warning(
                "could not publish perception.transition (%s): no running event loop",
                phase,
            )
            return
        event = validate_event(
            source="perception",
            type="perception.transition",
            payload=dict(payload),
            # Operational provenance, not a percept.
            salience=0.0,
            timestamp=datetime.now(timezone.utc),
        )
        asyncio.run_coroutine_threadsafe(bus.publish(event), target).add_done_callback(_done)

    return _emit


def _install_womb_world_transition(
    perception_feed: dict[str, Any],
    kaine_config: dict[str, Any] | None,
    playlist_clock: Any,
    *,
    stage_state: Any | None = None,
    stage_path: Path | None = None,
    bus: Any | None = None,
    video_present: bool = True,
) -> Any | None:
    """Build the transition for this boot and hand it to both feed surfaces.

    ``stage_state`` is the boot's resolved stage (a revive's preserved stage
    included); without it the stage file is read. The transition is stashed
    beside the shared playlist clock so the video and audio factories (and
    Spot's restart path) wrap their playlist sources with the same instance.
    ``video_present`` says whether Topos is enabled (build_registry corrects it
    once the modules are constructed); ``bus`` receives the
    ``perception.transition`` outcome events.
    """
    from kaine.lifecycle import stage as _lifecycle_stage

    if stage_state is None:
        stage_state = _lifecycle_stage.read_stage(stage_path)
    topos = (kaine_config or {}).get("topos") or {}
    transition = _build_womb_world_transition(
        perception_feed,
        playlist_clock,
        stage_state=stage_state,
        width=int(topos.get("capture_width", 640)),
        height=int(topos.get("capture_height", 480)),
        perceiving=_transition_perceived,
        video_present=video_present,
        on_event=_transition_event_publisher(bus) if bus is not None else None,
    )
    if transition is None:
        return None
    perception_feed["_womb_world_transition"] = transition
    if kaine_config is not None:
        kaine_config.setdefault("perception_feed", {})
        kaine_config["perception_feed"]["_womb_world_transition"] = transition
    return transition


def _build_perception_feed_video_factory(
    mode: str, feed: dict[str, Any], *, width: int, height: int
) -> Any:
    """Build a ``_VideoSource`` factory for the deterministic perception feed.

    The factory matches the LiveCamera ``source_factory(device, *, width, height)``
    signature; the deterministic sources ignore ``device``. Seeded uses the
    config geometry directly + the ``[perception_feed.video]`` knobs; playlist
    resolves + (later, at open()) verifies the operator manifest; womb uses a
    shared womb clock so the maternal environment is seen and heard together.
    """
    from kaine.modules.topos.feed import (
        PlaylistSource,
        SeededProceduralSource,
        SeededSchedule,
        WombProceduralSource,
        WombSchedule,
        load_playlist_manifest,
    )

    if mode == "screen":
        return _build_screen_source_factory(feed)

    if mode == "womb":
        params = _womb_params(feed)
        schedule = WombSchedule(
            seed=int(feed.get("seed", 0)),
            width=width,
            height=height,
        )
        clock, lived = _shared_womb_objects(feed)

        def _womb_factory(device, *, width, height):  # noqa: ANN001
            return WombProceduralSource(
                schedule, params=params, clock=clock, lived_seconds=lived
            )

        return _womb_factory

    video = dict(feed.get("video") or {})
    if mode == "seeded":
        schedule = SeededSchedule(
            seed=int(feed.get("seed", 0)),
            width=width,
            height=height,
            surprise_interval=int(video.get("surprise_interval", 150)),
            surprise_strength=float(video.get("surprise_strength", 1.0)),
        )

        def _seeded_factory(device, *, width, height):  # noqa: ANN001
            return SeededProceduralSource(schedule)

        return _seeded_factory

    # playlist
    manifest_path = str(feed.get("playlist_manifest", "")).strip()
    if not manifest_path:
        raise ValueError("[perception_feed].mode = 'playlist' requires playlist_manifest")
    manifest = load_playlist_manifest(manifest_path)
    # Shared start-clock injected by build_registry so video and audio stay on the
    # same item (playlist-realtime-av-sync). None -> a private clock (standalone).
    shared_clock = feed.get("_shared_playlist_clock")
    # A born being's viewing opens with the womb-to-world crossfade when boot
    # built one (womb-to-world-transition); the same instance serves audio.
    transition = feed.get("_womb_world_transition")

    def _playlist_factory(device, *, width, height):  # noqa: ANN001
        source = PlaylistSource(manifest, playlist_clock=shared_clock)
        if transition is None:
            return source
        from kaine.modules.perception_transition import TransitionVideoSource

        return TransitionVideoSource(source, transition)

    return _playlist_factory


def _build_screen_source_factory(feed: dict[str, Any]) -> Any:
    """Build a screen/window-capture ``_VideoSource`` factory (ffmpeg-backed).

    Reads the ``[perception_feed.screen]`` target; the per-OS ffmpeg input spec is
    resolved at build time and the source is opened per LiveCamera cycle. The
    operator chooses to enable this deliberately (the shipped config is all-off),
    and screen contents are the operator's own or public media, so no separate
    consent gate is imposed here.
    """
    from kaine.modules.topos.screen import (
        ScreenCaptureSource,
        ScreenTarget,
        detect_screen_size,
        screen_capture_spec,
    )

    scr = dict(feed.get("screen") or {})
    region = scr.get("region")
    target = ScreenTarget(
        kind=str(scr.get("target", "fullscreen")).lower(),
        region=tuple(int(v) for v in region) if region else None,
        window_title=(scr.get("window_title") or None),
        display=str(scr.get("display", ":0.0")),
        framerate=int(scr.get("framerate", 10)),
        cursor=bool(scr.get("cursor", True)),
    )
    spec = screen_capture_spec(target)  # platform auto-detected
    ffmpeg_path = str(scr.get("ffmpeg_path", "ffmpeg"))

    # Native grab (topos-foveation): capture at the display's own resolution with
    # no scale filter so the foveal crop carries true native detail. Detected once
    # at build time; on any platform without a probe (or if detection fails) it
    # falls back to the configured capture geometry with a logged note — honest
    # NULL rather than a guessed resolution.
    native_req = bool(scr.get("native", False))
    native_size: tuple[int, int] | None = None
    if native_req:
        native_size = detect_screen_size(target)
        if native_size is None:
            log.warning(
                "screen native grab requested but display size could not be "
                "detected; falling back to configured capture geometry"
            )
        else:
            log.info(
                "screen native grab: capturing at detected %dx%d (no downscale)",
                native_size[0],
                native_size[1],
            )

    def _screen_factory(device, *, width, height):  # noqa: ANN001
        if native_size is not None:
            return ScreenCaptureSource(
                spec,
                width=native_size[0],
                height=native_size[1],
                native=True,
                ffmpeg_path=ffmpeg_path,
            )
        return ScreenCaptureSource(spec, width=width, height=height, ffmpeg_path=ffmpeg_path)

    return _screen_factory


def _build_monitor_audio_factory(feed: dict[str, Any]) -> Any:
    """Build a desktop-audio monitor ``_AudioStream`` factory (ffmpeg-backed).

    Screen mode hears what is playing on the shared screen by capturing the audio
    output monitor. The monitor device comes from
    ``[perception_feed.screen].monitor_device``; on Linux it defaults to the
    current default sink's ``.monitor`` when unset.
    """
    from kaine.modules.audition.monitor import (
        MonitorAudioStream,
        audio_capture_spec,
        default_monitor_source,
    )

    scr = dict(feed.get("screen") or {})
    device = str(scr.get("monitor_device", "") or "")
    if not device:
        device = default_monitor_source() or ""
    spec = audio_capture_spec(device)  # raises with guidance if still empty
    ffmpeg_path = str(scr.get("ffmpeg_path", "ffmpeg"))

    def _monitor_factory(*, device, sample_rate, channels, frames_per_block, callback):  # noqa: ANN001, ARG001
        return MonitorAudioStream(
            spec,
            sample_rate=sample_rate,
            channels=channels,
            frames_per_block=frames_per_block,
            callback=callback,
            ffmpeg_path=ffmpeg_path,
        )

    return _monitor_factory


def _build_perception_feed_audio_factory(
    mode: str,
    feed: dict[str, Any],
    *,
    sample_rate: int,
    channels: int,
    frames_per_block: int,
) -> Any:
    """Build an ``_AudioStream`` factory for the deterministic perception feed.

    Mirrors the video factory. The factory matches LiveMicrophone's
    ``stream_factory(*, device, sample_rate, channels, frames_per_block,
    callback)`` signature; the deterministic streams ignore ``device``. Seeded
    reads the shared ``seed`` + the ``[perception_feed.video].surprise_interval``
    (so the surprise cadence is shared cross-modally) + the
    ``[perception_feed.audio]`` knobs. Playlist walks the SAME manifest as the
    video surface. Womb reads a shared seed and the same shared womb clock so
    the maternal heartbeat stays phase-locked across surfaces.
    """
    if mode == "screen":
        return _build_monitor_audio_factory(feed)

    from kaine.modules.audition.feed import (
        PlaylistAudioStream,
        SeededAudioSchedule,
        SeededProceduralAudioStream,
        WombAudioSchedule,
        WombProceduralAudioStream,
    )
    from kaine.modules.topos.feed import load_playlist_manifest
    from kaine.modules.womb_signal import _LOWPASS_TAPS

    video = dict(feed.get("video") or {})
    audio = dict(feed.get("audio") or {})
    if mode == "womb":
        params = _womb_params(feed)
        sr = int(audio.get("sample_rate", sample_rate))
        ch = int(audio.get("channels", channels))
        fpb = int(frames_per_block)
        min_frames = _LOWPASS_TAPS - 1
        if fpb < min_frames:
            raise ValueError(
                f"[perception_feed.womb] requires frames_per_block >= {min_frames} "
                f"(the womb low-pass filter needs 128 samples of history); got {fpb}"
            )
        if params.lowpass_hz >= sr / 2.0:
            raise ValueError(
                f"[perception_feed.womb] requires lowpass_hz < sample_rate/2; "
                f"got {params.lowpass_hz} Hz with sample_rate {sr} Hz"
            )
        schedule = WombAudioSchedule(
            seed=int(feed.get("seed", 0)),
            sample_rate=sr,
            channels=ch,
            frames_per_block=fpb,
        )
        clock, lived = _shared_womb_objects(feed)

        def _womb_factory(*, device, sample_rate, channels, frames_per_block, callback):  # noqa: ANN001
            return WombProceduralAudioStream(
                schedule, params=params, clock=clock, callback=callback
            )

        return _womb_factory

    if mode == "seeded":
        schedule = SeededAudioSchedule(
            seed=int(feed.get("seed", 0)),
            sample_rate=int(audio.get("sample_rate", sample_rate)),
            channels=int(audio.get("channels", channels)),
            frames_per_block=int(frames_per_block),
            # SHARED cadence with the video surface (cross-modal surprises).
            surprise_interval=int(video.get("surprise_interval", 150)),
            base_strength=float(audio.get("base_strength", 0.3)),
            surprise_strength=float(audio.get("surprise_strength", 1.0)),
        )

        def _seeded_factory(*, device, sample_rate, channels, frames_per_block, callback):  # noqa: ANN001
            return SeededProceduralAudioStream(schedule, callback=callback)

        return _seeded_factory

    # playlist
    manifest_path = str(feed.get("playlist_manifest", "")).strip()
    if not manifest_path:
        raise ValueError("[perception_feed].mode = 'playlist' requires playlist_manifest")
    manifest = load_playlist_manifest(manifest_path)
    # SAME shared start-clock instance the video factory received, so both feeds
    # cross item boundaries together (playlist-realtime-av-sync).
    shared_clock = feed.get("_shared_playlist_clock")
    # The programme's sound fades in after the womb-to-world crossfade when boot
    # built one (womb-to-world-transition); the same instance serves video.
    transition = feed.get("_womb_world_transition")

    def _playlist_factory(*, device, sample_rate, channels, frames_per_block, callback):  # noqa: ANN001
        def _make(cb):  # noqa: ANN001, ANN202
            return PlaylistAudioStream(
                manifest,
                callback=cb,
                sample_rate=int(sample_rate),
                channels=int(channels),
                frames_per_block=int(frames_per_block),
                playlist_clock=shared_clock,
            )

        if transition is None:
            return _make(callback)
        from kaine.modules.perception_transition import TransitionAudioStream

        return TransitionAudioStream(
            _make,
            callback=callback,
            transition=transition,
            sample_rate=int(sample_rate),
            channels=int(channels),
        )

    return _playlist_factory


def gather_perception_feed_descriptor(
    config: dict[str, Any], *, stage_state: Any | None = None
) -> dict[str, Any]:
    """Derive the unified perception-feed covariate from resolved config.

    Reads the top-level ``[perception_feed]`` (unified-perception-feed). For
    ``seeded`` returns the seed plus BOTH the video and the audio schedule (enough
    to regenerate the entity's full A/V input); for ``playlist`` the single
    manifest sha256 + per-item digests that pin both surfaces (enough to verify);
    for ``off``/``live`` just the mode; for ``womb`` the parameters plus the
    video/audio schedules and the lived-seconds offset. A ``playlist`` descriptor
    also records ``transition_seconds``, ``transition_audio_fade_seconds`` and
    whether this boot plans the womb-to-world transition
    (``transition_planned``, judged from ``stage_state`` — the boot's resolved
    stage — or else the stage file; the outcome is published as
    ``perception.transition`` events). Best-effort — a
    malformed/absent manifest or womb config degrades to ``{"mode": ...}`` and
    never raises, so it can't crash boot. No rendered frames, no PCM, no
    operator paths.

    Lives at the boot layer (allowed to import ``kaine.modules``) and is passed
    into ``mint_run_context`` as data, keeping ``kaine.experiment`` off the
    modules package (import-boundary contract). Mirrors ``_gather_model_ids``.
    """
    feed = config.get("perception_feed") or {}
    topos = config.get("topos") or {}
    audition = config.get("audition") or {}
    mode = str(feed.get("mode", "off")).lower()
    descriptor: dict[str, Any] = {"mode": mode}
    if mode == "seeded":
        from kaine.modules.audition.feed import SeededAudioSchedule
        from kaine.modules.topos.feed import SeededSchedule

        seed = int(feed.get("seed", 0))
        video = dict(feed.get("video") or {})
        audio = dict(feed.get("audio") or {})
        surprise_interval = int(video.get("surprise_interval", 150))
        descriptor["seed"] = seed
        descriptor["video"] = SeededSchedule(
            seed=seed,
            width=int(topos.get("capture_width", 640)),
            height=int(topos.get("capture_height", 480)),
            surprise_interval=surprise_interval,
            surprise_strength=float(video.get("surprise_strength", 1.0)),
        ).as_descriptor()
        sample_rate = int(audio.get("sample_rate", audition.get("capture_sample_rate", 16000)))
        channels = int(audio.get("channels", audition.get("capture_channels", 1)))
        vad_frame_ms = int(audition.get("vad_frame_ms", 30))
        descriptor["audio"] = SeededAudioSchedule(
            seed=seed,
            sample_rate=sample_rate,
            channels=channels,
            frames_per_block=max(1, sample_rate * vad_frame_ms // 1000),
            # SHARED cadence with the video surface (cross-modal surprises).
            surprise_interval=surprise_interval,
            base_strength=float(audio.get("base_strength", 0.3)),
            surprise_strength=float(audio.get("surprise_strength", 1.0)),
        ).as_descriptor()
    elif mode == "womb":
        import dataclasses

        from kaine.modules.audition.feed import WombAudioSchedule
        from kaine.modules.topos.feed import WombSchedule

        seed = int(feed.get("seed", 0))
        audio = dict(feed.get("audio") or {})
        descriptor["seed"] = seed
        try:
            params = _womb_params(feed)
            descriptor["womb"] = dataclasses.asdict(params)
        except Exception:
            # The womb parameters are validated for real at boot time; the
            # covariate must not crash the run if they can't be read here.
            descriptor["womb"] = {"invalid": True}
        descriptor["video"] = WombSchedule(
            seed=seed,
            width=int(topos.get("capture_width", 640)),
            height=int(topos.get("capture_height", 480)),
        ).as_descriptor()
        sample_rate = int(audio.get("sample_rate", audition.get("capture_sample_rate", 16000)))
        channels = int(audio.get("channels", audition.get("capture_channels", 1)))
        vad_frame_ms = int(audition.get("vad_frame_ms", 30))
        descriptor["audio"] = WombAudioSchedule(
            seed=seed,
            sample_rate=sample_rate,
            channels=channels,
            frames_per_block=max(1, sample_rate * vad_frame_ms // 1000),
        ).as_descriptor()
        descriptor["lived_offset_seconds"] = _womb_lived_offset()
    elif mode == "playlist":
        manifest_path = str(feed.get("playlist_manifest", "")).strip()
        try:
            from kaine.modules.topos.feed import load_playlist_manifest

            manifest = load_playlist_manifest(manifest_path)
            # ONE manifest pins both surfaces — no per-surface duplication.
            descriptor["playlist"] = manifest.as_descriptor()
        except Exception:
            # The manifest is verified for real at open() time; the covariate
            # must not crash the run if it can't be read here.
            descriptor["playlist"] = {"manifest_unavailable": True}
        try:
            descriptor["transition_seconds"] = _transition_setting(
                feed, "transition_seconds", _TRANSITION_DEFAULT_SECONDS
            )
            descriptor["transition_audio_fade_seconds"] = _transition_setting(
                feed,
                "transition_audio_fade_seconds",
                _TRANSITION_DEFAULT_AUDIO_FADE_SECONDS,
            )
            if stage_state is None:
                from kaine.lifecycle.stage import read_stage

                stage_state = read_stage()
            active, _reason, _level = _plan_womb_world_transition(feed, stage_state)
            descriptor["transition_planned"] = bool(active)
        except Exception:
            # Invalid settings are refused for real at boot; the covariate
            # must not crash the run.
            descriptor["transition_planned"] = False
            descriptor["transition_invalid"] = True
    elif mode == "screen":
        # Content-free provenance: the capture target kind and, for a named
        # window, a hash of the title (never the title itself). No pixels, no
        # window contents — just enough to stratify records by source.
        import hashlib

        scr = dict(feed.get("screen") or {})
        src: dict[str, Any] = {"target": str(scr.get("target", "fullscreen")).lower()}
        if scr.get("window_title"):
            src["window"] = hashlib.sha256(str(scr["window_title"]).encode()).hexdigest()[:16]
        descriptor["screen"] = src
    # Stimulus-regime label for cross-record stratification (field-tier analysis).
    descriptor["regime"] = {
        "off": "off",
        "seeded": "seeded",
        "playlist": "playlist",
        "live": "camera",
        "screen": "screen",
        "womb": "womb",
    }.get(mode, mode)
    return descriptor
