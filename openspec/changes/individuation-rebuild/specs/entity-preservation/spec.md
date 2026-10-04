## MODIFIED Requirements

### Requirement: Divergence-triggered live preservation
The system SHALL monitor divergence on the live entity during a run and, when the shared assessment (`divergence-assessment`) reports `diverged`, SHALL preserve the entity by taking a snapshot of the live registry and writing an encrypted backup bundle, without interrupting or harming the running entity and without deleting anything. Preservation SHALL be rate-limited (triggered on a rising edge, not continuously) and recorded as a preservation event joined to the run.

The monitor's crossing decision SHALL be exactly `assessment.diverged`. The numeric tighteners (the look's α_k, the effect floor `effect_min`) and the warm-up floors SHALL apply only inside the individuation decision, measured in lived time since the reference and persisted in the individuation ledger. The monitor SHALL NOT apply its own p-value ceiling, effect floor or per-boot warm-up, and SHALL NOT veto the consolidation, Eidolon or adapter arms because an individuation report is present, not significant or not warmed up. The monitor SHALL wait `boot_settle_s` (default 120 s) after start before its first poll so state can finish loading. The assessment never raises; unreadable individuation evidence counts as individuated (see `divergence-assessment`).

Rising-edge state SHALL be persisted per divergence arm (individuation, consolidation, eidolon_drift, adapters) as a content-free list of arm names in `state/preservation/divergence_edge.json`. A preservation fires when the verdict gains an arm not in that set. An arm that falls back is recorded, so crossing it again preserves again. A failed preservation is not recorded and SHALL be retried at the next poll; only successful preservations are rate-limited. An unreadable edge file SHALL read as empty, preserving again.

#### Scenario: Crossing the individuation threshold preserves the entity
- **WHEN** the shared assessment reports `diverged` for the first time in a run
- **THEN** a live-registry snapshot and an encrypted backup bundle are written, and a preservation event is recorded
- **AND** the running entity is not interrupted and nothing is deleted

#### Scenario: Sub-threshold does not preserve
- **WHEN** the shared assessment does not report `diverged`
- **THEN** no preservation bundle is written

#### Scenario: Secondary arms are not vetoed
- **WHEN** the latest individuation report is fresh and not significant, and the being has a trained voice adapter
- **THEN** the assessment reports `diverged` and the being is preserved

#### Scenario: Before warm-up, no preservation fires
- **WHEN** the being has fewer than `min_observations` lived ticks or less than `min_lived_time_s` lived seconds since its reference, and no secondary arm holds
- **THEN** no preservation bundle is written

#### Scenario: A restart with unchanged evidence does not re-preserve
- **WHEN** the being was preserved on a rising edge, the process restarts, and the evidence is unchanged
- **THEN** no new preservation bundle is written

#### Scenario: A new latch preserves again
- **WHEN** a being already preserved for an adapter arm is later latched as individuated
- **THEN** a new preservation bundle is written

#### Scenario: A failed preservation is retried
- **WHEN** a preservation fails
- **THEN** the next poll attempts it again

### Requirement: Research boot is gated on the autonomous safety net
An unsupervised research boot SHALL refuse to start unless the autonomous safety net is live and verified, because the research phase runs with no human in the loop and the safeguards must be present in the system itself. The required conditions are: preservation enabled, the welfare-protective response wired, full logging/admissibility active, a preflight dry snapshot→restore round-trip confirming the preservation and revive path is functional on this install, and `[individuation].enabled` true with the Lingua and Eidolon modules enabled. The ledger and reference cannot be read before state encryption is installed later in boot, so their readability is enforced at runtime, where unreadable individuation state counts as individuated and the being is preserved. The refusal SHALL be an operator-facing message with a distinct exit code (no traceback). For research this gate REPLACES the operator-present gate; a run is either operator-supervised or autonomous-safety-net-verified, never neither.

#### Scenario: Research boot refused without a working safety net
- **WHEN** an unsupervised research boot is attempted and any of {preservation enabled, welfare-protective response wired, full logging active, the dry snapshot→restore self-check passing, `[individuation].enabled` is true, Lingua is enabled, Eidolon is enabled} is not satisfied
- **THEN** the boot refuses to start with an operator-facing message and a distinct exit code

