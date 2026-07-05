# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Module wiring for KAINE's cycle entrypoint.

Each factory function below maps TOML keys to a module's constructor
kwargs explicitly. Unknown TOML keys raise at boot rather than
silently dropping. `build_registry` walks the `[modules]` toggles and
calls the right factory for each enabled module.

Hypnos depends on Mnemos / Nous / Thymos instances, so it's constructed
in a second pass after the others are in the registry.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Callable, Optional

from kaine.bus.client import AsyncBus
from kaine.config import require_known_keys
from kaine.entity_clock import EntityClock
from kaine.modules.base import BaseModule
from kaine.modules.registry import ModuleRegistry

log = logging.getLogger(__name__)


ModuleFactory = Callable[[AsyncBus, dict[str, Any]], BaseModule]


class ConfigurationError(ValueError):
    """Raised at startup when a module's config is invalid (e.g. a Nous
    complexity envelope whose worst-case step count exceeds the threshold)."""


class VoiceAlignmentConfigError(ConfigurationError):
    """Raised when voice_alignment is enabled and operator-approved but the
    [training] extras (unsloth, trl, peft, datasets) are not installed.

    This combination is a configuration error: silently falling back to
    FakeTrainer would produce training cycles that appear to succeed while
    writing no real adapter — a pretend process.  The operator must either
    install the extras or disable voice_alignment.
    """


def _require_keys(section: dict[str, Any], allowed: set[str]) -> None:
    # Delegates to the shared boundary-neutral guard; an empty table name
    # preserves boot's bare "unknown config keys: ..." message exactly.
    require_known_keys(section, allowed)


def _pop(section: dict[str, Any], allowed: set[str]) -> dict[str, Any]:
    _require_keys(section, allowed)
    return {k: section[k] for k in section if k in allowed}


def make_soma(
    bus: AsyncBus,
    section: dict[str, Any],
    *,
    entity_clock: Optional[EntityClock] = None,
) -> BaseModule:
    from kaine.modules.soma.module import Soma

    allowed = {
        "read_interval_s",
        "cycle_latency_target_ms",
        "cycle_latency_window",  # → SystemMetricsReader latency-averaging window
        "baseline_salience",
        "alert_salience",
        "thresholds",
        "weights",
        # Predictive interoception (soma-forward-model-fatigue)
        "forward_model_units",
        "prediction_error_window",
        "fatigue_decay_per_s",
        "fatigue_maintenance_threshold",
        "regulation_sustain_window_s",
        "regulation_threshold",
        # Developmental warm-up (soma-coldstart-regulation-warmup)
        "regulation_warmup_enabled",
        "regulation_warmup_min_samples",
        "regulation_warmup_min_seconds",
        "regulation_warmup_require_error_stabilized",
        "regulation_warmup_stable_window",
        "regulation_warmup_stable_variance",
    }
    kw = _pop(section, allowed)
    return Soma(bus, entity_clock=entity_clock, **kw)


def make_chronos(bus: AsyncBus, section: dict[str, Any]) -> BaseModule:
    from kaine.modules.chronos.module import Chronos

    allowed = {
        "cfc_units",
        "baseline_salience",
        "alert_salience",
        "anomaly_window",  # consumed by the anomaly detector default
        "anomaly_alert_threshold",
        "rumination_window",
        "rumination_threshold",
        "rumination_bucket_resolution",
        "user_input_streams",
        "forward_prediction",
        "prediction_error_window",
    }
    _require_keys(section, allowed)
    kwargs = {
        k: section[k]
        for k in (
            "cfc_units",
            "baseline_salience",
            "alert_salience",
            "anomaly_alert_threshold",
            "anomaly_window",
            "rumination_window",
            "rumination_threshold",
            "rumination_bucket_resolution",
            "user_input_streams",
            "forward_prediction",
            "prediction_error_window",
        )
        if k in section
    }
    return Chronos(bus, **kwargs)


def make_topos(
    bus: AsyncBus,
    section: dict[str, Any],
    *,
    entity_clock: Optional[EntityClock] = None,
) -> BaseModule:
    from kaine.modules.topos.live import LiveCameraConfig
    from kaine.modules.topos.module import Topos

    allowed = {
        "encoder_model_id",
        "device",
        "change_alert_threshold",
        "habituation_window",  # consumed by habituator default
        "baseline_salience",
        "alert_salience",
        # Live camera (eyes-only). Off by default.
        "capture_enabled",
        "capture_device",
        "capture_interval_s",
        # Subjective vision-sampling rate (Hz). The clean, biological expression
        # of the capture cadence (1 / capture_interval_s), decoupled from the
        # workspace tick. If set it takes precedence over capture_interval_s.
        # Shipped as 10.0 Hz in config/kaine.toml (benchmarked-cleared,
        # operator-approved); when absent the class default of 1.0 Hz holds.
        "vision_sample_hz",
        "capture_width",
        "capture_height",
        "capture_warmup_frames",
        # Forward prediction (disabled by default).
        "forward_prediction",
        "forward_model_units",
        "prediction_error_window",
        "visual_buffer_size",
        # Unified deterministic perception feed (unified-perception-feed). This
        # is the resolved top-level [perception_feed] config, injected by
        # build_registry under this reserved key (NOT a [topos.*] key the
        # operator sets). Selecting a seeded/playlist mode supplies a
        # source_factory and forces capture on. Shipped mode = "off". Popped
        # before the key check below.
        "perception_feed",
    }
    feed_section = dict(section.pop("perception_feed", {}) or {})
    _require_keys(section, allowed - {"perception_feed"})
    kwargs: dict[str, Any] = {}
    if "encoder_model_id" in section:
        kwargs["encoder_model_id"] = section["encoder_model_id"]
    if "device" in section:
        kwargs["device_preference"] = section["device"]
    for k in ("change_alert_threshold", "baseline_salience", "alert_salience"):
        if k in section:
            kwargs[k] = section[k]
    # Forward prediction knobs
    for k in ("forward_prediction", "forward_model_units", "prediction_error_window",
              "visual_buffer_size"):
        if k in section:
            kwargs[k] = section[k]
    kwargs["capture_enabled"] = bool(section.get("capture_enabled", False))

    # Unified deterministic perception feed selection (unified-perception-feed).
    # mode "off"/"live" leave the existing behaviour (off = capture disabled;
    # live = the real cv2 camera + real mic path). "seeded"/"playlist" supply a
    # source_factory and force capture on so LiveCamera reads from the
    # deterministic source.
    mode = str(feed_section.get("mode", "off")).lower()
    if mode not in ("off", "seeded", "playlist", "live"):
        raise ValueError(
            f"[perception_feed].mode must be off/seeded/playlist/live, got {mode!r}"
        )
    width = int(section.get("capture_width", 640))
    height = int(section.get("capture_height", 480))
    if mode == "live":
        # Real camera path: honour the existing live-camera config below.
        kwargs["capture_enabled"] = True
    elif mode in ("seeded", "playlist"):
        kwargs["source_factory"] = _build_perception_feed_video_factory(
            mode, feed_section, width=width, height=height
        )
        kwargs["capture_enabled"] = True

    if kwargs["capture_enabled"]:
        # Vision sampling is a subjective rate decoupled from the workspace tick.
        # Accept either capture_interval_s (subjective seconds/frame) or the
        # cleaner vision_sample_hz (frames/subjective second); the rate wins when
        # both are present. The shipped config sets vision_sample_hz = 10.0
        # (benchmark-cleared, operator-approved); when neither key is present the
        # class default of 1.0 s (1 Hz) holds.
        if "vision_sample_hz" in section:
            capture_interval_s = LiveCameraConfig.interval_from_hz(
                float(section["vision_sample_hz"])
            )
        else:
            capture_interval_s = float(section.get("capture_interval_s", 1.0))
        kwargs["live_camera_config"] = LiveCameraConfig(
            device=section.get("capture_device", 0),
            capture_interval_s=capture_interval_s,
            width=width,
            height=height,
            warmup_frames=int(section.get("capture_warmup_frames", 3)),
        )
    return Topos(bus, entity_clock=entity_clock, **kwargs)


