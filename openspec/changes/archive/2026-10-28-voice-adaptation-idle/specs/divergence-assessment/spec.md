## REMOVED Requirements

### Requirement: Consolidation divergence metric
**Reason**: The pair builder's chosen and rejected texts always differ, so the metric was 1.0 for every entity at every sleep; the paper (section 3.5) computes no organ-level divergence until a validated preference source exists.
**Migration**: None. Whether an entity has individuated is assessed by the individuation test and the remaining arms.

### Requirement: Divergence assessment incorporates the consolidation signal
**Reason**: The arm marked every entity as diverged at its first sleep and carried no information.
**Migration**: The individuation, voice-distinctiveness, self-model drift and adapter arms are unchanged.

### Requirement: Live preservation and decommission use the same consolidation thresholds
**Reason**: The consolidation thresholds are removed with the arm.
**Migration**: The live monitor and the decommission CLI keep reading the same distinctiveness threshold from `[sleep.voice_alignment]`.

## ADDED Requirements

### Requirement: An old consolidation record marks nothing
`assess_divergence` SHALL NOT read `state/sleep/consolidation_divergence.json`, and its signals SHALL carry no `consolidation_*` keys. The preservation monitor SHALL have no `consolidation` arm. A record left by an earlier boot SHALL remain a known state file for decommission, renames and lived-artifact checks.

#### Scenario: A record from an earlier boot
- **WHEN** the state tree holds a consolidation divergence record with rate 1.0 and no other arm is active
- **THEN** the assessment reports not diverged
