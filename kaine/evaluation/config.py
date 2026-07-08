# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from kaine.config import OPERATOR_CONFIG_PATH, SHIPPED_CONFIG_PATH, load_kaine_config

# ---------------------------------------------------------------------------
# Individuation config
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IndividuationConfig:
    """Parameters for the individuation boundary permutation-test instrument.

    Shipped disabled (``enabled = false``) so the instrument only runs when
    an operator explicitly sets ``[evaluation.individuation] enabled = true``
    and invokes it at a merge point.  The test is never called from the
    cognitive cycle.

    Attributes
    ----------
    enabled:
        Master gate.  When false, the test is not constructed.  Default
        false because this is an operator-run instrument, not a background
        observer.
    null_samples:
        Number of parent-vs-parent samples used to build the null
        distribution (default 50; minimum 2).
    significance_percentile:
        Fork divergence must exceed this percentile of the null distribution
        to be reported as significant (default 95.0).
    metric:
        Divergence metric.  Currently only ``"cosine_divergence"`` is
        supported (1 − cosine similarity of concatenated-response embeddings).
    battery_path:
        Path to a JSONL operator battery file.  Empty string = use the
        bundled default battery.
    output_dir:
        Directory where JSONL evidence reports are written.  Relative paths
        are resolved from the working directory at instrument-run time.
    """

    enabled: bool = False
    null_samples: int = 50
    significance_percentile: float = 95.0
    metric: str = "cosine_divergence"
    battery_path: str = ""
    output_dir: str = "data/evaluation/individuation"
    # Warm-up / minimum-lived-experience floor: ``significant`` cannot be true
    # (and ``warmed_up`` is false) until the entity has accumulated at least
    # ``min_observations`` logged lived events AND ``min_lived_time_s`` of
    # elapsed lived time. Fail-closed — a void/just-booted entity reads
    # not-individuated.
    min_observations: int = 200
    min_lived_time_s: float = 1800.0

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> "IndividuationConfig":
        data = dict(data or {})
        return cls(
            enabled=bool(data.get("enabled", cls.enabled)),
            null_samples=int(data.get("null_samples", cls.null_samples)),
            significance_percentile=float(
                data.get("significance_percentile", cls.significance_percentile)
            ),
            metric=str(data.get("metric", cls.metric)),
            battery_path=str(data.get("battery_path", cls.battery_path)),
            output_dir=str(data.get("output_dir", cls.output_dir)),
            min_observations=int(data.get("min_observations", cls.min_observations)),
            min_lived_time_s=float(
                data.get("min_lived_time_s", cls.min_lived_time_s)
            ),
        )


class RawArchiveConfinementError(ValueError):
    """Raised when the raw archive ``archive_dir`` is under ``data/evaluation/``.

    The raw archive captures VERBATIM bus content and must never be
    export-eligible. The metrics bundle builder only ever reads from
    ``data/evaluation/``; an ``archive_dir`` resolving under that tree would make
    verbatim content export-eligible. We fail closed rather than trust the path
    to merely be documented as outside the allowlist.
    """


# The metrics-export allowlist root. Anything resolving under this tree is
# export-eligible, so the local-only raw archive must NEVER live here.
_EXPORT_ALLOWLIST_ROOT = "data/evaluation"


def assert_raw_archive_outside_export_allowlist(archive_dir: str) -> None:
    """Fail closed when ``archive_dir`` resolves under ``data/evaluation/``.

    Uses ``Path.resolve().is_relative_to`` (Python 3.12) against the resolved
    export-allowlist root so symlink/``..`` games cannot smuggle the raw archive
    into the export tree. Enforced at config-load AND at consumer ``start()``.
    """
    resolved = Path(archive_dir).resolve()
    allowlist_root = Path(_EXPORT_ALLOWLIST_ROOT).resolve()
    if resolved == allowlist_root or resolved.is_relative_to(allowlist_root):
        raise RawArchiveConfinementError(
            f"raw archive archive_dir ({archive_dir!r}) resolves under the "
            f"metrics-export allowlist root ({_EXPORT_ALLOWLIST_ROOT}/): "
            f"{resolved}. The raw archive captures verbatim conversation content "
            "and is never export-eligible — set archive_dir to a path OUTSIDE "
            f"{_EXPORT_ALLOWLIST_ROOT}/ (e.g. the default state/research/raw_bus_archive)."
        )


