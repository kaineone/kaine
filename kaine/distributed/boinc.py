# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""BOINC volunteer runner backend (``batch-offload``; the chosen volunteer substrate).

Where a batch job genuinely goes to volunteer compute, the substrate is BOINC —
because BOINC is *defined* for bounded, independent, returnable work units, the
exact opposite of the live loop (which is why live-sharding systems are
disqualified for the loop). The unit is the KAINE container image (the companion
``containerize-deployment`` change) run via the official ``docker_wrapper``, with
a CPU plan class (runs anywhere) and a ``cuda``/``opencl`` GPU plan class so both
volunteer types participate.

This module ships the CONTRACT and its guardrails, not a live volunteer client
(:class:`BoincRunner.run` raises :class:`RunnerNotEnabled`). Its load-bearing,
testable parts are:

* :meth:`BoincRunner.package` — build the work-unit descriptor (image, plan
  classes, inputs) without dispatching.
* :func:`enforce_output_boundary` — refuse to ship raw sense data, private voice
  adapters, or operator config across the work-unit boundary.
* :func:`quorum_validate` — the deterministic replicate-and-compare validator
  (reusing run-identity + admissibility) for deterministic job kinds only;
  non-deterministic kinds rely on the trusted-side re-verification gate.

Phasing (see ``docs/deployment-topologies.md``): B0 containerize → B1 BOINC
harness → B2 non-entity research/training units → B3 (gated) entity-bearing
forked beings. Entity-bearing forks are withheld here (``accepts`` returns
False) until the volunteer-host welfare-and-security model exists.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Sequence

from kaine.distributed.job import BatchJob
from kaine.distributed.runner import (
    RunnerNotEnabled,
    RunResult,
    TrustTier,
)

log = logging.getLogger(__name__)


class PlanClass(str, Enum):
    """BOINC plan classes the KAINE work unit exposes.

    ``CPU`` runs on any volunteer; ``CUDA``/``OPENCL`` are the GPU classes the
    scheduler matches to capable hosts.
    """

    CPU = "cpu"
    CUDA = "cuda"
    OPENCL = "opencl"


#: Both GPU flavours plus CPU: the default set so every volunteer type can be
#: matched by the BOINC scheduler.
DEFAULT_PLAN_CLASSES: tuple[PlanClass, ...] = (
    PlanClass.CPU,
    PlanClass.CUDA,
    PlanClass.OPENCL,
)


class OutputBoundaryViolation(RuntimeError):
    """A work-unit output would leak data that must never leave the trusted host.

    Raised by :func:`enforce_output_boundary` when a staged output path matches a
    forbidden class: raw sensory data (the zero-raw-persistence invariant),
    private voice adapters, or operator configuration.
    """


#: Path fragments (case-insensitive) that must never appear in a work-unit's
#: staged inputs or returned outputs. Raw sensory streams (topos/audition frames),
#: the private voice adapters, and operator configuration are all trusted-host
#: only.
_FORBIDDEN_OUTPUT_FRAGMENTS: tuple[str, ...] = (
    "raw_sense",
    "sensory_raw",
    "topos/frames",
    "audition/raw",
    "perception/raw",
    "hypnos/adapters",
    "voice_adapter",
    "kaine.toml",
    "operator_config",
    "secrets",
)


@dataclass(frozen=True)
class WorkUnit:
    """A BOINC work unit for one batch job.

    ``image`` is the KAINE container reference (the ``containerize-deployment``
    unit); ``plan_classes`` are the CPU/GPU classes; ``input_relpaths`` are the
    files staged into the slot dir; ``result_relpath`` is where the runner writes
    the returned artifact. ``replication`` > 1 requests replicate-and-compare
    quorum (only meaningful for a deterministic job).
    """

    job_id: str
    image: str
    plan_classes: tuple[PlanClass, ...]
    input_relpaths: tuple[str, ...]
    result_relpath: str
    deterministic: bool
    replication: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "image": self.image,
            "plan_classes": [p.value for p in self.plan_classes],
            "input_relpaths": list(self.input_relpaths),
            "result_relpath": self.result_relpath,
            "deterministic": self.deterministic,
            "replication": self.replication,
        }