def _build_perception_feed_video_factory(
    mode: str, feed: dict[str, Any], *, width: int, height: int
) -> Any:
    """Build a ``_VideoSource`` factory for the deterministic perception feed.

    The factory matches the LiveCamera ``source_factory(device, *, width, height)``
    signature; the deterministic sources ignore ``device``. Seeded uses the
    config geometry directly + the ``[perception_feed.video]`` knobs; playlist
    resolves + (later, at open()) verifies the operator manifest.
    """
    from kaine.modules.topos.feed import (
        PlaylistSource,
        SeededProceduralSource,
        SeededSchedule,
        load_playlist_manifest,
    )

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
        raise ValueError(
            "[perception_feed].mode = 'playlist' requires playlist_manifest"
        )
    manifest = load_playlist_manifest(manifest_path)

    def _playlist_factory(device, *, width, height):  # noqa: ANN001
        return PlaylistSource(manifest)

    return _playlist_factory


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
    video surface.
    """
    from kaine.modules.audition.feed import (
        PlaylistAudioStream,
        SeededAudioSchedule,
        SeededProceduralAudioStream,
    )
    from kaine.modules.topos.feed import load_playlist_manifest

    video = dict(feed.get("video") or {})
    audio = dict(feed.get("audio") or {})
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
        raise ValueError(
            "[perception_feed].mode = 'playlist' requires playlist_manifest"
        )
    manifest = load_playlist_manifest(manifest_path)

    def _playlist_factory(*, device, sample_rate, channels, frames_per_block, callback):  # noqa: ANN001
        return PlaylistAudioStream(
            manifest,
            callback=callback,
            sample_rate=int(sample_rate),
            channels=int(channels),
            frames_per_block=int(frames_per_block),
        )

    return _playlist_factory


def gather_perception_feed_descriptor(config: dict[str, Any]) -> dict[str, Any]:
    """Derive the unified perception-feed covariate from resolved config.

    Reads the top-level ``[perception_feed]`` (unified-perception-feed). For
    ``seeded`` returns the seed plus BOTH the video and the audio schedule (enough
    to regenerate the entity's full A/V input); for ``playlist`` the single
    manifest sha256 + per-item digests that pin both surfaces (enough to verify);
    for ``off``/``live`` just the mode. Best-effort — a malformed/absent manifest
    degrades to ``{"mode": ...}`` and never raises, so it can't crash boot. No
    rendered frames, no PCM, no operator paths.

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
    return descriptor


# Worst-case EFE step product (factors * max_states * actions * horizon) above
# which Nous's active-inference planning risks overrunning the cycle budget on
# the target CPU. The default compact envelope (4*4*4*1 = 64) is far below this.
_NOUS_COMPLEXITY_THRESHOLD = 4096


def make_nous(bus: AsyncBus, section: dict[str, Any]) -> BaseModule:
    from kaine.modules.nous.engine import PymdpEngine
    from kaine.modules.nous.generative_model import build_generative_model
    from kaine.modules.nous.module import Nous

    allowed = {
        # Complexity envelope (validated below).
        "factors",
        "max_states_per_factor",
        "actions",
        "planning_horizon",
        "efe_timeout_ms",
        # Module knobs.
        "baseline_salience",
        "alert_salience",
        "timeout_salience",
    }
    cfg = _pop(section, allowed)

    factors = int(cfg.pop("factors", 4))
    max_states = int(cfg.pop("max_states_per_factor", 4))
    actions = int(cfg.pop("actions", 4))
    horizon = int(cfg.pop("planning_horizon", 1))
    efe_timeout_ms = float(cfg.pop("efe_timeout_ms", 250.0))

    if factors < 1 or max_states < 1 or actions < 1 or horizon < 1:
        raise ConfigurationError(
            "nous envelope values (factors, max_states_per_factor, actions, "
            "planning_horizon) must all be >= 1"
        )
    product = factors * max_states * actions * horizon
    if product > _NOUS_COMPLEXITY_THRESHOLD:
        raise ConfigurationError(
            f"nous complexity envelope {factors}*{max_states}*{actions}*{horizon}"
            f"={product} exceeds threshold {_NOUS_COMPLEXITY_THRESHOLD}; "
            "EFE planning would risk overrunning the cycle budget"
        )

    # Build the engine eagerly so a misconfigured envelope / missing reasoning
    # extra fails loudly at boot rather than mid-cycle.
    model = build_generative_model(max_states_per_factor=max_states)
    engine = PymdpEngine(model, efe_timeout_ms=efe_timeout_ms, policy_len=horizon)
    return Nous(bus, engine=engine, **cfg)


def make_mnemos(
    bus: AsyncBus,
    section: dict[str, Any],
    *,
    entity_clock: Optional[EntityClock] = None,
) -> BaseModule:
    from kaine.modules.mnemos.module import Mnemos

    allowed = {
        "backend",
        "collection_prefix",
        "short_term_capacity",
        "recall_top_k",
        "embedder_model_id",
        "device",  # forwarded as embedder_device_preference
        "baseline_salience",
        "alert_salience",
        "recall_on_workspace",
        "recall_cooldown_s",
        "qdrant",
        "replay",  # nested sub-table: selection_top_k, affect_weight, recency_weight, redact_content
    }
    _require_keys(section, allowed)
    qdrant = section.get("qdrant") or {}
    replay = section.get("replay") or {}
    kwargs: dict[str, Any] = {
        k: section[k]
        for k in allowed - {"qdrant", "device", "replay"}
        if k in section
    }
    if "device" in section:
        kwargs["embedder_device_preference"] = section["device"]
    if "host" in qdrant:
        kwargs["qdrant_host"] = qdrant["host"]
    if "port" in qdrant:
        kwargs["qdrant_port"] = qdrant["port"]
    if "api_key" in qdrant:
        kwargs["qdrant_api_key"] = qdrant["api_key"]
    # Replay sub-table
    if "selection_top_k" in replay:
        kwargs["replay_selection_top_k"] = int(replay["selection_top_k"])
    if "affect_weight" in replay:
        kwargs["replay_affect_weight"] = float(replay["affect_weight"])
    if "recency_weight" in replay:
        kwargs["replay_recency_weight"] = float(replay["recency_weight"])
    if "redact_content" in replay:
        kwargs["replay_redact_content"] = bool(replay["redact_content"])
    return Mnemos(bus, entity_clock=entity_clock, **kwargs)


def make_eidolon(bus: AsyncBus, section: dict[str, Any]) -> BaseModule:
    from kaine.modules.eidolon.module import Eidolon
    from kaine.modules.eidolon.self_inference import SelfInferenceEngine

    allowed = {
        "persistence_path",
        "drift_window",
        "drift_threshold",
        "save_interval_s",
        "internal_speech_stream",
        "external_speech_stream",
        "identity_history_cap",
        "voice_observations_cap",
        "baseline_salience",
        "alert_salience",
        "self_inference",  # nested sub-table
    }
    kw = _pop(section, allowed)

    # Build the SelfInferenceEngine from the optional [eidolon.self_inference]
    # sub-table.  Ships disabled by default — operator must set enabled = true.
    si_section = kw.pop("self_inference", None) or {}
    si_allowed = {"enabled", "vad_window_cycles", "speech_pattern_min_count", "seed_path"}
    _require_keys(si_section, si_allowed)
    si_enabled = bool(si_section.get("enabled", False))
    si_kwargs: dict[str, Any] = {"enabled": si_enabled}
    if "vad_window_cycles" in si_section:
        si_kwargs["vad_window_cycles"] = int(si_section["vad_window_cycles"])
    if "speech_pattern_min_count" in si_section:
        si_kwargs["speech_pattern_min_count"] = int(si_section["speech_pattern_min_count"])
    if "seed_path" in si_section:
        seed_raw = str(si_section["seed_path"]).strip()
        if seed_raw:
            si_kwargs["seed_path"] = seed_raw
    inference_engine = SelfInferenceEngine(**si_kwargs)

    return Eidolon(bus, self_inference=inference_engine, **kw)


def make_thymos(
    bus: AsyncBus,
    section: dict[str, Any],
    *,
    entity_clock: Optional[EntityClock] = None,
) -> BaseModule:
    from kaine.modules.thymos.coupling import CouplingConfig
    from kaine.modules.thymos.module import Thymos
    from kaine.modules.thymos.state import DimensionalState

    allowed = {
        "baseline_valence",
        "baseline_arousal",
        "baseline_dominance",
        "drift_rate_per_s",
        "publish_interval_s",
        "baseline_salience",
        "alert_salience",
        "soma_stream",
        "chronos_stream",
        "mnemos_stream",
        "social_drive_time_scale_s",
        "drives",   # nested per-drive sub-tables, consumed by DriveSet default
        "coupling", # nested [thymos.coupling] sub-table
    }
    _require_keys(section, allowed)
    baseline = DimensionalState(
        valence=float(section.get("baseline_valence", 0.0)),
        arousal=float(section.get("baseline_arousal", 0.3)),
        dominance=float(section.get("baseline_dominance", 0.0)),
    )
    kwargs: dict[str, Any] = {"baseline": baseline}
    for k in (
        "drift_rate_per_s",
        "publish_interval_s",
        "baseline_salience",
        "alert_salience",
        "soma_stream",
        "chronos_stream",
        "mnemos_stream",
        "social_drive_time_scale_s",
    ):
        if k in section:
            kwargs[k] = section[k]
    # Build CouplingConfig from the optional [thymos.coupling] sub-table.
    coupling_section = section.get("coupling") or {}
    coupling_allowed = {
        "enabled",
        "coupling_base",
        "coupling_familiarity_gain",
        "coupling_ceiling",
        "decay_s",
    }
    # Tolerate (ignore) the legacy ``coupling_max_rate_per_s`` key: it backed the
    # removed DriftSafeguard (thymos-emergent-affect-coupling). Existing local
    # configs that still carry it must not fail to boot.
    coupling_ignored = {"coupling_max_rate_per_s"}
    _require_keys(coupling_section, coupling_allowed | coupling_ignored)
    coupling_kwargs: dict[str, Any] = {}
    for k in coupling_allowed:
        if k in coupling_section:
            coupling_kwargs[k] = coupling_section[k]
    kwargs["coupling"] = CouplingConfig(**coupling_kwargs)
    return Thymos(bus, entity_clock=entity_clock, **kwargs)


def make_praxis(
    bus: AsyncBus, section: dict[str, Any], *, intent_secret: Optional[bytes] = None
) -> BaseModule:
    from kaine.modules.praxis.module import Praxis
    from kaine.modules.praxis.whitelist import CommandWhitelist, WhitelistEntry

    allowed = {
        "sandbox_path",
        "audit_log_path",
        "notification_command",
        "notification_fallback_log",
        "max_file_bytes",
        "baseline_salience",
        "alert_salience",
        "enabled_effectors",  # operator effector-enablement whitelist (empty = none)
        "shell_whitelist",  # nested table: {<command_name>: {arg_patterns, timeout_s, ...}}
    }
    _require_keys(section, allowed)
    whitelist_table = section.get("shell_whitelist") or {}
    entries: list[WhitelistEntry] = []
    for command_name, entry_cfg in whitelist_table.items():
        entries.append(
            WhitelistEntry(
                command=command_name,
                arg_patterns=tuple(entry_cfg.get("arg_patterns", ())),
                timeout_s=float(entry_cfg.get("timeout_s", 5.0)),
                cwd=entry_cfg.get("cwd"),
                description=entry_cfg.get("description", ""),
            )
        )
    # Effector-enablement whitelist: empty by default → no effector runs until the
    # operator names it here. The gate is enforced in Praxis.act for every effector.
    enabled_effectors = list(section.get("enabled_effectors", ()) or ())
    kwargs: dict[str, Any] = {
        "whitelist": CommandWhitelist(entries),
        "enabled_effectors": enabled_effectors,
    }
    # Per-boot act-intent provenance secret (Mechanism B). The cycle composition
    # root generates it and injects the SAME bytes into Volition (to sign) and
    # here (to verify). None only in headless/test construction, where the
    # fail-closed default in Praxis then refuses every act intent.
    if intent_secret is not None:
        kwargs["intent_secret"] = intent_secret
    for k in (
        "sandbox_path",
        "audit_log_path",
        "notification_command",
        "notification_fallback_log",
        "max_file_bytes",
        "baseline_salience",
        "alert_salience",
    ):
        if k in section:
            kwargs[k] = section[k]
    return Praxis(bus, **kwargs)


def make_lingua(bus: AsyncBus, section: dict[str, Any]) -> BaseModule:
    from kaine.modules.lingua.module import Lingua

    allowed = {
        "chat_url",
        "model_id",
        "temperature",
        "max_tokens",
        "think",
        "request_timeout_s",
        "api_key",
        "intent_log_path",
        "context_max_events",
        "context_char_budget",
        "persona_name",
        "persona_external",
        "persona_internal",
        "baseline_salience",
        "alert_salience",
    }
    kw = _pop(section, allowed)
    # Bearer token for a keyed model server (e.g. Unsloth Studio). Resolve from
    # [lingua].api_key, else the KAINE_MODEL_SERVER_API_KEY env var (so the secret
    # can stay out of the config file). None → keyless server (llama-server).
    kw["api_key"] = kw.get("api_key") or os.environ.get("KAINE_MODEL_SERVER_API_KEY")
    return Lingua(bus, **kw)


def make_audition(bus: AsyncBus, section: dict[str, Any]) -> BaseModule:
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
    if mode not in ("off", "seeded", "playlist", "live"):
        raise ValueError(
            f"[perception_feed].mode must be off/seeded/playlist/live, got {mode!r}"
        )
    audio_cfg = dict(feed_section.get("audio") or {})
    sample_rate = int(audio_cfg.get("sample_rate", section.get("capture_sample_rate", 16000)))
    channels = int(audio_cfg.get("channels", section.get("capture_channels", 1)))
    if mode == "live":
        kwargs["capture_enabled"] = True
    elif mode in ("seeded", "playlist"):
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
    return Audition(bus, **kwargs)


def make_vox(bus: AsyncBus, section: dict[str, Any]) -> BaseModule:
    from kaine.modules.vox.module import Vox

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
        "lingua_external_stream",
        "thymos_state_stream",
        "mirroring",  # nested sub-table: enabled, mirror_strength, mirror_ceiling, decay_s
    }
    # Pop all top-level keys; handle mirroring sub-table separately.
    _require_keys(section, allowed)
    kw: dict[str, Any] = {k: section[k] for k in allowed - {"mirroring"} if k in section}
    # [vox.mirroring] sub-table.
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
    return Vox(bus, **kw)