@dataclass(frozen=True)
class RawArchiveConfig:
    """Parameters for the OPTIONAL local-only raw bus archive.

    This archive captures verbatim bus events (including conversation content
    and transcripts) before the Redis ring buffer trims them. It is NEVER
    export-eligible: it writes outside ``data/evaluation/`` so the metrics
    bundle builder cannot reach it.

    Ships disabled. The consumer refuses to start unless ALL THREE are true:
    ``enabled``, ``entity_privacy_attested``, ``bystander_consent_attested``.
    The two attestation flags mirror the ``BundleTierError`` gate in
    ``kaine/research/submission.py``.

    Attributes
    ----------
    enabled:
        Master gate. Default false.
    entity_privacy_attested / bystander_consent_attested:
        Both must be explicitly set true before the consumer will start.
        Otherwise ``RawBusArchiveConsumer.start()`` raises
        ``RawArchiveAttestationError``.
    archive_dir:
        Storage path. MUST remain outside ``data/evaluation/`` (default
        ``state/research/raw_bus_archive``).
    retention_days:
        Daily-rotated file retention window (default 30).
    """

    enabled: bool = False
    entity_privacy_attested: bool = False
    bystander_consent_attested: bool = False
    archive_dir: str = "state/research/raw_bus_archive"
    retention_days: int = 30

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> "RawArchiveConfig":
        data = dict(data or {})
        archive_dir = str(data.get("archive_dir", cls.archive_dir))
        # Fail closed at config-load: the raw archive must never resolve under
        # the metrics-export allowlist root, or verbatim content becomes
        # export-eligible (the consumer re-checks at start()).
        assert_raw_archive_outside_export_allowlist(archive_dir)
        return cls(
            enabled=bool(data.get("enabled", cls.enabled)),
            entity_privacy_attested=bool(
                data.get("entity_privacy_attested", cls.entity_privacy_attested)
            ),
            bystander_consent_attested=bool(
                data.get("bystander_consent_attested", cls.bystander_consent_attested)
            ),
            archive_dir=archive_dir,
            retention_days=int(data.get("retention_days", cls.retention_days)),
        )


@dataclass(frozen=True)
class ResearchEventLogConfig:
    """Parameters for the curated, privacy-filtered research event log.

    The curated log subscribes to a curated allowlist of bus streams and writes
    privacy-filtered numeric/categorical records to an ``AsyncJsonlSink`` under
    ``data/evaluation/research_events/``. That directory is added to
    ``METRICS_ONLY_DIRS`` so the log is export-eligible in a metrics bundle.

    Ships disabled (``enabled = false``). INDEPENDENT of
    ``[evaluation].enabled`` — the evaluation sidecar and the research event log
    can each be enabled or disabled separately.

    Attributes
    ----------
    enabled:
        Master gate for the curated observer. Default false.
    log_dir:
        Directory for the curated log sink (under ``data/evaluation/``). The
        final path component MUST be ``research_events`` to be export-eligible.
    retention_days:
        Daily-rotated file retention window (default 30).
    raw_archive:
        Nested config for the OPTIONAL local-only raw bus archive.
    """

    enabled: bool = False
    log_dir: str = "data/evaluation/research_events"
    retention_days: int = 30
    raw_archive: RawArchiveConfig = field(default_factory=RawArchiveConfig)

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> "ResearchEventLogConfig":
        data = dict(data or {})
        return cls(
            enabled=bool(data.get("enabled", cls.enabled)),
            log_dir=str(data.get("log_dir", cls.log_dir)),
            retention_days=int(data.get("retention_days", cls.retention_days)),
            raw_archive=RawArchiveConfig.from_mapping(data.get("raw_archive")),
        )


