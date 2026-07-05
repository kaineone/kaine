# Praxis

The effector organ — KAINE's safety-gated "hands"; executes real-world actions
only for whitelisted effectors in response to explicit `act` intents from the
executive action-selection layer.

## Status

Implemented. Ships **disabled** (`[modules].praxis = false`). No extra
dependencies beyond core. The shell effector whitelist ships empty by default;
operators add commands explicitly.

---

## Responsibility

Praxis is the **action-execution layer** — the only path through which KAINE
produces side-effects in the environment beyond speech. In the GWT framing, it
is intent-driven: it never acts on the raw workspace broadcast. The sole trigger
is an `act` intent from the executive action-selection step (Nous → Volition),
which is itself gated by the inhibition flag. An inhibited entity performs no
effector actions.

Inhibition is a cognitive property of that legitimate path; it is made an
*enforced* boundary at the Praxis interface by act-intent provenance. Volition
signs each `act` intent with a per-boot HMAC secret (held only by the cycle
process), and `Praxis._handle_intent` verifies the signature before any effector
runs. A forged/unsigned/replayed intent from any other bus writer is dropped and
audit-logged as `provenance_rejected`. This is a SECOND boundary; the effector
whitelist + sandbox (empty by default) remain the primary enforced gate.

Three built-in effectors are registered at boot:

| Name | Action | Safety constraint |
|---|---|---|
| `file_write` | Write text to a sandboxed directory | Path escape check; max bytes limit |
| `notify` | Send a desktop notification via `notify-send` (or fallback log) | Title + body only; no system calls |
| `shell` | Run a whitelisted shell command | Whitelist: exact command + per-arg regex + timeout |

Additional effectors can be registered programmatically via
`register_effector()`, but none are shipped beyond these three.

---

## Inputs

| Stream | Event type | Description |
|---|---|---|
| `volition.out` | (act intent, `kind == "act"`) | Triggers effector execution; carries `effector`, `params`, and the provenance envelope (`run_id`, `seq`, `sig`) verified before any effector runs |

---

## Outputs

| Stream | Event type | Description |
|---|---|---|
| `praxis.out` | `praxis.action` | Result of each effector call: `effector`, `success`, `elapsed_ms`, `error` |

Every action (success or failure) is also appended to the audit log
(`state/praxis/audit.log`).

---

## Configuration

Full reference: [`../configuration.md`](../configuration.md). Key `[praxis]` keys:

| Key | Default | Description |
|---|---|---|
| `sandbox_path` | `"state/praxis/files"` | Absolute root for `file_write`; path escapes are rejected |
| `audit_log_path` | `"state/praxis/audit.log"` | Append-only JSONL action audit trail |
| `notification_command` | `"notify-send"` | Command for desktop notifications |
| `notification_fallback_log` | `"state/praxis/notifications.log"` | Fallback when `notify-send` absent |
| `max_file_bytes` | `1048576` | Maximum content size per `file_write` (1 MiB) |
| `baseline_salience` | `0.3` | Salience for successful actions |
| `alert_salience` | `0.7` | Salience for failed actions |
| `enabled_effectors` | `[]` | Operator effector-enablement whitelist. Any effector name not listed here — `file_write`, `notify`, `shell`, or a programmatically registered one — is blocked at `act()` before it runs and audit-logged, regardless of any other per-effector configuration (e.g. the shell sub-whitelist below). Ships empty: no effector runs until the operator explicitly opts it in. |

Shell whitelist (`[praxis.shell_whitelist]` sub-tables, one per allowed command):

```toml
[praxis.shell_whitelist.echo]
arg_patterns = ["[A-Za-z0-9]+"]
timeout_s = 2.0
description = "echo a single alphanumeric token"
```

Each entry specifies the exact command name (no shell metacharacters), a list
of per-positional-argument regex patterns (exact count match required), an
execution timeout, and an optional working directory (`cwd`).

---

## How it works

### Intent loop

On `initialize()`, Praxis seeds its cursor to the latest entry in
`volition.out` (so it only realizes intents formed after boot) and spawns
`_intent_loop()`. The loop polls `volition.out` for events with
`kind == "act"`. For each such event:

1. Extract `effector` name and `params` dict.
2. Look up the effector in `_REQUEST_TYPES` map (maps name → request dataclass).
   Unknown effectors are logged and dropped.
3. Coerce `params` into the typed request dataclass.
4. Call `effector.act(request)`.
5. Append to audit log.
6. Publish `praxis.action` event.

### Effector safety details

