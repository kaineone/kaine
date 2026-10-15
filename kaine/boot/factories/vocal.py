# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The vocal module factory."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    pass
from kaine.boot.config_kwargs import config_kwargs
from kaine.boot.errors import ConfigurationError, _require_keys
from kaine.bus.client import AsyncBus
from kaine.entity_clock import EntityClock
from kaine.modules.base import BaseModule


def make_vocal(
    bus: AsyncBus,
    section: dict[str, Any],
    *,
    entity_clock: Optional[EntityClock] = None,
) -> BaseModule:
    from kaine.modules.vocal.module import Vocal
    from kaine.modules.vocal.voices import normalize_gender

    allowed = {
        "chatterbox_url",
        "voice_mode",
        "predefined_voice_id",
        "output_format",
        "sink_path",
        "playback_enabled",
        "output_device",
        "sink_enabled",
        "retain_count",
        "suppress_self_hearing",
        "mic_mute_hangover_ms",
        "baseline_temperature",
        "baseline_exaggeration",
        "baseline_cfg_weight",
        "request_timeout_s",
        "baseline_salience",
        "alert_salience",
        "language_external_stream",
        "affect_state_stream",
        # Runtime backend selection (openspec runtime-backends). "chatterbox"
        # (default) uses the HTTP service above; "sherpa_onnx" runs Kokoro
        # in-process through sherpa-onnx (no torch, no service).
        "backend",
        "sherpa_model_dir",
        "sherpa_model_id",
        "sherpa_speaker_id",
        "sherpa_num_threads",
        "mirroring",  # nested sub-table: enabled, mirror_strength, mirror_ceiling, decay_s
        # shipped-voice selection, openspec vox-default-voice
        "voice_gender",
        "default_voice",
    }
    # Pop all top-level keys; handle mirroring sub-table separately.
    _require_keys(section, allowed)

    # Validate voice_gender at boot time so a typo is a configuration error.
    voice_gender = section.get("voice_gender", "any")
    try:
        normalized_gender = normalize_gender(voice_gender)
    except ValueError as exc:
        raise ConfigurationError(str(exc)) from exc
    default_voice = section.get("default_voice")

    raw_backend = section.get("backend")
    backend = str(raw_backend or "chatterbox").strip().lower()
    sherpa_model_dir = section.pop("sherpa_model_dir", None)
    sherpa_model_id = section.pop("sherpa_model_id", None)
    sherpa_speaker_id = section.pop("sherpa_speaker_id", None)
    sherpa_num_threads = section.pop("sherpa_num_threads", 2)
    backend_keys = {
        "backend",
        "sherpa_model_dir",
        "sherpa_model_id",
        "sherpa_speaker_id",
        "sherpa_num_threads",
    }
    kw = config_kwargs(section, sorted(allowed - {"mirroring"} - backend_keys), Vocal)
    # [vocal.mirroring] sub-table.
    mirroring_section = section.get("mirroring") or {}
    mirroring_allowed = {"enabled", "mirror_strength", "mirror_ceiling", "decay_s"}
    _require_keys(mirroring_section, mirroring_allowed)
    if "enabled" in mirroring_section:
        kw["mirroring_enabled"] = bool(mirroring_section["enabled"])
    if "mirror_strength" in mirroring_section:
        kw["mirror_strength"] = float(mirroring_section["mirror_strength"])
    if "mirror_ceiling" in mirroring_section:
        kw["mirror_ceiling"] = float(mirroring_section["mirror_ceiling"])
    if "decay_s" in mirroring_section:
        kw["mirror_decay_s"] = float(mirroring_section["decay_s"])

    if backend not in ("chatterbox", "sherpa_onnx"):
        raise ConfigurationError(
            f"unknown vocal backend {raw_backend!r}; "
            "must be 'chatterbox' or 'sherpa_onnx'"
        )

    if backend == "chatterbox":
        kw["backend"] = "chatterbox"
        return Vocal(bus, entity_clock=entity_clock, **kw)

    from kaine.model_paths import DEFAULT_TTS
    from kaine.modules.backends import BackendRegistry, UnknownBackendError
    from kaine.modules.vocal.client import ChatterboxClient, TTSClient
    from kaine.modules.vocal.sherpa_tts import APPLIED_PROSODY
    from kaine.modules.vocal.voices import kokoro_speaker_name, select_kokoro_speaker

    chatterbox_url = str(kw.get("chatterbox_url", "http://127.0.0.1:8883"))
    timeout_s = float(kw.get("request_timeout_s", 120.0))

    resolved: dict[str, Any] = {}

    def _chatterbox_factory() -> TTSClient:
        return ChatterboxClient(base_url=chatterbox_url, timeout_s=timeout_s)

    def _sherpa_factory() -> TTSClient:
        from kaine import speech_manifest
        from kaine.model_paths import speech_model_dir as model_dir
        from kaine.modules.vocal.sherpa_tts import SherpaKokoroTTS

        model_id = sherpa_model_id or DEFAULT_TTS
        model_dir_path = sherpa_model_dir or model_dir(model_id)
        entry = speech_manifest.MANIFEST.get(model_id)
        speakers = tuple(entry.speakers) if entry is not None else ()

        if sherpa_speaker_id is not None:
            speaker_id = int(sherpa_speaker_id)
            name = kokoro_speaker_name(speakers, speaker_id)
            note = "configured in [vocal].sherpa_speaker_id"
        else:
            choice = select_kokoro_speaker(
                speakers,
                gender=normalized_gender,
                default_voice=default_voice,
                model_id=model_id,
            )
            speaker_id = choice.speaker_id
            name = choice.name
            note = choice.note

        resolved["speaker_id"] = speaker_id
        resolved["note"] = f"{name}; {note}" if name else note
        return SherpaKokoroTTS(
            model_dir_path,
            model_id=model_id,
            speaker_id=speaker_id,
            num_threads=int(sherpa_num_threads),
        )

    registry = BackendRegistry[TTSClient]("vocal", default="chatterbox").register(
        "chatterbox", _chatterbox_factory
    ).register("sherpa_onnx", _sherpa_factory)
    try:
        client = registry.resolve(backend)
    except UnknownBackendError as exc:
        raise ConfigurationError(str(exc)) from exc
    if client is None:
        return None

    resolved_model_id = sherpa_model_id or DEFAULT_TTS
    kw["tts_client"] = client
    kw["backend"] = "sherpa_onnx"
    kw["applied_prosody"] = APPLIED_PROSODY
    kw["voice_label"] = f"{resolved_model_id} speaker {int(resolved['speaker_id'])}"
    kw["voice_note"] = resolved.get("note")
    return Vocal(bus, entity_clock=entity_clock, **kw)
