# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Construction of a :class:`~kaine.nexus.health.prober.HealthProber` from
loaded ``config/kaine.toml`` (+ ``config/secrets.toml``)."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from .prober import DependencySpec, HealthProber
from .probes import (
    DEFAULT_CACHE_TTL_S,
    DEFAULT_PROBE_TIMEOUT_S,
    nous_health_probe,
    probe_chat_llm,
    probe_chatterbox,
    probe_qdrant,
    probe_redis,
    probe_speaches,
    probe_state_encryption,
)

log = logging.getLogger(__name__)


def build_dependency_specs(
    *,
    redis_cfg: dict[str, Any],
    qdrant_cfg: dict[str, Any],
    qdrant_secret_key: str | None,
    redis_password: str | None,
    lingua_cfg: dict[str, Any],
    audition_cfg: dict[str, Any],
    vox_cfg: dict[str, Any],
    nous_cfg: dict[str, Any],
    state_encryption_cfg: dict[str, Any] | None = None,
) -> list[DependencySpec]:
    redis_host = str(redis_cfg.get("host", "127.0.0.1"))
    redis_port = int(redis_cfg.get("port", 6379))

    qdrant_host = str(qdrant_cfg.get("host", "127.0.0.1"))
    qdrant_port = int(qdrant_cfg.get("port", 6333))

    chat_url = str(lingua_cfg.get("chat_url", "http://127.0.0.1:11434"))
    model_id = lingua_cfg.get("model_id")
    chat_api_key = lingua_cfg.get("api_key") or os.environ.get(
        "KAINE_MODEL_SERVER_API_KEY"
    )

    speaches_url = str(audition_cfg.get("speaches_url", "http://127.0.0.1:8000"))
    chatterbox_url = str(vox_cfg.get("chatterbox_url", "http://127.0.0.1:8883"))
    # nous_cfg is retained in the signature for parity with other deps, but the
    # active-inference backend has no binary path — the probe imports pymdp/jax.
    del nous_cfg

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
            role="Mnemos (memory)",
            module="mnemos",
            probe=lambda: probe_qdrant(
                host=qdrant_host, port=qdrant_port, api_key=qdrant_secret_key
            ),
        ),
        DependencySpec(
            name="Chat LLM",
            role="Lingua / Hypnos",
            module="lingua",
            probe=lambda: probe_chat_llm(
                base_url=chat_url, model_id=model_id, api_key=chat_api_key
            ),
        ),
        DependencySpec(
            name="Speaches (STT)",
            role="Audition",
            module="audition",
            probe=lambda: probe_speaches(base_url=speaches_url),
        ),
        DependencySpec(
            name="Chatterbox (TTS)",
            role="Vox",
            module="vox",
            probe=lambda: probe_chatterbox(base_url=chatterbox_url),
        ),
        DependencySpec(
            name="pymdp + JAX",
            role="Nous (active inference)",
            module="nous",
            probe=nous_health_probe,
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
    import tomllib

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
    if secrets_path.exists():
        try:
            secrets = tomllib.loads(secrets_path.read_text())
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
        qdrant_cfg=(cfg.get("mnemos") or {}).get("qdrant") or {},
        qdrant_secret_key=qdrant_key,
        redis_password=redis_password,
        lingua_cfg=cfg.get("lingua") or {},
        audition_cfg=cfg.get("audition") or {},
        vox_cfg=cfg.get("vox") or {},
        nous_cfg=cfg.get("nous") or {},
        state_encryption_cfg=state_enc_cfg,
    )

    research_submission_cfg = dict(cfg.get("research_submission") or {})

    # Unified deterministic perception-feed surface (unified-perception-feed).
    topos_cfg = cfg.get("topos") or {}
    audition_cfg = cfg.get("audition") or {}
    perception_feed_cfg = dict(cfg.get("perception_feed") or {})
    topos_capture_geometry = (
        int(topos_cfg.get("capture_width", 640)),
        int(topos_cfg.get("capture_height", 480)),
    )
    audition_capture_geometry = (
        int(audition_cfg.get("capture_sample_rate", 16000)),
        int(audition_cfg.get("capture_channels", 1)),
    )

    # Model-server (language-organ) surface: chat_url + served alias + bearer key
    # (presence only — the key is never logged). Same resolution as the cycle.
    lingua_cfg = cfg.get("lingua") or {}
    model_server_cfg = {
        "chat_url": lingua_cfg.get("chat_url", "http://127.0.0.1:11434/v1"),
        "model_id": lingua_cfg.get("model_id"),
        "api_key": lingua_cfg.get("api_key")
        or os.environ.get("KAINE_MODEL_SERVER_API_KEY"),
    }

    # Graded consolidation-divergence thresholds for the entity-care divergence
    # assessment (rate, magnitude), read from [hypnos.voice_alignment].
    from kaine.lifecycle.divergence import consolidation_thresholds_from_config

    consolidation_thresholds = consolidation_thresholds_from_config(cfg)

    # Evaluation JSONL rollup root (for the welfare-counter row) and the
    # autonomous safety-net incident path (for the preservation panel backfill).
    # Both fall back to the canonical defaults when the section is absent.
    eval_paths = (cfg.get("evaluation") or {}).get("paths") or {}
    evaluation_logs_path = Path(
        str(eval_paths.get("evaluation_logs", "data/evaluation"))
    )
    preservation_incident_path = Path(
        str((cfg.get("preservation") or {}).get("incident_path", "state/cycle/preservation"))
    )

    return HealthProber(
        modules_enabled=modules_enabled,
        dependencies=specs,
        research_submission_cfg=research_submission_cfg,
        perception_feed_cfg=perception_feed_cfg,
        topos_capture_geometry=topos_capture_geometry,
        audition_capture_geometry=audition_capture_geometry,
        model_server_cfg=model_server_cfg,
        consolidation_thresholds=consolidation_thresholds,
        probe_timeout_s=probe_timeout_s,
        cache_ttl_s=cache_ttl_s,
        evaluation_logs_path=evaluation_logs_path,
        preservation_incident_path=preservation_incident_path,
        # spot_control_path / spot_escalation_path / runs_manifest_root stay at
        # their dataclass defaults (the canonical paths the cycle writes).
    )