**`FileWriteEffector`**: resolves the requested relative path inside the sandbox
directory using `Path.resolve()` and verifies that the resolved path is still
inside the sandbox via `relative_to()`. Absolute paths are rejected immediately.
Content is encoded as UTF-8 and capped at `max_bytes`. No binary writes in v1.

**`ShellEffector`**: `CommandWhitelist.match(command, args)` checks:
- The command exists in the whitelist dict (exact string match, no shell
  interpolation).
- The args list has exactly the same length as the entry's `arg_patterns` tuple.
- Each arg matches its corresponding regex via `re.fullmatch`.
The subprocess is run with `asyncio.create_subprocess_exec` (no shell), with
an `asyncio.wait_for` timeout; on timeout the process is killed and a
`TimeoutError` is raised. `cwd` is the entry's configured directory or the
process default.

**`NotifyEffector`**: calls `shutil.which(notification_command)` before invoking;
falls back to appending a log line when the command is absent.

### Audit log

`ActionAuditLog` appends one JSON line per action to `audit_log_path`. The record
contains effector name, a sanitized request summary (content/body fields stripped),
success/failure, elapsed_ms, and error string. The log is append-only and grows
without automatic pruning.

---

## Key files

| File | Role |
|---|---|
| `kaine/modules/praxis/module.py` | `Praxis` class; intent loop, `act()`, audit, event publishing |
| `kaine/modules/praxis/effectors.py` | `FileWriteEffector`, `NotifyEffector`, `ShellEffector`; request/result types |
| `kaine/modules/praxis/whitelist.py` | `CommandWhitelist`, `WhitelistEntry`; per-arg regex matching |
| `kaine/modules/praxis/audit_log.py` | `ActionAuditLog`; JSONL append |

---

## Enabling & use

1. Set `[modules].praxis = true` in `config/kaine.toml`.
2. Add any permitted shell commands to `[praxis.shell_whitelist]`. Keep the
   list as narrow as the use-case demands.
3. Enable Nous / Volition so that `act` intents can be generated; without them
   Praxis starts but will never execute anything.
4. Optionally install `libnotify` / `notify-send` for desktop notifications.

---

## Safety / zero-persistence note

- Praxis is **intent-driven only**: zero workspace reactivity. An inhibited entity
  (inhibition flag set) produces no executive intents, and therefore no effector
  actions.
- `enabled_effectors` is the primary gate: it blocks **every** effector — not
  just `shell` — before any of them runs, uniformly, with no effector
  special-cased. It ships empty, so nothing runs until the operator opts in.
- The shell whitelist (`[praxis.shell_whitelist]`) is a second, shell-specific
  boundary layered on top: even once `shell` is in `enabled_effectors`,
  individual commands must still be explicitly whitelisted. Commands not on the
  whitelist are silently rejected before any subprocess is spawned.
- The file-write sandbox prevents path traversal via `resolve()` + `relative_to()`.
- Act intents are provenance-verified: an `act` intent is realized only when its
  HMAC signature (over `kind`, `effector`, `params`, `run_id`, `seq`) matches the
  per-boot secret shared with Volition. Missing/invalid/replayed → dropped, logged
  `provenance_rejected`, no effector runs. Enforcement fails closed (no secret ⇒
  refuse every act intent).
- Replay guard is an in-process (per-boot) guarantee: Praxis rejects any `seq` at
  or below the highest already realized for a `run_id` (an O(1) high-water mark,
  not an unbounded set). A full process restart rotates the secret + `run_id`, so
  prior-boot signatures fail verification; a light module restart preserves the
  high-water mark on the same instance. It is not an unconditional non-replay
  claim — if Praxis ever becomes a heavy/externally-rebuilt module, a
  persisted/rotating replay window would be needed to keep it across a restart.
- All actions — including failures and provenance rejections — are written to the
  append-only audit log, giving the operator a complete record of what Praxis
  attempted.
- Content fields (file body, notification body) are stripped from the audit
  summary via `_summarize_request()` to avoid logging arbitrary content to disk.

---

## Tests

| File | Coverage |
|---|---|
| `tests/test_praxis_whitelist.py` | Whitelist matching; arg-count enforcement; regex patterns |
| `tests/test_praxis_effectors.py` | Sandbox path escape; file write; notify fallback; shell timeout |
| `tests/test_praxis_audit_log.py` | JSONL append; field presence |
| `tests/test_praxis_module.py` | Intent loop; act routing; unknown effector handling |

---

## Spec & related

- Spec: `openspec/specs/praxis/spec.md`
- See also: Volition (issues `act` intents), Nous (action selection), Syneidesis
  (inhibition gate that blocks intent generation).