def make_hypnos(
    bus: AsyncBus,
    section: dict[str, Any],
    *,
    mnemos: Optional[BaseModule] = None,
    nous_process: Optional[Any] = None,
    thymos: Optional[BaseModule] = None,
    phantasia: Optional[BaseModule] = None,
    kaine_config: Optional[dict[str, Any]] = None,
    entity_clock: Optional[EntityClock] = None,
) -> BaseModule:
    from kaine.modules.hypnos.module import Hypnos
    from kaine.modules.hypnos.voice_alignment import VoiceAlignmentConfig

    allowed = {
        "interval_seconds",
        "max_deferral_seconds",
        "per_defer_seconds",
        "nous_step_burst",
        "baseline_salience",
        "alert_salience",
        "voice_alignment",  # nested sub-table
        "consolidation",    # nested sub-table: fatigue_triggered, downscale_factor, replay_window_s
    }
    _require_keys(section, allowed)
    voice_cfg_section = section.get("voice_alignment") or {}
    voice_config: Optional[VoiceAlignmentConfig] = None
    if voice_cfg_section:
        base_model_path_raw = voice_cfg_section.get("base_model_path", "")
        base_model_path: Optional[str] = (
            str(base_model_path_raw).strip() or None
        )
        reload_endpoint_url_raw = voice_cfg_section.get("reload_endpoint_url", "")
        reload_endpoint_url: Optional[str] = (
            str(reload_endpoint_url_raw).strip() or None
        )
        restart_service_unit_raw = voice_cfg_section.get("restart_service_unit", "")
        restart_service_unit: Optional[str] = (
            str(restart_service_unit_raw).strip() or None
        )
        capability_probe_path_raw = voice_cfg_section.get(
            "capability_probe_path", ""
        )
        capability_probe_path: Optional[str] = (
            str(capability_probe_path_raw).strip() or None
        )
        abliteration_probe_path_raw = voice_cfg_section.get(
            "abliteration_probe_path", ""
        )
        abliteration_probe_path: Optional[str] = (
            str(abliteration_probe_path_raw).strip() or None
        )
        voice_config = VoiceAlignmentConfig(
            intent_log_path=Path(voice_cfg_section.get("intent_log_path", "state/lingua/intent_expression.jsonl")),
            adapter_output_dir=Path(voice_cfg_section.get("adapter_output_dir", "state/hypnos/adapters")),
            enabled=bool(voice_cfg_section.get("enabled", False)),
            base_model_path=base_model_path,
            model_id=str(voice_cfg_section.get("model_id", "kaineone/Qwen3.5-4B-abliterated")),
            max_samples=int(voice_cfg_section.get("max_samples", 200)),
            lora_rank=int(voice_cfg_section.get("lora_rank", 8)),
            learning_rate=float(voice_cfg_section.get("learning_rate", 5e-5)),
            dpo_beta=float(voice_cfg_section.get("dpo_beta", 0.1)),
            capability_loss_threshold=float(voice_cfg_section.get("capability_loss_threshold", 0.05)),
            seed=int(voice_cfg_section.get("seed", 42)),
            training_device=str(voice_cfg_section.get("training_device", "cuda:0")),
            adapter_retention=int(voice_cfg_section.get("adapter_retention", 5)),
            hot_swap_mode=str(voice_cfg_section.get("hot_swap_mode", "manual")),
            reload_endpoint_url=reload_endpoint_url,
            restart_service_unit=restart_service_unit,
            capability_probe_path=capability_probe_path,
            abliteration_probe_path=abliteration_probe_path,
            trainer_backend=str(
                voice_cfg_section.get("trainer_backend", "in_process")
            ).strip()
            or "in_process",
            trainer_python=str(voice_cfg_section.get("trainer_python", "")).strip(),
            trainer_workdir=str(
                voice_cfg_section.get(
                    "trainer_workdir", "state/hypnos/voice_align_jobs"
                )
            ).strip()
            or "state/hypnos/voice_align_jobs",
        )
    kwargs: dict[str, Any] = {}
    for k in (
        "interval_seconds",
        "max_deferral_seconds",
        "per_defer_seconds",
        "nous_step_burst",
        "baseline_salience",
        "alert_salience",
    ):
        if k in section:
            kwargs[k] = section[k]
    # [hypnos.consolidation] sub-table: fatigue_triggered, downscale_factor,
    # replay_window_s.  interval_seconds remains the max-interval safety net.
    consolidation = section.get("consolidation") or {}
    consolidation_allowed = {
        "fatigue_triggered",
        "downscale_factor",
        "replay_window_s",
        "associative_replay",
    }
    _require_keys(consolidation, consolidation_allowed)
    if "fatigue_triggered" in consolidation:
        kwargs["fatigue_triggered"] = bool(consolidation["fatigue_triggered"])
    if "downscale_factor" in consolidation:
        kwargs["downscale_factor"] = float(consolidation["downscale_factor"])
    if "replay_window_s" in consolidation:
        kwargs["replay_window_s"] = float(consolidation["replay_window_s"])
    if "associative_replay" in consolidation:
        kwargs["associative_replay_enabled"] = bool(consolidation["associative_replay"])
    if voice_config is not None:
        kwargs["voice_alignment_config"] = voice_config
    if entity_clock is not None:
        kwargs["entity_clock"] = entity_clock
    # Semantic embedder for the consolidation-divergence MAGNITUDE, on the same
    # scale as the A/B meter. Lives in the boundary-neutral kaine.text_embedding
    # (Hypnos never imports kaine.evaluation). Lazy: the heavy model only loads
    # the first sleep that actually builds pairs; absent the dep, magnitude
    # degrades to null and rate/counts still emit.
    try:
        from kaine.text_embedding import SentenceTransformerTextEmbedder

        kwargs["consolidation_embedder"] = SentenceTransformerTextEmbedder()
    except Exception:
        log.debug("hypnos: consolidation embedder unavailable", exc_info=True)
    # When the operator has opted in (config + env var) AND the
    # `[training]` extras importable, wire the real Unsloth-backed
    # trainer. Otherwise FakeTrainer ships the "no backend" reason.
    trainer = _resolve_trainer(voice_config)
    if trainer is not None:
        kwargs["trainer"] = trainer
        # On-device GPU window: when a real trainer is wired (voice-alignment
        # enabled + operator-approved), bracket the training step so the served
        # organ time-shares the single GPU (unload → train → reload). The runner
        # reuses the model-server lifecycle + gpu-preflight, injected here so the
        # domain module never imports the cycle runtime (modules→cycle boundary).
        runner = _make_organ_window_runner(voice_config, kaine_config or {})
        if runner is not None:
            kwargs["organ_window_runner"] = runner
    if mnemos is not None:
        kwargs["mnemos"] = mnemos
    if nous_process is not None:
        kwargs["nous_process"] = nous_process
    if thymos is not None:
        kwargs["thymos"] = thymos
    if phantasia is not None:
        kwargs["phantasia"] = phantasia
    return Hypnos(bus, **kwargs)


