# SPDX-License-Identifier: LicenseRef-CAL-0.2
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


import pytest

from kaine.boot import (
    SIMPLE_FACTORIES,
    build_registry,
    make_audition,
    make_vox,
    make_chronos,
    make_eidolon,
    make_empatheia,
    make_hypnos,
    make_lingua,
    make_mnemos,
    make_nous,
    make_phantasia,
    make_praxis,
    make_soma,
    make_thymos,
    make_topos,
    MetricsCollector,
)
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig


def _bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    return AsyncBus(BusConfig(password="x", audit_required=False), client=client)


def test_make_soma_from_config():
    bus = _bus()
    soma = make_soma(
        bus,
        {
            "read_interval_s": 1.0,
            "cycle_latency_target_ms": 300.0,
            "baseline_salience": 0.1,
            "alert_salience": 0.7,
        },
    )
    assert soma.name == "soma"


def test_make_soma_wires_cycle_latency_window():
    # The cycle_latency_window key must size the SystemMetricsReader's
    # latency-averaging window — not be silently dropped.
    bus = _bus()
    soma = make_soma(bus, {"cycle_latency_window": 17})
    assert soma._reader._latency_samples.maxlen == 17


def test_make_chronos_from_config():
    bus = _bus()
    chronos = make_chronos(
        bus,
        {
            "cfc_units": 32,
            "baseline_salience": 0.1,
            "alert_salience": 0.7,
            "anomaly_alert_threshold": 3.0,
        },
    )
    assert chronos.name == "chronos"


def test_make_chronos_wires_anomaly_and_rumination_windows():
    # The anomaly/rumination window knobs must reach the default detectors
    # rather than being accepted-then-dropped.
    bus = _bus()
    chronos = make_chronos(
        bus,
        {
            "anomaly_window": 21,
            "rumination_window": 13,
            "rumination_threshold": 7,
            "rumination_bucket_resolution": 0.5,
        },
    )
    assert chronos._anomaly.window == 21
    assert chronos._rumination.window == 13
    assert chronos._rumination.threshold == 7
    assert chronos._rumination._resolution == 0.5


def test_make_topos_from_config_does_not_load_transformers():
    bus = _bus()
    topos = make_topos(
        bus,
        {
            "encoder_model_id": "facebook/dinov2-small",
            "device": "auto",
            "change_alert_threshold": 0.5,
            "baseline_salience": 0.2,
            "alert_salience": 0.7,
        },
    )
    assert topos.name == "topos"
    # Encoder is lazy — the model is not loaded at __init__.
    assert hasattr(topos, "_encoder")
    # Default (no perception_feed) leaves the live cv2 path: no source_factory.
    assert topos._source_factory is None


