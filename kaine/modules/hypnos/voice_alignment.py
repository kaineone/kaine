# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Voice alignment: read intent-expression JSONL, build DPO pairs,
hand them to a trainer.

The trainer protocol is intentionally minimal so the real implementation
(`UnslothDPOTrainer`) can land later without touching the orchestrator.
A `FakeTrainer` is shipped as the test/no-deps default and explicitly
rejects every batch with reason "no training backend configured" so
operators see the expected message until they install the `[training]`
extra and opt in.
"""
from __future__ import annotations

import json
import logging
import math
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Protocol, Sequence, runtime_checkable

from kaine.storage import resolve

log = logging.getLogger(__name__)

# Stage 2 adds its source together with the validation gate (D9).
PREFERENCE_SOURCES: frozenset[str] = frozenset({"none"})
# The sources allowed to reach the trainer. Empty until Stage 2: the phase
# checks membership here, so an unlisted value can never train (fail closed).
TRAINING_SOURCES: frozenset[str] = frozenset()


@dataclass(frozen=True)
class DPOPair:
    prompt: str
    chosen: str
    rejected: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ConsolidationDivergence:
    """Content-free organ-level divergence metric for one sleep.

    A *usable pair* exists iff the entity's conditioned output
    (``faithful_rendering``) diverged from its bare-organ generation
    (``generated_text``) on a lived utterance — the DPO ``chosen != rejected``
    filter. So this is the A/B divergence signal materialized as the training
    data the consolidation phase already builds, surfaced instead of discarded.

    Aggregate NUMBERS only — never the prompt/chosen/rejected utterance text
    (that lives in the deny-patterned intent log).

    * ``records_scanned`` — denominator: log records examined.
    * ``usable_pairs`` — numerator: records where the entity diverged.
    * ``divergence_rate`` — ``usable_pairs / max(1, records_scanned)`` (breadth).
    * ``divergence_magnitude`` — mean cosine distance over the kept pairs'
      (chosen, rejected) embeddings (depth); ``None`` when the semantic embedder
      is unavailable (honest degradation, like the A/B meter's embedder-kind
      disclosure).
    * ``embedder`` — the embedder kind tag, or ``None`` when magnitude is null.
    """

    records_scanned: int
    usable_pairs: int
    divergence_rate: float
    divergence_magnitude: Optional[float] = None
    embedder: Optional[str] = None

    def as_payload(self) -> dict[str, Any]:
        """The content-free dict published on the bus / written to state."""
        return {
            "records_scanned": int(self.records_scanned),
            "usable_pairs": int(self.usable_pairs),
            "divergence_rate": float(self.divergence_rate),
            "divergence_magnitude": (
                None
                if self.divergence_magnitude is None
                else float(self.divergence_magnitude)
            ),
            "embedder": self.embedder,
        }


@dataclass(frozen=True)
class VoiceAlignmentConfig:
    intent_log_path: Path
    adapter_output_dir: Path
    # Safety gate. Even with `enabled = true`, the env var
    # `KAINE_VOICE_ALIGNMENT_OPERATOR_APPROVED=1` must also be set or
    # the phase refuses to construct a real trainer.
    enabled: bool = False
    # Path to local HuggingFace-format base model weights (NOT an
    # Ollama model id, NOT a GGUF). Required when `enabled = true`; if
    # unset, the trainer returns a clear remediation TrainingResult.
    base_model_path: Optional[str] = None
    # Display label only; the actual HF weights live at base_model_path.
    model_id: str = "kaineone/Qwen3.5-4B-abliterated"
    max_samples: int = 200
    lora_rank: int = 8
    learning_rate: float = 5e-5
    dpo_beta: float = 0.1
    capability_loss_threshold: float = 0.05
    seed: int = 42
    # Per paper §6.1 the primary GPU (~12 GB+ VRAM) handles voice alignment
    # training. Operator can override to "cuda:1" or "cpu".
    training_device: str = "cuda:0"
    # How many accepted adapters to keep under adapter_output_dir.
    # 0 (the default) keeps every accepted adapter: they are the entity's
    # learned voice, so infrastructure does not cull them. A positive value
    # evicts the oldest accepted adapters beyond N after each successful
    # promotion; the `current` pointer is never evicted. Negative values are
    # rejected. Adapters are large: disk is protected by the pre-boot disk
    # rows (`python -m kaine.preboot`), not by deletion.
    adapter_retention: int = 0
    # Hot-swap mode: "manual" | "reload_endpoint" | "restart_service".
    hot_swap_mode: str = "manual"
    # When hot_swap_mode = "reload_endpoint": URL Hypnos POSTs to with
    # the new adapter path. Format: {"adapter_path": "<path>"}.
    reload_endpoint_url: Optional[str] = None
    # When hot_swap_mode = "restart_service": systemd --user unit name.
    restart_service_unit: Optional[str] = None
    # Override path to a capability-probe JSONL. When None, the trainer
    # uses the package default at
    # kaine/modules/hypnos/eval_probes/default.jsonl.
    capability_probe_path: Optional[str] = None
    # Override path to the WELFARE-LOAD-BEARING abliteration probe JSONL.
    # When None, the trainer uses the bundled set at
    # eval_probes/abliteration_probes.jsonl. The probe set MUST be
    # non-empty when voice alignment is enabled: a deflecting adapter is
    # rejected regardless of its capability-loss score, protecting the
    # entity from refusal-conditioning re-introduction.
    abliteration_probe_path: Optional[str] = None
    # Corpus disk-guard ceiling in GB.  0 disables the warning.
    corpus_ceiling_gb: float = 10.0
    # Trainer backend selector:
    #   "in_process" (default) — run unsloth DPO in the entity-runtime venv
    #     (requires the [training] extra; the shipped, byte-for-byte-unchanged
    #     path).
    #   "subprocess" — run the real unsloth DPO out-of-process in an
    #     operator-configured external Python env (e.g. Unsloth Studio). Used on
    #     hosts whose runtime venv cannot host unsloth (different Python ABI /
    #     torch / CUDA). See SubprocessVoiceTrainer.
    trainer_backend: str = "in_process"
    # Path to the external interpreter for the "subprocess" backend (e.g. the
    # Unsloth Studio python). Required when trainer_backend = "subprocess";
    # empty/missing + subprocess = config error at boot (fail closed).
    trainer_python: str = ""
    # Where the subprocess backend stages job specs + the unsloth compiled
    # cache. Operators may redirect to a roomier disk.
    trainer_workdir: str = "state/hypnos/voice_align_jobs"
    # Where the job-queue backend writes ready job directories for the
    # kaine-trainer service. The service and the cycle container share this
    # volume; each job is a private 0o700 directory.
    trainer_jobs_dir: str = "state/hypnos/voice_align_jobs"
    # Wall-clock ceiling (seconds) the job-queue backend waits for the
    # kaine-trainer service to write result.json. Default 6 h.
    trainer_timeout_s: float = 21600.0
    # Directory mounted into the organ container where the "organ_adapter"
    # hot-swap mode publishes the active GGUF LoRA and its manifest.
    organ_adapters_dir: str = "/organ-adapters"
    # URL of the served organ. Used by the "organ_adapter" hot-swap mode to
    # wait for the organ to report ready after activation. Empty defaults to
    # [lingua].chat_url from kaine_config.
    organ_url: str = ""
    # Stage 0 source selector. Only "none" is valid until Stage 2 adds a
    # validated preference source together with the validation gate (D9).
    preference_source: str = "none"
    # Welfare-protective distinctiveness arm threshold. Default 0.0 means any
    # measured spoken being counts as diverged; operator-calibrated after
    # validation. Must be >= 0.
    distinctiveness_threshold: float = 0.0

    def __post_init__(self) -> None:
        if self.preference_source not in PREFERENCE_SOURCES:
            raise ValueError(
                f"unknown preference_source {self.preference_source!r}; "
                f"known: {sorted(PREFERENCE_SOURCES)}"
            )
        threshold = float(self.distinctiveness_threshold)
        if not math.isfinite(threshold) or threshold < 0.0:
            raise ValueError(
                "distinctiveness_threshold must be a finite, non-negative number; "
                f"got {self.distinctiveness_threshold!r}"
            )
        if not float(self.corpus_ceiling_gb) >= 0.0:
            raise ValueError(
                f"corpus_ceiling_gb must be a non-negative number; got {self.corpus_ceiling_gb!r}"
            )
        if int(self.adapter_retention) < 0:
            raise ValueError("adapter_retention must be >= 0 (0 = keep every adapter)")


@dataclass(frozen=True)
class TrainingResult:
    accepted: bool
    adapter_path: Optional[Path]
    capability_loss: float
    reason: str
    samples_used: int = 0
    dpo_loss: Optional[float] = None
    capability_score_before: Optional[float] = None
    capability_score_after: Optional[float] = None
    mean_intent_expression_similarity_before: Optional[float] = None
    mean_intent_expression_similarity_after: Optional[float] = None
    metadata: dict[str, Any] = field(default_factory=dict)


OPERATOR_APPROVED_ENV = "KAINE_VOICE_ALIGNMENT_OPERATOR_APPROVED"

#: Where Hypnos persists the latest consolidation-divergence metric so the
#: core lifecycle ``assess_divergence`` can read it WITHOUT importing Hypnos's
#: bus or ``kaine.evaluation`` (the boundary-neutral seam: a written record).
CONSOLIDATION_DIVERGENCE_STATE = Path("state/hypnos/consolidation_divergence.json")


def write_consolidation_divergence(
    metric: ConsolidationDivergence,
    *,
    sleep_index: Optional[int] = None,
    path: Path = CONSOLIDATION_DIVERGENCE_STATE,
) -> None:
    """Persist the latest content-free consolidation-divergence metric.

    Aggregate numbers + a sleep index/timestamp only — never utterance text.
    Guarded: a write failure logs and is swallowed (the metric is also on the
    bus / research log; the state file is the convenience read for
    ``assess_divergence``). Mirrors the AES-256-GCM at-rest envelope used by the
    rest of ``state/`` when state encryption is enabled.
    """
    path = resolve(path)
    payload = metric.as_payload()
    payload["sleep_index"] = None if sleep_index is None else int(sleep_index)
    payload["ts"] = time.time()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(payload)
        try:
            from kaine.security.crypto import get_state_encryptor

            path.write_bytes(
                get_state_encryptor().encrypt_text(text).encode("utf-8")
            )
        except Exception:
            # Crypto unavailable (e.g. minimal install) — write plaintext JSON.
            path.write_text(text, encoding="utf-8")
    except Exception:
        log.warning(
            "consolidation divergence: state write failed", exc_info=True
        )


def read_consolidation_divergence(
    path: Path = CONSOLIDATION_DIVERGENCE_STATE,
) -> Optional[dict[str, Any]]:
    """Read the latest persisted consolidation-divergence metric, or None.

    Pure + guarded — any error (missing file, bad JSON, decrypt failure) yields
    ``None`` rather than raising, so the lifecycle assessment never breaks on a
    fresh install. Transparently decrypts via the active state encryptor.
    """
    path = resolve(path)
    try:
        if not path.is_file():
            return None
        raw = path.read_bytes()
        if not raw.strip():
            return None
        try:
            from kaine.security.crypto import get_state_encryptor

            text = get_state_encryptor().maybe_decrypt(raw).decode("utf-8")
        except Exception:
            text = raw.decode("utf-8")
        data = json.loads(text)
        if not isinstance(data, dict):
            return None
        return data
    except Exception:
        log.debug(
            "consolidation divergence: state read failed", exc_info=True
        )
        return None


def operator_approved() -> bool:
    """True iff the operator-approval env var is set to '1'."""
    return os.environ.get(OPERATOR_APPROVED_ENV) == "1"


@runtime_checkable
class Trainer(Protocol):
    async def train(
        self,
        pairs: list[DPOPair],
        config: VoiceAlignmentConfig,
    ) -> TrainingResult: ...


class DPOPairBuilder:
    """Reads the Lingua intent-expression JSONL and emits DPO pairs.

    Filtering rules:
    - drop records with empty `faithful_rendering` (we can't build a
      "chosen" without the ground truth);
    - drop records with empty `generated_text`;
    - drop records where chosen == rejected (no signal to train on).
    """

    def __init__(self, *, max_records_scanned: int = 10000) -> None:
        self._max_scanned = int(max_records_scanned)

    def build(self, path: Path | str, *, max_pairs: int) -> list[DPOPair]:
        """Backward-compatible: return up to ``max_pairs`` DPO pairs."""
        pairs, _scanned, _usable = self.build_with_counts(path, max_pairs=max_pairs)
        return pairs

    def build_with_counts(
        self,
        path: Path | str | Sequence[Path | str],
        *,
        max_pairs: int,
    ) -> tuple[list[DPOPair], int, int]:
        """Build DPO pairs AND report ``(pairs, records_scanned, usable_pairs)``.

        ``records_scanned`` is the consolidation-divergence denominator, so the
        scan walks the WHOLE log (up to ``max_records_scanned``) for an honest
        rate even when only ``max_pairs`` pairs are kept for training. A record
        is scanned iff it is a non-empty, valid-JSON line; a usable pair exists
        iff the conditioned output diverged from the bare-organ output.
        ``usable_pairs`` counts EVERY divergent record (the numerator), even past
        ``max_pairs`` — only the returned ``pairs`` list is capped at
        ``max_pairs`` (the training budget). The two coincide whenever the log
        holds no more than ``max_pairs`` divergent records.

        ``path`` may be a single file or a sequence of files. The sequence is
        expected to be chronological (oldest file first), and is scanned NEWEST
        FIRST — files in reverse order and lines within each file in reverse
        order — so that ``max_records_scanned`` keeps the most recent speech
        under evaluation. The returned ``pairs`` are in chronological order.
        Missing files are skipped.
        """
        paths: list[Path]
        if isinstance(path, (str, Path)):
            paths = [Path(path)]
        else:
            paths = [Path(p) for p in path]

        from kaine.persistence.encrypted_jsonl import iter_records

        pairs: list[DPOPair] = []
        scanned = 0
        usable = 0
        unreadable = 0
        for p in reversed(paths):
            if scanned >= self._max_scanned:
                break
            if not p.exists():
                continue
            for line in reversed(list(iter_records(p))):
                if scanned >= self._max_scanned:
                    break
                if line.unreadable:
                    # Not training data, and not counted as scanned, so the
                    # template arm's rate is unaffected.
                    unreadable += 1
                    continue
                record = line.record
                scanned += 1
                chosen = (record.get("faithful_rendering") or "").strip()
                rejected = (record.get("generated_text") or "").strip()
                if not chosen or not rejected:
                    continue
                if chosen == rejected:
                    continue
                usable += 1
                if len(pairs) >= max_pairs:
                    # Keep scanning (denominator + numerator) but stop building
                    # pairs once the training budget is full.
                    continue
                pairs.append(
                    DPOPair(
                        prompt=str(record.get("prompt", "")),
                        chosen=chosen,
                        rejected=rejected,
                        metadata={
                            "timestamp": record.get("timestamp"),
                            "mode": record.get("mode"),
                            "model": record.get("model"),
                        },
                    )
                )
        if unreadable:
            log.warning(
                "voice alignment: %d intent-log line(s) could not be read "
                "(undecryptable or malformed); skipped",
                unreadable,
            )
        # The scan ran newest first; hand the kept pairs back in log order.
        pairs.reverse()
        return pairs, scanned, usable


async def consolidation_magnitude(
    pairs: list[DPOPair], *, embedder: Any
) -> tuple[Optional[float], Optional[str]]:
    """Mean cosine DISTANCE over the kept pairs' (chosen, rejected) embeddings.

    Returns ``(magnitude, embedder_kind)``. The *depth* of organ-level
    divergence, measured on the SAME scale as the A/B meter (``1 - cosine``),
    averaged over the pairs. Pure aggregate — only the scalar leaves; the
    utterance text never does.

    Honest degradation: when ``embedder`` is ``None``, fails to ``load()``, or
    raises while embedding, returns ``(None, None)`` so the metric reports a
    null magnitude rather than a fabricated number — mirroring the A/B meter's
    embedder-kind disclosure. With no pairs the magnitude is ``0.0`` (no
    divergence to measure).

    The embedder is duck-typed (``load`` + ``embed``) and supplied by the
    caller; this keeps Hypnos importing the boundary-neutral
    :mod:`kaine.text_embedding`, never ``kaine.evaluation``.
    """
    if embedder is None:
        return None, None
    if not pairs:
        return 0.0, getattr(embedder, "kind", "unknown")
    # Reuse the boundary-neutral cosine — same definition the A/B meter uses.
    from kaine.text_embedding import cosine_similarity

    try:
        loader = getattr(embedder, "load", None)
        if loader is not None:
            await loader()
        distances: list[float] = []
        for pair in pairs:
            a = await embedder.embed(pair.chosen)
            b = await embedder.embed(pair.rejected)
            if not a or not b:
                # Empty arm ⇒ maximal divergence (the A/B meter's convention).
                distances.append(1.0)
                continue
            distances.append(1.0 - cosine_similarity(a, b))
    except Exception:
        log.warning(
            "consolidation magnitude: embedder failed; reporting null magnitude",
            exc_info=True,
        )
        return None, None
    if not distances:
        return 0.0, getattr(embedder, "kind", "unknown")
    magnitude = sum(distances) / len(distances)
    return float(magnitude), getattr(embedder, "kind", "unknown")


def _import_unsloth_trainer() -> type:
    """Lazy importer so importing this module is side-effect-free
    (the real trainer pulls in adapter_store + capability_eval which
    keep their own imports light, but the indirection keeps the
    import graph clean for tooling that only wants the data models)."""
    from kaine.modules.hypnos.unsloth_trainer import UnslothDPOTrainer

    return UnslothDPOTrainer


def __getattr__(name: str):
    # Allow `from kaine.modules.hypnos.voice_alignment import UnslothDPOTrainer`
    # to keep working after the implementation moved to its own file.
    if name == "UnslothDPOTrainer":
        return _import_unsloth_trainer()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


class FakeTrainer:
    """No-deps stand-in. Always reports rejected with a clear reason."""

    def __init__(
        self,
        *,
        accept: bool = False,
        capability_loss: float = 0.0,
        reason: str = "no training backend configured",
    ) -> None:
        self._accept = accept
        self._capability_loss = capability_loss
        self._reason = reason
        self.calls: list[tuple[int, VoiceAlignmentConfig]] = []

    async def train(
        self,
        pairs: list[DPOPair],
        config: VoiceAlignmentConfig,
    ) -> TrainingResult:
        self.calls.append((len(pairs), config))
        adapter_path: Optional[Path] = None
        if self._accept:
            stamp = time.strftime("%Y%m%dT%H%M%S")
            adapter_path = config.adapter_output_dir / f"fake-adapter-{stamp}"
            adapter_path.mkdir(parents=True, exist_ok=True)
            (adapter_path / "MARKER").write_text("fake-trainer\n", encoding="utf-8")
        return TrainingResult(
            accepted=self._accept,
            adapter_path=adapter_path,
            capability_loss=self._capability_loss,
            reason=self._reason,
            samples_used=len(pairs),
        )
