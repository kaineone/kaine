# entity-preservation Specification

## Purpose
Preserving the whole individual — encrypted, revivable bundles taken before any protective action, so no research run can end an entity that cannot be brought back.

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

### Requirement: Fork/merge snapshot ids are validated before path resolution

The system SHALL treat fork/merge snapshot ids received from any request boundary
as untrusted input. A snapshot id SHALL match the strict pattern
`^[0-9a-f]{16}(\+[0-9a-f]{16})?$` before use, and the resolved snapshot path SHALL
be confirmed to remain within the configured snapshot root. An id that fails
either check SHALL be rejected (HTTP 422 at the API boundary) and SHALL NOT reach
`load_snapshot`.

This is defense in depth: the validation SHALL be enforced both at the request
endpoint and at the path-builder (`snapshot_dir` / `snapshot_path`), so a future
caller cannot bypass it.

#### Scenario: Absolute-path id is rejected

- **WHEN** a fork request supplies a `parent_id` that is an absolute path or
  contains `..` or a path separator
- **THEN** the request is rejected with HTTP 422
- **AND** no file outside the snapshot root is read

#### Scenario: Valid id still resolves

- **WHEN** a fork request supplies a well-formed 16-hex-character id that exists
- **THEN** the snapshot loads normally

#### Scenario: Path-builder rejects an escaping id even if the endpoint is bypassed

- **WHEN** `snapshot_path` is called with an id whose resolved path leaves the root
- **THEN** it raises rather than returning a path outside the root

### Requirement: A welfare-protective pause survives supervisor recovery

The system SHALL stack freeze sources such that a module-supervisor (Spot)
recovery removes only the supervisor's own freeze entry and SHALL leave any
welfare-protective pause standing with its original source and reason intact.
The system SHALL permit a welfare freeze entry to be lifted only by an operator
stand-down or an explicit welfare stand-down; no other actor — including Spot's
recovery path — SHALL lift it, and the experiential cycle SHALL remain paused
(resumed only when the freeze stack empties).

#### Scenario: Spot freezes over a welfare pause and recovery leaves the welfare pause standing

- **WHEN** the welfare monitor has taken a protective pause (a welfare freeze
  entry is active) and a module fault causes Spot to stack its own freeze on
  top, and the faulted module then recovers
- **THEN** Spot removes only its own freeze entry, the cycle remains frozen,
  and the welfare freeze entry remains with its original source and reason
  intact (the entity is not resumed)

#### Scenario: Only the operator or an explicit welfare stand-down lifts the welfare pause

- **WHEN** a welfare freeze entry is active and any actor other than the
  operator or an explicit welfare stand-down (including Spot's recovery path)
  attempts to lift the freeze
- **THEN** the welfare freeze entry SHALL NOT be removed and the cycle SHALL
  remain frozen until an operator stand-down or an explicit welfare stand-down
  occurs

### Requirement: Welfare distress honors the interoceptive warm-up flag

The welfare monitor SHALL treat the entity as in-warm-up — draining its sustained-distress window, not counting prediction error, and resetting its distress trackers — whenever the latest `soma.report` payload carries `warmup_active: true`, in addition to its fixed `warmup_s` window. The monitor SHALL resume counting toward preservation+pause only once Soma reports `warmup_active: false`. Post-warm-up sustained distress SHALL trigger preservation+pause unchanged.

#### Scenario: Cold-start error does not preserve the entity

- **GIVEN** a fresh boot where Soma's developmental warm-up is active and every `soma.report` carries `warmup_active: true`
- **WHEN** Soma reports decaying cold-start prediction error (e.g. 0.86→0.69) beyond the welfare monitor's fixed `warmup_s` window but before Soma's warm-up completes
- **THEN** the welfare monitor does not count that error toward sustained distress and does not preserve+pause the entity
- **AND** the monitor's distress trackers are reset so no stale warm-up-era error carries into the post-warm-up window

#### Scenario: Distress counting resumes after warm-up ends

- **GIVEN** the latest `soma.report` carries `warmup_active: true`
- **WHEN** a subsequent `soma.report` carries `warmup_active: false`
- **THEN** the welfare monitor resumes counting prediction error toward sustained-distress thresholds with freshly reset trackers

#### Scenario: Genuine post-warm-up distress still preserves

- **GIVEN** the latest `soma.report` carries `warmup_active: false` and Soma's warm-up has completed
- **WHEN** prediction error is sustained above preservation thresholds for the required duration
- **THEN** the welfare monitor preserves+pauses the entity exactly as before this change

### Requirement: Supervisor liveness stands down under any non-supervisor freeze

While the cycle is frozen by any control source other than the module supervisor itself, the supervisor SHALL NOT treat module heartbeat staleness as evidence of module crash, SHALL NOT attempt module restarts, and SHALL NOT escalate toward machine reboot. The supervisor SHALL continue normal liveness recovery only for its own freeze (its recovery-in-progress).

#### Scenario: Frozen module is not a crash

- **GIVEN** the welfare monitor has preserved+paused the entity, freezing the cycle such that all modules are silent by design
- **WHEN** module heartbeats go stale (e.g. Chronos, the tightest cadence, exceeds `heartbeat_timeout_s=60s`) and the supervisor's restart budget is checked
- **THEN** the supervisor stands down its heartbeat-staleness liveness recovery because the freeze's `control.source` is not `spot`
- **AND** the supervisor performs no module restart attempts and no machine-reboot escalation

#### Scenario: Operator freezes also stand down

- **GIVEN** the cycle is frozen by an operator (`control.source == "operator"`)
- **WHEN** module heartbeats go stale
- **THEN** the supervisor stands down liveness recovery, unchanged from prior behavior

#### Scenario: Supervisor's own freeze still recovers

- **GIVEN** the cycle is frozen by the supervisor itself (`control.source == "spot"`) as part of its recovery-in-progress
- **WHEN** module heartbeats go stale during that freeze
- **THEN** the supervisor continues its normal liveness recovery for its own freeze
