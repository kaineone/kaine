## ADDED Requirements

### Requirement: Workspace-following observers use the canonical broadcast decode

Observers that follow `workspace.broadcast` SHALL consume it via the bus's
`subscribe_workspace` path — the same decoded-snapshot path every module uses —
not the standard `Event` decode. The standard decode rejects broadcast entries
(which carry a `snapshot` field rather than `salience`/`type`/`payload`), so an
observer using it receives nothing. A `WorkspaceSubscriberObserver` base SHALL
follow the broadcast and dispatch the decoded snapshot payload to its handler;
`TrajectoryRecorder` and `AttributionRecorder` SHALL use it.

#### Scenario: Trajectory records one row per broadcast

- **WHEN** the workspace broadcasts a snapshot (a `{snapshot: <json>}` entry)
- **THEN** the trajectory recorder writes one row carrying that snapshot's
  `tick_index`, `selected`, and `salience_scores`
- **AND** a session of N broadcasts yields N trajectory rows

#### Scenario: The standard-Event decode path would have recorded nothing

- **WHEN** the same broadcast entry is offered through the standard `Event`
  decode used by stream-following observers
- **THEN** it does not decode to a usable event
- **AND** confirms why the workspace observers must use `subscribe_workspace`

### Requirement: Evaluation layer stays decoupled from modules

The new workspace-following observer base SHALL touch only the bus reader
protocol; `kaine.evaluation` SHALL NOT import `kaine.modules.*`. The
`memory_source` and `cognitive_query_client` that the memory-probe and
eidolon-accuracy observers require SHALL be constructed as adapters at the cycle
entrypoint (the allowed coupling point) and injected, so those observers
instantiate when enabled without the evaluation layer importing any module.

#### Scenario: Evaluation layer imports no modules

- **WHEN** the evaluation package is imported
- **THEN** it imports no `kaine.modules.*` module

#### Scenario: Providers wired → probe observers instantiate

- **WHEN** the sidecar is built with a `memory_source` and a
  `cognitive_query_client` and the corresponding flags enabled
- **THEN** the `memory_probes` and `eidolon_accuracy` observers are included
- **AND** with neither provided they are skipped, and the sidecar still starts