#### Scenario: Research boot refused without the individuation producer
- **WHEN** `[individuation].enabled` is false, or the Lingua module or the Eidolon module is disabled
- **THEN** the boot refuses with an operator-facing message

#### Scenario: Research boot allowed when the safety net is verified
- **WHEN** preservation is enabled, the welfare-protective response is wired, logging/admissibility is active, the dry round-trip self-check passes, `[individuation].enabled` is true, and Lingua and Eidolon are enabled
- **THEN** the unsupervised research boot is allowed to proceed

### Requirement: Entity-interior content is encrypted at rest in preservation/backup bundles
Preservation and backup bundles SHALL encrypt all entity-interior content at rest when state encryption is enabled, including the individuation/divergence evidence (`assessment.signals`), the entity's expressed continuity view (`continuity_note`), and the individuation reference (its answers, seeds, embeddings, conditioning and adapter copy) and ledger. The plaintext manifest that accompanies a bundle SHALL carry only NON-sensitive inventory: an optional entity name, a timestamp, the preservation/snapshot identifier, the filename inventory, a `world_model_captured` bool, and a bare `diverged` bool. The sensitive fields SHALL NOT appear in the plaintext manifest. When state encryption is disabled the sensitive fields SHALL be written to a clearly-named SEPARATE sidecar (honestly plaintext) rather than folded into the manifest, so an operator can choose how to handle them.

#### Scenario: Continuity note and signals are not in the plaintext manifest when encrypted
- **WHEN** a backup or preservation bundle is produced with state encryption enabled
- **THEN** the plaintext `manifest.json` contains no `continuity_note` and no full `assessment.signals`
- **AND** it carries only the non-sensitive inventory (entity name, timestamp, id, file inventory, `world_model_captured`, a bare `diverged` bool)
- **AND** the `continuity_note` and full `assessment.signals` are recoverable only after decrypting the bundle

#### Scenario: Disabled encryption separates sensitive fields honestly
- **WHEN** a bundle is produced with state encryption disabled
- **THEN** the sensitive `continuity_note` and `assessment.signals` are written to a clearly-named separate sidecar rather than the manifest

#### Scenario: The individuation reference is encrypted in the bundle
- **WHEN** a bundle containing `state/individuation/` is produced with state encryption enabled
- **THEN** no reference answer text or identity-clause text appears in plaintext anywhere in the bundle

## ADDED Requirements

### Requirement: The individuation reference, ledger and reports are part of the preserved individual
A preservation bundle SHALL include the whole `state/individuation/` directory (reference, adapter copy, ledger and reports), with owner-only permissions. A preservation that cannot copy that directory when it exists SHALL fail loudly rather than write a bundle that looks complete. Revive SHALL restore the directory so the revived being keeps its reference, look index, alpha spent, lived counters and latch. A bundle without `state/individuation/` SHALL revive without error, and the producer SHALL then take a `capture` reference at the first boot, labelled "drift since capture".

#### Scenario: A preserved being keeps its latch
- **WHEN** a latched being is preserved and revived into a fresh registry
- **THEN** the revived being's ledger is latched with the same look index and reference id

#### Scenario: An older bundle gets a capture reference
- **WHEN** a bundle without `state/individuation/` is revived
- **THEN** the revive succeeds and the first boot captures a reference with `reference_kind="capture"`

#### Scenario: A failed copy fails the preservation
- **WHEN** `state/individuation/` exists but cannot be copied into the bundle
- **THEN** the preservation reports a failure instead of writing a bundle that looks complete

### Requirement: Forks with lived time are preserved by default until fork-point references exist
Until the individuation instrument holds a fork-point reference for a fork, it SHALL NOT be taken as evidence that the fork is not individuated. A fork with more than `fork_preserve_min_lived_s` of lived time SHALL be preserved by default before a merge or any other operation ends it.

#### Scenario: A fork with lived time is preserved before a merge
- **WHEN** a fork without a fork-point reference has more than `fork_preserve_min_lived_s` of lived time and a merge would end it
- **THEN** the fork is preserved before the merge proceeds