@dataclass(frozen=True)
class EvaluationPaths:
    trajectory_dir: str = "data/workspace_trajectory"
    evaluation_logs: str = "data/evaluation"
    retention_days: int = 30

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> "EvaluationPaths":
        data = dict(data or {})
        return cls(
            trajectory_dir=str(data.get("trajectory_dir", cls.trajectory_dir)),
            evaluation_logs=str(data.get("evaluation_logs", cls.evaluation_logs)),
            retention_days=int(data.get("retention_days", cls.retention_days)),
        )


@dataclass(frozen=True)
class ObserversConfig:
    """Per-observer toggle flags under ``[evaluation.observers]``.

    All default to ``True`` so the sidecar is fully instrumented when
    enabled.  Each toggle is gated by the parent ``EvaluationConfig.enabled``
    flag — if the sidecar is disabled, none of these observers runs.
    """

    coherence: bool = True
    replay: bool = True
    replay_redact_content: bool = True   # privacy default: IDs only
    empatheia: bool = True
    voice_alignment_divergence: bool = True
    fatigue: bool = True
    prediction_error: bool = True
    welfare: bool = True
    nous_policy: bool = True

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> "ObserversConfig":
        data = dict(data or {})
        return cls(
            coherence=bool(data.get("coherence", cls.coherence)),
            replay=bool(data.get("replay", cls.replay)),
            replay_redact_content=bool(
                data.get("replay_redact_content", cls.replay_redact_content)
            ),
            empatheia=bool(data.get("empatheia", cls.empatheia)),
            voice_alignment_divergence=bool(
                data.get("voice_alignment_divergence", cls.voice_alignment_divergence)
            ),
            fatigue=bool(data.get("fatigue", cls.fatigue)),
            prediction_error=bool(data.get("prediction_error", cls.prediction_error)),
            welfare=bool(data.get("welfare", cls.welfare)),
            nous_policy=bool(data.get("nous_policy", cls.nous_policy)),
        )


@dataclass(frozen=True)
class WelfareConfig:
    """Parameters for the welfare Gray-Zone observer.

    Threaded to ``WelfareObserver`` at sidecar construction time.
    All defaults are safe (conservative thresholds, no behavior change
    to conditions a–c when added fields are absent from TOML).

    Attributes
    ----------
    interoceptive_distress_threshold:
        Minimum ``prediction_error`` magnitude (from ``soma.report``)
        that is considered a high-distress state.  Default 0.8 — well
        above normal operating range, conservative enough not to fire
        spuriously during ordinary regulation.
    interoceptive_distress_duration_s:
        How many consecutive seconds the magnitude must stay at or above
        ``interoceptive_distress_threshold`` before a
        ``sustained_interoceptive_distress`` Welfare Event is registered.
        Default 30 s.  The sustain timer resets whenever the magnitude
        drops below the threshold, so a single sustained episode produces
        a single event rather than one per tick.
    """

    interoceptive_distress_threshold: float = 0.8
    interoceptive_distress_duration_s: float = 30.0

    def __post_init__(self) -> None:
        if self.interoceptive_distress_threshold < 0.0:
            raise ValueError(
                "interoceptive_distress_threshold must be non-negative"
            )
        if self.interoceptive_distress_duration_s <= 0.0:
            raise ValueError(
                "interoceptive_distress_duration_s must be positive"
            )

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> "WelfareConfig":
        data = dict(data or {})
        return cls(
            interoceptive_distress_threshold=float(
                data.get(
                    "interoceptive_distress_threshold",
                    cls.interoceptive_distress_threshold,
                )
            ),
            interoceptive_distress_duration_s=float(
                data.get(
                    "interoceptive_distress_duration_s",
                    cls.interoceptive_distress_duration_s,
                )
            ),
        )


