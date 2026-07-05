## ADDED Requirements

### Requirement: BaseModule liveness and restart contract
`BaseModule` SHALL maintain a monotonic heartbeat that is refreshed centrally —
after each `on_workspace` in the workspace loop and at the end of `publish` — so
that any initialized module receiving the workspace broadcast keeps a fresh
heartbeat regardless of its own publishing activity. `BaseModule` SHALL expose
`heartbeat_age() -> float` (seconds since the last beat) and `health() -> dict`
reporting at least `name`, `heartbeat_age_s`, `tasks_total`, `tasks_done`, and
`tasks_failed`, derived from its task list; `health()` SHALL NOT raise.
`BaseModule` SHALL expose an async `restart()` that tears down and recreates the
module's own tasks (a light restart), and `holds_external_resources() -> bool`
(default `False`) that a subclass overrides to signal it must be rebuilt rather
than light-restarted.

#### Scenario: Heartbeat refreshes on broadcast and publish
- **WHEN** a module handles a workspace broadcast or publishes an event
- **THEN** its `heartbeat_age()` drops toward zero

#### Scenario: Health snapshot reports task state
- **WHEN** `health()` is called on a module with a crashed task
- **THEN** the returned dict reports `tasks_failed >= 1` and does not raise

#### Scenario: Default modules are light-restartable
- **WHEN** a module that has not overridden `holds_external_resources()` is asked
  for it
- **THEN** the result is `False` and `restart()` recreates its tasks

#### Scenario: Resource-holding modules opt into heavy restart
- **WHEN** a module that constructs external clients or model handles is asked for
  `holds_external_resources()`
- **THEN** the result is `True`

### Requirement: ModuleRegistry instance replacement
`ModuleRegistry` SHALL expose `replace(name, module)` that swaps the instance
registered under `name` for a new one whose `name` matches, so a supervisor can
substitute a freshly rebuilt module without re-registering. It SHALL raise if the
name is not present or the replacement's `name` differs.

#### Scenario: Replace swaps the instance
- **WHEN** `replace("mnemos", new_mnemos)` is called and a `mnemos` is registered
- **THEN** `get("mnemos")` returns the new instance

#### Scenario: Replace rejects a name mismatch
- **WHEN** `replace("mnemos", a_vox_instance)` is called
- **THEN** it raises rather than registering a mismatched instance
