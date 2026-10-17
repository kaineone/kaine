# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Construction of a :class:`~kaine.dashboard.health.prober.HealthProber` from
loaded ``config/kaine.toml`` (+ ``config/secrets.toml``)."""
from __future__ import annotations

import dataclasses
import logging
import os
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from kaine import model_paths, secrets_file
from kaine.defaults import language_section_api_key, language_section_chat_url
from kaine.storage import resolve

from .prober import DependencySpec, HealthProber
from .probes import (
    DEFAULT_CACHE_TTL_S,
    DEFAULT_PROBE_TIMEOUT_S,
    DEGRADED,
    NOT_CONFIGURED,
    planning_health_probe,
    probe_chat_llm,
    probe_chatterbox,
    probe_qdrant,
    probe_redis,
    probe_sherpa_stt,
    probe_sherpa_tts,
    probe_speaches,
    probe_state_encryption,
)

log = logging.getLogger(__name__)


async def _async_not_configured(reason: str) -> tuple[str, str]:
    """Neutral skip result for a dependency the runtime will not use."""
    return NOT_CONFIGURED, reason


async def _async_degraded(reason: str) -> tuple[str, str]:
    """Warning result for a dependency that is configured but not recognised."""
    return DEGRADED, reason


def build_dependency_specs(
    *,
    redis_cfg: dict[str, Any],
    qdrant_cfg: dict[str, Any],
    qdrant_secret_key: str | None,
    redis_password: str | None,
    language_cfg: dict[str, Any],
    audition_cfg: dict[str, Any],
    vocal_cfg: dict[str, Any],
    planning_cfg: dict[str, Any],
    state_encryption_cfg: dict[str, Any] | None = None,
) -> list[DependencySpec]:
    redis_host = str(redis_cfg.get("host", "127.0.0.1"))
    redis_port = int(redis_cfg.get("port", 6379))

    # Parity with load_bus_config: every containerized service connects via
    # KAINE_REDIS_URL (redis://[:password@]host[:port][/db]); the health probe
    # must probe the same endpoint the runtime will actually use.
    redis_url = os.environ.get("KAINE_REDIS_URL")
    if redis_url:
        parsed = urlparse(redis_url)
        redis_host = parsed.hostname or redis_host
        if parsed.port is not None:
            redis_port = int(parsed.port)
        # URL password wins when present; otherwise the env/secrets password.
        if parsed.password is not None:
            redis_password = unquote(parsed.password)

    qdrant_host = str(qdrant_cfg.get("host", "127.0.0.1"))
    qdrant_port = int(qdrant_cfg.get("port", 6333))

    chat_url = language_section_chat_url(language_cfg)
    model_id = language_cfg.get("model_id")
    chat_api_key = language_section_api_key(language_cfg)

    speaches_url = str(audition_cfg.get("speaches_url", "http://127.0.0.1:8000"))
    transcription_enabled = bool(audition_cfg.get("transcription_enabled", True))
    chatterbox_url = str(vocal_cfg.get("chatterbox_url", "http://127.0.0.1:8883"))

    audition_backend = str(audition_cfg.get("backend") or "speaches").strip().lower()
    vocal_backend = str(vocal_cfg.get("backend") or "chatterbox").strip().lower()

    def _audition_sherpa_model_dir() -> str:
        d = audition_cfg.get("sherpa_model_dir")
        if d:
            return str(d)
        return str(
            model_paths.speech_model_dir(
                audition_cfg.get("sherpa_model_id") or model_paths.DEFAULT_STT
            )
        )

    def _vocal_sherpa_model_dir() -> str:
        d = vocal_cfg.get("sherpa_model_dir")
        if d:
            return str(d)
        return str(
            model_paths.speech_model_dir(
                vocal_cfg.get("sherpa_model_id") or model_paths.DEFAULT_TTS
            )
        )

    audition_sherpa_model_id = (
        audition_cfg.get("sherpa_model_id") or model_paths.DEFAULT_STT
    )
    vocal_sherpa_model_id = vocal_cfg.get("sherpa_model_id") or model_paths.DEFAULT_TTS
    audition_sherpa_num_threads = int(audition_cfg.get("sherpa_num_threads", 2))
    vocal_sherpa_num_threads = int(vocal_cfg.get("sherpa_num_threads", 2))
    vocal_sherpa_speaker_id = int(vocal_cfg.get("sherpa_speaker_id", 0))

    # The planning module probe needs the configured backend so it checks the right engine.
    planning_backend = str(planning_cfg.get("backend", "pymdp"))

    speech_rows: list[DependencySpec] = []
    if audition_backend == "speaches":
        speech_rows.append(
            DependencySpec(
                name="Speaches (STT)",
                role="Audition",
                module="audition",
                # STT-ectomy: with transcription disabled the run never calls
                # the STT backend, so the probe reports not-configured (SKIP).
                probe=(
                    (lambda: _async_not_configured("transcription disabled"))
                    if not transcription_enabled
                    else (lambda: probe_speaches(base_url=speaches_url))
                ),
            )
        )
    elif audition_backend == "sherpa_onnx":
        speech_rows.append(
            DependencySpec(
                name="sherpa-onnx (Moonshine)",
                role="Audition",
                module="audition",
                probe=(
                    (lambda: _async_not_configured("transcription disabled"))
                    if not transcription_enabled
                    else (
                        lambda _mdir=_audition_sherpa_model_dir(),
                        _mid=audition_sherpa_model_id,
                        _nt=audition_sherpa_num_threads: probe_sherpa_stt(
                            model_dir=_mdir,
                            model_id=_mid,
                            num_threads=_nt,
                        )
                    )
                ),
            )
        )
    else:
        speech_rows.append(
            DependencySpec(
                name=f"Audition backend {audition_backend!r}",
                role="Audition",
                module="audition",
                probe=lambda: _async_degraded(
                    f"unknown [audition].backend {audition_backend!r}; expected \"speaches\" or \"sherpa_onnx\""
                ),
            )
        )

    if vocal_backend == "chatterbox":
        speech_rows.append(
            DependencySpec(
                name="Chatterbox (TTS)",
                role="Vocal",
                module="vocal",
                probe=lambda: probe_chatterbox(base_url=chatterbox_url),
            )
        )
    elif vocal_backend == "sherpa_onnx":
        speech_rows.append(
            DependencySpec(
                name="sherpa-onnx (Kokoro)",
                role="Vocal",
                module="vocal",
                probe=(
                    lambda _mdir=_vocal_sherpa_model_dir(),
                    _mid=vocal_sherpa_model_id,
                    _sid=vocal_sherpa_speaker_id,
                    _nt=vocal_sherpa_num_threads: probe_sherpa_tts(
                        model_dir=_mdir,
                        model_id=_mid,
                        speaker_id=_sid,
                        num_threads=_nt,
                    )
                ),
            )
        )
    else:
        speech_rows.append(
            DependencySpec(
                name=f"Vocal backend {vocal_backend!r}",
                role="Vocal",
                module="vocal",
                probe=lambda: _async_degraded(
                    f"unknown [vocal].backend {vocal_backend!r}; expected \"chatterbox\" or \"sherpa_onnx\""
                ),
            )
        )

    return [
        DependencySpec(
            name="Redis",
            role="bus",
            module=None,  # the bus is never "disabled"; it's foundational
            probe=lambda: probe_redis(
                host=redis_host, port=redis_port, password=redis_password
            ),
        ),
        DependencySpec(
            name="Qdrant",
            role="Episodic memory (memory)",
            module="episodic_memory",
            probe=lambda: probe_qdrant(
                host=qdrant_host, port=qdrant_port, api_key=qdrant_secret_key
            ),
        ),
        DependencySpec(
            name="Chat LLM",
            role="Language / Sleep",
            module="language",
            probe=lambda: probe_chat_llm(
                base_url=chat_url, model_id=model_id, api_key=chat_api_key
            ),
        ),
        *speech_rows,
        DependencySpec(
            name=(
                "pymdp + JAX"
                if planning_backend == "pymdp"
                else "NumPy active inference"
                if planning_backend == "numpy"
                else f"Planning backend {planning_backend!r}"
            ),
            role="Planning (active inference)",
            module="planning",
            probe=lambda: planning_health_probe(backend=planning_backend),
        ),
        DependencySpec(
            name="State encryption",
            role="security",
            module=None,  # not gated by a module toggle; always probed
            probe=lambda _sec=state_encryption_cfg or {}: probe_state_encryption(
                section=_sec
            ),
        ),
    ]


def load_health_prober(
    *,
    kaine_toml: str | os.PathLike[str] | None = None,
    secrets_toml: str | os.PathLike[str] | None = None,
    probe_timeout_s: float = DEFAULT_PROBE_TIMEOUT_S,
    cache_ttl_s: float = DEFAULT_CACHE_TTL_S,
) -> HealthProber:
    """Build a :class:`HealthProber` from ``config/kaine.toml`` and
    ``config/secrets.toml`` (+ env overrides for secrets)."""

    from kaine.config import OPERATOR_CONFIG_PATH, load_kaine_config

    toml_path = Path(kaine_toml or "config/kaine.toml")
    secrets_path = Path(secrets_toml or "config/secrets.toml")

    cfg: dict[str, Any] = {}
    if toml_path.exists():
        try:
            # Deep-merge the gitignored operator override so the health board
            # reflects the operator's enabled modules / model ids.
            cfg = load_kaine_config(toml_path, OPERATOR_CONFIG_PATH)
        except Exception:
            log.warning("could not parse %s for health prober", toml_path, exc_info=True)

    secrets: dict[str, Any] = {}
    try:
        secrets = secrets_file.load_secrets_doc(secrets_path)
    except Exception:
        log.warning("could not parse secrets for health prober", exc_info=True)

    modules_enabled = {
        str(k): bool(v) for k, v in (cfg.get("modules") or {}).items()
    }

    redis_secret = (secrets.get("redis") or {})
    qdrant_secret = (secrets.get("qdrant") or {})
    redis_password = os.environ.get("KAINE_REDIS_PASSWORD") or redis_secret.get("password")
    qdrant_key = os.environ.get("KAINE_QDRANT_API_KEY") or qdrant_secret.get("api_key")

    state_enc_cfg = (cfg.get("security") or {}).get("state_encryption") or {}

    specs = build_dependency_specs(
        redis_cfg=cfg.get("redis") or {},
        qdrant_cfg=(cfg.get("episodic_memory") or {}).get("qdrant") or {},
        qdrant_secret_key=qdrant_key,
        redis_password=redis_password,
        language_cfg=cfg.get("language") or {},
        audition_cfg=cfg.get("audition") or {},
        vocal_cfg=cfg.get("vocal") or {},
        planning_cfg=cfg.get("planning") or {},
        state_encryption_cfg=state_enc_cfg,
    )

    research_submission_cfg = dict(cfg.get("research_submission") or {})

    # Unified deterministic perception-feed surface (unified-perception-feed).
    vision_cfg = cfg.get("vision") or {}
    audition_cfg = cfg.get("audition") or {}
    perception_feed_cfg = dict(cfg.get("perception_feed") or {})
    vision_capture_geometry = (
        int(vision_cfg.get("capture_width", 640)),
        int(vision_cfg.get("capture_height", 480)),
    )
    audition_capture_geometry = (
        int(audition_cfg.get("capture_sample_rate", 16000)),
        int(audition_cfg.get("capture_channels", 1)),
    )

    # Model-server (language-organ) surface: chat_url + served alias + bearer key
    # (presence only — the key is never logged). Same resolution as the cycle.
    language_cfg = cfg.get("language") or {}
    model_server_cfg = {
        "chat_url": language_section_chat_url(language_cfg),
        "model_id": language_cfg.get("model_id"),
        "api_key": language_section_api_key(language_cfg),
    }

    # Graded consolidation-divergence thresholds for the entity-care divergence
    # assessment (rate, magnitude), read from [sleep.voice_alignment].
    from kaine.lifecycle.divergence import (
        adapter_dir_for,
        voice_alignment_thresholds_from_config,
        voice_paths_for,
    )

    consolidation_thresholds = voice_alignment_thresholds_from_config(cfg)
    state_root = resolve(Path("state"))
    adapter_output_dir = adapter_dir_for(cfg, state_root)
    voice_paths = voice_paths_for(cfg, state_root)

    # Evaluation JSONL rollup root (for the welfare-counter row) and the
    # autonomous safety-net incident path (for the preservation panel backfill).
    # Both fall back to the canonical defaults when the section is absent.
    eval_paths = (cfg.get("evaluation") or {}).get("paths") or {}
    evaluation_logs_path = resolve(
        Path(str(eval_paths.get("evaluation_logs", "data/evaluation")))
    )
    preservation_incident_path = resolve(
        Path(str((cfg.get("preservation") or {}).get("incident_path", "state/cycle/preservation")))
    )

    _defaults = {f.name: f.default for f in dataclasses.fields(HealthProber)}

    return HealthProber(
        modules_enabled=modules_enabled,
        dependencies=specs,
        research_submission_cfg=research_submission_cfg,
        perception_feed_cfg=perception_feed_cfg,
        vision_capture_geometry=vision_capture_geometry,
        audition_capture_geometry=audition_capture_geometry,
        model_server_cfg=model_server_cfg,
        consolidation_thresholds=consolidation_thresholds,
        adapter_output_dir=adapter_output_dir,
        voice_paths=voice_paths,
        probe_timeout_s=probe_timeout_s,
        cache_ttl_s=cache_ttl_s,
        evaluation_logs_path=evaluation_logs_path,
        preservation_incident_path=preservation_incident_path,
        cycle_runtime_path=resolve(_defaults["cycle_runtime_path"]),
        runs_manifest_root=resolve(_defaults["runs_manifest_root"]),
        supervisor_control_path=resolve(_defaults["supervisor_control_path"]),
        supervisor_escalation_path=resolve(_defaults["supervisor_escalation_path"]),
        gpu_preflight_path=resolve(_defaults["gpu_preflight_path"]),
        episodic_memory_store_health_path=resolve(_defaults["episodic_memory_store_health_path"]),
    )
