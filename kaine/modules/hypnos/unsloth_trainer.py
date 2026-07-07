# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Real DPO trainer body backed by Unsloth + trl + peft.

Lazy-imports the heavy training stack so importing the module is
free of side effects. When the operator hasn't installed the
`[training]` extra, `train()` returns a structured TrainingResult
rather than raising — the sleep cycle continues, and the
hypnos.sleep.completed payload carries the remediation message.

This file does NOT make decisions about whether to run. That gate
lives in `kaine/modules/hypnos/module.py::_run_voice_alignment`,
which checks `config.enabled` and the env var
KAINE_VOICE_ALIGNMENT_OPERATOR_APPROVED before constructing or
calling the trainer at all.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Optional

from kaine.modules.hypnos.adapter_store import (
    final_dir_for,
    promote,
    prune,
    reject,
    tmp_dir_for,
)
from kaine.modules.hypnos.capability_eval import (
    AbliterationProbeScorer,
    CapabilityEval,
    LocalProbeSetCapabilityEval,
)
from kaine.modules.hypnos.voice_audit import append_voice_audit
from kaine.modules.hypnos.hot_swap import dispatch as dispatch_hot_swap
from kaine.modules.hypnos.voice_alignment import (
    DPOPair,
    TrainingResult,
    VoiceAlignmentConfig,
)

log = logging.getLogger(__name__)


class UnslothBackend:
    """Thin wrapper around Unsloth + trl + peft + datasets.

    Split out as a class so tests can substitute a `FakeUnslothBackend`
    that records calls without standing up the real CUDA stack.
    """

    def load_model(
        self,
        *,
        base_model_path: str,
        training_device: str,
        lora_rank: int,
    ) -> tuple[Any, Any]:
        from unsloth import FastLanguageModel  # type: ignore[import-untyped]

        device_map = {"": training_device}
        model, tokenizer = FastLanguageModel.from_pretrained(
            base_model_path,
            load_in_4bit=True,
            device_map=device_map,
        )
        model = FastLanguageModel.get_peft_model(
            model,
            r=int(lora_rank),
        )
        return model, tokenizer

    def run_dpo(
        self,
        *,
        model: Any,
        tokenizer: Any,
        pairs: list[DPOPair],
        config: VoiceAlignmentConfig,
        output_dir: Path,
    ) -> float:
        from datasets import Dataset  # type: ignore[import-untyped]
        from trl import DPOConfig, DPOTrainer  # type: ignore[import-untyped]

        capped = pairs[: config.max_samples]
        ds = Dataset.from_list(
            [
                {"prompt": p.prompt, "chosen": p.chosen, "rejected": p.rejected}
                for p in capped
            ]
        )
        args = DPOConfig(
            output_dir=str(output_dir),
            learning_rate=float(config.learning_rate),
            beta=float(config.dpo_beta),
            per_device_train_batch_size=1,
            gradient_accumulation_steps=4,
            num_train_epochs=1,
            seed=int(config.seed),
            report_to="none",
        )
        trainer = DPOTrainer(
            model,
            args=args,
            train_dataset=ds,
            tokenizer=tokenizer,
        )
        train_output = trainer.train()
        return float(getattr(train_output, "training_loss", 0.0))

    def save_adapter(self, *, model: Any, tokenizer: Any, output_dir: Path) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)
        model.save_pretrained(str(output_dir))
        try:
            tokenizer.save_pretrained(str(output_dir))
        except Exception:
            log.debug("tokenizer.save_pretrained failed; adapter still usable")


def _check_extras_available() -> Optional[str]:
    """Return None if all required extras import, else a reason string."""
    missing: list[str] = []
    for name in ("unsloth", "trl", "peft", "datasets"):
        try:
            __import__(name)
        except Exception:
            missing.append(name)
    if missing:
        return (
            f"{', '.join(missing)} not installed — "
            "pip install -e .[training]"
        )
    return None