def _resolve_trainer(
    voice_config: Optional["VoiceAlignmentConfig"],
) -> Optional[Any]:
    """Pick a Trainer based on operator opt-in + the configured backend.

    Returns None (Hypnos falls back to FakeTrainer) when voice_alignment is
    disabled or the operator approval env var is unset — both are honest
    outcomes (training simply not in play).

    For ``trainer_backend = "in_process"`` (default): raises
    VoiceAlignmentConfigError when voice_alignment is enabled AND
    operator-approved AND the [training] extras are missing.  That combination
    is a config error: FakeTrainer would silently produce fake training runs.

    For ``trainer_backend = "subprocess"``: the heavy stack lives in an external
    env, so the [training] extras are NOT required in the runtime venv. Instead
    ``trainer_python`` must be set and exist on disk — empty/missing is a config
    error at boot (mirrors the missing-extra guard; never silently degrade).
    """
    if voice_config is None or not voice_config.enabled:
        return None
    from kaine.modules.hypnos.voice_alignment import operator_approved

    if not operator_approved():
        return None

    backend = (voice_config.trainer_backend or "in_process").strip()
    if backend not in ("in_process", "subprocess"):
        raise VoiceAlignmentConfigError(
            f"[hypnos.voice_alignment].trainer_backend must be 'in_process' or "
            f"'subprocess', got {backend!r}."
        )

    if backend == "subprocess":
        return _resolve_subprocess_trainer(voice_config)

    try:
        import unsloth  # noqa: F401  # type: ignore[import-untyped]
        import trl  # noqa: F401  # type: ignore[import-untyped]
        import peft  # noqa: F401  # type: ignore[import-untyped]
        import datasets  # noqa: F401  # type: ignore[import-untyped]
    except Exception as exc:
        # voice_alignment.enabled=True + operator_approved=True + missing extras
        # is a configuration error, not an acceptable silent fallback.  Installing
        # FakeTrainer here would let training cycles "succeed" while writing nothing
        # — a pretend process.  Raise so the operator sees a clear boot failure
        # instead of silently producing useless training runs.
        raise VoiceAlignmentConfigError(
            f"voice_alignment is enabled and operator-approved but the [training] "
            f"extras are not installed ({exc}). Install them with:\n"
            f"  .venv/bin/pip install 'kaine[training]'\n"
            f"or disable voice_alignment in kaine.toml / kaine.operator.toml."
        ) from exc
    _require_non_empty_abliteration_probes(voice_config)

    from kaine.modules.hypnos.unsloth_trainer import UnslothDPOTrainer

    return UnslothDPOTrainer(base_model_path=voice_config.base_model_path)


