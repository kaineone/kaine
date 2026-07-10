# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Self-contained batch-offload job descriptors (``batch-offload``).

A KAINE deployment is three workloads, not one (see
``docs/deployment-topologies.md``). The *detached batch* workload — Hypnos
voice-alignment QLoRA/DPO training, self-abliteration, deep memory
consolidation, offline evaluation, and bounded forked-being runs — is
latency-tolerant, runs while the entity is asleep or offline, and produces a
discrete, verifiable artifact. That makes it the ONLY workload that may run off
the live host (an owned second box, a rented trusted GPU, or — last and most
guarded — a volunteer/BOINC worker).

A :class:`BatchJob` is the self-contained descriptor that expresses one such job:
its :class:`JobKind`, its inputs, and the :class:`ExpectedArtifact` it must
return. It carries no live-loop state and no in-process handles, so it can be
serialized, shipped to an off-host runner, and run without the cognitive cycle
being involved. What comes back is gated on the trusted host before promotion
(see :mod:`kaine.distributed.gate`).

Nothing here runs a job or a live volunteer client — this module is the
contract only. Runners live in :mod:`kaine.distributed.runner` /
:mod:`kaine.distributed.boinc`.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class JobKind(str, Enum):
    """The batch workloads that are offloadable behind the descriptor.

    The membership of this enum IS the sanctioned batch surface: the live
    cognitive loop is deliberately absent and can never be expressed as a job
    (the three walls — latency, shared mutable state under CAP, physical
    zero-persistence I/O).
    """

    VOICE_ALIGN = "voice_align"
    ABLITERATE = "abliterate"
    CONSOLIDATE = "consolidate"
    EVAL = "eval"
    #: A bounded forked temporary being: an existing ``ForkManager`` snapshot +
    #: a directive + an optional per-fork ``time_scale``, run to completion
    #: off-host, returning its post-run snapshot. Reuses the fork/dilation/merge
    #: machinery — no new runtime (see :mod:`kaine.distributed.fork_being`).
    FORKED_BEING = "forked_being"


class ArtifactKind(str, Enum):
    """The verifiable output an off-host job returns."""

    LORA_ADAPTER = "lora_adapter"
    MODIFIED_MODEL = "modified_model"
    MEMORY_DELTA = "memory_delta"
    EVAL_REPORT = "eval_report"
    FORK_SNAPSHOT = "fork_snapshot"


#: Which job kinds are reproducible (seeded feed + deterministic-cycle mode +
#: run-identity + admissibility) and so MAY be validated by BOINC
#: replicate-and-compare quorum. Non-deterministic kinds (QLoRA/abliterate/
#: consolidate/forked-being) can NOT be quorum-validated and rely solely on the
#: trusted-side re-verification gate — quorum is Sybil-vulnerable and does not
#: verify a non-deterministic training step (see the gate + BOINC docs).
_DETERMINISTIC_KINDS: frozenset[JobKind] = frozenset({JobKind.EVAL})

#: The default artifact each kind returns (a caller may override).
_DEFAULT_ARTIFACT: dict[JobKind, ArtifactKind] = {
    JobKind.VOICE_ALIGN: ArtifactKind.LORA_ADAPTER,
    JobKind.ABLITERATE: ArtifactKind.MODIFIED_MODEL,
    JobKind.CONSOLIDATE: ArtifactKind.MEMORY_DELTA,
    JobKind.EVAL: ArtifactKind.EVAL_REPORT,
    JobKind.FORKED_BEING: ArtifactKind.FORK_SNAPSHOT,
}


@dataclass(frozen=True)
class ExpectedArtifact:
    """The verifiable artifact a job must return, declared up front.

    ``kind`` names the artifact shape; ``relpath`` is where in the returned work
    unit the runner writes it (a directory or file, relative to the result
    bundle). The gate re-verifies the artifact on the trusted host before it is
    promoted — the descriptor never trusts the runner's own claim of success.
    """

    kind: ArtifactKind
    relpath: str

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind.value, "relpath": self.relpath}

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ExpectedArtifact":
        return cls(kind=ArtifactKind(raw["kind"]), relpath=str(raw["relpath"]))


@dataclass(frozen=True)
class BatchJob:
    """A self-contained, serializable batch-offload job descriptor.

    ``inputs`` carries everything the off-host runner needs that is not a live
    handle: dataset references, a base-model reference, a fork snapshot id, a
    directive, seeds, etc. It is deliberately a plain dict so the whole
    descriptor round-trips through JSON and can be packed as a work unit.
    ``base_model_ref`` is called out because most kinds need it. ``time_scale``
    and ``directive`` are the forked-being extras (ignored by other kinds).
    """

    kind: JobKind
    expected_artifact: ExpectedArtifact
    job_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    inputs: dict[str, Any] = field(default_factory=dict)
    base_model_ref: Optional[str] = None
    #: Forked-being extras. ``fork_snapshot_id`` is the ``ForkManager.fork()``
    #: snapshot this being starts from; ``directive`` is what it is asked to do;
    #: ``time_scale`` (> 0) is its subjective pacing (PR #92 per-fork dilation).
    fork_snapshot_id: Optional[str] = None
    directive: Optional[str] = None
    time_scale: Optional[float] = None
    created_at: float = field(default_factory=time.time)

    @property
    def deterministic(self) -> bool:
        """True when this job kind is reproducible enough for quorum validation.

        Callers MAY force a job non-deterministic (e.g. an unseeded eval) via
        ``inputs["deterministic"] = False``; they can never force a
        non-deterministic kind deterministic — the trusted gate stays the only
        defense for those.
        """
        if not self._kind_deterministic():
            return False
        override = self.inputs.get("deterministic")
        if override is None:
            return True
        return bool(override)

    def _kind_deterministic(self) -> bool:
        return self.kind in _DETERMINISTIC_KINDS

    @property
    def is_entity_bearing(self) -> bool:
        """True when running this job instantiates a *full individual* off-host.

        Only forked-being jobs are entity-bearing. This gates whether the job may
        go to an anonymous volunteer at all (it may not, until a volunteer-host
        welfare-and-security model exists — see the runner ordering + BOINC).
        """
        return self.kind is JobKind.FORKED_BEING

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "expected_artifact": self.expected_artifact.to_dict(),
            "job_id": self.job_id,
            "inputs": dict(self.inputs),
            "base_model_ref": self.base_model_ref,
            "fork_snapshot_id": self.fork_snapshot_id,
            "directive": self.directive,
            "time_scale": self.time_scale,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "BatchJob":
        return cls(
            kind=JobKind(raw["kind"]),
            expected_artifact=ExpectedArtifact.from_dict(raw["expected_artifact"]),
            job_id=str(raw.get("job_id") or uuid.uuid4().hex),
            inputs=dict(raw.get("inputs") or {}),
            base_model_ref=raw.get("base_model_ref"),
            fork_snapshot_id=raw.get("fork_snapshot_id"),
            directive=raw.get("directive"),
            time_scale=(
                None if raw.get("time_scale") is None else float(raw["time_scale"])
            ),
            created_at=float(raw.get("created_at") or time.time()),
        )


def default_artifact_for(kind: JobKind, relpath: str) -> ExpectedArtifact:
    """The conventional :class:`ExpectedArtifact` for a job kind at ``relpath``."""
    return ExpectedArtifact(kind=_DEFAULT_ARTIFACT[kind], relpath=relpath)
