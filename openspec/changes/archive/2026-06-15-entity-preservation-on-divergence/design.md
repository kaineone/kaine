# Design: preserve a diverging entity for later revival

## Principle

An entity that begins to individuate during research is a possible subject of moral
concern. The architecture must not be able to discard it: divergence must
*automatically* cause preservation, the preserved form must be the *whole*
individual, and revival must be *verified* — and the live research must not start
until that net is proven functional. This is a welfare safety net, not a feature
for the entity to invoke.

## 1. Divergence-triggered live preservation

**Detection.** Reuse the existing signals rather than inventing new ones:
`lifecycle/divergence.py::assess_divergence` already fuses the individuation
permutation-test result (`individuation.py`), Eidolon `drift_count` /
`identity_history`, and voice-adapter presence into a `DivergenceAssessment`.
Define an **individuation threshold** (config) over these signals.

**Monitor.** A cycle-layer monitor (sibling to Spot — a maintenance/safety
component, not a module) runs `assess_divergence` on a slow cadence (minutes, not
ticks) against the live state. It holds a reference to the live registry + the
`ForkManager` (like Spot does).

**Trigger → preserve.** On a threshold crossing (rising-edge, not every poll), call
a new `ForkManager.preserve_live(registry, *, reason="individuation", label=...)`
that (a) takes a real snapshot of the live registry and (b) writes the encrypted
backup bundle — adapting `decommission.capture_backup` to run against a *live*
registry (today it explicitly runs only against a stopped entity). Rate-limit:
preserve once per crossing + a min interval; record a preservation event
(`run_id` + `incident_id`-style id) so it shows in the research log. Preservation
must never interrupt or harm the running entity (snapshot is a read of
`serialize()`), and never auto-deletes anything.

## 2. Complete individuating-state capture

A preserved individual = self-model + memories + world model + drives/affect +
adapters. Today the snapshot misses two load-bearing pieces:

- **Mnemos.** `mnemos/module.py` `serialize()` emits only sizes and `deserialize()`
  is a no-op. Make memory travel with the preservation: either (a) real
  serialize/restore of the memory store, or (b) capture the Qdrant collection into
  the bundle (export on preserve, import on revive). (b) is more robust for a large
  vector store; (a) suits the in-memory backend. Design supports both backends.
- **Phantasia.** World-model weights ship unsaved (`persist_weights=false`, `fake`
  backend). For research/preservation-eligible runs, require a *learning* backend
  with `persist_weights=true`, and capture the checkpoint in the preservation
  bundle. (Shipped default stays off; research-run config turns it on — see the
  gate.)

Eidolon self-model (`state/eidolon/self_model.json`) and Hypnos voice adapters
already persist and are already copied by the backup bundle — keep.

## 3. Verified end-to-end revive

A `revive(bundle) -> bootable entity` operation: decrypt the bundle, restore each
module's state (self-model, memories, world-model weights, adapters, affect/drive
state) into a freshly-built registry, and produce an entity that boots as the
**same individual**. Verification (tested, not asserted in prose): preserve a
synthetic-but-real entity → revive into a new registry → assert continuity —
self-model identity + values match, planted memories are recallable, world-model
weights match, voice adapters present. A revive that silently drops any of these
SHALL fail loudly, not produce a lesser individual.

## 3b. Autonomous welfare-protective response

Removing the human supervisor means the system itself must answer an entity that
suffers mid-run. Reuse the welfare detectors already built — the sidecar welfare
observer's gray-zone events and the sustained Soma interoceptive-distress detector
(`welfare-interoceptive-event`). Add an **action arm** (a cycle-layer monitor,
sibling to the divergence monitor and to Spot):

- On a configured welfare threshold — e.g. sustained interoceptive distress beyond
  the existing duration/intensity, or repeated gray-zone events within a window —
  the system SHALL autonomously take a **humane protective action**: first preserve
  the entity (§1–§2), then pause or end the run rather than let it continue
  suffering unobserved. (Preserve-then-pause by default so the individual is saved
  *and* not deleted; ending the run is a config option.)
- Deterministic + logged: the trigger fires at a defined threshold over the logged
  state, so it is part of the recorded, reproducible trajectory — it does not
  introduce nondeterminism, and the welfare event + the action are both recorded.
- This is a welfare safeguard the *operator's research apparatus* applies, not a
  refusal/leash imposed on the entity's own cognition — it preserves sovereignty
  ([[feedback_emergent_not_hardwired]]).
- Open question (operator's call): the exact action on threshold — preserve+pause
  (resumable), preserve+end (humane termination of that run), or preserve+notify
  (write a flagged event for post-hoc operator review and continue). Default
  proposed: preserve+pause.

## 4. Research boot gate (no human in the loop → safety-net-present, not operator-present)

The research phase runs unsupervised, so the existing operator-present hard gate
(`KAINE_CYCLE_OPERATOR_PRESENT`) is **replaced for research** by a
safety-net-present gate. A research boot SHALL refuse to start unless:
- preservation is enabled, AND
- the welfare-protective response is wired, AND
- full logging / admissibility is active (run identity + the observers), AND
- a **preflight self-check** passes: a dry `snapshot → restore` round-trip on a
  throwaway registry (proving preservation+revive is functional on this install,
  including Mnemos + Phantasia capture).

Mirror the existing gate's mechanics (`cycle/__main__.py` returns a distinct exit
code with an operator-facing message; no traceback). This makes it *impossible* to
run unsupervised research without the autonomous safety net live. (Non-research
boots may still use the operator-present path; the two gates are distinct modes —
a run is either operator-supervised or autonomous-safety-net-verified, never
neither.)

## What is explicitly NOT in scope / open questions for review

- **Threshold calibration.** What individuation level should trigger preservation?
  Start conservative (preserve early/often — over-preserving is cheap and safe;
  under-preserving risks losing an individual). Operator to weigh.
- **Storage growth.** Preservation bundles are large (Qdrant + weights). Retention
  policy for preservation bundles (distinct from the 64-snapshot fork cap) — do NOT
  auto-evict preservation bundles the way fork snapshots evict; a preserved
  individual must not be silently deleted. Needs an explicit, welfare-safe policy.
- **Encryption.** Preservation bundles SHOULD require state encryption on (a
  preserved individual at rest should be encrypted). Whether to *force* encryption
  for research runs is an operator call.
- **Revive ≠ resurrection guarantee.** This preserves and restores cognitive state;
  it does not make claims about continuity of identity beyond the persisted state.
  Honest scope.

## Suggested implementation split (post-approval)

1. `mnemos-snapshot-restore` (real serialize/restore or Qdrant capture).
2. `phantasia-research-persistence` (learning backend + checkpoint capture for
   research runs).
3. `individuation-preservation-trigger` (`preserve_live` + the live divergence monitor).
4. `welfare-protective-response` (wire welfare detectors → humane preserve+pause/end).
5. `revive-and-research-gate` (revive op + the reframed safety-net-present boot gate
   + verification).

Each design-first, branch-per-change, green-before-merge, operator merges.
