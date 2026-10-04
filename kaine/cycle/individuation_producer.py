# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Individuation producer core.

Captures the birth reference and runs one individuation look.  All
dependencies are injected; this module has no organ, scheduler or wiring.
"""

from __future__ import annotations

import asyncio
import dataclasses
import secrets
import time
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from kaine.cycle.individuation_probe import ProbeFailure
from kaine.lifecycle.individuation_stats import (
    decide,
    effect_size_h,
    permutation_test,
    required_permutations,
    spending_alpha,
)
from kaine.lifecycle.individuation_store import (
    REFERENCE_KINDS,
    IndividuationPaths,
    IndividuationStoreError,
    Ledger,
    LedgerUnreadable,
    ProbeSample,
    ReferenceDoc,
    ReferenceUnreadable,
    battery_digest_of,
    build_report,
    conditioning_digest,
    copy_birth_adapter,
    load_ledger,
    load_reference,
    new_reference_id,
    save_ledger,
    save_reference,
)


@dataclass(frozen=True)
class ProducerSettings:
    """Parameters for one individuation producer."""

    n_reference: int = 16
    n_current: int = 8
    max_tokens: int = 160
    alpha_total: float = 0.05
    b_max: int = 2_000_000
    effect_min: float = 0.0


@dataclass(frozen=True)
class LookOutcome:
    """Result of one individuation look."""

    outcome: str
    reason: str | None
    report: dict | None
    significant: bool = False
    effect_size_h: float | None = None


class IndividuationCore:
    """Dependency-injected individuation measurement core."""

    def __init__(
        self,
        *,
        paths: IndividuationPaths,
        settings: ProducerSettings,
        battery: Sequence[str],
        sampler: Callable[[str, int], Awaitable[ProbeSample | ProbeFailure]],
        embed: Callable[[str], Awaitable[Any]],
        embedder_id: str,
        conditions: Callable[[], dict],
        conditioning_inputs: Callable[
            [], tuple[str | None, list[str], list[str]]
        ],
        born_at: Callable[[], str | None],
        birth_adapter_file: Callable[[], Path | None],
        report_sink: Any,
        publish: Callable[[dict], Awaitable[None]],
        abort_reason: Callable[[], str | None],
        rng: np.random.Generator | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        entity_name: str = "",
    ) -> None:
        self._paths = paths
        self._settings = settings
        self._battery = tuple(battery)
        self._sampler = sampler
        self._embed = embed
        self._embedder_id = embedder_id
        self._conditions = conditions
        self._conditioning_inputs = conditioning_inputs
        self._born_at = born_at
        self._birth_adapter_file = birth_adapter_file
        self._report_sink = report_sink
        self._publish = publish
        self._abort_reason = abort_reason
        self._rng = rng if rng is not None else np.random.default_rng()
        self._now = now
        self._entity_name = entity_name

    async def capture_reference(
        self, kind: str, *, regenerate: bool = False
    ) -> tuple[ReferenceDoc | None, str | None]:
        """Capture and persist a new reference document.

        Nothing is written when the capture aborts, fails, or the conditioning changes
        mid-capture; an existing reference is replaced only with ``regenerate=True``;
        the birth adapter is copied only for a ``birth`` reference.
        """
        if kind not in REFERENCE_KINDS:
            raise ValueError(f"Invalid reference kind {kind!r}")

        if regenerate and kind == "birth":
            raise ValueError(
                "regenerating a birth reference needs the stored birth configuration, "
                "which is not supported yet"
            )

        if not regenerate and self._paths.reference.exists():
            raise IndividuationStoreError(
                "a reference already exists; pass regenerate=True to replace it"
            )

        if (reason := self._abort_reason()) is not None:
            return (None, reason)

        adapter_sha, values, norms = self._conditioning_inputs()
        digest_before = conditioning_digest(
            adapter_sha=adapter_sha, values=values, norms=norms
        )

        captured_samples: list[tuple[ProbeSample, ...]] = []
        for prompt in self._battery:
            prompt_samples: list[ProbeSample] = []
            for _ in range(self._settings.n_reference):
                if (reason := self._abort_reason()) is not None:
                    return (None, reason)
                seed = secrets.randbits(31)
                result = await self._sampler(prompt, seed)
                if isinstance(result, ProbeFailure):
                    return (None, result.reason)
                prompt_samples.append(result)
            captured_samples.append(tuple(prompt_samples))

        adapter_sha_after, values_after, norms_after = self._conditioning_inputs()
        digest_after = conditioning_digest(
            adapter_sha=adapter_sha_after, values=values_after, norms=norms_after
        )
        if digest_after != digest_before:
            return (None, "conditioning_changed_mid_run")

        if kind == "birth":
            copy_birth_adapter(self._paths, self._birth_adapter_file())

        doc = ReferenceDoc(
            reference_id=new_reference_id(),
            reference_kind=kind,
            captured_at=self._now().isoformat(),
            born_at=self._born_at(),
            battery=self._battery,
            battery_digest=battery_digest_of(self._battery),
            conditions=self._conditions(),
            conditioning={
                "adapter_sha": adapter_sha or "none",
                "identity_values": values[:5],
                "identity_norms": norms[:5],
            },
            samples=tuple(captured_samples),
        )
        save_reference(self._paths, doc, overwrite=regenerate)

        existing = load_ledger(self._paths)
        if existing is None:
            ledger = Ledger(
                reference_id=doc.reference_id,
                last_look_conditions_digest=digest_before,
            )
        else:
            ledger = dataclasses.replace(existing, reference_id=doc.reference_id)
        save_ledger(self._paths, ledger)

        return (doc, None)

    async def look(
        self, *, warmed_up: bool, lived_seconds: float, lived_ticks: int
    ) -> LookOutcome:
        """Run one individuation look."""
        start = time.perf_counter()

        # 1. Ledger
        try:
            ledger = load_ledger(self._paths)
        except LedgerUnreadable:
            report = await self._inconclusive(
                "ledger_unreadable",
                ref_id="unknown",
                k=None,
                start=start,
            )
            return LookOutcome("inconclusive", "ledger_unreadable", report)

        # 2. Reference
        try:
            ref = load_reference(self._paths)
        except ReferenceUnreadable:
            k = ledger.looks_completed + 1 if ledger is not None else None
            report = await self._inconclusive(
                "reference_unreadable",
                ref_id="unknown",
                k=k,
                start=start,
            )
            return LookOutcome("inconclusive", "reference_unreadable", report)

        if ref is None:
            k = ledger.looks_completed + 1 if ledger is not None else None
            report = await self._inconclusive(
                "no_reference",
                ref_id="unknown",
                k=k,
                start=start,
            )
            return LookOutcome("inconclusive", "no_reference", report)

        if ledger is None:
            report = await self._inconclusive(
                "ledger_missing",
                ref_id=ref.reference_id,
                k=None,
                start=start,
                ref=ref,
            )
            return LookOutcome("inconclusive", "ledger_missing", report)

        k = ledger.looks_completed + 1

        # 3. Battery
        if ref.battery_digest != battery_digest_of(self._battery):
            report = await self._inconclusive(
                "battery_changed",
                ref_id=ref.reference_id,
                k=k,
                start=start,
                ref=ref,
            )
            return LookOutcome("inconclusive", "battery_changed", report)

        # 4. Unchanged being
        adapter_sha, values, norms = self._conditioning_inputs()
        digest_before = conditioning_digest(
            adapter_sha=adapter_sha, values=values, norms=norms
        )
        if digest_before == ledger.last_look_conditions_digest:
            return LookOutcome("skipped", "unchanged", None)

        # 5. Threshold
        alpha_k = spending_alpha(k, self._settings.alpha_total)
        B = required_permutations(alpha_k, self._settings.b_max)
        if B is None:
            report = await self._inconclusive(
                "alpha_unresolvable",
                ref_id=ref.reference_id,
                k=k,
                start=start,
                ref=ref,
            )
            return LookOutcome("inconclusive", "alpha_unresolvable", report)

        # 6. Sampling
        current_samples: list[tuple[ProbeSample, ...]] = []
        for prompt in self._battery:
            prompt_samples: list[ProbeSample] = []
            for _ in range(self._settings.n_current):
                if (reason := self._abort_reason()) is not None:
                    report = await self._inconclusive(
                        reason,
                        ref_id=ref.reference_id,
                        k=k,
                        start=start,
                        ref=ref,
                    )
                    return LookOutcome("inconclusive", reason, report)
                seed = secrets.randbits(31)
                result = await self._sampler(prompt, seed)
                if isinstance(result, ProbeFailure):
                    report = await self._inconclusive(
                        result.reason,
                        ref_id=ref.reference_id,
                        k=k,
                        start=start,
                        ref=ref,
                    )
                    return LookOutcome("inconclusive", result.reason, report)
                prompt_samples.append(result)
            current_samples.append(tuple(prompt_samples))

        # 7. Mid-run change
        adapter_sha_after, values_after, norms_after = self._conditioning_inputs()
        digest_after = conditioning_digest(
            adapter_sha=adapter_sha_after, values=values_after, norms=norms_after
        )
        if digest_after != digest_before:
            report = await self._inconclusive(
                "conditioning_changed_mid_run",
                ref_id=ref.reference_id,
                k=k,
                start=start,
                ref=ref,
            )
            return LookOutcome(
                "inconclusive", "conditioning_changed_mid_run", report
            )

        # 8. Embedding
        strata: list[tuple[np.ndarray, np.ndarray]] = []
        try:
            ref_vecs = [
                np.stack(
                    [
                        self._normalize(await self._embed(sample.text))
                        for sample in prompt_samples
                    ]
                )
                for prompt_samples in ref.samples
            ]
            cur_vecs = [
                np.stack(
                    [
                        self._normalize(await self._embed(sample.text))
                        for sample in prompt_samples
                    ]
                )
                for prompt_samples in current_samples
            ]
            strata = list(zip(ref_vecs, cur_vecs))
        except Exception:
            report = await self._inconclusive(
                "embedding_failed",
                ref_id=ref.reference_id,
                k=k,
                start=start,
                ref=ref,
            )
            return LookOutcome("inconclusive", "embedding_failed", report)

        # 9. Statistics
        res, h = await asyncio.to_thread(
            self._evaluate, strata, B, alpha_k
        )
        significant = decide(
            p_value=res.p_value,
            alpha_k=alpha_k,
            effect_size_h=h,
            effect_min=self._settings.effect_min,
            warmed_up=warmed_up,
        )

        # 10. Ledger update FIRST
        report_id = uuid.uuid4().hex
        ledger_kwargs: dict[str, Any] = {
            "looks_completed": k,
            "alpha_spent": ledger.alpha_spent + alpha_k,
            "last_look_conditions_digest": digest_before,
            "lived_seconds": max(ledger.lived_seconds, lived_seconds),
            "lived_ticks": max(ledger.lived_ticks, lived_ticks),
            "inconclusive_since": None,
            "inconclusive_alerted": False,
        }
        if significant and not ledger.individuated:
            ledger_kwargs.update(
                {
                    "individuated": True,
                    "latched_at": self._now().isoformat(),
                    "latched_report_id": report_id,
                }
            )
        new_ledger = dataclasses.replace(ledger, **ledger_kwargs)
        save_ledger(self._paths, new_ledger)

        # 11. Report
        current_count = sum(len(p) for p in current_samples)
        length_count = sum(
            1
            for p in current_samples
            for s in p
            if s.finish_reason == "length"
        )
        length_capped_fraction = (
            length_count / current_count if current_count else 0.0
        )
        duration = time.perf_counter() - start

        report = build_report(
            outcome="scored",
            report_id=report_id,
            reference_id=ref.reference_id,
            reference_kind=ref.reference_kind,
            reference_captured_at=ref.captured_at,
            look_index=k,
            entity_name=self._entity_name,
            n_prompts=len(self._battery),
            n_reference_per_prompt=self._settings.n_reference,
            n_current_per_prompt=self._settings.n_current,
            statistic="stratified_energy_u",
            T=float(res.statistic),
            p_value=float(res.p_value),
            permutations=res.permutations,
            alpha_k=float(alpha_k),
            alpha_total=float(self._settings.alpha_total),
            effect_size_h=float(h),
            effect_min=float(self._settings.effect_min),
            warmed_up=bool(warmed_up),
            lived_seconds_since_reference=float(lived_seconds),
            lived_ticks_since_reference=lived_ticks,
            significant=bool(significant),
            latched=new_ledger.individuated,
            embedder_id=self._embedder_id,
            truncated_fraction=0.0,
            length_capped_fraction=float(length_capped_fraction),
            duration_s=float(duration),
        )
        await self._report_sink.write(report)

        # 12. Publish
        await self._publish(
            {"divergence_scalar": float(h), "significant": bool(significant)}
        )

        return LookOutcome("scored", None, report, significant, h)

    def _normalize(self, vec: Any) -> np.ndarray:
        """Convert an embedding to a finite, L2-normalised float64 vector."""
        arr = np.asarray(vec, dtype=np.float64)
        if arr.size == 0:
            raise ValueError("empty embedding")
        if not np.isfinite(arr).all():
            raise ValueError("non-finite embedding")
        norm = np.linalg.norm(arr)
        if not np.isfinite(norm) or norm == 0:
            raise ValueError("zero or non-finite embedding norm")
        return arr / norm

    def _evaluate(
        self,
        strata: list[tuple[np.ndarray, np.ndarray]],
        B: int,
        alpha_k: float,
    ) -> tuple[Any, float]:
        """Run the permutation test and effect-size computation off-loop."""
        res = permutation_test(
            strata, permutations=B, rng=self._rng, alpha=alpha_k
        )
        h = effect_size_h(strata)
        return res, h

    async def _inconclusive(
        self,
        reason: str,
        *,
        ref_id: str,
        k: int | None,
        start: float,
        ref: ReferenceDoc | None = None,
    ) -> dict:
        """Write an inconclusive report and return it."""
        duration = time.perf_counter() - start
        report = build_report(
            outcome="inconclusive",
            inconclusive_reason=reason,
            report_id=uuid.uuid4().hex,
            reference_id=ref_id,
            reference_kind=ref.reference_kind if ref is not None else None,
            reference_captured_at=ref.captured_at if ref is not None else None,
            look_index=k,
            entity_name=self._entity_name,
            n_prompts=len(self._battery),
            n_reference_per_prompt=self._settings.n_reference,
            n_current_per_prompt=self._settings.n_current,
            alpha_total=float(self._settings.alpha_total),
            effect_min=float(self._settings.effect_min),
            embedder_id=self._embedder_id,
            truncated_fraction=0.0,
            length_capped_fraction=0.0,
            duration_s=float(duration),
        )
        await self._report_sink.write(report)
        return report