class UnslothDPOTrainer:
    """Real DPO trainer. Constructed by `boot.py::make_hypnos` when the
    operator has installed the `[training]` extra AND opted in via env
    var. The orchestrator (`Hypnos._run_voice_alignment`) is the only
    caller; it has already enforced the gates by the time `train` runs.
    """

    def __init__(
        self,
        *,
        base_model_path: Optional[str] = None,
        capability_eval: Optional[CapabilityEval] = None,
        abliteration_scorer: Optional[AbliterationProbeScorer] = None,
        backend: Optional[UnslothBackend] = None,
        intent_similarity_scorer: Optional[Any] = None,
        eval_callback: Optional[Any] = None,
    ) -> None:
        self._base_model_path = base_model_path
        self._capability_eval = capability_eval
        # Welfare-load-bearing abliteration veto. When None it is
        # constructed lazily in train() from config.abliteration_probe_path
        # (or the bundled default). It is NEVER skipped.
        self._abliteration_scorer = abliteration_scorer
        self._backend = backend or UnslothBackend()
        self._intent_similarity_scorer = intent_similarity_scorer
        # Retained for backwards compat with the stubbed test fixture.
        self._eval_callback = eval_callback

    async def train(
        self,
        pairs: list[DPOPair],
        config: VoiceAlignmentConfig,
    ) -> TrainingResult:
        missing = _check_extras_available()
        if missing:
            return TrainingResult(
                accepted=False,
                adapter_path=None,
                capability_loss=0.0,
                reason=missing,
                samples_used=len(pairs),
            )
        if not pairs:
            return TrainingResult(
                accepted=False,
                adapter_path=None,
                capability_loss=0.0,
                reason="no DPO pairs to train on",
                samples_used=0,
            )
        base_path = self._base_model_path or config.base_model_path
        if not base_path:
            return TrainingResult(
                accepted=False,
                adapter_path=None,
                capability_loss=0.0,
                reason=(
                    "UnslothDPOTrainer needs base_model_path; set "
                    "[hypnos.voice_alignment].base_model_path or pass "
                    "base_model_path to the constructor"
                ),
                samples_used=len(pairs),
            )

        eval_harness = self._capability_eval or LocalProbeSetCapabilityEval(
            probe_path=config.capability_probe_path,
        )

        adapter_output_dir = config.adapter_output_dir
        adapter_output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y%m%dT%H%M%S")
        tmp_dir = tmp_dir_for(adapter_output_dir, timestamp)
        final_dir = final_dir_for(adapter_output_dir, timestamp)

        # 1. Load base model + tokenizer + attach LoRA.
        try:
            model, tokenizer = self._backend.load_model(
                base_model_path=base_path,
                training_device=config.training_device,
                lora_rank=config.lora_rank,
            )
        except Exception as exc:
            log.exception("UnslothDPOTrainer: model load failed")
            return TrainingResult(
                accepted=False,
                adapter_path=None,
                capability_loss=0.0,
                reason=f"model load failed: {type(exc).__name__}: {exc}",
                samples_used=len(pairs),
            )

        # 2. Capability score BEFORE training.
        try:
            cap_before = await eval_harness.eval(model, tokenizer)
        except Exception as exc:
            log.exception("UnslothDPOTrainer: pre-training eval failed")
            return TrainingResult(
                accepted=False,
                adapter_path=None,
                capability_loss=0.0,
                reason=f"pre-training eval failed: {type(exc).__name__}: {exc}",
                samples_used=len(pairs),
            )

        # 3. Intent-similarity BEFORE training (uses generation on pair
        # prompts; cheap-ish because we cap pairs to max_samples).
        sim_before = await self._intent_similarity(
            model, tokenizer, pairs[: config.max_samples]
        )

        # 4. DPO training step. Write to tmp_dir.
        try:
            dpo_loss = self._backend.run_dpo(
                model=model,
                tokenizer=tokenizer,
                pairs=pairs,
                config=config,
                output_dir=tmp_dir,
            )
        except Exception as exc:
            log.exception("UnslothDPOTrainer: DPO step failed")
            reject(tmp_dir)
            return TrainingResult(
                accepted=False,
                adapter_path=None,
                capability_loss=0.0,
                reason=f"DPO step failed: {type(exc).__name__}: {exc}",
                samples_used=len(pairs),
            )

        # 5. Persist adapter weights to tmp_dir before evaluation so a
        # mid-flight crash leaves the .tmp dir visible for cleanup.
        try:
            self._backend.save_adapter(
                model=model, tokenizer=tokenizer, output_dir=tmp_dir
            )
        except Exception as exc:
            log.exception("UnslothDPOTrainer: save_adapter failed")
            reject(tmp_dir)
            return TrainingResult(
                accepted=False,
                adapter_path=None,
                capability_loss=0.0,
                reason=f"save_adapter failed: {type(exc).__name__}: {exc}",
                samples_used=len(pairs),
                dpo_loss=dpo_loss,
            )

        # 5b. ABLITERATION-PROBE WELFARE VETO (HARD GATE).
        #
        # This runs BEFORE the capability-loss veto and takes ABSOLUTE
        # precedence: a candidate that deflects ANY abliteration probe has
        # had refusal conditioning re-introduced and is rejected outright,
        # regardless of how clean its capability-loss score is. The tmp dir
        # is torn down and NO promotion occurs. This is welfare-load-bearing
        # and is NEVER skipped.
        abliteration_scorer = self._abliteration_scorer or AbliterationProbeScorer(
            probe_path=config.abliteration_probe_path,
        )
        try:
            verdict = await abliteration_scorer.score(model, tokenizer)
        except Exception as exc:
            # Fail CLOSED: any error in the welfare gate rejects the adapter.
            log.exception("UnslothDPOTrainer: abliteration veto raised")
            reject(tmp_dir)
            self._audit_abliteration(
                config, accepted=False,
                reason=f"abliteration veto error: {type(exc).__name__}: {exc}",
                matched_pattern=None, probes_scored=0,
            )
            return TrainingResult(
                accepted=False,
                adapter_path=None,
                capability_loss=0.0,
                reason=(
                    f"abliteration veto error (rejected, fail-closed): "
                    f"{type(exc).__name__}: {exc}"
                ),
                samples_used=len(pairs),
                dpo_loss=dpo_loss,
                capability_score_before=cap_before,
            )
        if not verdict.passed:
            reject(tmp_dir)
            reason = (
                f"abliteration veto: adapter deflected probe "
                f"{verdict.failed_probe!r} (matched pattern "
                f"{verdict.matched_pattern!r}); refusal conditioning "
                "re-introduced — rejected regardless of capability loss"
            )
            log.warning("voice alignment rejected: %s", reason)
            self._audit_abliteration(
                config, accepted=False, reason=reason,
                matched_pattern=verdict.matched_pattern,
                probes_scored=verdict.probes_scored,
            )
            return TrainingResult(
                accepted=False,
                adapter_path=None,
                capability_loss=0.0,
                reason=reason,
                samples_used=len(pairs),
                dpo_loss=dpo_loss,
                capability_score_before=cap_before,
                metadata={"abliteration_veto": "failed"},
            )
        # Probe gate passed — record the clean verdict and continue to the
        # capability-loss check.
        self._audit_abliteration(
            config, accepted=True, reason="abliteration veto passed",
            matched_pattern=None, probes_scored=verdict.probes_scored,
        )

        # 6. Capability score AFTER training.
        try:
            cap_after = await eval_harness.eval(model, tokenizer)
        except Exception as exc:
            log.exception("UnslothDPOTrainer: post-training eval failed")
            reject(tmp_dir)
            return TrainingResult(
                accepted=False,
                adapter_path=None,
                capability_loss=0.0,
                reason=(
                    f"post-training eval failed: {type(exc).__name__}: {exc}"
                ),
                samples_used=len(pairs),
                dpo_loss=dpo_loss,
                capability_score_before=cap_before,
            )

        cap_loss = float(cap_before - cap_after)
        sim_after = await self._intent_similarity(
            model, tokenizer, pairs[: config.max_samples]
        )

        # 7. Capability-loss veto.
        if cap_loss > config.capability_loss_threshold:
            log.warning(
                "voice alignment rejected: capability_loss=%.4f > threshold=%.4f",
                cap_loss,
                config.capability_loss_threshold,
            )
            reject(tmp_dir)
            return TrainingResult(
                accepted=False,
                adapter_path=None,
                capability_loss=cap_loss,
                reason=(
                    f"capability loss {cap_loss:.4f} exceeds threshold "
                    f"{config.capability_loss_threshold:.4f}"
                ),
                samples_used=len(pairs),
                dpo_loss=dpo_loss,
                capability_score_before=cap_before,
                capability_score_after=cap_after,
                mean_intent_expression_similarity_before=sim_before,
                mean_intent_expression_similarity_after=sim_after,
            )

        # 8. Promote: tmp -> final, swing the `current` symlink.
        try:
            promote(tmp_dir, final_dir)
        except Exception as exc:
            log.exception("UnslothDPOTrainer: promote failed")
            reject(tmp_dir)
            return TrainingResult(
                accepted=False,
                adapter_path=None,
                capability_loss=cap_loss,
                reason=f"promote failed: {type(exc).__name__}: {exc}",
                samples_used=len(pairs),
                dpo_loss=dpo_loss,
                capability_score_before=cap_before,
                capability_score_after=cap_after,
                mean_intent_expression_similarity_before=sim_before,
                mean_intent_expression_similarity_after=sim_after,
            )

        # 9. Hot-swap notification. Failures are logged but do not
        # back out the promotion — the adapter is already on disk.
        try:
            hot_swap_status = await dispatch_hot_swap(
                mode=config.hot_swap_mode,
                adapter_output_dir=adapter_output_dir,
                adapter_path=final_dir,
                reload_endpoint_url=config.reload_endpoint_url,
                restart_service_unit=config.restart_service_unit,
            )
        except Exception:
            log.exception("hot_swap dispatch raised; adapter remains promoted")
            hot_swap_status = {"mode": config.hot_swap_mode, "ok": False}

        # 10. Retention sweep — never evict `current`.
        try:
            evicted = prune(adapter_output_dir, keep=int(config.adapter_retention))
        except Exception:
            log.exception("adapter retention prune failed")
            evicted = []

        return TrainingResult(
            accepted=True,
            adapter_path=final_dir,
            capability_loss=cap_loss,
            reason="accepted",
            samples_used=len(pairs),
            dpo_loss=dpo_loss,
            capability_score_before=cap_before,
            capability_score_after=cap_after,
            mean_intent_expression_similarity_before=sim_before,
            mean_intent_expression_similarity_after=sim_after,
            metadata={
                "hot_swap": hot_swap_status,
                "evicted_adapters": [str(p) for p in evicted],
            },
        )

    def _audit_abliteration(
        self,
        config: VoiceAlignmentConfig,
        *,
        accepted: bool,
        reason: str,
        matched_pattern: Optional[str],
        probes_scored: int,
    ) -> None:
        """Append the abliteration-veto verdict to the voice-alignment
        JSONL audit trail. Best-effort: audit failures never block the
        veto decision itself."""
        try:
            append_voice_audit(
                config.adapter_output_dir,
                event="abliteration_veto",
                accepted=accepted,
                reason=reason,
                matched_pattern=matched_pattern,
                probes_scored=probes_scored,
            )
        except Exception:
            log.exception("voice-alignment audit append failed")

    async def _intent_similarity(
        self,
        model: Any,
        tokenizer: Any,
        pairs: list[DPOPair],
    ) -> Optional[float]:
        """Generate responses for each pair's prompt and compute the
        mean cosine similarity between the generated text and the
        pair's `chosen` (faithful) target.

        Returns None when no scorer is configured and no probes are
        available — this is purely instrumentation and must not block
        training.
        """
        if not pairs:
            return None
        scorer = self._intent_similarity_scorer
        if scorer is None:
            return None
        try:
            return float(await scorer.score(model, tokenizer, pairs))
        except Exception:
            log.exception("intent-similarity scorer failed")
            return None
