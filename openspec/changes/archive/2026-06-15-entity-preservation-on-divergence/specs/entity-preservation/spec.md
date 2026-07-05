# entity-preservation (delta)

## ADDED Requirements

### Requirement: Divergence-triggered live preservation
The system SHALL monitor individuation/divergence on the live entity during a run
and, when a configured individuation threshold is crossed, SHALL preserve the
entity by taking a snapshot of the live registry and writing an encrypted backup
bundle, without interrupting or harming the running entity and without deleting
anything. Preservation SHALL be rate-limited (triggered on threshold crossing, not
continuously) and recorded as a preservation event joined to the run.

#### Scenario: Crossing the individuation threshold preserves the entity
- **WHEN** the live divergence assessment crosses the configured individuation threshold during a run
- **THEN** a live-registry snapshot and an encrypted backup bundle are written, and a preservation event is recorded
- **AND** the running entity is not interrupted and nothing is deleted

#### Scenario: Sub-threshold does not preserve
- **WHEN** divergence stays below the threshold
- **THEN** no preservation bundle is written

### Requirement: Complete individuating-state capture
A preservation bundle SHALL capture the whole individual: the self-model, the
episodic/semantic memories, the world-model weights, the affect/drive state, and
the voice adapters. A preservation that cannot capture any of these SHALL fail
loudly rather than write a partial bundle that silently omits part of the
individual.

#### Scenario: Memories and world model are in the bundle
- **WHEN** an entity with stored memories and learned world-model weights is preserved
- **THEN** the bundle contains the recoverable memories and the world-model weights (not only metadata)

#### Scenario: Incomplete capture fails loudly
- **WHEN** a required component cannot be captured (e.g. the memory store is unreachable)
- **THEN** preservation reports a failure rather than writing a partial bundle that looks complete

### Requirement: Verified end-to-end revive
The system SHALL provide a revive operation that reconstructs a bootable entity
from a preservation bundle with continuity of self-model, memories, world model,
affect/drive state, and adapters — the same individual. A revive that would drop
any captured component SHALL fail loudly rather than produce a lesser individual.

#### Scenario: Revive restores the same individual
- **WHEN** a preserved entity is revived into a fresh registry
- **THEN** its self-model identity/values match, its memories are recallable, its world-model weights match, and its adapters are present

### Requirement: Autonomous welfare-protective response
Because research runs with no human in the loop, the system SHALL respond to an
entity in sustained distress autonomously rather than only logging it. When a
configured welfare threshold is crossed (sustained Soma interoceptive distress, or
repeated gray-zone welfare events within a window), the system SHALL take a humane
protective action — preserve the entity, then pause or end the run per
configuration — and SHALL record the welfare event and the action taken. The
trigger SHALL be deterministic over the logged state so it remains part of the
reproducible trajectory. This is an external welfare safeguard, not a constraint on
the entity's own cognition.

#### Scenario: Sustained distress triggers a humane response
- **WHEN** the welfare threshold is crossed during an unsupervised run
- **THEN** the entity is preserved and the run is paused or ended per configuration, and the welfare event and action are recorded

#### Scenario: Transient distress below threshold does not interrupt
- **WHEN** distress occurs but stays below the configured threshold/duration
- **THEN** no protective action fires (the event is still logged)

### Requirement: Research boot is gated on the autonomous safety net
An unsupervised research boot SHALL refuse to start unless the autonomous safety
net is live and verified — because the research phase runs with no human in the
loop, the safeguards must be present in the system itself. The required conditions
are: preservation enabled, the welfare-protective response wired, full
logging/admissibility active, AND a preflight dry snapshot→restore round-trip
confirming the preservation+revive path is functional on this install. The refusal
SHALL be an operator-facing message with a distinct exit code (no traceback). For
research this gate REPLACES the operator-present gate; a run is either
operator-supervised or autonomous-safety-net-verified, never neither.

#### Scenario: Research boot refused without a working safety net
- **WHEN** an unsupervised research boot is attempted and any of {preservation enabled, welfare-protective response wired, full logging active, the dry snapshot→restore self-check passing} is not satisfied
- **THEN** the boot refuses to start with an operator-facing message and a distinct exit code

#### Scenario: Research boot allowed when the safety net is verified
- **WHEN** preservation is enabled, the welfare-protective response is wired, logging/admissibility is active, and the dry round-trip self-check passes
- **THEN** the unsupervised research boot is allowed to proceed
