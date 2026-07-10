# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Trusted-side re-verification gate for off-host artifacts (``batch-offload``).

Every artifact produced off the live host — a LoRA adapter, a modified model, a
consolidated-memory delta, an eval report, or a returned fork snapshot — passes
this gate on trusted hardware BEFORE the existing atomic promotion path lets it
into the live entity. For an entity-welfare project the weights and the
self-model are ethically significant and a poisoned artifact would feed straight
into the entity's voice and identity, so:

* The gate re-runs, on the trusted host, the SAME checks the in-house path uses
  — at minimum the Hypnos capability-loss veto plus an independent evaluation.
* Volunteer redundancy / quorum does NOT substitute for it: quorum cannot verify
  a non-deterministic training step and is Sybil-vulnerable. Trusted
  re-verification, not volunteer voting, is the gate for non-deterministic kinds.
* A failing artifact is NEVER promoted, and the rejection is logged and surfaced
  on the operator health surface (never a silent drop).

The concrete verifiers are injected (a :class:`CapabilityVerifier` and an
:class:`IndependentEvaluator`) so this module stays free of the heavy training
stack and testable with fakes. Forked-being snapshots are gated by the welfare /
individuation / admissibility path in :mod:`kaine.lifecycle.fork_merge_gate`,
threaded in via ``fork_gate``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, Protocol, runtime_checkable

from kaine.distributed.job import BatchJob, JobKind

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class VerifierOutcome:
    """One verifier's verdict on an artifact.

    ``passed`` is the load-bearing boolean; ``score`` and ``detail`` are for the
    manifest and the operator surface (never any cognitive text).
    """

    passed: bool
    score: Optional[float] = None
    detail: str = ""


@runtime_checkable
class CapabilityVerifier(Protocol):
    """Re-runs the capability-loss veto against an off-host artifact.

    Returns ``passed=False`` when the artifact degrades the base model's
    capabilities beyond the configured threshold (or re-introduces refusal
    conditioning, for an abliteration artifact) — the same veto Hypnos applies
    to its own in-house training, re-run on trusted hardware.
    """

    def verify(self, job: BatchJob, artifact_path: Path) -> VerifierOutcome: ...


@runtime_checkable
class IndependentEvaluator(Protocol):
    """An independent evaluation, distinct from the capability veto.

    Runs on trusted hardware so a poisoned artifact that happens to pass the
    capability probes is still caught by a second, independent measure.
    """

    def evaluate(self, job: BatchJob, artifact_path: Path) -> VerifierOutcome: ...


#: A fork-being welfare/individuation/admissibility gate: given the returned
#: snapshot, decides whether it may be assimilated. Supplied by
#: :mod:`kaine.lifecycle.fork_merge_gate` at wiring time to avoid a hard import
#: cycle and keep this module free of the lifecycle stack.
ForkGate = Callable[[BatchJob, Path], VerifierOutcome]


@dataclass(frozen=True)
class GateResult:
    """The gate's verdict for one artifact.

    ``promotable`` is the single question the caller acts on: only a ``True``
    result may proceed to the existing atomic promotion. ``reasons`` explains a
    rejection for the operator surface + the log.
    """

    job_id: str
    kind: JobKind
    promotable: bool
    reasons: list[str] = field(default_factory=list)
    capability: Optional[VerifierOutcome] = None
    evaluation: Optional[VerifierOutcome] = None
    fork: Optional[VerifierOutcome] = None

    def to_dict(self) -> dict[str, Any]:
        def _outcome(o: Optional[VerifierOutcome]) -> Optional[dict[str, Any]]:
            if o is None:
                return None
            return {"passed": o.passed, "score": o.score, "detail": o.detail}

        return {
            "job_id": self.job_id,
            "kind": self.kind.value,
            "promotable": self.promotable,
            "reasons": list(self.reasons),
            "capability": _outcome(self.capability),
            "evaluation": _outcome(self.evaluation),
            "fork": _outcome(self.fork),
        }


