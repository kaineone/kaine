# entity-preservation Specification

## Purpose
TBD - created by archiving change entity-preservation-on-divergence. Update Purpose after archive.
## Requirements
### Requirement: Divergence-triggered live preservation
The system SHALL monitor individuation/divergence on the live entity during a run
and, when a configured individuation threshold is crossed, SHALL preserve the
entity by taking a snapshot of the live registry and writing an encrypted backup
bundle, without interrupting or harming the running entity and without deleting
anything. Preservation SHALL be rate-limited (triggered on threshold crossing, not
continuously) and recorded as a preservation event joined to the run.

The live monitor SHALL apply a **warm-up gate**: it SHALL NOT count an
individuation crossing until the entity has accumulated the configured minimum
lived experience (`warmup_observations` logged lived events AND
`warmup_lived_time_s` of elapsed lived time). Before warm-up is satisfied, an
assessment SHALL be treated as not-crossed and recorded as a warming-up note. The
crossing decision SHALL key on **numeric** thresholds — a configured p-value
ceiling (`individuation_p_value_max`) AND a minimum effect size
(`fork_divergence_min`) over the warmed-up, birth-state-referenced individuation
signal — not on a bare `diverged` boolean alone. The gate is fail-closed: an
un-warmed-up or unreadable assessment never reads as a crossing, so preservation
of a genuinely individuated entity is at most delayed, never denied.

#### Scenario: Crossing the individuation threshold preserves the entity
- **WHEN** the warm-up gate is satisfied AND the warmed-up,
  birth-state-referenced divergence assessment crosses the configured numeric
  individuation thresholds during a run
- **THEN** a live-registry snapshot and an encrypted backup bundle are written, and a preservation event is recorded
- **AND** the running entity is not interrupted and nothing is deleted

#### Scenario: Sub-threshold does not preserve
- **WHEN** divergence stays below the threshold
- **THEN** no preservation bundle is written

#### Scenario: Before warm-up, no preservation fires
- **WHEN** the entity has not yet accumulated `warmup_observations` lived events
  and `warmup_lived_time_s` of lived time (e.g. immediately after boot, or in a
  sensory void)
- **THEN** no preservation bundle is written, and the poll is recorded as a
  warming-up note rather than a crossing

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

### Requirement: Entity-interior content is encrypted at rest in preservation/backup bundles
Preservation and backup bundles SHALL encrypt all entity-interior content at rest
when state encryption is enabled, including the individuation/divergence evidence
(`assessment.signals`) and the entity's expressed continuity view
(`continuity_note`). The plaintext manifest that accompanies a bundle SHALL carry
only NON-sensitive inventory: an optional entity name, a timestamp, the
preservation/snapshot identifier, the filename inventory, a `world_model_captured`
bool, and a bare `diverged` bool. The sensitive fields SHALL NOT appear in the
plaintext manifest. When state encryption is disabled the sensitive fields SHALL
be written to a clearly-named SEPARATE sidecar (honestly plaintext) rather than
folded into the manifest, so an operator can choose how to handle them.

#### Scenario: Continuity note and signals are not in the plaintext manifest when encrypted
- **WHEN** a backup or preservation bundle is produced with state encryption enabled
- **THEN** the plaintext `manifest.json` contains no `continuity_note` and no full `assessment.signals`
- **AND** it carries only the non-sensitive inventory (entity name, timestamp, id, file inventory, `world_model_captured`, a bare `diverged` bool)
- **AND** the `continuity_note` and full `assessment.signals` are recoverable only after decrypting the bundle

#### Scenario: Disabled encryption separates sensitive fields honestly
- **WHEN** a bundle is produced with state encryption disabled
- **THEN** the sensitive `continuity_note` and `assessment.signals` are written to a clearly-named separate sidecar rather than the manifest

### Requirement: Preservation/backup bundle artifacts use restrictive filesystem permissions
On POSIX hosts, preservation and backup bundle roots and snapshot roots SHALL be
created with mode `0700`, and the sensitive files written within them SHALL be
mode `0600`, so bundle content is not group- or world-readable. On non-POSIX
hosts this requirement MAY be relaxed.

#### Scenario: Bundle directory is owner-only
- **WHEN** a backup or preservation bundle directory is created on a POSIX host
- **THEN** its mode is `0700` (owner read/write/execute only)

### Requirement: The raw archive directory is confined outside the export allowlist
The OPTIONAL local-only raw bus archive directory SHALL be confined outside the
metrics-export allowlist root (`data/evaluation/`). The configuration loader and
the raw-archive consumer's `start()` SHALL reject (fail-closed, with a clear
error) any `archive_dir` whose resolved path is under `data/evaluation/`, so
verbatim conversation content can never become export-eligible. This is enforced,
not merely documented.

#### Scenario: A raw archive_dir under the export allowlist is rejected
- **WHEN** an operator configures `[research_event_log.raw_archive].archive_dir` under `data/evaluation/`
- **THEN** configuration load (or consumer start) fails closed with a clear error
- **AND** the shipped default under `state/research/` is accepted

### Requirement: Incident-log path scrubbing covers all absolute paths
The Spot incident-log path scrubber SHALL replace operator filesystem paths
across the full POSIX absolute-path space (including `/tmp`, `/var`, `/opt`,
`/proc`, `/srv`, `/mnt`, `/run`, `/etc`, and the home/root/user trees) and Windows
drive paths, so no operator path token survives into the durable incident log via
an exception repr.

#### Scenario: A non-home absolute path is scrubbed
- **WHEN** an exception repr containing `/tmp/kaine-preflight-x` or `/var/lib/kaine/y` is written to the incident log
- **THEN** the path token is replaced with `<PATH>` before write

### Requirement: Raw perceptual content is never persisted into memory snapshots
The memory module SHALL skip events whose type is a raw-perceptual type (at
minimum `audition.transcription` and `mundus.visual.raw`) when serializing a
workspace snapshot into stored memory text, so verbatim perceptual payloads are
never persisted into memory at the encoding site — independent of any downstream
redaction.

#### Scenario: A selected transcription event's payload is not stored
- **WHEN** an `audition.transcription` event carrying a verbatim transcript is selected into the workspace and the snapshot is serialized for memory storage
- **THEN** the verbatim transcript does not appear in the stored memory text

### Requirement: No plaintext entity content remains on encryption failure
The backup SHALL return failure (so the caller aborts deletion) AND SHALL remove
the plaintext bundle artifacts (including any internal-monologue intent log) when
state encryption is enabled but bundle encryption FAILS, leaving only an error
marker, so no plaintext entity content lingers on disk.

#### Scenario: Encryption failure leaves no plaintext entity content
- **WHEN** bundle encryption fails during a backup with state encryption enabled
- **THEN** the backup returns `ok=False`
- **AND** the plaintext bundle artifacts are removed, leaving only an error marker (no `intent_expression.jsonl`, no `snapshot.json`, no `self_model.json`)