def _require_non_empty_abliteration_probes(
    voice_config: "VoiceAlignmentConfig",
) -> None:
    """Welfare invariant shared by both trainer backends.

    When voice alignment is actually going to run, the abliteration probe set
    MUST be non-empty — a run without an abliteration gate could silently
    re-introduce refusal conditioning. Raises EmptyAbliterationProbeSetError
    with a clear remediation message. (The subprocess external script also
    fails closed on an empty set; this is the boot-time belt-and-suspenders.)
    """
    from kaine.modules.hypnos.capability_eval import (
        DEFAULT_ABLITERATION_PROBE_PATH,
        require_non_empty_abliteration_probes,
    )

    probe_path = (
        voice_config.abliteration_probe_path or DEFAULT_ABLITERATION_PROBE_PATH
    )
    require_non_empty_abliteration_probes(probe_path)


def _resolve_subprocess_trainer(
    voice_config: "VoiceAlignmentConfig",
) -> Any:
    """Construct the out-of-process trainer for the "subprocess" backend.

    The heavy unsloth/torch stack lives in an EXTERNAL operator-configured env,
    so the runtime venv does NOT need the [training] extra. What it does need —
    and what fails the boot loudly when absent (never a silent degrade) — is a
    ``trainer_python`` that is set and points at an existing interpreter, plus
    the same non-empty abliteration probe set the in-process path requires.
    """
    from pathlib import Path as _Path

    from kaine.modules.hypnos.subprocess_trainer import SubprocessVoiceTrainer

    trainer_python = (voice_config.trainer_python or "").strip()
    if not trainer_python:
        raise VoiceAlignmentConfigError(
            "voice_alignment is enabled with trainer_backend = 'subprocess' but "
            "[hypnos.voice_alignment].trainer_python is empty. Set it to the "
            "external trainer interpreter (e.g. the Unsloth Studio python at "
            "~/.unsloth/studio/.../bin/python), or use trainer_backend = "
            "'in_process', or disable voice_alignment."
        )
    if not _Path(trainer_python).exists():
        raise VoiceAlignmentConfigError(
            f"voice_alignment trainer_backend = 'subprocess' but trainer_python "
            f"does not exist: {trainer_python}. Point it at the external trainer "
            "interpreter, or use trainer_backend = 'in_process', or disable "
            "voice_alignment."
        )

    _require_non_empty_abliteration_probes(voice_config)

    return SubprocessVoiceTrainer(
        trainer_python=trainer_python,
        trainer_workdir=voice_config.trainer_workdir,
    )


def _make_organ_window_runner(
    voice_config: "VoiceAlignmentConfig",
    kaine_config: dict[str, Any],
) -> Optional[Any]:
    """Build the on-device unload→train→reload runner Hypnos brackets training with.

    Returns an async callable ``runner(train_thunk) -> (TrainingResult,
    OrganWindowResult)``. ``boot`` is the allowed composition root, so it may
    import both the domain bracket (kaine.modules.hypnos.organ_window) AND the
    cycle-runtime preflight (kaine.cycle.preflight) — wiring them together here
    keeps the domain module itself free of the forbidden modules→cycle import
    (the preflight is INJECTED into the controller).

    The runner closes over the full ``kaine_config`` so the model-server
    lifecycle resolves the served organ exactly as the bootstrap does (one
    provenance). On a host where the bracket does not apply (multi-GPU or
    hot_swap_mode=manual) the runner trains with the organ resident.
    """
    from kaine.cycle.preflight import GpuPreflightConfig, run_preflight
    from kaine.modules.hypnos.organ_window import (
        OrganServerController,
        run_with_organ_window,
    )

    serve_device = str(voice_config.training_device or "cuda:0")
    hot_swap_mode = str(voice_config.hot_swap_mode or "manual")

    def _preflight_fn(config: dict[str, Any]) -> bool:
        # Cooperative headroom check before reload (report-only; never kills a
        # foreign process). Preserves KAINE's own service ports as keep set.
        gpu_cfg = GpuPreflightConfig.from_section(config.get("gpu_preflight") or {})
        if not gpu_cfg.enabled:
            return True
        lingua = config.get("lingua") or {}
        keep = [m for m in [lingua.get("model_id")] if m]
        return bool(run_preflight(gpu_cfg, keep_models=keep).ok)

    controller = OrganServerController(
        config=kaine_config,
        preflight_fn=_preflight_fn,
    )

    async def runner(train_thunk: Any) -> Any:
        return await run_with_organ_window(
            train=train_thunk,
            config=kaine_config,
            serve_device=serve_device,
            hot_swap_mode=hot_swap_mode,
            controller=controller,
        )

    return runner


def make_mundus(bus: AsyncBus, section: dict[str, Any]) -> BaseModule:
    from kaine.modules.mundus.module import Mundus

    # Body-agnostic control plane: select exactly one embodiment adapter and
    # build it from its own nested `[mundus.<adapter>]` table. Adapter-specific
    # settings (transport, per-family/channel exposure) live under that table,
    # never flat in `[mundus]`. An unknown adapter name fails closed at boot.
    adapter_name = str(section.get("adapter", "opensim"))
    adapter_section = dict(section.get(adapter_name, {}) or {})

    # `expose_<family>`/`expose_<channel>` keys under the adapter table →
    # operator exposure overrides on top of the descriptor defaults.
    expose = {
        key[len("expose_"):]: bool(value)
        for key, value in adapter_section.items()
        if key.startswith("expose_")
    }

    if adapter_name == "opensim":
        from kaine.modules.mundus.adapters.opensim import OpenSimAdapter

        adapter = OpenSimAdapter(
            host=str(adapter_section.get("bridge_host", "127.0.0.1")),
            port=int(adapter_section.get("bridge_port", 7781)),
        )
    elif adapter_name == "stub":
        from kaine.modules.mundus.adapters.stub import StubAdapter

        adapter = StubAdapter()
    else:
        raise ValueError(
            f"mundus: unknown adapter {adapter_name!r}; no embodiment constructed "
            "(fail-closed). Set [mundus].adapter to a known adapter."
        )

    kwargs: dict[str, Any] = {}
    for key in ("mirror_speech", "speech_stream"):
        if key in section:
            kwargs[key] = section[key]
    # Constructed only when [modules].mundus is on; the operational two-layer gate
    # is [mundus].enabled (default true here) AND KAINE_MUNDUS_OPERATOR_APPROVED=1.
    return Mundus(
        bus,
        adapter=adapter,
        enabled=bool(section.get("enabled", True)),
        expose=expose or None,
        **kwargs,
    )


