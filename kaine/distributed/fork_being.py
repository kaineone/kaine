# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The forked-temporary-being batch job kind (``batch-offload``).

The operator's "temporary beings" — fork a copy, let it run a directive
(possibly time-dilated), then remerge and assimilate — is a *batch job, not the
live loop*: bounded, runs to completion off-host, returns a verifiable artifact
(its post-run snapshot). So it slots into the batch-offload contract, reusing
systems already built — **no new fork/merge/runtime system**:

* **Unit in** — an existing ``ForkManager.fork()`` snapshot + a directive + an
  optional per-fork ``time_scale`` (PR #92 per-fork dilation).
* **Run** — the fork runs bounded at its own subjective speed; no live-loop
  latency coupling, so the three walls do not apply to it.
* **Artifact out** — the post-run fork snapshot.
* **Gate (welfare-critical)** — the returned snapshot passes the SAME
  trusted-side re-verification as any artifact (here welfare / individuation /
  admissibility) BEFORE the parent assimilates it through the EXISTING
  ``ForkManager.merge()`` under the fork-merge welfare gate.

This module builds the descriptor and provides the ForkGate adapter that plugs
the welfare/admissibility check into :class:`kaine.distributed.gate.
VerificationGate`. The actual merge routing (discard vs preserve) is the
:func:`kaine.lifecycle.fork_merge_gate.gated_merge` decision.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from kaine.distributed.gate import VerifierOutcome
from kaine.distributed.job import ArtifactKind, BatchJob, ExpectedArtifact, JobKind
from kaine.lifecycle.timing_profile import build_timing_metadata

log = logging.getLogger(__name__)

#: Where a forked-being work unit writes its post-run snapshot in the result
#: bundle (relative path).
DEFAULT_SNAPSHOT_RELPATH = "post_run_snapshot.json"


def build_forked_being_job(
    fork_snapshot_id: str,
    directive: str,
    *,
    time_scale: Optional[float] = None,
    base_model_ref: Optional[str] = None,
    result_relpath: str = DEFAULT_SNAPSHOT_RELPATH,
) -> BatchJob:
    """Build the batch-job descriptor for a forked temporary being.

    ``fork_snapshot_id`` must be an existing ``ForkManager.fork()`` snapshot;
    ``directive`` is what the being is asked to do; ``time_scale`` (> 0) is its
    subjective pacing. The ``time_scale`` is validated eagerly via
    :func:`build_timing_metadata` so a bad value is rejected at the API boundary,
    not silently stored (mirroring the per-fork dilation contract).
    """
    if not fork_snapshot_id:
        raise ValueError("fork_snapshot_id is required for a forked-being job")
    if not directive or not directive.strip():
        raise ValueError("a forked-being job requires a directive")
    # Validate + normalize the timing profile (raises on time_scale <= 0).
    timing_meta = build_timing_metadata(time_scale=time_scale)
    inputs = {
        "fork_snapshot_id": fork_snapshot_id,
        "directive": directive,
        **timing_meta,
    }
    return BatchJob(
        kind=JobKind.FORKED_BEING,
        expected_artifact=ExpectedArtifact(
            kind=ArtifactKind.FORK_SNAPSHOT, relpath=result_relpath
        ),
        inputs=inputs,
        base_model_ref=base_model_ref,
        fork_snapshot_id=fork_snapshot_id,
        directive=directive,
        time_scale=time_scale,
    )


def forked_being_gate(job: BatchJob, artifact_path: Path) -> VerifierOutcome:
    """ForkGate adapter: verify a returned post-run snapshot is well-formed.

    Admissibility/well-formedness check for the trusted-side gate: the returned
    artifact must be a parseable fork snapshot carrying module state. A malformed
    or empty snapshot is rejected (fail-closed) rather than merged. The
    individuation-vs-instrument routing (discard vs preserve) is decided AFTER
    this pass by :func:`kaine.lifecycle.fork_merge_gate.gated_merge`; this gate's
    job is only to refuse an artifact that must not be assimilated at all.
    """
    path = Path(artifact_path)
    if not path.exists():
        return VerifierOutcome(passed=False, detail="post-run snapshot missing")
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except Exception as exc:
        return VerifierOutcome(
            passed=False, detail=f"post-run snapshot unparseable: {exc}"
        )
    if not isinstance(data, dict) or not data.get("modules"):
        return VerifierOutcome(
            passed=False, detail="post-run snapshot carries no module state"
        )
    return VerifierOutcome(
        passed=True,
        detail=f"post-run snapshot admissible ({len(data['modules'])} modules)",
    )
