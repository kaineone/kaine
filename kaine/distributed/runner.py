# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Batch-offload runner abstraction with trusted-first ordering (``batch-offload``).

A batch job runs on exactly one runner. Because the artifact feeds the entity's
voice and identity, runners are tried **trusted-first**: an owned second box or
a rented *trusted* GPU before any volunteer worker, and an anonymous volunteer
is the last, most-guarded option. A job that instantiates a full individual
off-host (a forked being) is NOT eligible for an anonymous volunteer at all
until a volunteer-host welfare-and-security model exists.

This module is the abstraction and the ordering only. :class:`LocalTrustedRunner`
runs a job in-process via an injected executor (used by tests and by an
owned-host deployment); the BOINC volunteer backend lives in
:mod:`kaine.distributed.boinc` and is intentionally not a live client here (the
design ships the contract and the trusted-first ordering, not a volunteer
client).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Any, Callable, Protocol, runtime_checkable

from kaine.distributed.job import BatchJob

log = logging.getLogger(__name__)


class TrustTier(IntEnum):
    """Runner trust, ordered so that ``sorted`` yields trusted-first.

    Lower is more trusted. The ordering is load-bearing: :func:`order_runners`
    and :func:`select_runner` walk it ascending, so an owned host always wins
    over a rented GPU, which always wins over a volunteer.
    """

    OWNED_HOST = 0
    RENTED_TRUSTED_GPU = 1
    VOLUNTEER = 2


class RunnerError(RuntimeError):
    """Base class for runner faults."""


class RunnerNotEnabled(RunnerError):
    """A runner backend exists as a contract but is not enabled to dispatch.

    Raised by the volunteer backend: the batch-offload contract and the
    trusted-first ordering ship here, but no live volunteer client is
    implemented — enabling it is a later, guarded phase.
    """


class NoEligibleRunner(RunnerError):
    """No configured runner may run this job under the trust policy."""


@dataclass(frozen=True)
class RunResult:
    """What a runner returns: where the artifact landed + provenance."""

    job_id: str
    artifact_path: Path
    tier: TrustTier
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Runner(Protocol):
    """A place a batch job can run."""

    @property
    def tier(self) -> TrustTier: ...

    def accepts(self, job: BatchJob) -> bool:
        """Whether this runner can, in principle, run ``job``."""
        ...

    def run(self, job: BatchJob, workdir: Path) -> RunResult: ...


class LocalTrustedRunner:
    """Runs a job in-process on the trusted host via an injected executor.

    ``executor(job, workdir) -> Path`` performs the actual work and returns the
    artifact path. Keeping the executor injected keeps this class free of the
    training stack and lets tests drive it with a fake executor that just writes
    an artifact file. Tier is the most-trusted (owned host).
    """

    tier: TrustTier = TrustTier.OWNED_HOST

    def __init__(self, executor: Callable[[BatchJob, Path], Path]) -> None:
        self._executor = executor

    def accepts(self, job: BatchJob) -> bool:  # noqa: D401 - trivial
        return True

    def run(self, job: BatchJob, workdir: Path) -> RunResult:
        workdir = Path(workdir)
        workdir.mkdir(parents=True, exist_ok=True)
        artifact = self._executor(job, workdir)
        return RunResult(
            job_id=job.job_id,
            artifact_path=Path(artifact),
            tier=self.tier,
            metadata={"runner": "local-trusted"},
        )


def order_runners(runners: list[Runner]) -> list[Runner]:
    """Return ``runners`` ordered trusted-first (stable within a tier)."""
    return sorted(runners, key=lambda r: int(r.tier))


def select_runner(
    job: BatchJob,
    runners: list[Runner],
    *,
    volunteer_welfare_model_ready: bool = False,
) -> Runner:
    """Choose the most-trusted eligible runner for ``job``.

    Walks the runners trusted-first and returns the first that ``accepts`` the
    job under the trust policy:

    * An entity-bearing job (a forked being) is NEVER dispatched to a VOLUNTEER
      runner unless ``volunteer_welfare_model_ready`` is True — the preservation
      and welfare protections must travel with and govern the off-host fork and
      the operator must be able to recall or preserve it before that is allowed.

    Raises :class:`NoEligibleRunner` if none qualify.
    """
    for runner in order_runners(runners):
        if not runner.accepts(job):
            continue
        if (
            runner.tier is TrustTier.VOLUNTEER
            and job.is_entity_bearing
            and not volunteer_welfare_model_ready
        ):
            log.info(
                "skipping volunteer runner for entity-bearing job %s: "
                "volunteer-host welfare model not ready",
                job.job_id,
            )
            continue
        return runner
    raise NoEligibleRunner(
        f"no eligible runner for job {job.job_id} (kind={job.kind.value}, "
        f"entity_bearing={job.is_entity_bearing})"
    )