def make_perception(
    bus: AsyncBus,
    section: dict[str, Any],
    *,
    entity_clock: Optional[EntityClock] = None,
) -> BaseModule:
    from kaine.modules.perception.module import PerceptionLocus

    kwargs: dict[str, Any] = {}
    for key in ("allow_self_switch", "min_dwell_s"):
        if key in section:
            kwargs[key] = section[key]
    return PerceptionLocus(bus, entity_clock=entity_clock, **kwargs)


def make_empatheia(bus: AsyncBus, section: dict[str, Any]) -> BaseModule:
    from kaine.modules.empatheia.module import Empatheia

    allowed = {
        "backend",
        "collection",
        "speaker_label",
        "deviation_threshold",
        "baseline_salience",
        "alert_salience",
        "qdrant",  # nested sub-table: host, port, api_key
    }
    _require_keys(section, allowed)
    qdrant = section.get("qdrant") or {}
    kwargs: dict[str, Any] = {
        k: section[k]
        for k in allowed - {"qdrant"}
        if k in section
    }
    if "host" in qdrant:
        kwargs["qdrant_host"] = qdrant["host"]
    if "port" in qdrant:
        kwargs["qdrant_port"] = qdrant["port"]
    if "api_key" in qdrant:
        kwargs["qdrant_api_key"] = qdrant["api_key"]
    return Empatheia(bus, **kwargs)


def make_phantasia(bus: AsyncBus, section: dict[str, Any]) -> BaseModule:
    from kaine.modules.phantasia.module import Phantasia

    allowed = {
        "backend",
        "training_enabled",
        "training_device",
        "trajectory_buffer_size",
        "rollout_horizon",
        "persist_weights",
        "checkpoint_path",
        "mnemos_stream",
        "hypnos_stream",
        "salience",  # nested sub-table: baseline, alert
        "world_model",  # nested sub-table: real-backend hyperparams (extra-gated)
    }
    _require_keys(section, allowed)
    kwargs: dict[str, Any] = {}
    for k in (
        "backend",
        "training_enabled",
        "training_device",
        "trajectory_buffer_size",
        "rollout_horizon",
        "persist_weights",
        "checkpoint_path",
        "mnemos_stream",
        "hypnos_stream",
    ):
        if k in section:
            kwargs[k] = section[k]
    salience = section.get("salience") or {}
    if "baseline" in salience:
        kwargs["baseline_salience"] = float(salience["baseline"])
    if "alert" in salience:
        kwargs["alert_salience"] = float(salience["alert"])
    world_model = section.get("world_model") or {}
    if world_model:
        kwargs["world_model_kwargs"] = dict(world_model)
    return Phantasia(bus, **kwargs)


SIMPLE_FACTORIES: dict[str, ModuleFactory] = {
    "soma": make_soma,
    "chronos": make_chronos,
    "topos": make_topos,
    "nous": make_nous,
    "mnemos": make_mnemos,
    "eidolon": make_eidolon,
    "thymos": make_thymos,
    "praxis": make_praxis,
    "lingua": make_lingua,
    "audition": make_audition,
    "vox": make_vox,
    "mundus": make_mundus,
    "perception": make_perception,
    "empatheia": make_empatheia,
    "phantasia": make_phantasia,
}


def install_state_encryption(kaine_config: dict[str, Any]) -> None:
    """Install the process-global StateEncryptor from `[security.state_encryption]`.

    Runs before any module persists state. When encryption is enabled but no
    key is available this raises `CryptoConfigError` so the entity does not
    boot without its key (fail-closed). When disabled (the shipped default)
    the installed encryptor is a transparent no-op.
    """
    from kaine.security.crypto import install_from_section

    section = (kaine_config.get("security") or {}).get("state_encryption") or {}
    install_from_section(section)


# Factories for modules that time a COGNITIVE process and therefore take the
# shared subjective EntityClock (biological-timing-and-dilation Phase 2). The
# clock dilates their integrals/cadences coherently with the cycle's tick
# pacing. Every other module is purely event-driven (paces off the subjective
# cycle already) or times only infrastructure, so it gets no clock.
_CLOCKED_FACTORIES: frozenset[str] = frozenset(
    {"soma", "topos", "mnemos", "thymos", "perception"}
)


def build_registry(
    bus: AsyncBus,
    kaine_config: dict[str, Any],
    *,
    entity_clock: Optional[EntityClock] = None,
    intent_secret: Optional[bytes] = None,
) -> ModuleRegistry:
    """Construct every enabled module from kaine.toml and register it.

    Builds (or receives) the ONE shared ``EntityClock`` for this boot from
    ``[cycle].time_scale`` and injects the SAME instance into every cognitive
    module plus onto the registry. The cycle entrypoint reads
    ``registry.entity_clock`` back and hands it to the ``CognitiveCycle``, so the
    tick pacing and the modules' cognitive timers all dilate off one
    ``time_scale`` — no two cognitive clocks ever desynchronize. At the shipped
    default ``time_scale = 1.0`` the clock reads real elapsed time, so behavior
    is identical to before this wiring.
    """
    install_state_encryption(kaine_config)
    toggles = kaine_config.get("modules") or {}
    registry = ModuleRegistry()
    # One shared subjective clock for the whole mind. Built here from
    # [cycle].time_scale (default 1.0 = real-time) unless the caller already
    # constructed one, so build_registry and the cycle can share a single
    # instance regardless of construction order.
    if entity_clock is None:
        time_scale = float((kaine_config.get("cycle") or {}).get("time_scale", 1.0))
        entity_clock = EntityClock(scale=time_scale)
    registry.entity_clock = entity_clock
    # The unified perception feed is a single top-level [perception_feed] section
    # (unified-perception-feed) that parameterizes BOTH the vision surface
    # (Topos) and the hearing surface (Audition) from one source of truth. Read
    # it once and inject it into both factories' sections under a reserved key
    # the factories pop. Keeping it top-level (not under [topos]/[audition])
    # means picture and sound cannot drift to different seeds/manifests.
    perception_feed = dict(kaine_config.get("perception_feed") or {})
    # A configured deterministic feed (seeded/playlist) is the entity's VIRTUAL
    # world, so booting with one selected must bind the senses to it: select the
    # `virtual` locus and mark both modalities desired. Without this the locus-
    # gated capture supervisors keep the virtual feed dark (the shipped desired-
    # state defaults to locus=`physical`, flags off) and Topos/Audition publish
    # nothing — the "awake but senseless" failure. mode off/live leave the
    # desired-state to the operator (live = real camera/mic, operator-toggled).
    _feed_mode = str(perception_feed.get("mode", "off")).lower()
    if _feed_mode in ("seeded", "playlist") and (
        bool(toggles.get("topos", False)) or bool(toggles.get("audition", False))
    ):
        from kaine import perception_state as _ps

        _desired = _ps.select_virtual_feed()
        if _desired.locus != "virtual":
            log.warning(
                "perception feed mode=%s configured but locus is locked to %s; "
                "the virtual feed will not deliver until the operator unlocks it",
                _feed_mode,
                _desired.locus,
            )
        else:
            log.info(
                "perception feed mode=%s -> locus=virtual audio=%s video=%s",
                _feed_mode,
                _desired.audio_live_desired,
                _desired.video_live_desired,
            )
    for name, factory in SIMPLE_FACTORIES.items():
        if not bool(toggles.get(name, False)):
            continue
        section = dict(kaine_config.get(name) or {})
        if name in ("topos", "audition"):
            section["perception_feed"] = dict(perception_feed)
        if name in _CLOCKED_FACTORIES:
            module = factory(bus, section, entity_clock=entity_clock)
        elif name == "praxis":
            # Praxis alone takes the per-boot provenance secret so it can verify
            # act-intent signatures at the boundary (see make_praxis).
            module = factory(bus, section, intent_secret=intent_secret)
        else:
            module = factory(bus, section)
        registry.register(module)
        log.info("registered module %s", name)

    if bool(toggles.get("hypnos", False)):
        mnemos = registry.get("mnemos") if "mnemos" in registry else None
        thymos = registry.get("thymos") if "thymos" in registry else None
        phantasia = registry.get("phantasia") if "phantasia" in registry else None
        # Nous is now a pymdp/JAX active-inference engine with no NAR subprocess,
        # so there is no process for Hypnos's belief-revision phase to step;
        # that phase skips cleanly when nous_process is None.
        hypnos = make_hypnos(
            bus,
            dict(kaine_config.get("hypnos") or {}),
            mnemos=mnemos,
            nous_process=None,
            thymos=thymos,
            phantasia=phantasia,
            kaine_config=kaine_config,
            entity_clock=entity_clock,
        )
        registry.register(hypnos)
        log.info("registered module hypnos")
    _wire_self_hearing_gate(registry)
    _wire_lingua_self_model(registry)
    _wire_eidolon_capabilities(registry)
    _log_device_assignments(registry, kaine_config)
    _wire_oscillators(registry, kaine_config)
    return registry


