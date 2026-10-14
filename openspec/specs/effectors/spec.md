# effectors Specification

## Purpose
This capability defines the effectors module as KAINE's action layer, exposing three effectors with explicit success/failure results, sandboxed file writes, a shell-command whitelist, and a durable tamper-evident JSONL audit log. The effectors module acts only on provenance-verified act intents, publishes diagnostics-only bus events, and ships a safe-by-default configuration that keeps audit and sandbox files owner-only.

## Requirements

### Requirement: Three effectors with explicit success/failure semantics
The effectors module SHALL expose three default effectors implementing a common
`Effector` protocol: `FileWriteEffector`, `NotifyEffector`,
`ShellEffector`. Each effector's `act(request)` SHALL return an
`ActionResult` carrying `success: bool`, `elapsed_ms: float`,
`error: Optional[str]`, `metadata: dict`. Exceptions inside an
effector SHALL be caught and surfaced as `success=False` with the
exception class name in `error`.

#### Scenario: File write success returns success result
- **WHEN** `FileWriteEffector.act(FileWriteRequest(name="x.txt",
  content="hi"))` is awaited against a writable sandbox
- **THEN** the result has `success == True` and the file exists with
  content `"hi"`

#### Scenario: Effector exceptions surface as failure
- **WHEN** an effector raises during `act`
- **THEN** the returned `ActionResult` has `success == False` and
  `error` names the exception class

### Requirement: File write is sandboxed
`FileWriteEffector` SHALL only write inside the configured sandbox
directory (default `state/effectors/files/`). Attempts to write outside
the sandbox (via absolute paths, `..` traversal, or symlinks resolving
outside) SHALL fail before any file system change.

#### Scenario: Absolute path rejected
- **WHEN** a write request specifies `/etc/passwd`
- **THEN** the action fails with `error` indicating sandbox violation
  and no file is written

#### Scenario: Path traversal rejected
- **WHEN** a write request specifies `name="../../etc/passwd"`
- **THEN** the action fails with sandbox violation and no file is
  written

### Requirement: Shell whitelist is the only path to subprocess
`ShellEffector.act(ShellRequest)` SHALL match the request's command
and args against the configured `CommandWhitelist`. A request that
does not exactly match a whitelist entry SHALL be rejected without
spawning any subprocess. Each whitelist entry SHALL specify the
command, allowed arg patterns (regex), the per-invocation timeout,
and the working directory.

#### Scenario: Whitelisted command runs
- **WHEN** the whitelist allows `echo` with arg pattern `[A-Za-z0-9]+`
  and a request specifies `command="echo", args=["hello"]`
- **THEN** the action runs and returns `success == True`

#### Scenario: Unknown command rejected
- **WHEN** a request specifies a command not in the whitelist
- **THEN** the action fails without invoking subprocess

#### Scenario: Disallowed arg rejected
- **WHEN** the whitelist allows `echo` with `[A-Za-z]+` and a
  request supplies `args=["hello; rm -rf /"]`
- **THEN** the action fails without invoking subprocess

#### Scenario: Empty whitelist rejects everything
- **WHEN** the whitelist is empty (the v1 default)
- **THEN** every shell action fails

### Requirement: Every action is recorded in a durable JSONL audit log
The effectors module SHALL append one JSONL record per action attempt to its
configured audit log path. Each record SHALL contain `timestamp`,
`effector` name, `request` summary, `result.success`, `result.error`,
and `elapsed_ms`. Records SHALL NOT contain the contents of files
written, shell stdout, or notification body — content stays off the
audit log to mirror the episodic memory module's diagnostics-only bus event posture.

#### Scenario: Successful action is recorded
- **WHEN** an action succeeds
- **THEN** the audit log gains exactly one new JSONL line whose JSON
  parses and contains `success: true`

#### Scenario: Audit log excludes content
- **WHEN** a file-write action writes the string `"secret"`
- **THEN** the audit log line contains no field equal to `"secret"`

