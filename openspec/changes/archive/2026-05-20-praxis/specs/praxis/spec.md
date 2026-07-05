## ADDED Requirements

### Requirement: Three effectors with explicit success/failure semantics
Praxis SHALL expose three default effectors implementing a common
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
directory (default `state/praxis/files/`). Attempts to write outside
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
Praxis SHALL append one JSONL record per action attempt to its
configured audit log path. Each record SHALL contain `timestamp`,
`effector` name, `request` summary, `result.success`, `result.error`,
and `elapsed_ms`. Records SHALL NOT contain the contents of files
written, shell stdout, or notification body — content stays off the
audit log to mirror Mnemos's diagnostics-only bus event posture.

#### Scenario: Successful action is recorded
- **WHEN** an action succeeds
- **THEN** the audit log gains exactly one new JSONL line whose JSON
  parses and contains `success: true`

#### Scenario: Audit log excludes content
- **WHEN** a file-write action writes the string `"secret"`
- **THEN** the audit log line contains no field equal to `"secret"`

### Requirement: Praxis publishes diagnostics-only bus events
On each action, Praxis SHALL publish a `praxis.action` event to its
`praxis.out` stream. The payload SHALL contain `effector`,
`success`, `elapsed_ms`, and `error` only — no file contents, no
shell stdout, no notification body.

#### Scenario: Action publishes one bus event
- **WHEN** any action is awaited
- **THEN** exactly one `praxis.action` event appears on `praxis.out`
  whose payload keys are exactly `{effector, success, elapsed_ms,
  error}`

### Requirement: Default Praxis config is safe-by-default
The repository SHALL ship a `[praxis]` block in `config/kaine.toml`
with: `sandbox_path` default `state/praxis/files/`,
`audit_log_path` default `state/praxis/audit.log`,
`max_file_bytes` default 1_048_576 (1 MiB), `notification_command`
default `notify-send`, and `[praxis.shell_whitelist]` empty by
default. `[modules].praxis = false` SHALL keep first boot from
auto-registering Praxis.

#### Scenario: kaine.toml carries defaults
- **WHEN** an operator inspects `config/kaine.toml`
- **THEN** they find a `[praxis]` section with the documented keys
  and `[modules].praxis == false`
