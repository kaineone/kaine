# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Real-module boot wiring smoke test.

Builds the registry from a minimal in-memory config TOML against
fakeredis. Heavy collaborators (transformers, torch, qdrant, pynvml,
NAR subprocess) are bypassed by passing in pre-built protocol-conforming
stand-ins via the existing constructor injection points where they
exist; otherwise we monkey-patch the class to avoid network/GPU calls
at __init__ time.

This is the FIRST test that exercises real module classes through the
config path. Phase 9's integration tests used `StreamProducerFake`.
"""

from __future__ import annotations

import logging

import pytest

from kaine.boot import (
    SIMPLE_FACTORIES,
    ConfigurationError,
    build_registry,
    make_affect,
    make_audition,
    make_effectors,
    make_episodic_memory,
    make_interoception,
    make_language,
    make_planning,
    make_self_model,
    make_sequence,
    make_sleep,
    make_social_cognition,
    make_vision,
    make_vocal,
    make_world_model,
    rewire_module,
)
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.entity_clock import EntityClock
from kaine.security.crypto import (
    CryptoConfig,
    CryptoConfigError,
    StateEncryptor,
    get_state_encryptor,
    set_state_encryptor,
)


def _bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    return AsyncBus(BusConfig(password="x", audit_required=False), client=client)


def test_make_interoception_from_config():
    bus = _bus()
    interoception = make_interoception(
        bus,
        {
            "read_interval_s": 1.0,
            "cycle_latency_target_ms": 300.0,
            "baseline_salience": 0.1,
            "alert_salience": 0.7,
        },
    )
    assert interoception.name == "soma"


def test_make_interoception_wires_cycle_latency_window():
    # The cycle_latency_window key must size the SystemMetricsReader's
    # latency-averaging window — not be silently dropped.
    bus = _bus()
    interoception = make_interoception(bus, {"cycle_latency_window": 17})
    assert interoception._reader._latency_samples.maxlen == 17


def test_make_sequence_from_config():
    bus = _bus()
    sequence = make_sequence(
        bus,
        {
            "cfc_units": 32,
            "baseline_salience": 0.1,
            "alert_salience": 0.7,
            "anomaly_alert_threshold": 3.0,
        },
    )
    assert sequence.name == "chronos"


def test_make_sequence_wires_anomaly_and_rumination_windows():
    # The anomaly/rumination window knobs must reach the default detectors
    # rather than being accepted-then-dropped.
    bus = _bus()
    sequence = make_sequence(
        bus,
        {
            "anomaly_window": 21,
            "rumination_window": 13,
            "rumination_threshold": 7,
            "rumination_bucket_resolution": 0.5,
        },
    )
    assert sequence._anomaly.window == 21
    assert sequence._rumination.window == 13
    assert sequence._rumination.threshold == 7
    assert sequence._rumination._resolution == 0.5


def test_make_vision_from_config_does_not_load_transformers():
    bus = _bus()
    vision = make_vision(
        bus,
        {
            "encoder_model_id": "facebook/dinov2-small",
            "device": "auto",
            "change_alert_threshold": 0.5,
            "baseline_salience": 0.2,
            "alert_salience": 0.7,
        },
    )
    assert vision.name == "topos"
    # Encoder is lazy — the model is not loaded at __init__.
    assert hasattr(vision, "_encoder")
    # Default (no perception_feed) leaves the live cv2 path: no source_factory.
    assert vision._source_factory is None


def test_make_vision_seeded_feed_selects_source_factory():
    """[perception_feed].mode = "seeded" supplies a deterministic source_factory
    and forces capture on (unified-perception-feed)."""
    from kaine.modules.vision.feed import SeededProceduralSource

    bus = _bus()
    vision = make_vision(
        bus,
        {
            "encoder_model_id": "facebook/dinov2-small",
            "capture_width": 64,
            "capture_height": 48,
            "perception_feed": {
                "mode": "seeded",
                "seed": 5,
                "video": {"surprise_interval": 20, "surprise_strength": 0.5},
            },
        },
    )
    assert vision._capture_enabled is True
    factory = vision._source_factory
    assert factory is not None
    src = factory(0, width=64, height=48)
    assert isinstance(src, SeededProceduralSource)
    assert src.schedule.seed == 5
    assert src.schedule.width == 64 and src.schedule.height == 48
    assert src.schedule.surprise_interval == 20
    assert src.schedule.surprise_strength == 0.5


def test_make_vision_live_mode_forces_capture_on():
    """mode = "live" turns the real camera path on (replaces old 'camera')."""
    bus = _bus()
    vision = make_vision(
        bus,
        {
            "encoder_model_id": "facebook/dinov2-small",
            "perception_feed": {"mode": "live"},
        },
    )
    assert vision._capture_enabled is True
    # Live mode uses the real cv2 path — no deterministic source injected.
    assert vision._source_factory is None


def test_make_vision_off_feed_keeps_camera_path():
    """mode = "off" leaves capture disabled and no deterministic source."""
    bus = _bus()
    vision = make_vision(
        bus,
        {
            "encoder_model_id": "facebook/dinov2-small",
            "perception_feed": {"mode": "off"},
        },
    )
    assert vision._capture_enabled is False
    assert vision._source_factory is None


def test_make_vision_rejects_bad_feed_mode():
    bus = _bus()
    with pytest.raises(ValueError):
        make_vision(
            bus,
            {
                "encoder_model_id": "facebook/dinov2-small",
                "perception_feed": {"mode": "bogus"},
            },
        )


def test_make_vision_foveation_off_by_default():
    """No [topos].foveation key → foveation stays off (single whole-frame encode)."""
    bus = _bus()
    vision = make_vision(bus, {"encoder_model_id": "facebook/dinov2-small"})
    assert vision.foveation_enabled is False


def test_make_vision_foveation_threads_config():
    """[topos].foveation = true plus knobs flow through to the module."""
    bus = _bus()
    vision = make_vision(
        bus,
        {
            # Foveation is a per-frame spatial path — it requires the per-frame
            # (clip_len=1) DINOv2 fallback, not the temporally-native default.
            "encoder_backend": "dinov2",
            "encoder_model_id": "facebook/dinov2-small",
            "foveation": True,
            "foveation_grid": [8, 10],
            "foveation_hysteresis": 0.25,
            "foveation_arousal_size_min": 0.1,
            "foveation_arousal_size_max": 0.6,
            "peripheral_width": 256,
            "peripheral_height": 144,
            "foveal_size": 196,
        },
    )
    assert vision.foveation_enabled is True
    assert vision._saliency.grid == (8, 10)
    assert vision._foveation_hysteresis == 0.25
    assert vision._foveation_size_range == (0.1, 0.6)
    assert vision._peripheral_size == (256, 144)
    assert vision._foveal_size == (196, 196)


def test_make_vision_screen_native_grab_detects_and_passes_through(monkeypatch):
    """[perception_feed.screen].native builds a native-passthrough source at the
    detected resolution; the ffmpeg command carries no scale filter."""
    import kaine.modules.vision.screen as screen_mod

    monkeypatch.setattr(screen_mod, "detect_screen_size", lambda target: (2560, 1440))
    bus = _bus()
    vision = make_vision(
        bus,
        {
            "encoder_model_id": "facebook/dinov2-small",
            "capture_width": 640,
            "capture_height": 480,
            "perception_feed": {
                "mode": "screen",
                "screen": {"target": "fullscreen", "native": True},
            },
        },
    )
    src = vision._source_factory(0, width=640, height=480)
    assert src._native is True
    assert (src._width, src._height) == (2560, 1440)  # detected, not configured
    assert not any(a.startswith("scale=") for a in src.command())


def test_make_planning_from_config():
    pytest.importorskip("pymdp")
    pytest.importorskip("jax")
    bus = _bus()
    planning = make_planning(
        bus,
        {
            "factors": 4,
            "max_states_per_factor": 4,
            "actions": 4,
            "planning_horizon": 1,
            "efe_timeout_ms": 250,
            "baseline_salience": 0.4,
            "alert_salience": 0.8,
        },
    )
    assert planning.name == "nous"


def test_make_planning_rejects_oversized_envelope():
    from kaine.boot import ConfigurationError

    bus = _bus()
    with pytest.raises(ConfigurationError):
        make_planning(
            bus,
            {
                "factors": 16,
                "max_states_per_factor": 16,
                "actions": 16,
                "planning_horizon": 4,
            },
        )


def test_make_episodic_memory_from_config_does_not_connect_qdrant():
    bus = _bus()
    episodic_memory = make_episodic_memory(
        bus,
        {
            "backend": "inmemory",  # avoid Qdrant connect at construction
            "collection_prefix": "mnemos_",
            "short_term_capacity": 128,
            "recall_top_k": 5,
            "qdrant": {"host": "127.0.0.1", "port": 6533},
            "baseline_salience": 0.15,
            "alert_salience": 0.6,
        },
    )
    assert episodic_memory.name == "mnemos"


def test_make_episodic_memory_rejects_embedder_model_id():
    bus = _bus()
    with pytest.raises(ConfigurationError) as exc:
        make_episodic_memory(
            bus,
            {
                "backend": "inmemory",
                "collection_prefix": "mnemos_",
                "short_term_capacity": 128,
                "recall_top_k": 5,
                "embedder_model_id": "sentence-transformers/all-mpnet-base-v2",
            },
        )
    assert "[embedding].model_id" in str(exc.value)


def test_make_episodic_memory_rejects_device():
    bus = _bus()
    with pytest.raises(ConfigurationError) as exc:
        make_episodic_memory(
            bus,
            {
                "backend": "inmemory",
                "collection_prefix": "mnemos_",
                "short_term_capacity": 128,
                "recall_top_k": 5,
                "device": "cpu",
            },
        )
    assert "[embedding].device" in str(exc.value)


def test_make_self_model_from_config(tmp_path):
    bus = _bus()
    self_model = make_self_model(
        bus,
        {
            "persistence_path": str(tmp_path / "self_model.json"),
            "drift_window": 100,
            "drift_threshold": 0.6,
            "save_interval_s": 30.0,
            "internal_speech_stream": "lingua.internal",
            "identity_history_cap": 256,
            "baseline_salience": 0.05,
            "alert_salience": 0.7,
        },
    )
    assert self_model.name == "eidolon"


def test_make_affect_from_config_builds_baseline():
    bus = _bus()
    affect = make_affect(
        bus,
        {
            "baseline_valence": 0.0,
            "baseline_arousal": 0.3,
            "baseline_dominance": 0.0,
            "drift_rate_per_s": 0.05,
            "publish_interval_s": 1.0,
            "baseline_salience": 0.1,
            "alert_salience": 0.7,
        },
    )
    assert affect.name == "thymos"


def test_make_affect_tolerates_legacy_coupling_max_rate_key(caplog):
    """A stale [thymos.coupling].coupling_max_rate_per_s key is ignored with a warning.

    The DriftSafeguard it backed was removed (thymos-emergent-affect-coupling);
    existing local configs that still carry the key must not break boot.
    """
    bus = _bus()
    with caplog.at_level(logging.WARNING):
        affect = make_affect(
            bus,
            {
                "coupling": {
                    "enabled": True,
                    "coupling_base": 0.05,
                    "decay_s": 8.0,
                    "coupling_max_rate_per_s": 0.30,  # legacy, must be ignored
                },
            },
        )
    assert affect.name == "thymos"
    assert affect._coupling.enabled is True
    assert affect._coupling.decay_s == 8.0
    assert not hasattr(affect._coupling, "coupling_max_rate_per_s")
    assert "[thymos.coupling].coupling_max_rate_per_s is retired" in caplog.text


def test_make_affect_ignores_retired_social_drive_time_scale(caplog):
    """A stale [thymos].social_drive_time_scale_s key is ignored with a warning."""
    with caplog.at_level(logging.WARNING):
        affect = make_affect(
            _bus(),
            {
                "publish_interval_s": 1.0,
                "social_drive_time_scale_s": 600.0,
            },
        )
    assert affect.name == "thymos"
    assert not hasattr(affect, "_social_drive_time_scale_s")
    assert "[thymos].social_drive_time_scale_s is retired" in caplog.text


def test_make_affect_rejects_truly_unknown_coupling_key():
    """A genuinely unknown coupling key still raises (tolerance is legacy-only)."""
    bus = _bus()
    with pytest.raises(ValueError):
        make_affect(bus, {"coupling": {"bogus_key": 1.0}})


def test_make_effectors_with_empty_whitelist(tmp_path):
    bus = _bus()
    effectors = make_effectors(
        bus,
        {
            "sandbox_path": str(tmp_path / "praxis"),
            "audit_log_path": str(tmp_path / "audit.log"),
            "shell_whitelist": {},
            "baseline_salience": 0.3,
            "alert_salience": 0.7,
        },
    )
    assert effectors.name == "praxis"


def test_make_effectors_translates_shell_whitelist_entries(tmp_path):
    bus = _bus()
    effectors = make_effectors(
        bus,
        {
            "sandbox_path": str(tmp_path / "praxis"),
            "audit_log_path": str(tmp_path / "audit.log"),
            "shell_whitelist": {
                "echo": {
                    "arg_patterns": ["[A-Za-z0-9]+"],
                    "timeout_s": 2.0,
                    "description": "echo a token",
                },
            },
        },
    )
    assert effectors.name == "praxis"
    # The shell effector should have a non-empty whitelist now.
    shell = effectors._effectors["shell"]
    assert "echo" in shell._whitelist._entries


def test_make_language_from_config(tmp_path):
    bus = _bus()
    language = make_language(
        bus,
        {
            "chat_url": "http://127.0.0.1:11434/v1",
            "model_id": "kaineone/Qwen3.5-4B-abliterated-GGUF",
            "temperature": 0.7,
            "max_tokens": 512,
            "request_timeout_s": 60.0,
            "intent_log_path": str(tmp_path / "intent.jsonl"),
        },
    )
    assert language.name == "lingua"


def test_make_audition_from_config():
    bus = _bus()
    a = make_audition(
        bus,
        {
            "speaches_url": "http://127.0.0.1:8000",
            "stt_model": "Systran/faster-distil-whisper-small.en",
            "emotion_model_id": "emotion2vec/emotion2vec_plus_base",
            "request_timeout_s": 60.0,
        },
    )
    assert a.name == "audition"
    # No perception_feed → live mic path, no deterministic stream factory.
    assert a._stream_factory is None
    assert a.general_audition is False  # off by default


def test_make_audition_general_audition_threads_config():
    bus = _bus()
    a = make_audition(
        bus,
        {
            "stt_model": "fake",
            "general_audition": True,
            "arousal_window_min": 0.2,
            "arousal_window_max": 0.9,
            "acoustic_change_alert_threshold": 0.4,
            "capture_enabled": True,
            "vad_backend": "rms",
        },
    )
    assert a.general_audition is True
    assert a._arousal_window_range == (0.2, 0.9)
    assert a._acoustic_change_alert_threshold == 0.4
    assert a._acoustic_encoder is not None
    # Capture switches to continuous windows so non-speech is heard, not gated.
    assert a._live_mic is not None
    assert a._live_mic._cfg.continuous_capture is True


def test_make_audition_seeded_feed_selects_stream_factory():
    """[perception_feed].mode = "seeded" supplies a deterministic _AudioStream
    factory and forces capture on (unified-perception-feed)."""
    from kaine.modules.audition.feed import SeededProceduralAudioStream

    bus = _bus()
    a = make_audition(
        bus,
        {
            "speaches_url": "http://127.0.0.1:8000",
            "capture_sample_rate": 16000,
            "capture_channels": 1,
            "vad_frame_ms": 30,
            "perception_feed": {
                "mode": "seeded",
                "seed": 9,
                "video": {"surprise_interval": 11},
                "audio": {"base_strength": 0.2, "surprise_strength": 0.6},
            },
        },
    )
    assert a._capture_enabled is True
    factory = a._stream_factory
    assert factory is not None
    captured: list[bytes] = []
    stream = factory(
        device=None,
        sample_rate=16000,
        channels=1,
        frames_per_block=480,
        callback=captured.append,
    )
    assert isinstance(stream, SeededProceduralAudioStream)
    assert stream.schedule.seed == 9
    # The audio surprise cadence is the SHARED [perception_feed.video].interval.
    assert stream.schedule.surprise_interval == 11
    assert stream.schedule.base_strength == 0.2
    # The factory wired the callback through — synthesis lands in our list.
    stream.pcm_at(0)  # pure-function path is independent of the producer thread


def test_make_audition_live_mode_forces_capture_on():
    """mode = "live" turns the real mic path on (no deterministic stream)."""
    bus = _bus()
    a = make_audition(
        bus,
        {"speaches_url": "http://127.0.0.1:8000", "perception_feed": {"mode": "live"}},
    )
    assert a._capture_enabled is True
    assert a._stream_factory is None


def test_make_audition_rejects_bad_feed_mode():
    bus = _bus()
    with pytest.raises(ValueError):
        make_audition(
            bus,
            {
                "speaches_url": "http://127.0.0.1:8000",
                "perception_feed": {"mode": "bogus"},
            },
        )


def test_make_vocal_from_config(tmp_path):
    bus = _bus()
    a = make_vocal(
        bus,
        {
            "chatterbox_url": "http://127.0.0.1:8883",
            "voice_mode": "predefined",
            "output_format": "wav",
            "sink_path": str(tmp_path / "vox"),
            "baseline_temperature": 0.7,
            "baseline_exaggeration": 0.5,
            "baseline_cfg_weight": 0.5,
            "request_timeout_s": 120.0,
        },
    )
    assert a.name == "vox"


def test_make_social_cognition_from_config():
    bus = _bus()
    emp = make_social_cognition(
        bus,
        {
            "backend": "inmemory",
            "collection": "empatheia_agents",
            "speaker_label": "operator",
            "deviation_threshold": 0.5,
            "baseline_salience": 0.15,
            "alert_salience": 0.6,
        },
    )
    assert emp.name == "empatheia"


def test_make_social_cognition_rejects_unknown_keys():
    bus = _bus()
    import pytest

    with pytest.raises(ValueError, match="unknown config keys"):
        make_social_cognition(bus, {"backend": "inmemory", "bogus_key": True})


def test_make_world_model_from_config():
    bus = _bus()
    world_model = make_world_model(
        bus,
        {
            "backend": "fake",
            "training_enabled": False,
            "training_device": "cpu",
            "trajectory_buffer_size": 256,
            "rollout_horizon": 6,
            "salience": {"baseline": 0.1, "alert": 0.7},
            "world_model": {"deter_dim": 32, "stoch_dim": 8},
        },
    )
    assert world_model.name == "phantasia"


def test_make_world_model_rejects_unknown_keys():
    bus = _bus()
    with pytest.raises(ValueError, match="unknown config keys"):
        make_world_model(bus, {"backend": "fake", "bogus_key": True})


def test_make_sleep_without_deps(tmp_path):
    bus = _bus()
    sleep = make_sleep(
        bus,
        {
            "interval_seconds": 3600.0,
            "max_deferral_seconds": 600.0,
            "per_defer_seconds": 60.0,
            "voice_alignment": {
                "intent_log_path": str(tmp_path / "intent.jsonl"),
                "adapter_output_dir": str(tmp_path / "adapters"),
                "model_id": "kaineone/Qwen3.5-4B-abliterated-GGUF",
            },
        },
    )
    assert sleep.name == "hypnos"


def test_make_sleep_ignores_retired_planning_step_burst(tmp_path, caplog):
    """A stale [hypnos].nous_step_burst key is ignored with a warning."""
    with caplog.at_level(logging.WARNING):
        sleep = make_sleep(
            _bus(),
            {
                "interval_seconds": 3600.0,
                "nous_step_burst": 200,
                "voice_alignment": {
                    "intent_log_path": str(tmp_path / "intent.jsonl"),
                    "adapter_output_dir": str(tmp_path / "adapters"),
                    "model_id": "kaineone/Qwen3.5-4B-abliterated-GGUF",
                },
            },
        )
    assert sleep.name == "hypnos"
    assert not hasattr(sleep, "_planning_step_burst")
    assert "[hypnos].nous_step_burst is retired" in caplog.text


def test_make_sleep_still_rejects_unknown_key():
    """A typoed sleep key is still rejected."""
    with pytest.raises(ValueError, match="unknown config keys"):
        make_sleep(_bus(), {"nous_step_bursts": 200})


def test_build_registry_respects_disabled_toggles():
    bus = _bus()
    registry = build_registry(
        bus,
        {
            "modules": {"soma": True, "chronos": False, "topos": False},
            "soma": {
                "read_interval_s": 1.0,
                "cycle_latency_target_ms": 300.0,
                "baseline_salience": 0.1,
                "alert_salience": 0.7,
            },
        },
    )
    assert "soma" in registry
    assert "chronos" not in registry
    assert "topos" not in registry


def test_build_registry_constructs_sleep_last():
    bus = _bus()
    registry = build_registry(
        bus,
        {
            "modules": {
                "mnemos": True,
                "thymos": True,
                "hypnos": True,
            },
            "mnemos": {
                "backend": "inmemory",
                "collection_prefix": "mnemos_",
                "short_term_capacity": 128,
                "recall_top_k": 5,
                "qdrant": {"host": "127.0.0.1", "port": 6533},
            },
            "thymos": {
                "baseline_valence": 0.0,
                "baseline_arousal": 0.3,
                "baseline_dominance": 0.0,
                "drift_rate_per_s": 0.05,
                "publish_interval_s": 1.0,
            },
            "hypnos": {
                "interval_seconds": 3600.0,
                "max_deferral_seconds": 600.0,
            },
        },
    )
    assert set(["mnemos", "thymos", "hypnos"]).issubset(set(registry._modules))
    sleep = registry.get("hypnos")
    # the sleep module should have been wired to the constructed episodic memory module and the affect module.
    assert sleep._episodic_memory is registry.get("mnemos")
    assert sleep._affect is registry.get("thymos")


def test_factory_rejects_unknown_config_key():
    bus = _bus()
    with pytest.raises(ValueError, match="unknown config keys"):
        make_interoception(bus, {"baseline_salience": 0.1, "bogus_key": True})


def test_simple_factories_covers_expected_modules():
    assert set(SIMPLE_FACTORIES) == {
        "soma",
        "chronos",
        "topos",
        "nous",
        "mnemos",
        "eidolon",
        "thymos",
        "praxis",
        "lingua",
        "audition",
        "vox",
        "mundus",
        "perception",
        "empatheia",
        "phantasia",
    }
    # the sleep module is intentionally outside SIMPLE_FACTORIES (interdependency
    # wiring happens in build_registry's second pass).



def test_committed_config_ships_all_modules_disabled():
    """Guard: the COMMITTED config/kaine.toml must keep every module toggle off
    (operator-supervised first boot — see the first-boot toggle convention).

    Reads the committed file via git rather than the working copy, so it is
    robust to a developer's local edits — enabling modules locally to actually
    run KAINE is expected and must not trip this guard; committing an all-on
    config must."""
    import subprocess
    import tomllib
    from pathlib import Path

    root = Path(__file__).parent.parent
    blob = ""
    try:
        blob = subprocess.run(
            ["git", "show", "HEAD:config/kaine.toml"],
            capture_output=True,
            text=True,
            cwd=root,
            check=True,
        ).stdout
    except Exception:
        pytest.skip("git not available to read the committed config")
    parsed = tomllib.loads(blob)
    modules = parsed.get("modules", {})
    enabled = sorted(name for name, on in modules.items() if on)
    assert enabled == [], f"committed config must ship all modules off; enabled: {enabled}"

    # And building from an all-off config yields an empty registry.
    assert len(build_registry(_bus(), {"modules": {}})) == 0


def test_shipped_language_model_id_is_published_kaine_organ():
    """The shipped [lingua].model_id is the PUBLISHED KAINE organ's served alias.

    The wizard downloads, and scripts/model-server-bootstrap.sh serves, the organ
    under this exact alias — so the alias is part of the served-name contract, not
    free text. Reads the working-copy file (matches test_shipped_lingua_organ_is_
    abliterated; a local operator scale-up still satisfies the kaineone/ prefix)."""
    import tomllib
    from pathlib import Path

    root = Path(__file__).parent.parent
    raw = tomllib.loads((root / "config" / "kaine.toml").read_text())
    model_id = raw["lingua"]["model_id"]
    assert model_id == "kaineone/Qwen3.5-4B-abliterated-GGUF", (
        "shipped [lingua].model_id must be the published KAINE organ's served "
        f"alias; got {model_id!r}"
    )


def test_shipped_config_ships_spot_disabled():
    """Guard: the shipped config/kaine.toml must keep the supervisor off.

    Reads the working-copy file directly (the [spot] section may not yet be in
    HEAD), matching the all-off first-boot convention for module toggles."""
    import tomllib
    from pathlib import Path

    root = Path(__file__).parent.parent
    config = tomllib.loads((root / "config" / "kaine.toml").read_text())
    spot = config.get("spot", {})
    assert spot.get("enabled", False) is False, (
        "shipped config must ship [spot].enabled = false (operator-supervised first boot)"
    )
    # [spot.incident_log] ships enabled = true, but it is dormant because the supervisor
    # itself ships disabled — turning the supervisor on later gives the operator the
    # durable incident log automatically.
    incident_log = spot.get("incident_log", {})
    assert incident_log.get("enabled", False) is True, (
        "shipped config must ship [spot.incident_log].enabled = true (dormant "
        "while [spot].enabled = false)"
    )


def test_shipped_config_research_submission_disabled():
    """Guard: the shipped config/kaine.toml must keep research_submission off.

    The [research_submission] section ships disabled with an empty recipient
    so no operator accidentally auto-sends telemetry on first run."""
    import tomllib
    from pathlib import Path

    root = Path(__file__).parent.parent
    config = tomllib.loads((root / "config" / "kaine.toml").read_text())
    rs = config.get("research_submission", {})
    assert rs.get("enabled", False) is False, (
        "shipped config must ship [research_submission].enabled = false"
    )
    assert rs.get("recipient", "") == "", (
        "shipped config must ship [research_submission].recipient = '' (empty)"
    )


def test_make_language_accepts_outcome_reply_window(tmp_path):
    # the language module factory should accept cycle-specific config keys it does not consume.
    language = make_language(
        _bus(),
        {"intent_log_path": str(tmp_path / "i.jsonl"), "outcome_reply_window_s": 45},
    )
    assert language is not None


def test_make_language_api_key_from_env(monkeypatch, tmp_path):
    # The model-server key may come from the env (kept out of config files).
    monkeypatch.setenv("KAINE_MODEL_SERVER_API_KEY", "sk-env")
    language = make_language(_bus(), {"intent_log_path": str(tmp_path / "i.jsonl")})
    assert language._chat_client._api_key == "sk-env"


def test_make_language_api_key_from_config_wins_over_env(monkeypatch, tmp_path):
    monkeypatch.setenv("KAINE_MODEL_SERVER_API_KEY", "sk-env")
    language = make_language(
        _bus(),
        {"api_key": "sk-cfg", "intent_log_path": str(tmp_path / "i.jsonl")},
    )
    assert language._chat_client._api_key == "sk-cfg"


def test_wire_self_model_capabilities_injects_effectors_whitelist(tmp_path):
    """_wire_eidolon_capabilities feeds the effectors module's effector whitelist into
    the self-model module's self-inference engine, so the self-model's capability_map reflects
    what the entity can execute (eidolon-self-inference spec)."""
    from kaine.boot import _wire_self_model_capabilities
    from kaine.modules.registry import ModuleRegistry
    from kaine.modules.self_model.document import SelfModelDocument

    bus = _bus()
    effectors = make_effectors(
        bus,
        {
            "sandbox_path": str(tmp_path / "praxis"),
            "audit_log_path": str(tmp_path / "audit.log"),
            "enabled_effectors": ["file_write", "notify"],
            "shell_whitelist": {},
            "baseline_salience": 0.3,
            "alert_salience": 0.7,
        },
    )
    self_model = make_self_model(
        bus,
        {
            "persistence_path": str(tmp_path / "self_model.json"),
            "self_inference": {"enabled": True},
        },
    )
    registry = ModuleRegistry()
    registry.register(effectors)
    registry.register(self_model)

    _wire_self_model_capabilities(registry)

    model = self_model.self_inference.maintenance_cycle_end(SelfModelDocument())
    assert model.capability_map.get("effectors") == ["file_write", "notify"]


# ---------------------------------------------------------------------------
# Supervisor recovery re-wiring (performance-test-coverage)
# ---------------------------------------------------------------------------


def test_rewire_module_restores_self_hearing_gate():
    """After the supervisor rebuilds a module, rewire_module must re-inject the shared
    SpeakingGate between the vocal module and the audition module."""
    from kaine.modules.registry import ModuleRegistry
    from kaine.modules.vocal.coordination import SpeakingGate

    bus = _bus()
    vocal = make_vocal(
        bus,
        {
            "chatterbox_url": "http://127.0.0.1:8883",
            "voice_mode": "predefined",
            "output_format": "wav",
            "sink_path": "/tmp/vox",
        },
    )
    audition = make_audition(bus, {"speaches_url": "http://127.0.0.1:8000"})
    registry = ModuleRegistry()
    registry.register(vocal)
    registry.register(audition)

    rewire_module(registry, "audition", {})
    original_gate = audition._speaking_gate
    assert isinstance(original_gate, SpeakingGate)
    assert vocal._speaking_gate is original_gate

    # Simulate the supervisor rebuilding audition with a fresh instance.
    new_audition = make_audition(bus, {"speaches_url": "http://127.0.0.1:8000"})
    registry.replace("audition", new_audition)
    rewire_module(registry, "audition", {})

    assert new_audition._speaking_gate is original_gate
    assert vocal._speaking_gate is original_gate


def test_rewire_module_reseeds_self_model_whitelist(tmp_path):
    """After the supervisor rebuilds the self-model module, rewire_module must re-inject the effectors module's
    effector whitelist into the new self-inference engine."""
    from kaine.modules.registry import ModuleRegistry
    from kaine.modules.self_model.document import SelfModelDocument

    bus = _bus()
    effectors = make_effectors(
        bus,
        {
            "sandbox_path": str(tmp_path / "praxis"),
            "audit_log_path": str(tmp_path / "audit.log"),
            "enabled_effectors": ["file_write", "notify"],
            "shell_whitelist": {},
        },
    )
    self_model = make_self_model(
        bus,
        {
            "persistence_path": str(tmp_path / "self_model.json"),
            "self_inference": {"enabled": True},
        },
    )
    registry = ModuleRegistry()
    registry.register(effectors)
    registry.register(self_model)

    rewire_module(registry, "eidolon", {})
    model = self_model.self_inference.maintenance_cycle_end(SelfModelDocument())
    assert model.capability_map.get("effectors") == ["file_write", "notify"]

    # Simulate the supervisor rebuilding the self-model module.
    new_self_model = make_self_model(
        bus,
        {
            "persistence_path": str(tmp_path / "self_model2.json"),
            "self_inference": {"enabled": True},
        },
    )
    registry.replace("eidolon", new_self_model)
    rewire_module(registry, "eidolon", {})

    new_model = new_self_model.self_inference.maintenance_cycle_end(SelfModelDocument())
    assert new_model.capability_map.get("effectors") == ["file_write", "notify"]


def test_rewire_module_leaves_oscillators_untouched():
    """rewire_module never builds or replaces oscillators: a restarted module
    receives its predecessor's oscillator from the supervisor's heavy restart path, and
    every other module keeps its own (oscillator-continuity-on-restart; the
    the supervisor hand-over is covered in tests/test_oscillator_continuity.py)."""
    from kaine.modules.registry import ModuleRegistry

    bus = _bus()
    section = {"read_interval_s": 1.0, "cycle_latency_target_ms": 300.0}
    interoception = make_interoception(bus, dict(section))
    registry = ModuleRegistry()
    registry.register(interoception)
    kaine_config = {
        "oscillator": {"enabled": True, "population_size": 16, "plv_window": 10}
    }

    existing = object()
    interoception.attach_oscillator(existing)
    rewire_module(registry, "soma", kaine_config)
    assert interoception.oscillator is existing

    # A freshly rebuilt instance swapped in without the supervisor's hand-over is not
    # given an oscillator by rewire_module.
    new_interoception = make_interoception(bus, dict(section))
    registry.replace("soma", new_interoception)
    rewire_module(registry, "soma", kaine_config)
    assert new_interoception.oscillator is None


# ---------------------------------------------------------------------------
# State-encryption boot wiring (performance-test-coverage)
# ---------------------------------------------------------------------------


def test_build_registry_encryption_enabled_fail_closed_without_key(
    monkeypatch,
):
    """build_registry refuses to boot when state encryption is enabled but no
    key is resolvable."""
    monkeypatch.delenv("KAINE_STATE_KEY", raising=False)
    monkeypatch.setattr("kaine.security.crypto._load_key_from_keyring", lambda: None)
    bus = _bus()
    with pytest.raises(CryptoConfigError):
        build_registry(
            bus,
            {
                "modules": {},
                "security": {"state_encryption": {"enabled": True}},
            },
        )


def test_build_registry_encryption_enabled_installs_encryptor(monkeypatch, tmp_path):
    """When a key is present and encryption is enabled, build_registry installs
    an active encryptor as the process-global."""
    import base64
    import os

    key = base64.b64encode(os.urandom(32)).decode("ascii")
    monkeypatch.setenv("KAINE_STATE_KEY", key)
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))
    bus = _bus()
    try:
        build_registry(
            bus,
            {
                "modules": {},
                "security": {"state_encryption": {"enabled": True}},
            },
        )
        assert get_state_encryptor().enabled is True
    finally:
        set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))


def test_make_audition_uses_the_entity_clock():
    clk = EntityClock()
    audition = make_audition(_bus(), {}, entity_clock=clk)
    assert audition._clock is clk
