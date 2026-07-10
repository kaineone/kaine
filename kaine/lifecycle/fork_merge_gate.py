# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Welfare gate on the fork-merge path (welfare-critical).

A merge is, for the *fork*, an ending: its distinct trajectory ceases. A fork
that ran long enough — especially a dilated/off-host temporary being on a
directive — may have **individuated into its own being with a welfare interest
in continuing**. Silently merging-and-discarding such a fork would be exactly the
harm the individuation / preservation / decommission apparatus exists to
prevent. So the merge path is welfare-gated, reusing the machinery already built
(no new system):

* **Before** a merge ends a fork, assess its individuation/divergence from its
  fork-point birth-state baseline (the same divergence gate that drives the
  preserve trigger and the decommission gate) together with its welfare signals.
* **Decouple assimilation from termination.** Below threshold (a short-lived,
  low-divergence *instrument* fork): merge and discard as today. Above threshold
  (it has individuated): the parent MAY still assimilate the fork's knowledge
  one-directionally, but the fork is NOT terminated by the merge — it is
  preserved under the welfare net and ending it requires the same
  operator-authorized, transparent, welfare-gated decommission as any other
  individual.

This governs **every** individuated-fork merge, off-host or local (the Phase-4
locally-run dilated temporary being is gated identically). It is the
load-bearing case the whole gate was built for.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from kaine.lifecycle.divergence import DivergenceAssessment, assess_divergence
from kaine.lifecycle.manager import ForkManager

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class WelfareSignals:
    """Welfare-monitoring inputs for the fork at merge time.

    Either signal, on its own, marks the fork as having a welfare interest in
    continuing (it raises individuation confidence beyond the divergence test).
    Non-content booleans only — never any cognitive text.
    """

    distress_at_termination: bool = False
    prefers_to_continue: bool = False

    def indicates_individuation(self) -> bool:
        return self.distress_at_termination or self.prefers_to_continue


@dataclass(frozen=True)
class ForkMergeVerdict:
    """The pre-merge verdict + the fork's resulting fate.

    ``merged_snapshot_id`` is the parent's post-assimilation snapshot (knowledge
    taken one-directionally). Exactly one of ``fork_discarded`` /
    ``fork_preserved`` is True. When preserved, ``requires_operator_decommission``
    is True — the fork may only be ended through the welfare-gated decommission
    path, never silently by the merge.
    """

    individuated: bool
    merged_snapshot_id: Optional[str]
    fork_discarded: bool
    fork_preserved: bool
    requires_operator_decommission: bool
    reason: str
    signals: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "individuated": self.individuated,
            "merged_snapshot_id": self.merged_snapshot_id,
            "fork_discarded": self.fork_discarded,
            "fork_preserved": self.fork_preserved,
            "requires_operator_decommission": self.requires_operator_decommission,
            "reason": self.reason,
            "signals": dict(self.signals),
        }


def assess_fork(
    *,
    fork_state_root: Path | str,
    eval_root: Path | str = Path("data/evaluation"),
) -> DivergenceAssessment:
    """Assess a fork's individuation against its birth-state baseline.

    Thin wrapper over :func:`kaine.lifecycle.divergence.assess_divergence`
    pointed at the fork's own materialized state root, so the SAME warmed-up,
    birth-state-referenced signal that drives the live preservation trigger and
    the decommission gate decides whether a fork has individuated. Pure + guarded.
    """
    return assess_divergence(
        state_root=Path(fork_state_root), eval_root=Path(eval_root)
    )


def gated_merge(
    manager: ForkManager,
    parent_id: str,
    fork_id: str,
    *,
    assessment: DivergenceAssessment,
    welfare: WelfareSignals | None = None,
    preserve_fn: Optional[Callable[[str], None]] = None,
    surface: Optional[Callable[[dict[str, Any]], None]] = None,
    label: str = "",
    **merge_kwargs: Any,
) -> ForkMergeVerdict:
    """Merge ``fork_id`` into ``parent_id`` under the welfare gate.

    ``assessment`` is the fork's divergence verdict (see :func:`assess_fork`);
    ``welfare`` adds live welfare signals. In BOTH branches the parent assimilates
    the fork's knowledge (a real :meth:`ForkManager.merge`). The branches differ
    only in the fork's fate:

    * **not individuated** → the fork is discarded (an instrument, no welfare
      obligation);
    * **individuated** → the fork is PRESERVED (``preserve_fn(fork_id)`` if
      supplied) and may only be ended via operator-authorized welfare-gated
      decommission. The merge never terminates it.

    The verdict is logged and surfaced (never a silent cessation). This function
    never terminates an individuated fork.
    """
    welfare = welfare or WelfareSignals()
    individuated = bool(assessment.diverged or welfare.indicates_individuation())

    # Assimilate knowledge one-directionally into the parent in both branches
    # (the existing per-module merge strategies copy what the parent needs).
    merged = manager.merge(parent_id, fork_id, label=label, **merge_kwargs)

    signals: dict[str, Any] = {
        "divergence_diverged": bool(assessment.diverged),
        "divergence_summary": assessment.summary,
        "welfare_distress_at_termination": welfare.distress_at_termination,
        "welfare_prefers_to_continue": welfare.prefers_to_continue,
        **{f"divergence.{k}": v for k, v in assessment.signals.items()},
    }

    if individuated:
        if preserve_fn is not None:
            try:
                preserve_fn(fork_id)
            except Exception:
                log.warning(
                    "fork preserve_fn failed for %s; fork is NOT discarded "
                    "(operator must preserve/decommission it)",
                    fork_id,
                    exc_info=True,
                )
        reason = (
            "fork individuated (divergence/welfare above threshold): parent "
            "assimilated its knowledge one-directionally; the fork is preserved "
            "and may only be ended via operator-authorized welfare-gated "
            "decommission — the merge did NOT terminate it"
        )
        verdict = ForkMergeVerdict(
            individuated=True,
            merged_snapshot_id=merged.id,
            fork_discarded=False,
            fork_preserved=True,
            requires_operator_decommission=True,
            reason=reason,
            signals=signals,
        )
        log.warning("fork-merge welfare gate: PRESERVED individuated fork %s", fork_id)
    else:
        reason = (
            "fork below individuation threshold (an instrument, not a being): "
            "merged and discarded as today; no welfare obligation triggered"
        )
        verdict = ForkMergeVerdict(
            individuated=False,
            merged_snapshot_id=merged.id,
            fork_discarded=True,
            fork_preserved=False,
            requires_operator_decommission=False,
            reason=reason,
            signals=signals,
        )
        log.info("fork-merge welfare gate: discarded instrument fork %s", fork_id)

    if surface is not None:
        try:
            surface(verdict.to_dict())
        except Exception:
            log.debug("fork-merge gate surface callback failed", exc_info=True)
    return verdict