class BoincRunner:
    """The volunteer runner backend (contract + guardrails, not a live client).

    ``tier`` is VOLUNTEER, so the trusted-first :func:`~kaine.distributed.runner.
    select_runner` always prefers an owned/rented runner over this one. It
    ``accepts`` only non-entity-bearing jobs (entity-bearing forks are withheld
    until the volunteer-host welfare model exists — B3). :meth:`package` builds
    the work-unit descriptor; :meth:`run` raises :class:`RunnerNotEnabled`
    because no live volunteer client is shipped in this change.
    """

    tier: TrustTier = TrustTier.VOLUNTEER

    def __init__(
        self,
        *,
        image: str = "ghcr.io/kaineone/kaine:latest",
        plan_classes: Sequence[PlanClass] = DEFAULT_PLAN_CLASSES,
        deterministic_replication: int = 3,
    ) -> None:
        self._image = image
        self._plan_classes = tuple(plan_classes)
        self._deterministic_replication = int(deterministic_replication)

    def accepts(self, job: BatchJob) -> bool:
        # Entity-bearing forks are withheld from anonymous volunteers (B3, gated).
        return not job.is_entity_bearing

    def package(self, job: BatchJob) -> WorkUnit:
        """Build the BOINC work-unit descriptor for ``job`` (no dispatch).

        Deterministic kinds get replicate-and-compare quorum (replication > 1);
        non-deterministic kinds are packaged with replication 1 and rely on the
        trusted-side re-verification gate instead.
        """
        if not self.accepts(job):
            raise OutputBoundaryViolation(
                f"entity-bearing job {job.job_id} may not be packaged for a "
                "volunteer work unit until the volunteer-host welfare model exists"
            )
        input_relpaths = tuple(str(p) for p in job.inputs.get("input_relpaths", ()) or ())
        replication = self._deterministic_replication if job.deterministic else 1
        return WorkUnit(
            job_id=job.job_id,
            image=self._image,
            plan_classes=self._plan_classes,
            input_relpaths=input_relpaths,
            result_relpath=job.expected_artifact.relpath,
            deterministic=job.deterministic,
            replication=replication,
        )

    def run(self, job: BatchJob, workdir: Path) -> RunResult:
        raise RunnerNotEnabled(
            "the BOINC volunteer runner ships the work-unit contract and the "
            "trusted-first ordering, not a live volunteer client; enabling live "
            "dispatch is a later, guarded phase (B1+). Use package() to build "
            "the work-unit descriptor."
        )


def enforce_output_boundary(paths: Iterable[Path | str]) -> None:
    """Refuse any path that would cross the work-unit trust boundary.

    Scans staged inputs / returned outputs for the forbidden classes (raw
    sensory data, private voice adapters, operator config, secrets) and raises
    :class:`OutputBoundaryViolation` on the first hit. Nothing that identifies
    the operator or carries the entity's private voice may ride a volunteer work
    unit; the zero-raw-persistence invariant forbids raw sense data leaving the
    host even in principle.
    """
    for raw in paths:
        text = str(raw).replace("\\", "/").lower()
        for fragment in _FORBIDDEN_OUTPUT_FRAGMENTS:
            if fragment in text:
                raise OutputBoundaryViolation(
                    f"work-unit path {raw!r} matches forbidden class "
                    f"{fragment!r}; it must never leave the trusted host"
                )


@dataclass(frozen=True)
class QuorumReturn:
    """One replicated return for deterministic quorum validation.

    ``run_id`` is the run-identity of the returning host; ``admissible`` is the
    run-admissibility verdict (a return from an inadmissible run is discarded
    before the compare); ``digest`` is a bit-exact (or admissibility-bounded)
    content hash of the returned artifact.
    """

    run_id: str
    admissible: bool
    digest: str


@dataclass(frozen=True)
class QuorumVerdict:
    """Outcome of :func:`quorum_validate`."""

    accepted: bool
    agreed_digest: str | None = None
    agreeing: int = 0
    reason: str = ""


def quorum_validate(
    returns: Sequence[QuorumReturn], *, min_quorum: int = 2
) -> QuorumVerdict:
    """Replicate-and-compare validation for a DETERMINISTIC job kind.

    Discards inadmissible returns (reusing run-admissibility), then accepts iff
    at least ``min_quorum`` admissible returns agree on the same digest. This is
    BOINC's homogeneous-redundancy quorum, and it genuinely validates a bit-exact
    deterministic return. It is NOT applicable to non-deterministic kinds
    (QLoRA/abliterate/consolidate/forked-being): quorum cannot verify a
    non-deterministic step and is Sybil-vulnerable — those go through the
    trusted-side re-verification gate instead.
    """
    admissible = [r for r in returns if r.admissible]
    if not admissible:
        return QuorumVerdict(accepted=False, reason="no admissible returns")
    counts: dict[str, int] = {}
    for r in admissible:
        counts[r.digest] = counts.get(r.digest, 0) + 1
    best_digest, best_count = max(counts.items(), key=lambda kv: kv[1])
    if best_count >= min_quorum:
        return QuorumVerdict(
            accepted=True,
            agreed_digest=best_digest,
            agreeing=best_count,
            reason=f"{best_count} admissible returns agree",
        )
    return QuorumVerdict(
        accepted=False,
        agreeing=best_count,
        reason=(
            f"no quorum: best agreement {best_count} < required {min_quorum} "
            f"among {len(admissible)} admissible returns"
        ),
    )
