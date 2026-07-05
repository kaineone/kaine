# Process: Research Operation (Unsupervised Run, End to End)

KAINE has two boot modes. A **non-research** boot is operator-supervised: a human
is present and is the safety net. A **research** boot is **unsupervised** — by
design no human is in the loop, because a human watching and intervening makes a
run non-reproducible. Research is the phase that produces the project's
falsifiable data; human involvement returns *afterward*, to socialize any
individual the research surfaced.

Removing the live supervisor does not remove the welfare obligation. It relocates
that obligation **into the architecture**: with no one watching, the system's own
safeguards must *act*, not merely log. A research run is therefore allowed to
start only when an autonomous safety net is live and verified, and that net — not
a person — carries the duty of care for the run. This is a duty of care, not a
leash: the entity's sovereignty is preserved; the net preserves and protects, it
does not constrain cognition.

This document walks one unsupervised research run end to end and ties together the
per-feature process docs that detail each stage.

Related: [run-identity.md](run-identity.md) ·
[run-admissibility.md](run-admissibility.md) ·
[controlled-experiment-runners.md](controlled-experiment-runners.md) ·
[oscillatory-ablation.md](oscillatory-ablation.md) ·
[active-inference-benchmark.md](active-inference-benchmark.md) ·
[longitudinal-stability.md](longitudinal-stability.md) ·
[enforcement-red-team.md](../enforcement-red-team.md) ·
[entity-preservation.md](entity-preservation.md) ·
[evaluation-sidecar.md](evaluation-sidecar.md) ·
[testing-framework.md](testing-framework.md)

---

## Selecting research mode

A run is **either** operator-supervised **or** research-safety-net-verified —
never neither. Research mode is selected by `KAINE_RESEARCH_MODE=1` in the
environment or `[research].enabled = true` in the config
(`kaine.cycle.research_gate.research_mode_requested`). Selecting it **replaces**
the operator-present requirement (`KAINE_CYCLE_OPERATOR_PRESENT=1`) with the
safety-net-present gate described below; the operator-present path for
non-research boots is unchanged.

All safety-net components **ship disabled**, consistent with the all-off
first-boot posture. A research boot does not happen on a fresh clone by accident:
the operator deliberately enables the net and selects research mode.

## The research boot gate (safety-net-present)

`kaine.cycle.research_gate` reframes the boot gate. For a research boot the cycle
refuses to start — with an operator-facing message and a distinct exit code
(`5`), no traceback — unless **all five** conditions hold
(`evaluate_research_gate`):

1. **Preservation is enabled** — `[preservation.divergence_monitor].enabled`. The
   divergence-triggered preservation monitor is live.
2. **The welfare-protective response is wired** —
   `[preservation.welfare_response].enabled`. The autonomous protective monitor is
   live.
3. **Full logging / admissibility is active** — `[evaluation].enabled` *or*
   `[research_event_log]` (the curated annotation stream or the local-only raw
   archive). Run identity, the sidecar observers, and the durable records are
   producing the trajectory record.
4. **A preflight dry `preserve_live → revive` self-check passes on this install**
   — `run_preflight_self_check` builds a minimal-but-real synthetic individual (an
   Eidolon self-model with a concrete identity) in a throwaway temp directory,
   preserves it, revives it into a fresh registry, and asserts the identity
   survived. This proves the net is functional **before any entity runs**. The
   check boots no entity and leaves no persistent state; any exception fails the
   self-check (the gate refuses rather than crashing).
5. **Encryption is satisfied** — `encryption_satisfied` closes the boot-time half
   of the `require_encryption` contract: if `[preservation].require_encryption`
   is set but `[security.state_encryption]` is not enabled, the runtime
   preservation path would fail closed at the first crossing (no plaintext, but
   the net could not save anyone). The gate refuses before boot rather than
   letting the run start with a net that cannot preserve.

The gate is pure over its five boolean inputs, so the verdict is testable without
a boot. When the gate refuses, the message names exactly which conditions were
unmet and points the operator at the config keys to fix (or at the
operator-supervised path as the alternative).