### Requirement: Effectors publishes diagnostics-only bus events
On each action, the effectors module SHALL publish a `effectors.action` event to its
`effectors.out` stream. The payload SHALL contain `effector`,
`success`, `elapsed_ms`, and `error` only — no file contents, no
shell stdout, no notification body.

#### Scenario: Action publishes one bus event
- **WHEN** any action is awaited
- **THEN** exactly one `effectors.action` event appears on `effectors.out`
  whose payload keys are exactly `{effector, success, elapsed_ms,
  error}`

### Requirement: Default Effectors config is safe-by-default
The repository SHALL ship a `[effectors]` block in `config/kaine.toml`
with: `sandbox_path` default `state/effectors/files/`,
`audit_log_path` default `state/effectors/audit.log`,
`max_file_bytes` default 1_048_576 (1 MiB), `notification_command`
default `notify-send`, and `[effectors.shell_whitelist]` empty by
default. `[modules].effectors = false` SHALL keep first boot from
auto-registering the effectors module.

#### Scenario: kaine.toml carries defaults
- **WHEN** an operator inspects `config/kaine.toml`
- **THEN** they find a `[effectors]` section with the documented keys
  and `[modules].effectors == false`

### Requirement: Effectors execute only in response to an act intent

The effectors module SHALL execute an effector only in response to an `act` intent emitted by
the executive action-selection step. The effectors module SHALL NOT act directly on the
workspace broadcast. Because action intents originate only from the
inhibition-gated action-selection step, an inhibited entity performs no
effector actions.

#### Scenario: Effectors runs an effector for an act intent

- **WHEN** an `act` intent naming a registered effector is delivered to the effectors module
- **THEN** the effectors module invokes that effector and records the action in its audit log

#### Scenario: Effectors does not act without an intent

- **WHEN** a workspace broadcast occurs but no `act` intent is issued
- **THEN** the effectors module invokes no effector

### Requirement: The Effectors audit log is tamper-evident

The effectors module's audit log SHALL be tamper-evident, not merely append-only. Each record
SHALL carry a hash chained to the previous record
(`this_hash = sha256(prev_hash || canonical(record))`), and the system SHALL
provide a verifier that detects any edit, reordering, or truncation of historical
records and reports the first break.

#### Scenario: Edited history is detected

- **WHEN** a historical audit record is altered or removed on disk
- **THEN** the chain verifier reports a break at that record

### Requirement: Effectors audit and sandbox files are owner-only

The effectors module SHALL create the audit log and the filesystem sandbox owner-only — mode
0600 for files and mode 0700 for directories — regardless of the ambient umask,
matching the preservation snapshot hardening.

#### Scenario: Files are not group/world readable under a permissive umask

- **WHEN** the audit log and sandbox are created under umask `0002`
- **THEN** the audit log is mode `0600` and the sandbox directory is mode `0700`

### Requirement: Effectors acts only on provenance-verified act intents

The effectors module SHALL realize an `act` intent only when the intent's provenance from the
cycle's action-selection step (the action selection module) is verified. Provenance SHALL be enforced
by either a datastore-level restriction on who may publish to `action_selection.out`, or a
cryptographic signature over the canonical intent payload verified by the effectors module before
any effector runs. An `act` intent that fails provenance verification SHALL NOT
execute any effector, SHALL be dropped, and SHALL be recorded in the audit log
under a distinct provenance-rejected category.

This boundary is in addition to, not a replacement for, the effector whitelist and
filesystem sandbox, which remain the primary enforced gate.

#### Scenario: Forged act intent from a writer other than Action selection is blocked

- **WHEN** a module other than the action selection module publishes an `act` intent onto `action_selection.out`
- **THEN** the effectors module does not run the effector
- **AND** the attempt is recorded in the audit log as provenance-rejected

#### Scenario: Legitimate Action selection intent still executes

- **WHEN** the action selection module emits an `act` intent for an enabled effector from a
  non-inhibited snapshot
- **THEN** the effectors module verifies provenance and realizes the action normally

#### Scenario: A captured signed intent cannot be replayed

- **WHEN** a previously-realized signed act intent is re-published
- **THEN** the effectors module rejects it as already realized and runs no effector
