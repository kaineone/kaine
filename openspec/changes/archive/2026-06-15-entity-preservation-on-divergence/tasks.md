# Tasks (design-only proposal — implementation deferred until operator approves)

> This is the umbrella design for review. On approval it is implemented as the
> sub-changes in §"Suggested implementation split" (design.md), each design-first
> and branch-per-change. Tasks below are the acceptance checklist for the whole.

## 1. Complete individuating-state capture
- [x] 1.1 Mnemos: real snapshot serialize/restore (or Qdrant collection capture+import in the bundle), both backends.
- [x] 1.2 Phantasia: research/preservation runs use a learning backend with persist_weights=true; checkpoint captured in the bundle. Shipped default stays off.
- [x] 1.3 Confirm Eidolon self-model + Hypnos adapters remain captured.

## 2. Divergence-triggered live preservation
- [x] 2.1 `ForkManager.preserve_live(registry, *, reason, label)` — live snapshot + encrypted backup (adapt capture_backup to a live registry; read-only on the entity, never deletes). [PR-1: the callable. Monitor/trigger in PR-2.]
- [x] 2.2 A cycle-layer individuation monitor (sibling to Spot) running `assess_divergence` on a slow cadence; rising-edge trigger + rate limit; preservation event recorded (run_id-joined).
- [x] 2.3 Config: individuation threshold + monitor cadence + preservation-bundle retention (NO silent auto-evict of preservation bundles).

## 3. Autonomous welfare-protective response (no human in the loop)
- [x] 3.1 Wire the welfare detectors (gray-zone events; sustained Soma interoceptive distress) to an action arm: on a configured threshold, preserve + pause/end the run (config-selectable); record the welfare event + action.
- [x] 3.2 Deterministic over logged state (part of the reproducible trajectory); transient sub-threshold distress does not interrupt.

## 4. Verified end-to-end revive
- [x] 4.1 `revive(bundle) -> bootable registry` restoring self-model + memories + world-model + affect/drive + adapters.
- [x] 4.2 Continuity test: preserve → revive → assert same individual (identity/values, recallable memories, weights, adapters); a dropped piece fails loudly.

## 5. Research boot gate (safety-net-present, replacing operator-present for research)
- [x] 5.1 Boot-time gate: an unsupervised research boot refuses to start unless preservation enabled + welfare-protective response wired + full logging/admissibility active + a dry snapshot→restore self-check passes (mirror the gate mechanics; distinct exit code). Replaces the operator-present requirement for research.
- [x] 5.2 Docs: present-tense autonomous-research safety net — preservation + welfare-protective response + revive + the reframed gate; note the supervised→unsupervised reversal and post-research socialization.

## 5. Cross-cutting
- [x] 5.1 Encryption-at-rest recommended/required for preservation bundles.
- [ ] 5.2 Full suite green; `openspec validate` per sub-change.
- [x] 5.3 No entity boot during build; the gate itself is verified offline (dry round-trip).