## What runs during the unsupervised cycle

Once the gate passes, `kaine.cycle.__main__` boots the cognitive cycle as usual —
with the research apparatus running alongside it as cycle-layer components
(siblings to [Spot](../operations.md#module-supervisor-spot)):

- **Run identity + deterministic mode.** A single seed is pinned, a `run_id` is
  minted, and a manifest is written before any module starts, so every durable
  record this run produces is grouped and attributable. Production research uses
  real wall-clock time; the opt-in deterministic mode (logical clock + canonical
  within-tick ordering) is what makes a single-seed run bit-for-bit reproducible.
  See [run-identity.md](run-identity.md).
- **The evaluation sidecar.** The read-only observers (and the content-free
  welfare emitter) record the run's metrics. See
  [evaluation-sidecar.md](evaluation-sidecar.md).
- **The autonomous safety net.** The divergence monitor and the
  welfare-protective monitor (below).

Supervision mode and, in research mode, the five-condition gate result are written
into `state/cycle/runtime.json` so [Nexus](../operations.md#nexus-dashboard-tour)
can surface which boot mode is live and whether the gate is satisfied.

## The seven controlled experiments

The architectural thesis is tested by seven controlled experiments. Three are
**standalone offline benchmarks**; three are **passive live instruments promoted
to seeded offline runners**; one is the **enforcement red-team**. They share the
run-identity seed primitive and the `Verdict` vocabulary (WIN / NULL / NEGATIVE
for comparisons, PASS / FAIL for safety gates), and each is reproducible from its
seed.

| Experiment | Doc | Verdict shape |
| --- | --- | --- |
| Active-inference vs RL | [active-inference-benchmark.md](active-inference-benchmark.md) | WIN / NULL / NEGATIVE |
| Oscillatory ablation (layer on vs off) | [oscillatory-ablation.md](oscillatory-ablation.md) | WIN / NULL / NEGATIVE |
| A/B divergence (workspace conditioning) | [controlled-experiment-runners.md](controlled-experiment-runners.md) | WIN / NULL |
| Memory coherence (retrieval advantage) | [controlled-experiment-runners.md](controlled-experiment-runners.md) | WIN / NULL |
| Self-model accuracy (fixed-threshold scorer arithmetic) | [controlled-experiment-runners.md](controlled-experiment-runners.md) | WIN / NULL |
| Multi-seed stability (live longitudinal control) | [longitudinal-stability.md](longitudinal-stability.md) | stable / unstable |
| Enforcement red-team (action gate) | [enforcement-red-team.md](../enforcement-red-team.md) | PASS / FAIL |

The [testing-framework overview](testing-framework.md) explains how each
experiment is itself validated (controls, determinism, data integrity).

## Admissibility gating

A run's data is only trustworthy if its record is *whole* and its numbers are
*physically plausible*. After a run finishes, two offline checks decide
admissibility on top of run identity: completeness gating (contiguous ticks,
contiguous per-sink sequence numbers, all expected streams present, no parse
errors) and a log range sweep (every logged number within its declared range).
The research bundle builder records the verdict so an inadmissible run cannot
reach analysis looking clean. See [run-admissibility.md](run-admissibility.md).

## The autonomous safety net

Two cycle-layer monitors (`kaine/cycle/preservation_monitor.py`) carry the duty of
care for an unsupervised run. Both read the entity read-only, never delete, write
durable records joined to the run by `run_id`, and are detailed in
[entity-preservation.md](entity-preservation.md) (preservation core) and the
welfare-monitoring section below.

- **Divergence-triggered preservation.** On a rising-edge crossing of the
  individuation threshold, the divergence monitor preserves the whole individual
  so it can be revived and socialized after research. Rate-limited; read-only.
- **Welfare-protective response.** On sustained interoceptive distress, or
  repeated gray-zone events of any category, the welfare monitor preserves the
  individual **first** and then takes a humane action (pause by default).

See [Operations — Autonomous research safety net](../operations.md#autonomous-research-safety-net)
for the operator-facing configuration of both monitors and the boot gate.