def rewire_module(
    registry: ModuleRegistry, name: str, kaine_config: dict[str, Any]
) -> None:
    """Re-run the post-registration wiring after Spot rebuilds ``name``.

    Spot's heavy restart path constructs a fresh module and swaps it into the
    registry via ``replace``; the new instance must be re-wired exactly as
    ``build_registry`` wires the full set. The individual wirings are idempotent
    and cheap, so we re-run the global helpers rather than scoping to one
    module (the ``name`` argument documents intent and lets a future
    optimization narrow the work without changing callers).
    """
    _wire_self_hearing_gate(registry)
    _wire_lingua_self_model(registry)
    _wire_eidolon_capabilities(registry)
    _wire_oscillators(registry, kaine_config)


# Allowed keys for the workspace-level [oscillator] section (oscillatory-layer).
_OSCILLATOR_ALLOWED_KEYS: set[str] = {
    "enabled",
    "population_size",
    "plv_window",
    "coherence_floor",
    "coherence_ceiling",
    "beta",
    "threshold",
    "base_drive",
}

# Spec minimums for the oscillatory-binding layer.
_OSCILLATOR_MIN_POPULATION = 16
_OSCILLATOR_MIN_PLV_WINDOW = 10


def oscillator_enabled(kaine_config: dict[str, Any]) -> bool:
    """Whether the oscillatory-binding layer is enabled in config."""
    section = kaine_config.get("oscillator") or {}
    return bool(section.get("enabled", False))


def make_coherence_scorer(kaine_config: dict[str, Any]):
    """Build a `CoherenceScorer` from the [oscillator] section, or ``None`` when
    the layer is disabled. Validates keys and the spec minimums."""
    from kaine.workspace.coherence import CoherenceScorer

    section = dict(kaine_config.get("oscillator") or {})
    _require_keys(section, _OSCILLATOR_ALLOWED_KEYS)
    if not bool(section.get("enabled", False)):
        return None
    plv_window = int(section.get("plv_window", _OSCILLATOR_MIN_PLV_WINDOW))
    population_size = int(section.get("population_size", _OSCILLATOR_MIN_POPULATION))
    if population_size < _OSCILLATOR_MIN_POPULATION:
        raise ConfigurationError(
            f"[oscillator].population_size must be >= {_OSCILLATOR_MIN_POPULATION}"
        )
    if plv_window < _OSCILLATOR_MIN_PLV_WINDOW:
        raise ConfigurationError(
            f"[oscillator].plv_window must be >= {_OSCILLATOR_MIN_PLV_WINDOW}"
        )
    floor = float(section.get("coherence_floor", 0.8))
    ceiling = float(section.get("coherence_ceiling", 1.25))
    return CoherenceScorer(
        plv_window=plv_window,
        coherence_floor=floor,
        coherence_ceiling=ceiling,
    )


# Allowed keys for the [syneidesis] section (workspace selection + the live
# four-factor salience source selectors). A typo (e.g. `salience_goal_factors`)
# must fail loudly rather than silently leave the goal factor on its default.
_SYNEIDESIS_ALLOWED_KEYS: set[str] = {
    "top_k",
    "publication_threshold",
    "novelty_window",
    "salience_thymos_factor",
    "salience_goal_factor",
}

# Shipped default source per salience factor (wire-salience-goal-thymos, STAGED
# rollout). The Thymos factor ships LIVE (the real, tested StateModulator); the
# goal factor ships on the static baseline pending validation. A factor "warns"
# only when the operator selects "static" for a factor whose default is REAL —
# i.e. a deliberate downgrade — so flipping the goal default to "drive_relevance"
# later would automatically make goal="static" a warned downgrade.
_SALIENCE_THYMOS_FACTOR_DEFAULT = "state_modulator"
_SALIENCE_GOAL_FACTOR_DEFAULT = "static"


def make_salience_factors(kaine_config: dict[str, Any], affect_provider: Any):
    """Select the goal + Thymos salience factors from the [syneidesis] section.

    Returns ``(thymos_modulator, goal_scorer, downgraded_factors)``. Both real
    factors read the entity's current affect/drives through ``affect_provider``
    (dependency injection — the workspace layer never imports ``kaine.modules``).
    ``downgraded_factors`` names each factor the operator deliberately set to the
    static negative control *when that factor ships real by default*, so
    :class:`RuleBasedSalience` warns on a genuine downgrade only (never on the
    staged goal default). Validates the section's keys and the selected values.
    """
    from kaine.modules.thymos.modulator import StateModulator
    from kaine.workspace import (
        DriveRelevanceGoalScorer,
        StaticGoalScorer,
        StaticThymosModulator,
    )

    section = dict(kaine_config.get("syneidesis") or {})
    _require_keys(section, _SYNEIDESIS_ALLOWED_KEYS)

    thymos_factor = str(
        section.get("salience_thymos_factor", _SALIENCE_THYMOS_FACTOR_DEFAULT)
    )
    goal_factor = str(section.get("salience_goal_factor", _SALIENCE_GOAL_FACTOR_DEFAULT))

    if thymos_factor == "state_modulator":
        thymos_modulator = StateModulator(affect_provider.dimensional_state)
    elif thymos_factor == "static":
        thymos_modulator = StaticThymosModulator()
    else:
        raise ConfigurationError(
            "unknown [syneidesis].salience_thymos_factor "
            f"{thymos_factor!r} (expected 'state_modulator' or 'static')"
        )

    if goal_factor == "drive_relevance":
        goal_scorer = DriveRelevanceGoalScorer(affect_provider.drive_values)
    elif goal_factor == "static":
        goal_scorer = StaticGoalScorer()
    else:
        raise ConfigurationError(
            "unknown [syneidesis].salience_goal_factor "
            f"{goal_factor!r} (expected 'drive_relevance' or 'static')"
        )

    # A factor is a deliberate downgrade when it is static but ships real.
    downgraded_factors: list[str] = []
    if thymos_factor == "static" and _SALIENCE_THYMOS_FACTOR_DEFAULT != "static":
        downgraded_factors.append("thymos_modulation (set to static)")
    if goal_factor == "static" and _SALIENCE_GOAL_FACTOR_DEFAULT != "static":
        downgraded_factors.append("goal_relevance (set to static)")

    # Honest, non-alarming note that the goal factor is on its staged static
    # baseline (the intended shipped state, not an operator downgrade).
    if goal_factor == "static" and _SALIENCE_GOAL_FACTOR_DEFAULT == "static":
        log.info(
            "salience goal factor is on the staged static baseline "
            "(set [syneidesis].salience_goal_factor = 'drive_relevance' to activate "
            "the drive-relevance scorer once validated)"
        )

    return thymos_modulator, goal_scorer, downgraded_factors


