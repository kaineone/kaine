# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The Hypnos factory, with the voice-alignment trainer resolvers, probe-set checks and organ-window runner it needs."""
from __future__ import annotations

import logging
import math
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from kaine.modules.hypnos.voice_alignment import VoiceAlignmentConfig
from kaine.boot.common import _effective_hot_swap_mode
from kaine.boot.errors import VoiceAlignmentConfigError, _require_keys
from kaine.bus.client import AsyncBus
from kaine.defaults import lingua_section_api_key, lingua_section_chat_url
from kaine.entity_clock import EntityClock
from kaine.modules.base import BaseModule
from kaine.storage import resolve
from kaine.text_embedding import (
    Embedder,
)

log = logging.getLogger(__name__)


def voice_alignment_config_from_section(
    voice_cfg_section: dict[str, Any],
    kaine_config: Optional[dict[str, Any]] = None,
) -> Optional["VoiceAlignmentConfig"]:
    """Parse [hypnos.voice_alignment] into a VoiceAlignmentConfig (None when the table is empty)."""
    from kaine.modules.hypnos.voice_alignment import PREFERENCE_SOURCES, VoiceAlignmentConfig

    voice_config: Optional[VoiceAlignmentConfig] = None
    if voice_cfg_section:
        base_model_path_raw = voice_cfg_section.get("base_model_path", "")
        base_model_path: Optional[str] = str(base_model_path_raw).strip() or None
        reload_endpoint_url_raw = voice_cfg_section.get("reload_endpoint_url", "")
        reload_endpoint_url: Optional[str] = str(reload_endpoint_url_raw).strip() or None
        restart_service_unit_raw = voice_cfg_section.get("restart_service_unit", "")
        restart_service_unit: Optional[str] = str(restart_service_unit_raw).strip() or None
        capability_probe_path_raw = voice_cfg_section.get("capability_probe_path", "")
        capability_probe_path: Optional[str] = str(capability_probe_path_raw).strip() or None
        abliteration_probe_path_raw = voice_cfg_section.get("abliteration_probe_path", "")
        abliteration_probe_path: Optional[str] = str(abliteration_probe_path_raw).strip() or None
        try:
            corpus_ceiling_gb = float(voice_cfg_section.get("corpus_ceiling_gb", 10.0))
        except (TypeError, ValueError) as exc:
            raise VoiceAlignmentConfigError(
                "[hypnos.voice_alignment].corpus_ceiling_gb must be a number; "
                f"got {voice_cfg_section.get('corpus_ceiling_gb')!r}"
            ) from exc
        if not corpus_ceiling_gb >= 0:
            raise VoiceAlignmentConfigError(
                "[hypnos.voice_alignment].corpus_ceiling_gb must be non-negative; "
                f"got {corpus_ceiling_gb}"
            )
        try:
            distinctiveness_threshold = float(
                voice_cfg_section.get("distinctiveness_threshold", 0.0)
            )
        except (TypeError, ValueError) as exc:
            raise VoiceAlignmentConfigError(
                "[hypnos.voice_alignment].distinctiveness_threshold must be a "
                f"number; got {voice_cfg_section.get('distinctiveness_threshold')!r}"
            ) from exc
        if not math.isfinite(distinctiveness_threshold) or distinctiveness_threshold < 0:
            raise VoiceAlignmentConfigError(
                "[hypnos.voice_alignment].distinctiveness_threshold must be a "
                f"finite, non-negative float; got {distinctiveness_threshold}"
            )
        preference_source_raw = voice_cfg_section.get("preference_source", "none")
        if not isinstance(preference_source_raw, str):
            raise VoiceAlignmentConfigError(
                f"[hypnos.voice_alignment].preference_source must be one of "
                f"{sorted(PREFERENCE_SOURCES)}; got {type(preference_source_raw).__name__}: "
                f"{preference_source_raw!r}"
            )
        preference_source = preference_source_raw.strip()
        if preference_source not in PREFERENCE_SOURCES:
            raise VoiceAlignmentConfigError(
                f"[hypnos.voice_alignment].preference_source={preference_source!r} is unknown; "
                f"known sources: {sorted(PREFERENCE_SOURCES)}"
            )
        voice_config = VoiceAlignmentConfig(
            intent_log_path=resolve(
                voice_cfg_section.get("intent_log_path", "state/lingua/intent_expression.jsonl")
            ),
            adapter_output_dir=resolve(
                voice_cfg_section.get("adapter_output_dir", "state/hypnos/adapters")
            ),
            enabled=bool(voice_cfg_section.get("enabled", False)),
            base_model_path=base_model_path,
            model_id=str(voice_cfg_section.get("model_id", "kaineone/Qwen3.5-4B-abliterated")),
            max_samples=int(voice_cfg_section.get("max_samples", 200)),
            lora_rank=int(voice_cfg_section.get("lora_rank", 8)),
            learning_rate=float(voice_cfg_section.get("learning_rate", 5e-5)),
            dpo_beta=float(voice_cfg_section.get("dpo_beta", 0.1)),
            capability_loss_threshold=float(
                voice_cfg_section.get("capability_loss_threshold", 0.05)
            ),
            seed=int(voice_cfg_section.get("seed", 42)),
            training_device=str(voice_cfg_section.get("training_device", "cuda:0")),
            adapter_retention=int(voice_cfg_section.get("adapter_retention", 0)),
            hot_swap_mode=str(voice_cfg_section.get("hot_swap_mode", "manual")),
            reload_endpoint_url=reload_endpoint_url,
            restart_service_unit=restart_service_unit,
            capability_probe_path=capability_probe_path,
            abliteration_probe_path=abliteration_probe_path,
            trainer_backend=str(voice_cfg_section.get("trainer_backend", "in_process")).strip()
            or "in_process",
            trainer_python=str(voice_cfg_section.get("trainer_python", "")).strip(),
            trainer_workdir=str(
                resolve(
                    str(
                        voice_cfg_section.get("trainer_workdir", "state/hypnos/voice_align_jobs")
                    ).strip()
                    or "state/hypnos/voice_align_jobs"
                )
            ),
            trainer_jobs_dir=str(
                resolve(
                    str(
                        voice_cfg_section.get("trainer_jobs_dir", "state/hypnos/voice_align_jobs")
                    ).strip()
                    or "state/hypnos/voice_align_jobs"
                )
            ),
            trainer_timeout_s=float(voice_cfg_section.get("trainer_timeout_s", 21600.0)),
            organ_adapters_dir=str(voice_cfg_section.get("organ_adapters_dir", "/organ-adapters")),
            organ_url=str(
                str(voice_cfg_section.get("organ_url", "")).strip()
                or (
                    ((kaine_config or {}).get("lingua") or {}).get("chat_url", "")
                    or ""
                )
            ),
            corpus_ceiling_gb=corpus_ceiling_gb,
            preference_source=preference_source,
            distinctiveness_threshold=distinctiveness_threshold,
        )
    return voice_config


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
    embedder: Optional[Embedder] = None,
) -> BaseModule:
    from kaine.modules.hypnos.module import Hypnos

    allowed = {
        "interval_seconds",
        "max_deferral_seconds",
        "per_defer_seconds",
        "nous_step_burst",
        "baseline_salience",
        "alert_salience",
        "requested_rest_min_interval_s",
        "voice_alignment",  # nested sub-table
        "consolidation",  # nested sub-table: fatigue_triggered, downscale_factor, replay_window_s
    }
    _require_keys(section, allowed)
    voice_cfg_section = section.get("voice_alignment") or {}
    voice_config: Optional[VoiceAlignmentConfig] = voice_alignment_config_from_section(
        voice_cfg_section, kaine_config
    )
    if voice_config is not None:
        _validate_backend_pairing(voice_config)
        effective = _effective_hot_swap_mode(voice_config.hot_swap_mode, kaine_config)
        if effective != voice_config.hot_swap_mode:
            log.warning(
                "hot_swap_mode=%s ignored: the model server is a shared service, so KAINE does not unload, restart or reload it; using manual",
                voice_config.hot_swap_mode,
            )
            voice_config = replace(voice_config, hot_swap_mode=effective)
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
    if "requested_rest_min_interval_s" in section:
        raw_interval = section["requested_rest_min_interval_s"]
        if (
            isinstance(raw_interval, bool)
            or not isinstance(raw_interval, (int, float))
            or not math.isfinite(raw_interval)
            or raw_interval <= 0
        ):
            raise ValueError(
                "[hypnos].requested_rest_min_interval_s must be a number greater than 0"
            )
        kwargs["requested_rest_min_interval_s"] = float(raw_interval)
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

    # Voice-measures arm needs the path of the organ GGUF so it can look up
    # the correct base voice profile. Prefer an explicit [lingua].model_gguf_path;
    # otherwise fall back to the deterministic served-GGUF path.
    organ_gguf_path: Optional[Path] = None
    try:
        from kaine.organ_server.served import served_gguf_path

        organ_gguf_path = served_gguf_path()
    except Exception:
        organ_gguf_path = None
    if kaine_config:
        raw_gguf = (
            ((kaine_config.get("lingua") or {}).get("model_gguf_path") or "")
        ).strip()
        if raw_gguf:
            organ_gguf_path = resolve(Path(raw_gguf))
    kwargs["organ_gguf_path"] = organ_gguf_path
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
    if embedder is not None:
        kwargs["consolidation_embedder"] = embedder
    # When the operator has opted in (config + env var) AND the
    # `[training]` extras importable, wire the real Unsloth-backed
    # trainer. Otherwise FakeTrainer ships the "no backend" reason.
    trainer = _resolve_trainer(voice_config, kaine_config)
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
    # Shared playlist clock (playlist-sleep-pause): boot stashes the SAME
    # instance used by both playlist feeds under the [perception_feed] section;
    # pass it to Hypnos so sleep suspends/resumes playback at the same seam as
    # the locus flip. Absent in non-playlist modes → honest no-op.
    if kaine_config is not None:
        _pf = kaine_config.get("perception_feed") or {}
        _pclock = _pf.get("_shared_playlist_clock")
        if _pclock is not None:
            kwargs["playlist_clock"] = _pclock
    return Hypnos(bus, **kwargs)


