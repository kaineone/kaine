## ADDED Requirements

### Requirement: SelfModel structure and empty defaults
Eidolon SHALL define a `SelfModel` data type carrying at minimum:
`values` (list of strings), `behavioral_norms` (list of strings),
`capability_map` (dict), `personality_baseline` (dict mapping trait
names to floats), `identity_history` (list of dated snapshots), and
`internal_speech_count` (int). On a fresh deployment every field
SHALL be empty / zero — Eidolon prescribes no identity.

#### Scenario: Fresh SelfModel is empty
- **WHEN** `SelfModel()` is constructed with no arguments
- **THEN** `values == []`, `behavioral_norms == []`,
  `capability_map == {}`, `personality_baseline == {}`,
  `identity_history == []`, and `internal_speech_count == 0`

### Requirement: JSON persistence at a configurable path
Eidolon SHALL persist its SelfModel to a JSON file at a configurable
path (default `state/eidolon/self_model.json`). Writes SHALL be
atomic — Eidolon writes to a temporary file first and renames it
into place, so a crash mid-save SHALL NOT corrupt the persisted
document. On startup, an existing file at the configured path SHALL
be loaded; absent file means a fresh empty SelfModel is used.

#### Scenario: Existing file is loaded on init
- **WHEN** a `self_model.json` with `values = ["honesty"]` exists at
  the configured path
- **THEN** the Eidolon module after `initialize` has a SelfModel
  whose `values == ["honesty"]`

#### Scenario: Save is atomic
- **WHEN** Eidolon writes the SelfModel and is interrupted partway
  through
- **THEN** the on-disk JSON file is either fully the prior version
  or fully the new version, never half-written

### Requirement: Workspace broadcasts update the drift detector
Eidolon SHALL subscribe to `workspace.broadcast` and update its
`DriftDetector` with each observed broadcast. The default
`SourceDistributionDrift` SHALL track two histograms of event-source
frequencies — a recent window (default 100 broadcasts) and all-time
cumulative.

#### Scenario: Recent window respects size cap
- **WHEN** 150 broadcasts have been observed with default window 100
- **THEN** the recent histogram counts the last 100 only, while the
  cumulative histogram counts all 150

### Requirement: Drift score elevation publishes a diagnostics event
Eidolon SHALL compute the symmetric KL divergence between the recent
and cumulative histograms (smoothed with a small epsilon). When the
score exceeds the configured threshold, Eidolon SHALL publish an
`eidolon.drift` event whose payload contains `score`, `recent_count`,
`historical_count`, and `top_drifted_sources` (a list of source names
without any payload content). The salience SHALL escalate to the
configured `alert_salience` when the threshold is crossed.

#### Scenario: Drift above threshold publishes alert
- **WHEN** drift score crosses the configured threshold
- **THEN** an `eidolon.drift` event is published with salience equal
  to `alert_salience` and a payload containing only the documented
  diagnostics keys

#### Scenario: Drift event carries no contents
- **WHEN** any `eidolon.drift` event is published
- **THEN** its payload contains no keys named `text`, `payload`,
  `value`, `belief`, or any other field that could leak module
  contents

### Requirement: Internal-speech subscription increments counter
Eidolon SHALL subscribe to a configurable internal-speech stream
(default `lingua.internal`). For each event observed on that stream
the module SHALL increment `SelfModel.internal_speech_count`.
Eidolon SHALL NOT record the content of internal speech in the
SelfModel — only the count and bounded hash fingerprints.

#### Scenario: Counter increments per internal-speech event
- **WHEN** three events arrive on the configured internal-speech
  stream while Eidolon is running
- **THEN** `SelfModel.internal_speech_count` after the third event
  equals the prior count plus three

### Requirement: Periodic save and final-save-on-shutdown
Eidolon SHALL persist the SelfModel to disk every `save_interval_s`
seconds (default 30) while running. `shutdown()` SHALL force a final
save regardless of how recently the periodic save fired.

#### Scenario: Shutdown forces a final save
- **WHEN** `Eidolon.shutdown()` is awaited
- **THEN** the on-disk file reflects the current in-memory SelfModel

### Requirement: Default Eidolon config and disabled-by-default
The repository SHALL ship an `[eidolon]` block in `config/kaine.toml`
with default values for `persistence_path`, `drift_window`,
`drift_threshold`, `save_interval_s`, `internal_speech_stream`,
`identity_history_cap`, `baseline_salience`, and `alert_salience`.
`[modules].eidolon = false` SHALL keep first boot from auto-registering
Eidolon.

#### Scenario: kaine.toml carries defaults
- **WHEN** an operator inspects `config/kaine.toml`
- **THEN** they find an `[eidolon]` section with the documented keys
  and `[modules].eidolon == false`