@dataclass(frozen=True)
class EvaluationConfig:
    enabled: bool = True
    workspace_trajectory: bool = True
    ab_divergence: bool = True
    ab_sample_rate: float = 1.0
    voice_tracking: bool = True
    module_attribution: bool = True
    affect_correlation: bool = True
    memory_probes: bool = True
    memory_probe_interval_minutes: int = 60
    proactive_audit: bool = True
    eidolon_accuracy: bool = True
    eidolon_accuracy_interval_hours: int = 24
    sleep_snapshots: bool = True
    # Live oscillatory ablation (concurrent dual-path). Off by default: it scores
    # each experiential tick twice to record the coherence-off counterfactual, a
    # small hot-path cost only research runs should pay. The entity's behaviour is
    # unchanged whether or not it is on.
    oscillatory_ablation: bool = False
    paths: EvaluationPaths = field(default_factory=EvaluationPaths)
    # Internal — used by ABDivergenceObserver to reach the same OpenAI-compatible
    # model server Lingua uses (/v1/chat/completions). `think` mirrors Lingua's:
    # thinking models must have CoT suppressed or the bare baseline runs away
    # reasoning and returns empty content — so it DEFAULTS to False here too. The
    # server's `--reasoning-budget 0` flag does not reliably suppress CoT, so
    # suppression is enforced client-side via enable_thinking (see lingua.client).
    chat_url: str = "http://127.0.0.1:11434"
    # The A/B-divergence baseline runs this model bare (no architecture). It MUST
    # equal the language organ's model or the divergence measures a model
    # difference, not the architecture's conditioning. At cycle startup this is
    # DERIVED from [lingua].model_id (see from_mapping's lingua_model_id); the
    # default below is only a fallback for standalone/no-lingua reads.
    chat_model_id: str = "kaineone/Qwen3.5-4B-abliterated-GGUF"
    chat_timeout_s: float = 60.0
    chat_think: Optional[bool] = False
    # Bearer token for a keyed model server (e.g. Unsloth Studio). DERIVED from
    # the lingua key at cycle startup so the baseline authenticates to the SAME
    # server as the organ; None for a keyless server (llama-server).
    chat_api_key: Optional[str] = None
    # Used by MemoryProbeRunner to decide whether a probe is "out-of-context"
    # — anything older than this is fair game.
    llm_context_window_seconds: int = 3600
    # When true, _embedder_default raises instead of falling back to HashEmbedder
    # if SentenceTransformerTextEmbedder fails to load. Default false so
    # minimal/CPU installs without sentence-transformers still run.
    require_semantic_embedder: bool = False
    # Sidecar observers.
    observers: ObserversConfig = field(default_factory=ObserversConfig)
    # Welfare observer parameters (interoceptive-distress detector).
    welfare: WelfareConfig = field(default_factory=WelfareConfig)
    # Individuation boundary permutation-test instrument (Guardian-only,
    # operator-run at merge points; never invoked from the cognitive cycle).
    individuation: IndividuationConfig = field(default_factory=IndividuationConfig)

    @classmethod
    def from_mapping(
        cls,
        data: dict[str, Any] | None,
        *,
        lingua_model_id: str | None = None,
        lingua_api_key: str | None = None,
    ) -> "EvaluationConfig":
        data = dict(data or {})
        # The A/B-divergence baseline runs this model bare (no architecture), so it
        # MUST equal the language organ's model — otherwise the divergence measures
        # a model difference instead of the architecture's conditioning. Derive it
        # from [lingua].model_id; an explicit value that DIFFERS is a fail-closed
        # error (a silently-mismatched baseline invalidates the core metric).
        explicit_model = data.get("chat_model_id")
        if (
            explicit_model is not None
            and lingua_model_id is not None
            and str(explicit_model) != str(lingua_model_id)
        ):
            raise ValueError(
                f"evaluation.chat_model_id ({explicit_model!r}) must equal the "
                f"language organ's [lingua].model_id ({lingua_model_id!r}): the "
                "A/B-divergence baseline must run the SAME model as Lingua, or the "
                "divergence measures a model difference instead of the architecture. "
                "Remove evaluation.chat_model_id (it derives from lingua) or set "
                "them equal."
            )
        chat_model_id = str(explicit_model or lingua_model_id or cls.chat_model_id)
        return cls(
            enabled=bool(data.get("enabled", cls.enabled)),
            workspace_trajectory=bool(
                data.get("workspace_trajectory", cls.workspace_trajectory)
            ),
            ab_divergence=bool(data.get("ab_divergence", cls.ab_divergence)),
            ab_sample_rate=float(data.get("ab_sample_rate", cls.ab_sample_rate)),
            voice_tracking=bool(data.get("voice_tracking", cls.voice_tracking)),
            module_attribution=bool(
                data.get("module_attribution", cls.module_attribution)
            ),
            affect_correlation=bool(
                data.get("affect_correlation", cls.affect_correlation)
            ),
            memory_probes=bool(data.get("memory_probes", cls.memory_probes)),
            memory_probe_interval_minutes=int(
                data.get(
                    "memory_probe_interval_minutes", cls.memory_probe_interval_minutes
                )
            ),
            proactive_audit=bool(data.get("proactive_audit", cls.proactive_audit)),
            eidolon_accuracy=bool(data.get("eidolon_accuracy", cls.eidolon_accuracy)),
            eidolon_accuracy_interval_hours=int(
                data.get(
                    "eidolon_accuracy_interval_hours",
                    cls.eidolon_accuracy_interval_hours,
                )
            ),
            sleep_snapshots=bool(data.get("sleep_snapshots", cls.sleep_snapshots)),
            paths=EvaluationPaths.from_mapping(data.get("paths")),
            chat_url=str(data.get("chat_url", cls.chat_url)),
            chat_model_id=chat_model_id,
            chat_timeout_s=float(data.get("chat_timeout_s", cls.chat_timeout_s)),
            chat_think=(
                None
                if data.get("chat_think", cls.chat_think) is None
                else bool(data.get("chat_think", cls.chat_think))
            ),
            # Same server as the organ → same key; derive from lingua, allow an
            # explicit override. None for a keyless server.
            chat_api_key=(data.get("chat_api_key") or lingua_api_key),
            llm_context_window_seconds=int(
                data.get(
                    "llm_context_window_seconds", cls.llm_context_window_seconds
                )
            ),
            require_semantic_embedder=bool(
                data.get("require_semantic_embedder", cls.require_semantic_embedder)
            ),
            observers=ObserversConfig.from_mapping(data.get("observers")),
            welfare=WelfareConfig.from_mapping(data.get("welfare")),
            individuation=IndividuationConfig.from_mapping(data.get("individuation")),
        )


