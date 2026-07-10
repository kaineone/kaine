# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Distributed substrate: batch-offload contract, gate, and runner ordering.

This package owns the *horizontal* scaling seam — running KAINE's detached batch
workloads off the live host — and the explicit untrusted-compute boundary that
keeps the live cognitive loop and the stateful stores on trusted hardware. See
``docs/deployment-topologies.md`` for the workload/target matrix and the
rationale (the three walls).

Nothing here runs the live cognitive loop or a live volunteer client: it is the
job descriptor (:mod:`kaine.distributed.job`), the trusted-side re-verification
gate (:mod:`kaine.distributed.gate`), the trusted-first runner abstraction
(:mod:`kaine.distributed.runner`), the BOINC volunteer contract + guardrails
(:mod:`kaine.distributed.boinc`), and the forked-temporary-being job kind
(:mod:`kaine.distributed.fork_being`).
"""
from __future__ import annotations

from kaine.distributed.boinc import (
    BoincRunner,
    OutputBoundaryViolation,
    PlanClass,
    QuorumReturn,
    QuorumVerdict,
    WorkUnit,
    enforce_output_boundary,
    quorum_validate,
)
from kaine.distributed.fork_being import (
    build_forked_being_job,
    forked_being_gate,
)
from kaine.distributed.gate import (
    GateResult,
    VerificationGate,
    VerifierOutcome,
    promote_if_verified,
)
from kaine.distributed.job import (
    ArtifactKind,
    BatchJob,
    ExpectedArtifact,
    JobKind,
    default_artifact_for,
)
from kaine.distributed.runner import (
    LocalTrustedRunner,
    NoEligibleRunner,
    Runner,
    RunnerNotEnabled,
    RunResult,
    TrustTier,
    order_runners,
    select_runner,
)

__all__ = [
    "ArtifactKind",
    "BatchJob",
    "BoincRunner",
    "ExpectedArtifact",
    "GateResult",
    "JobKind",
    "LocalTrustedRunner",
    "NoEligibleRunner",
    "OutputBoundaryViolation",
    "PlanClass",
    "QuorumReturn",
    "QuorumVerdict",
    "Runner",
    "RunnerNotEnabled",
    "RunResult",
    "TrustTier",
    "VerificationGate",
    "VerifierOutcome",
    "WorkUnit",
    "build_forked_being_job",
    "default_artifact_for",
    "enforce_output_boundary",
    "forked_being_gate",
    "order_runners",
    "promote_if_verified",
    "quorum_validate",
    "select_runner",
]
