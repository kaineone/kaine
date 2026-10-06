# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The Audition factory."""
from __future__ import annotations

import logging
from dataclasses import replace
from typing import TYPE_CHECKING, Any, Mapping, Optional

if TYPE_CHECKING:
    pass
from kaine.boot.common import _check_injections
from kaine.boot.errors import ConfigurationError, _require_keys
from kaine.boot.perception_feed import _build_perception_feed_audio_factory
from kaine.bus.client import AsyncBus
from kaine.hardware import resolve_device
from kaine.modules.base import BaseModule

log = logging.getLogger(__name__)


def _live_mic_source_label(mode: str) -> str:
    """Return the audition source label for the live-microphone path.

    Perception feeds model the channel they play on; a real microphone stays
    ``live_mic``.
    """
    if mode in ("seeded", "playlist", "womb", "screen"):
        return mode
    return "live_mic"


def _audition_sherpa_failure_reason() -> str:
    from kaine.backend_state import backend_failures

    for record in reversed(backend_failures()):
        if record.module == "audition" and record.backend == "sherpa_onnx":
            return record.reason
    return "unknown failure"


def make_audition(
    bus: AsyncBus,
    section: dict[str, Any],
    *,
    injections: Optional[Mapping[str, Any]] = None,
) -> BaseModule:
    from kaine.modules.audition.acoustic import ACOUSTIC_ENCODERS, build_acoustic_encoder
    from kaine.modules.audition.live import LiveMicConfig
    from kaine.modules.audition.module import Audition

    allowed = {
        "speaches_url",
        "stt_model",
        "emotion_model_id",
        "emotion_device",
        "request_timeout_s",
        "baseline_salience",
        "alert_salience",
        # Runtime backend selection (openspec runtime-backends). "speaches"
        # (default) uses the HTTP service above; "sherpa_onnx" runs Moonshine
        # in-process through sherpa-onnx (no torch, no service).
        "backend",
        "sherpa_model_dir",
        "sherpa_model_id",
        "sherpa_num_threads",
        # Live microphone (eyes-and-ears). Off by default.
        "capture_enabled",
        "capture_device",
        "capture_sample_rate",
        "capture_channels",
        "vad_backend",
        "vad_aggressiveness",
        "vad_frame_ms",
        "min_utterance_ms",
        "max_utterance_ms",
        "silence_hangover_ms",
        "desired_state_poll_ms",
        # Forward model + prosody (disabled by default — purely additive).
        "forward_model_units",
        "prediction_error_window",
        "auditory_buffer_size",
        "prosody_enabled",
        # General auditory perception (auditory-perception). Off by default → the
        # existing speech pipeline is unchanged. See the block below.
        "general_audition",
        "transcription_enabled",
        "arousal_window_min",
        "arousal_window_max",
        "acoustic_change_alert_threshold",
        "acoustic_change_alert_factor",
        "acoustic_encoder",
        "acoustic_device",
        # Unified deterministic perception feed (unified-perception-feed). The
        # resolved top-level [perception_feed] config, injected by build_registry
        # under this reserved key. Selecting seeded/playlist supplies a
        # stream_factory and forces capture on. Popped before the key check.
        "perception_feed",
    }
    feed_section = dict(section.pop("perception_feed", {}) or {})
    _require_keys(section, allowed - {"perception_feed"})
    base_keys = {
        "speaches_url",
        "stt_model",
        "emotion_model_id",
        "emotion_device",
        "request_timeout_s",
        "baseline_salience",
        "alert_salience",
    }
    kwargs: dict[str, Any] = {k: section[k] for k in base_keys if k in section}
    kwargs["capture_enabled"] = bool(section.get("capture_enabled", False))

    # Unified deterministic perception-feed selection (unified-perception-feed).
    # mode "off"/"live" leave the existing behaviour (off = capture disabled;
    # live = the real sounddevice mic). "seeded"/"playlist" supply a
    # stream_factory and force capture on so LiveMicrophone reads from the
    # deterministic source instead of the mic.
    mode = str(feed_section.get("mode", "off")).lower()
    if mode not in ("off", "seeded", "playlist", "womb", "live", "screen"):
        raise ValueError(
            f"[perception_feed].mode must be off/seeded/playlist/womb/live/screen, got {mode!r}"
        )
    # 'screen' hears the desktop audio monitor (what is playing on screen), so it
    # takes a stream_factory like seeded/playlist; the deterministic feeds and the
    # monitor all satisfy the same LiveMicrophone seam.
    audio_cfg = dict(feed_section.get("audio") or {})
    sample_rate = int(audio_cfg.get("sample_rate", section.get("capture_sample_rate", 16000)))
    channels = int(audio_cfg.get("channels", section.get("capture_channels", 1)))
    if mode == "live":
        kwargs["capture_enabled"] = True
    elif mode in ("seeded", "playlist", "womb", "screen"):
        kwargs["capture_enabled"] = True
        vad_frame_ms = int(section.get("vad_frame_ms", 30))
        frames_per_block = max(1, sample_rate * vad_frame_ms // 1000)
        kwargs["stream_factory"] = _build_perception_feed_audio_factory(
            mode,
            feed_section,
            sample_rate=sample_rate,
            channels=channels,
            frames_per_block=frames_per_block,
        )

    if kwargs["capture_enabled"]:
        kwargs["live_mic_config"] = LiveMicConfig(
            device=section.get("capture_device") or None,
            sample_rate=sample_rate,
            channels=channels,
            source_label=_live_mic_source_label(mode),
            vad_backend=section.get("vad_backend", "webrtcvad"),
            vad_aggressiveness=int(section.get("vad_aggressiveness", 2)),
            vad_frame_ms=int(section.get("vad_frame_ms", 30)),
            min_utterance_ms=int(section.get("min_utterance_ms", 300)),
            max_utterance_ms=int(section.get("max_utterance_ms", 30000)),
            silence_hangover_ms=int(section.get("silence_hangover_ms", 600)),
            desired_state_poll_ms=int(section.get("desired_state_poll_ms", 250)),
        )
    # Forward model + prosody knobs.
    for k in ("forward_model_units", "prediction_error_window", "auditory_buffer_size"):
        if k in section:
            kwargs[k] = int(section[k])
    if "prosody_enabled" in section:
        kwargs["prosody_enabled"] = bool(section["prosody_enabled"])

    # General auditory perception (auditory-perception). When on, every captured
    # window is perceived as sound and speech-to-text runs only on detected
    # speech. The live mic must then deliver CONTINUOUS windows rather than
    # VAD-segmented utterances, or non-speech would be gated out before it is
    # heard; ``continuous_capture=True`` on the mic config switches it to
    # fixed-window delivery. The deterministic feeds and the desktop monitor
    # already stream continuous blocks.
    general_audition = bool(section.get("general_audition", False))
    injected = _check_injections("audition", injections, {"acoustic_encoder"})

    if "acoustic_encoder" in injected:
        # The plugin seam fills the encoder. The config value must then be
        # unset or the default "spectral"; otherwise it conflicts with the seam.
        if section.get("acoustic_encoder") is not None and str(
            section.get("acoustic_encoder", "")
        ).strip().lower() not in ("", "spectral"):
            raise ConfigurationError(
                "the audition.acoustic_encoder seam is filled by a plugin; "
                "[audition].acoustic_encoder must be left unset"
            )
        if not general_audition:
            raise ConfigurationError(
                "a plugin-filled acoustic encoder would never run because general_audition is disabled"
            )
        kwargs["acoustic_encoder"] = injected["acoustic_encoder"]
    elif general_audition:
        name = section.get("acoustic_encoder", "spectral")
        if not isinstance(name, str):
            raise ConfigurationError("[audition].acoustic_encoder must be a string")
        try:
            kwargs["acoustic_encoder"] = build_acoustic_encoder(
                name,
                device=resolve_device(str(section.get("acoustic_device", "cpu"))),
            )
        except ValueError as exc:
            raise ConfigurationError(str(exc)) from exc
    elif "acoustic_encoder" in section:
        # Validate the name even when general audition is off, so a typo still
        # fails at boot rather than being silently ignored. Only the name is
        # checked: an encoder that will never run is not built.
        name = section["acoustic_encoder"]
        if not isinstance(name, str) or name.strip().lower() not in ACOUSTIC_ENCODERS:
            raise ConfigurationError(
                f"unknown acoustic encoder {name!r}; known: "
                + ", ".join(sorted(ACOUSTIC_ENCODERS))
            )

    if general_audition:
        kwargs["general_audition"] = True
        wmin = section.get("arousal_window_min")
        wmax = section.get("arousal_window_max")
        if wmin is not None or wmax is not None:
            kwargs["arousal_window_range"] = (
                float(wmin if wmin is not None else 0.15),
                float(wmax if wmax is not None else 1.0),
            )
        if "acoustic_change_alert_threshold" in section:
            kwargs["acoustic_change_alert_threshold"] = float(
                section["acoustic_change_alert_threshold"]
            )
        if "acoustic_change_alert_factor" in section:
            kwargs["acoustic_change_alert_factor"] = float(section["acoustic_change_alert_factor"])
        if isinstance(kwargs.get("live_mic_config"), LiveMicConfig):
            kwargs["live_mic_config"] = replace(kwargs["live_mic_config"], continuous_capture=True)
    # STT gate (default true = unchanged). When false, no transcript path.
    if "transcription_enabled" in section:
        kwargs["transcription_enabled"] = bool(section["transcription_enabled"])

    # Backend seam (openspec runtime-backends). The backend value is normalised
    # once and all disclosures derive from the resolved backend.
    backend = str(section.get("backend") or "speaches").strip().lower()
    if backend not in ("speaches", "sherpa_onnx"):
        raise ConfigurationError(
            f"unknown audition backend {section.get('backend')!r}; "
            "must be 'speaches' or 'sherpa_onnx'"
        )

    transcription_enabled = bool(kwargs.get("transcription_enabled", False))

    # With transcription off, do not resolve or construct any STT backend. The
    # gate guarantees the client is never called; Audition builds its default
    # SpeachesClient, which is never used.
    if backend == "speaches" or not transcription_enabled:
        kwargs["backend"] = backend
        return Audition(bus, **kwargs)

    from kaine.modules.audition.stt_client import SpeachesClient, STTClient
    from kaine.modules.backends import BackendRegistry, UnknownBackendError

    speaches_url = str(section.get("speaches_url", "http://127.0.0.1:8000"))
    timeout_s = float(section.get("request_timeout_s", 60.0))

    def _speaches_factory() -> STTClient:
        return SpeachesClient(base_url=speaches_url, timeout_s=timeout_s)

    def _sherpa_factory() -> STTClient:
        from kaine.model_paths import DEFAULT_STT
        from kaine.model_paths import speech_model_dir as model_dir
        from kaine.modules.audition.sherpa_stt import SherpaMoonshineSTT

        model_id = section.get("sherpa_model_id") or DEFAULT_STT
        model_dir_path = section.get("sherpa_model_dir") or model_dir(model_id)
        num_threads = int(section.get("sherpa_num_threads", 2))
        return SherpaMoonshineSTT(
            model_dir_path,
            model_id=model_id,
            num_threads=num_threads,
        )

    registry = BackendRegistry[STTClient]("audition", default="speaches").register(
        "speaches", _speaches_factory
    ).register("sherpa_onnx", _sherpa_factory)
    try:
        client = registry.resolve(backend)
    except UnknownBackendError as exc:
        raise ConfigurationError(str(exc)) from exc

    from kaine.model_paths import DEFAULT_STT

    model_id = section.get("sherpa_model_id") or DEFAULT_STT
    if client is None:
        # Sherpa factory failed already (recorded and logged by resolve_backend).
        # Hearing continues; transcription is simply disabled.
        failure = _audition_sherpa_failure_reason()
        log.warning(
            "audition: sherpa-onnx transcription unavailable (%s); "
            "hearing continues without transcription. "
            "Fetch the model: python -m kaine.setup.speech_models --stt %s",
            failure,
            model_id,
        )
        kwargs["transcription_enabled"] = False
        kwargs["backend"] = "sherpa_onnx"
        kwargs["stt_model"] = model_id
        return Audition(bus, **kwargs)

    kwargs["stt_client"] = client
    kwargs["backend"] = "sherpa_onnx"
    kwargs["stt_model"] = model_id
    return Audition(bus, **kwargs)