def _validate_backend_pairing(voice_config: "VoiceAlignmentConfig") -> None:
    """Refuse a hot-swap mode the configured trainer backend cannot serve."""
    if not voice_config.enabled:
        return
    backend = (voice_config.trainer_backend or "in_process").strip()
    mode = (voice_config.hot_swap_mode or "manual").strip()
    if mode == "organ_adapter" and backend != "job_queue":
        raise VoiceAlignmentConfigError(
            "[hypnos.voice_alignment].hot_swap_mode = \"organ_adapter\" needs "
            "trainer_backend = \"job_queue\": only the trainer service converts an "
            f"accepted adapter to the GGUF form the organ loads (got {backend!r})."
        )


def _resolve_trainer(
    voice_config: Optional["VoiceAlignmentConfig"],
    kaine_config: dict[str, Any] | None = None,
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
    if backend not in ("in_process", "subprocess", "job_queue"):
        raise VoiceAlignmentConfigError(
            f"[hypnos.voice_alignment].trainer_backend must be 'in_process', "
            f"'subprocess' or 'job_queue', got {backend!r}."
        )

    if backend == "subprocess":
        return _resolve_subprocess_trainer(voice_config)
    if backend == "job_queue":
        return _resolve_job_queue_trainer(voice_config, kaine_config)

    try:
        import datasets  # noqa: F401  # type: ignore[import-untyped]
        import peft  # noqa: F401  # type: ignore[import-untyped]
        import trl  # noqa: F401  # type: ignore[import-untyped]
        import unsloth  # noqa: F401  # type: ignore[import-untyped]
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
    _require_non_empty_capability_probes(voice_config)

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

    probe_path = voice_config.abliteration_probe_path or DEFAULT_ABLITERATION_PROBE_PATH
    require_non_empty_abliteration_probes(probe_path)


def _require_non_empty_capability_probes(
    voice_config: "VoiceAlignmentConfig",
) -> None:
    """Promotion-gate invariant shared by every trainer backend.

    When voice alignment is actually going to run, the capability probe set
    MUST be non-empty — an empty probe set would score every model 0.0, the
    capability loss would always be 0.0, and the capability-loss veto would
    pass every adapter. Raises EmptyCapabilityProbeSetError with a clear
    remediation message. (The subprocess external script also fails closed on
    an empty set; this is the boot-time belt-and-suspenders.)
    """
    from kaine.modules.hypnos.capability_eval import (
        DEFAULT_PROBE_PATH,
        EmptyCapabilityProbeSetError,
        load_probes,
    )

    probe_path = voice_config.capability_probe_path or DEFAULT_PROBE_PATH
    probes = load_probes(probe_path)
    if not probes:
        raise EmptyCapabilityProbeSetError(
            f"[hypnos.voice_alignment].capability_probe_path has no usable "
            f"capability probe: {probe_path}. The capability-loss veto cannot run "
            'on an empty probe set; point it at a JSONL file of {"prompt", '
            '"expected"} lines, or leave it empty for the bundled set.'
        )


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
    _require_non_empty_capability_probes(voice_config)

    return SubprocessVoiceTrainer(
        trainer_python=trainer_python,
        trainer_workdir=voice_config.trainer_workdir,
    )


def _resolve_job_queue_trainer(
    voice_config: "VoiceAlignmentConfig",
    kaine_config: dict[str, Any] | None = None,
) -> Any:
    """Construct the job-queue trainer for the "job_queue" backend.

    The real training happens in the kaine-trainer container service, which
    watches a shared jobs volume. The runtime venv does not need the [training]
    extra, but it still needs the same non-empty abliteration probe set, and a
    positive trainer_timeout_s.
    """
    from pathlib import Path

    from kaine.modules.hypnos.job_queue_trainer import JobQueueVoiceTrainer
    from kaine.modules.hypnos.organ_adapter import organ_root_url

    _require_non_empty_abliteration_probes(voice_config)
    _require_non_empty_capability_probes(voice_config)

    timeout_s = voice_config.trainer_timeout_s
    if timeout_s <= 0:
        raise VoiceAlignmentConfigError(
            f"[hypnos.voice_alignment].trainer_timeout_s must be > 0, got "
            f"{timeout_s!r}."
        )

    lingua = (kaine_config or {}).get("lingua") or {}
    chat_url = lingua_section_chat_url(lingua)
    api_key = lingua_section_api_key(lingua) or ""

    return JobQueueVoiceTrainer(
        jobs_dir=voice_config.trainer_jobs_dir,
        timeout_s=timeout_s,
        organ_adapters_dir=Path(voice_config.organ_adapters_dir),
        organ_url=organ_root_url(voice_config.organ_url or chat_url),
        organ_api_key=api_key,
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
        return bool(
            run_preflight(
                gpu_cfg,
                keep_models=keep,
                services_config=config.get("services"),
            ).ok
        )

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
            trainer_backend=str(voice_config.trainer_backend or "in_process"),
        )

    return runner