def load_evaluation_config(
    path: str | os.PathLike[str] | None = None,
    *,
    lingua_model_id: str | None = None,
    lingua_api_key: str | None = None,
    operator_path: str | os.PathLike[str] = OPERATOR_CONFIG_PATH,
) -> EvaluationConfig:
    # Read the shipped config deep-merged with the operator override (operator
    # values win), so SSD-redirected paths like [evaluation].trajectory_dir set
    # in config/kaine.operator.toml actually take effect here — not just the
    # shipped defaults.
    target = Path(path or SHIPPED_CONFIG_PATH)
    if not target.exists():
        return EvaluationConfig.from_mapping(
            None, lingua_model_id=lingua_model_id, lingua_api_key=lingua_api_key
        )
    merged = load_kaine_config(target, operator_path)
    return EvaluationConfig.from_mapping(
        merged.get("evaluation"),
        lingua_model_id=lingua_model_id,
        lingua_api_key=lingua_api_key,
    )


def load_research_event_log_config(
    path: str | os.PathLike[str] | None = None,
    *,
    operator_path: str | os.PathLike[str] = OPERATOR_CONFIG_PATH,
) -> ResearchEventLogConfig:
    """Load ``[research_event_log]`` from the shipped config deep-merged with the
    operator override (operator values win).

    Independent of ``[evaluation]`` so the curated research log (and the
    local-only raw archive) can be gated entirely on their own flags. Reading the
    merged config means an SSD-redirected ``[research_event_log].log_dir`` set in
    config/kaine.operator.toml takes effect here. Returns the all-disabled default
    when the shipped file or the block is absent.
    """
    target = Path(path or SHIPPED_CONFIG_PATH)
    if not target.exists():
        return ResearchEventLogConfig.from_mapping(None)
    merged = load_kaine_config(target, operator_path)
    return ResearchEventLogConfig.from_mapping(merged.get("research_event_log"))
