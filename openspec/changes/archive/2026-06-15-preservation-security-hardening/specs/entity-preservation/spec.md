# entity-preservation (delta)

## ADDED Requirements

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