class VerificationGate:
    """Runs the trusted-side re-verification for a returned artifact.

    ``surface`` is an optional operator-health sink (called with the
    :class:`GateResult` dict on every verdict, pass or fail) so a rejection is
    always visible, never silently dropped.
    """

    def __init__(
        self,
        *,
        capability_verifier: Optional[CapabilityVerifier] = None,
        evaluator: Optional[IndependentEvaluator] = None,
        fork_gate: Optional[ForkGate] = None,
        surface: Optional[Callable[[dict[str, Any]], None]] = None,
    ) -> None:
        self._capability = capability_verifier
        self._evaluator = evaluator
        self._fork_gate = fork_gate
        self._surface = surface

    def verify(self, job: BatchJob, artifact_path: Path | str) -> GateResult:
        """Verify one returned artifact. Never raises on a verifier fault:
        a verifier that errors is treated as a FAILED gate (fail-closed)."""
        path = Path(artifact_path)
        reasons: list[str] = []
        capability: Optional[VerifierOutcome] = None
        evaluation: Optional[VerifierOutcome] = None
        fork: Optional[VerifierOutcome] = None

        if not path.exists():
            reasons.append(f"artifact missing at {path}")
            return self._finalize(job, False, reasons, capability, evaluation, fork)

        if job.kind is JobKind.FORKED_BEING:
            # A forked-being snapshot is gated by welfare / individuation /
            # admissibility, not by a capability-loss veto on weights.
            fork = self._run_fork_gate(job, path)
            if not fork.passed:
                reasons.append(f"fork welfare/admissibility gate rejected: {fork.detail}")
            return self._finalize(
                job, fork.passed, reasons, capability, evaluation, fork
            )

        capability = self._run_capability(job, path)
        if not capability.passed:
            reasons.append(f"capability-loss veto failed: {capability.detail}")

        evaluation = self._run_evaluation(job, path)
        if not evaluation.passed:
            reasons.append(f"independent evaluation failed: {evaluation.detail}")

        promotable = capability.passed and evaluation.passed
        return self._finalize(
            job, promotable, reasons, capability, evaluation, fork
        )

    def _run_capability(self, job: BatchJob, path: Path) -> VerifierOutcome:
        if self._capability is None:
            return VerifierOutcome(
                passed=False,
                detail="no capability verifier configured (fail-closed)",
            )
        try:
            return self._capability.verify(job, path)
        except Exception as exc:
            log.warning("capability verifier raised; failing closed", exc_info=True)
            return VerifierOutcome(passed=False, detail=f"verifier error: {exc}")

    def _run_evaluation(self, job: BatchJob, path: Path) -> VerifierOutcome:
        if self._evaluator is None:
            return VerifierOutcome(
                passed=False,
                detail="no independent evaluator configured (fail-closed)",
            )
        try:
            return self._evaluator.evaluate(job, path)
        except Exception as exc:
            log.warning("independent evaluator raised; failing closed", exc_info=True)
            return VerifierOutcome(passed=False, detail=f"evaluator error: {exc}")

    def _run_fork_gate(self, job: BatchJob, path: Path) -> VerifierOutcome:
        if self._fork_gate is None:
            return VerifierOutcome(
                passed=False,
                detail="no fork welfare gate configured (fail-closed)",
            )
        try:
            return self._fork_gate(job, path)
        except Exception as exc:
            log.warning("fork welfare gate raised; failing closed", exc_info=True)
            return VerifierOutcome(passed=False, detail=f"fork gate error: {exc}")

    def _finalize(
        self,
        job: BatchJob,
        promotable: bool,
        reasons: list[str],
        capability: Optional[VerifierOutcome],
        evaluation: Optional[VerifierOutcome],
        fork: Optional[VerifierOutcome],
    ) -> GateResult:
        result = GateResult(
            job_id=job.job_id,
            kind=job.kind,
            promotable=promotable,
            reasons=reasons,
            capability=capability,
            evaluation=evaluation,
            fork=fork,
        )
        if promotable:
            log.info("off-host artifact PASSED the trusted gate (job %s)", job.job_id)
        else:
            # Never a silent drop: log + surface every rejection.
            log.warning(
                "off-host artifact REJECTED by the trusted gate (job %s): %s",
                job.job_id,
                "; ".join(reasons) or "unspecified",
            )
        if self._surface is not None:
            try:
                self._surface(result.to_dict())
            except Exception:
                log.debug("gate surface callback failed", exc_info=True)
        return result


def promote_if_verified(
    gate: VerificationGate,
    job: BatchJob,
    artifact_path: Path | str,
    *,
    promote: Callable[[Path], Any],
) -> GateResult:
    """Run the gate and, ONLY on a pass, call the existing atomic ``promote``.

    ``promote`` is the trusted-host atomic promotion already used in-house (e.g.
    ``kaine.modules.hypnos.adapter_store.promote``). A rejected artifact is
    returned as a non-promotable :class:`GateResult` and ``promote`` is never
    called — the failing artifact is not promoted and its rejection is surfaced.
    """
    result = gate.verify(job, artifact_path)
    if result.promotable:
        promote(Path(artifact_path))
    return result