def _wire_oscillators(registry: ModuleRegistry, kaine_config: dict[str, Any]) -> None:
    """Attach a live `ModuleOscillator` to every registered module when the
    oscillatory-binding layer is enabled. No-op when disabled. When snnTorch is
    absent, `make_oscillator` returns None and the module keeps reporting the
    neutral phase (graceful degradation)."""
    section = dict(kaine_config.get("oscillator") or {})
    if not bool(section.get("enabled", False)):
        return
    from kaine.oscillator import make_oscillator, snntorch_available

    if not snntorch_available():
        log.warning(
            "[oscillator].enabled is true but snnTorch is unavailable; modules "
            "report the neutral phase and the coherence factor degrades to 1.0 "
            "(install the [oscillator] extra to activate)"
        )
        return
    population_size = int(section.get("population_size", _OSCILLATOR_MIN_POPULATION))
    plv_window = int(section.get("plv_window", _OSCILLATOR_MIN_PLV_WINDOW))
    beta = float(section.get("beta", 0.9))
    threshold = float(section.get("threshold", 1.0))
    base_drive = float(section.get("base_drive", 1.5))
    for module in list(registry.all_modules()):
        osc = make_oscillator(
            population_size=population_size,
            plv_window=plv_window,
            beta=beta,
            threshold=threshold,
            base_drive=base_drive,
        )
        if osc is not None and hasattr(module, "attach_oscillator"):
            module.attach_oscillator(osc)
            log.info("attached oscillator to module %s", module.name)


def _wire_lingua_self_model(registry: ModuleRegistry) -> None:
    """Give Lingua a read-only accessor to the Eidolon self-model so its persona
    is seeded from accumulated identity (values/norms/name). No-op unless both
    modules are enabled; on a fresh start the model is empty and the persona
    stays minimal."""
    if "lingua" not in registry or "eidolon" not in registry:
        return
    lingua = registry.get("lingua")
    eidolon = registry.get("eidolon")
    if not hasattr(lingua, "set_self_model_provider"):
        return

    def _provider() -> dict[str, Any]:
        try:
            m = eidolon.model
            return {
                "name": getattr(m, "name", None),
                "values": list(getattr(m, "values", []) or []),
                "behavioral_norms": list(getattr(m, "behavioral_norms", []) or []),
                "personality_baseline": dict(getattr(m, "personality_baseline", {}) or {}),
            }
        except Exception:
            return {}

    lingua.set_self_model_provider(_provider)
    log.info("wired lingua persona to eidolon self-model")


def _wire_eidolon_capabilities(registry: ModuleRegistry) -> None:
    """Inject the Praxis effector whitelist into Eidolon's self-inference engine
    so the self-model's ``capability_map`` reflects what the entity can execute
    (the ``eidolon-self-inference`` "Capability map from Praxis whitelist"
    requirement). No-op unless both modules are present. Idempotent: the whitelist
    is fixed for the boot, so re-running (e.g. after a Spot rebuild) is safe."""
    if "praxis" not in registry or "eidolon" not in registry:
        return
    praxis = registry.get("praxis")
    eidolon = registry.get("eidolon")
    engine = getattr(eidolon, "self_inference", None)
    if engine is None or not hasattr(engine, "set_whitelist_commands"):
        return
    effectors = sorted(getattr(praxis, "enabled_effectors", ()) or ())
    engine.set_whitelist_commands(effectors)
    log.info("wired eidolon capability whitelist from praxis (%d effectors)", len(effectors))


def _wire_self_hearing_gate(registry: ModuleRegistry) -> None:
    """Share one SpeakingGate between vox and audition so the entity does
    not transcribe its own spoken output. No-op unless both modules are
    enabled. Whether the gate is ever *opened* is controlled by vox's
    `suppress_self_hearing` flag, so an isolated-headset operator can stay
    full-duplex by setting it false."""
    if "vox" not in registry or "audition" not in registry:
        return
    from kaine.modules.vox.coordination import SpeakingGate

    gate = SpeakingGate()
    vox = registry.get("vox")
    audition = registry.get("audition")
    if hasattr(vox, "set_speaking_gate"):
        vox.set_speaking_gate(gate)
    if hasattr(audition, "set_speaking_gate"):
        audition.set_speaking_gate(gate)
    log.info("wired self-hearing gate between vox and audition")


def _log_device_assignments(
    registry: ModuleRegistry, kaine_config: dict[str, Any]
) -> None:
    """One-line-per-module log of which compute device each pinned
    module landed on. Reads the resolved config rather than reaching
    into the constructed modules so this stays cheap and never raises.
    """
    rows: list[tuple[str, str]] = []
    if "topos" in registry:
        rows.append(("topos.encoder", str((kaine_config.get("topos") or {}).get("device", "auto"))))
    if "mnemos" in registry:
        rows.append(("mnemos.embedder", str((kaine_config.get("mnemos") or {}).get("device", "auto"))))
    if "audition" in registry:
        rows.append(("audition.emotion", str((kaine_config.get("audition") or {}).get("emotion_device", "cpu"))))
    if "chronos" in registry:
        rows.append(("chronos.network", "cpu (pinned)"))
    if "hypnos" in registry:
        va = (kaine_config.get("hypnos") or {}).get("voice_alignment") or {}
        rows.append(("hypnos.voice_alignment", str(va.get("training_device", "cuda:0"))))
        rows.append((
            "hypnos.voice_alignment.hot_swap",
            str(va.get("hot_swap_mode", "manual")),
        ))
    if not rows:
        return
    log.info("device assignment summary:")
    for module_name, device in rows:
        log.info("  device assignment: %s → %s", module_name, device)


class MetricsCollector:
    """Live cycle metrics for Nexus diagnostics.

    Snapshot is read at request time so the JSON endpoint always
    returns current values.
    """

    def __init__(self, cycle: Any, registry: ModuleRegistry) -> None:
        self._cycle = cycle
        self._registry = registry

    def snapshot(self) -> dict[str, Any]:
        cycle = self._cycle
        return {
            "tick_index": getattr(cycle, "tick_index", 0),
            "processing_rate_hz": getattr(cycle, "processing_rate_hz", 0.0),
            "experiential_rate_hz": getattr(cycle, "experiential_rate_hz", 0.0),
            "error_counts": dict(getattr(cycle, "error_counts", {}) or {}),
            "modules": sorted(name for name in self._iter_module_names()),
        }

    def _iter_module_names(self):
        try:
            for module in self._registry.all_modules():
                yield module.name
        except Exception:
            return