def test_make_topos_seeded_feed_selects_source_factory():
    """[perception_feed].mode = "seeded" supplies a deterministic source_factory
    and forces capture on (unified-perception-feed)."""
    from kaine.modules.topos.feed import SeededProceduralSource

    bus = _bus()
    topos = make_topos(
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
    assert topos._capture_enabled is True
    factory = topos._source_factory
    assert factory is not None
    src = factory(0, width=64, height=48)
    assert isinstance(src, SeededProceduralSource)
    assert src.schedule.seed == 5
    assert src.schedule.width == 64 and src.schedule.height == 48
    assert src.schedule.surprise_interval == 20
    assert src.schedule.surprise_strength == 0.5


def test_make_topos_live_mode_forces_capture_on():
    """mode = "live" turns the real camera path on (replaces old 'camera')."""
    bus = _bus()
    topos = make_topos(
        bus,
        {
            "encoder_model_id": "facebook/dinov2-small",
            "perception_feed": {"mode": "live"},
        },
    )
    assert topos._capture_enabled is True
    # Live mode uses the real cv2 path — no deterministic source injected.
    assert topos._source_factory is None


def test_make_topos_off_feed_keeps_camera_path():
    """mode = "off" leaves capture disabled and no deterministic source."""
    bus = _bus()
    topos = make_topos(
        bus,
        {
            "encoder_model_id": "facebook/dinov2-small",
            "perception_feed": {"mode": "off"},
        },
    )
    assert topos._capture_enabled is False
    assert topos._source_factory is None


def test_make_topos_rejects_bad_feed_mode():
    bus = _bus()
    with pytest.raises(ValueError):
        make_topos(
            bus,
            {
                "encoder_model_id": "facebook/dinov2-small",
                "perception_feed": {"mode": "bogus"},
            },
        )


def test_make_topos_foveation_off_by_default():
    """No [topos].foveation key → foveation stays off (single whole-frame encode)."""
    bus = _bus()
    topos = make_topos(bus, {"encoder_model_id": "facebook/dinov2-small"})
    assert topos.foveation_enabled is False


def test_make_topos_foveation_threads_config():
    """[topos].foveation = true plus knobs flow through to the module."""
    bus = _bus()
    topos = make_topos(
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
    assert topos.foveation_enabled is True
    assert topos._saliency.grid == (8, 10)
    assert topos._foveation_hysteresis == 0.25
    assert topos._foveation_size_range == (0.1, 0.6)
    assert topos._peripheral_size == (256, 144)
    assert topos._foveal_size == (196, 196)


def test_make_topos_screen_native_grab_detects_and_passes_through(monkeypatch):
    """[perception_feed.screen].native builds a native-passthrough source at the
    detected resolution; the ffmpeg command carries no scale filter."""
    import kaine.modules.topos.screen as screen_mod

    monkeypatch.setattr(screen_mod, "detect_screen_size", lambda target: (2560, 1440))
    bus = _bus()
    topos = make_topos(
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
    src = topos._source_factory(0, width=640, height=480)
    assert src._native is True
    assert (src._width, src._height) == (2560, 1440)  # detected, not configured
    assert not any(a.startswith("scale=") for a in src.command())


def test_make_nous_from_config():
    pytest.importorskip("pymdp")
    pytest.importorskip("jax")
    bus = _bus()
    nous = make_nous(
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
    assert nous.name == "nous"


def test_make_nous_rejects_oversized_envelope():
    from kaine.boot import ConfigurationError

    bus = _bus()
    with pytest.raises(ConfigurationError):
        make_nous(
            bus,
            {
                "factors": 16,
                "max_states_per_factor": 16,
                "actions": 16,
                "planning_horizon": 4,
            },
        )


def test_make_mnemos_from_config_does_not_connect_qdrant():
    bus = _bus()
    mnemos = make_mnemos(
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
    assert mnemos.name == "mnemos"


def test_make_mnemos_forwards_embedder_model_id():
    bus = _bus()
    mnemos = make_mnemos(
        bus,
        {
            "backend": "inmemory",
            "collection_prefix": "mnemos_",
            "short_term_capacity": 128,
            "recall_top_k": 5,
            "embedder_model_id": "sentence-transformers/all-mpnet-base-v2",
        },
    )
    # Embedder should be configured with the requested model id (model
    # weights are not loaded until initialize()).
    assert mnemos._core._embedder.model_id == "sentence-transformers/all-mpnet-base-v2"


def test_make_eidolon_from_config(tmp_path):
    bus = _bus()
    eidolon = make_eidolon(
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
    assert eidolon.name == "eidolon"


def test_make_thymos_from_config_builds_baseline():
    bus = _bus()
    thymos = make_thymos(
        bus,
        {
            "baseline_valence": 0.0,
            "baseline_arousal": 0.3,
            "baseline_dominance": 0.0,
            "drift_rate_per_s": 0.05,
            "publish_interval_s": 1.0,
            "baseline_salience": 0.1,
            "alert_salience": 0.7,
            "social_drive_time_scale_s": 600.0,
        },
    )
    assert thymos.name == "thymos"


def test_make_thymos_tolerates_legacy_coupling_max_rate_key():
    """A stale [thymos.coupling].coupling_max_rate_per_s key is ignored, not an error.

    The DriftSafeguard it backed was removed (thymos-emergent-affect-coupling);
    existing local configs that still carry the key must not break boot.
    """
    bus = _bus()
    thymos = make_thymos(
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
    assert thymos.name == "thymos"
    assert thymos._coupling.enabled is True
    assert thymos._coupling.decay_s == 8.0
    assert not hasattr(thymos._coupling, "coupling_max_rate_per_s")


def test_make_thymos_rejects_truly_unknown_coupling_key():
    """A genuinely unknown coupling key still raises (tolerance is legacy-only)."""
    bus = _bus()
    with pytest.raises(ValueError):
        make_thymos(bus, {"coupling": {"bogus_key": 1.0}})


def test_make_praxis_with_empty_whitelist(tmp_path):
    bus = _bus()
    praxis = make_praxis(
        bus,
        {
            "sandbox_path": str(tmp_path / "praxis"),
            "audit_log_path": str(tmp_path / "audit.log"),
            "shell_whitelist": {},
            "baseline_salience": 0.3,
            "alert_salience": 0.7,
        },
    )
    assert praxis.name == "praxis"


def test_make_praxis_translates_shell_whitelist_entries(tmp_path):
    bus = _bus()
    praxis = make_praxis(
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
    assert praxis.name == "praxis"
    # The shell effector should have a non-empty whitelist now.
    shell = praxis._effectors["shell"]
    assert "echo" in shell._whitelist._entries


def test_make_lingua_from_config(tmp_path):
    bus = _bus()
    lingua = make_lingua(
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
    assert lingua.name == "lingua"


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


def test_make_vox_from_config(tmp_path):
    bus = _bus()
    a = make_vox(
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


def test_make_empatheia_from_config():
    bus = _bus()
    emp = make_empatheia(
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


def test_make_empatheia_rejects_unknown_keys():
    bus = _bus()
    import pytest

    with pytest.raises(ValueError, match="unknown config keys"):
        make_empatheia(bus, {"backend": "inmemory", "bogus_key": True})


def test_make_phantasia_from_config():
    bus = _bus()
    phantasia = make_phantasia(
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
    assert phantasia.name == "phantasia"


def test_make_phantasia_rejects_unknown_keys():
    bus = _bus()
    with pytest.raises(ValueError, match="unknown config keys"):
        make_phantasia(bus, {"backend": "fake", "bogus_key": True})


def test_make_hypnos_without_deps(tmp_path):
    bus = _bus()
    hypnos = make_hypnos(
        bus,
        {
            "interval_seconds": 3600.0,
            "max_deferral_seconds": 600.0,
            "per_defer_seconds": 60.0,
            "nous_step_burst": 200,
            "voice_alignment": {
                "intent_log_path": str(tmp_path / "intent.jsonl"),
                "adapter_output_dir": str(tmp_path / "adapters"),
                "model_id": "kaineone/Qwen3.5-4B-abliterated-GGUF",
            },
        },
    )
    assert hypnos.name == "hypnos"


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


def test_build_registry_constructs_hypnos_last():
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
                "social_drive_time_scale_s": 600.0,
            },
            "hypnos": {
                "interval_seconds": 3600.0,
                "max_deferral_seconds": 600.0,
            },
        },
    )
    assert set(["mnemos", "thymos", "hypnos"]).issubset(set(registry._modules))
    hypnos = registry.get("hypnos")
    # Hypnos should have been wired to the constructed mnemos and thymos.
    assert hypnos._mnemos is registry.get("mnemos")
    assert hypnos._thymos is registry.get("thymos")


def test_factory_rejects_unknown_config_key():
    bus = _bus()
    with pytest.raises(ValueError, match="unknown config keys"):
        make_soma(bus, {"baseline_salience": 0.1, "bogus_key": True})


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
    # Hypnos is intentionally outside SIMPLE_FACTORIES (interdependency
    # wiring happens in build_registry's second pass).


def test_metrics_collector_snapshots_live_cycle_values():
    class FakeCycle:
        tick_index = 42
        processing_rate_hz = 3.333
        experiential_rate_hz = 1.0
        error_counts: dict[str, int] = {}

    class FakeRegistry:
        def all_modules(self):
            class M:
                name = "soma"

            return iter([M()])

    collector = MetricsCollector(FakeCycle(), FakeRegistry())
    snap = collector.snapshot()
    assert snap["tick_index"] == 42
    assert snap["processing_rate_hz"] == 3.333
    assert snap["modules"] == ["soma"]


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
    assert enabled == [], (
        f"committed config must ship all modules off; enabled: {enabled}"
    )

    # And building from an all-off config yields an empty registry.
    assert len(build_registry(_bus(), {"modules": {}})) == 0


def test_shipped_lingua_model_id_is_published_kaine_organ():
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
    """Guard: the shipped config/kaine.toml must keep the Spot supervisor off.

    Reads the working-copy file directly (the [spot] section may not yet be in
    HEAD), matching the all-off first-boot convention for module toggles."""
    import tomllib
    from pathlib import Path

    root = Path(__file__).parent.parent
    config = tomllib.loads((root / "config" / "kaine.toml").read_text())
    spot = config.get("spot", {})
    assert spot.get("enabled", False) is False, (
        "shipped config must ship [spot].enabled = false (operator-supervised "
        "first boot)"
    )
    # [spot.incident_log] ships enabled = true, but it is dormant because Spot
    # itself ships disabled — turning Spot on later gives the operator the
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


def test_make_lingua_api_key_from_env(monkeypatch, tmp_path):
    # The model-server key may come from the env (kept out of config files).
    monkeypatch.setenv("KAINE_MODEL_SERVER_API_KEY", "sk-env")
    lingua = make_lingua(_bus(), {"intent_log_path": str(tmp_path / "i.jsonl")})
    assert lingua._chat_client._api_key == "sk-env"


def test_make_lingua_api_key_from_config_wins_over_env(monkeypatch, tmp_path):
    monkeypatch.setenv("KAINE_MODEL_SERVER_API_KEY", "sk-env")
    lingua = make_lingua(
        _bus(),
        {"api_key": "sk-cfg", "intent_log_path": str(tmp_path / "i.jsonl")},
    )
    assert lingua._chat_client._api_key == "sk-cfg"


def test_wire_eidolon_capabilities_injects_praxis_whitelist(tmp_path):
    """_wire_eidolon_capabilities feeds the Praxis effector whitelist into
    Eidolon's self-inference engine, so the self-model's capability_map reflects
    what the entity can execute (eidolon-self-inference spec)."""
    from kaine.boot import _wire_eidolon_capabilities
    from kaine.modules.registry import ModuleRegistry
    from kaine.modules.eidolon.document import SelfModel

    bus = _bus()
    praxis = make_praxis(
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
    eidolon = make_eidolon(
        bus,
        {
            "persistence_path": str(tmp_path / "self_model.json"),
            "self_inference": {"enabled": True},
        },
    )
    registry = ModuleRegistry()
    registry.register(praxis)
    registry.register(eidolon)

    _wire_eidolon_capabilities(registry)

    model = eidolon.self_inference.maintenance_cycle_end(SelfModel())
    assert model.capability_map.get("effectors") == ["file_write", "notify"]
