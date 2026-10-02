# Praxis

Praxis is KAINE's action-execution module — its safety-gated "hands". This page covers what Praxis can do, how it decides to act, the whitelist and sandbox gates, the audit trail, and the security model that protects the host. Read it if you plan to enable real-world effectors, or if you are changing action selection, effectors, or the audit code.

## Status

Implemented, built, and tested, but it ships **disabled** (`[modules].praxis = false`). It is held behind a positive base-thesis result (see [Architecture](../02-architecture/README.md)). No extra dependencies beyond core are required. The shell whitelist ships empty, so no shell command runs until an operator adds it explicitly.

## Responsibility

Praxis is the only path through which KAINE changes the host state beyond speech. In the [global workspace](../08-cognitive-cycle/global-workspace.md) framing it is intent-driven: it never acts on the raw workspace broadcast. It waits for an `act` intent on `volition.out` from the executive action-selection step. The shipped policy in [Nous](../09-modules/nous.md) proposes only `think`, `speak`, and `rest` intents, so no shipped policy emits `act`. Praxis runs only when an operator-supplied policy or code emits `act` intents. An inhibited entity produces no executive intents, and therefore no effector actions.

Praxis enforces two boundaries:

1. The operator-controlled **effector enablement whitelist** and per-effector rules (file sandbox, shell command whitelist).
2. **Act-intent provenance**: Volition signs each `act` intent with a per-boot HMAC secret held only by the cycle process. `Praxis._handle_intent` verifies that signature before any effector runs. Forged, unsigned, or replayed intents from any other bus writer are dropped and audit-logged as `provenance_rejected`.

## Inputs

| Stream | Event type | Description |
|---|---|---|
| `volition.out` | `act` intent (`kind == "act"`) | Triggers execution. Carries `effector`, `params`, and a provenance envelope (`run_id`, `seq`, `sig`) that is verified before any effector runs. |

## Outputs

| Stream | Event type | Description |
|---|---|---|
| `praxis.out` | `praxis.action` | Result of each effector call. Always includes `effector`, `success`, `elapsed_ms`, `error`, and `blocked`. If the provenance check fails, `provenance_rejected` is set. |

## Configuration

Full reference: [Configuration reference](../appendix-a-configuration/modules.md).

`[praxis]` keys:

| Key | Default | Description |
|---|---|---|
| `sandbox_path` | `"state/praxis/files"` | Root for `file_write`. The path is resolved through `kaine.storage.resolve`. Path escapes outside this root are rejected. |
| `audit_log_path` | `"state/praxis/audit.log"` | Append-only, hash-chained JSONL action audit trail. |
| `notification_command` | `"notify-send"` | Command used for desktop notifications. |
| `notification_fallback_log` | `"state/praxis/notifications.log"` | Fallback log when `notify-send` is absent. |
| `max_file_bytes` | `1048576` | Maximum content size per `file_write` (1 MiB). |
| `baseline_salience` | `0.3` | Salience assigned to successful actions. |
| `alert_salience` | `0.7` | Salience assigned to failed actions. |
| `enabled_effectors` | `[]` | Operator effector enablement whitelist. Any effector name not listed here is blocked before it runs and logged, regardless of per-effector configuration. Ships empty. |

Shell whitelist entries are `[praxis.shell_whitelist.<command>]` sub-tables:

```toml
[praxis.shell_whitelist.echo]
arg_patterns = ["[A-Za-z0-9]+"]
timeout_s = 2.0
description = "echo a single alphanumeric token"
```

Each entry pins the exact command name, one regex per argument position, a per-entry timeout, and an optional `cwd`. The argument count must match the number of `arg_patterns` exactly. `timeout_s` defaults to `5.0`. `cwd` must be an absolute path if set. Commands containing a space, tab, newline, `;`, `&`, `|`, or `` ` `` are rejected.

## How it works

### Intent loop

During `initialize()`, Praxis seeds its cursor to the latest `volition.out` entry so it only realizes intents formed after boot, then starts `_intent_loop()`. For each `act` intent:

1. Verify the provenance signature and replay guard. Missing, invalid, or replayed intents are dropped and logged as `provenance_rejected` before any effector code runs.
2. Look up the effector in `_REQUEST_TYPES` (maps name to request dataclass). An unknown name is dropped with only a log warning; no audit record or `praxis.action` is emitted.
3. Later in `act()`, check the `effector` name against `enabled_effectors`. If it is not listed, `act()` returns a blocked failure, publishes it at `alert_salience`, and appends it to the audit log.
4. Coerce `params` into the typed request dataclass.
5. Call `effector.act(request)`.
6. Append the result to the audit log.
7. Publish a `praxis.action` event.

### Effector safety details

**`FileWriteEffector`** resolves the requested path inside the sandbox using `Path.resolve()`. Absolute paths are rejected. A path that contains `..` is accepted only if it still resolves inside the sandbox. Symlinks that resolve outside the sandbox are rejected. Content is encoded as UTF-8 and capped at `max_file_bytes`. Binary writes are not supported in v1.

**`ShellEffector`** uses `CommandWhitelist.match(command, args)`:
- The command name must match a whitelist key exactly, with no shell interpolation.
- Commands that contain a space, tab, newline, `;`, `&`, `|`, or `` ` `` are rejected.
- The number of arguments must exactly match the entry's `arg_patterns`, and each argument must match its regex via `re.fullmatch`.
- The subprocess is started with `asyncio.create_subprocess_exec` (no shell), wrapped in `asyncio.wait_for` using the entry's timeout. On timeout the process is killed. `cwd` must be absolute if set; otherwise the process default is used.

**`NotifyEffector`** calls `shutil.which(notification_command)` before invoking it. If the command is absent, it appends a log line to the fallback file.

### Audit log

`ActionAuditLog` writes one JSON object per line using O_APPEND single-line semantics. Each record contains `timestamp`, `effector`, `request` (content fields stripped), `success`, `elapsed_ms`, `error`, `blocked`, and `provenance_rejected`.

The log is hash-chained: each line stores `prev_hash` and `this_hash` derived from a genesis hash, and `verify()` can detect tampering. The file is opened with mode `0600` and fsynced after each append. Content fields such as `content`, `body`, and `stdout` are stripped before logging. A provenance-rejected record logs only the effector name and a generic reason — never the signature or the params. The log grows without automatic pruning.

## Enabling and use

1. Set `[modules].praxis = true` in `config/kaine.toml`.
2. Add any permitted shell commands to `[praxis.shell_whitelist]`. Keep the list as narrow as the use case demands.
3. Provide an action-selection policy that emits `act` intents; the shipped policies do not, so without one Praxis starts but never executes anything.
4. Optionally install `libnotify` / `notify-send` for desktop notifications.

## Agency security model

This section covers the security material in `kaine/modules/praxis/AUDIT.md`. That file remains a separate pointer for reviewers.

Praxis is the only KAINE module that can change the host state. If it is compromised, KAINE can modify the machine it runs on.

### Threat model

Praxis assumes the operator controls the code that runs. The current plugin hooks do not expose Praxis, so adding or changing an effector still requires code changes.

Only the cycle's executive action-selection step (Volition) may direct Praxis. Praxis realizes an `act` intent only when it carries a valid provenance signature. An intent forged by any other bus writer — [Lingua](../09-modules/lingua.md) is the most exposed because it is LLM-output-driven — is dropped before any effector runs. Whatever the source, Praxis still refuses anything not allowed by the operator-configured whitelist.

### Two enforced boundaries

1. **Effector whitelist + sandbox** is the primary gate. The operator-controlled `enabled_effectors` list and each effector's own rules decide what can run.
2. **Act-intent provenance** is the second gate. Inhibition is a cognitive property of the legitimate path; provenance enforcement makes it an enforced boundary at the Praxis interface and closes the bus-injection path.

### Act-intent provenance

A per-boot HMAC secret is generated by, and held only in, the cycle process. It is never published to the bus, written to disk, or logged. Volition attaches `sig = HMAC-SHA256(secret, canonical(kind, effector, params, run_id, seq))` to each `act` intent.

`Praxis._handle_intent` verifies the signature in constant time before reading the effector name or building a request. A missing, invalid, or replayed signature drops the intent and is logged as `provenance_rejected`.

Replay guard is in-process and per-boot: `(run_id, seq)` is signed, and Praxis rejects any `seq` at or below the highest it has already realized for that `run_id` (an O(1) high-water mark). A full process restart rotates the secret and `run_id`, so signatures from a prior boot fail verification; a light module restart preserves the high-water mark because Spot re-initializes the same instance. If Praxis ever becomes a heavy module that is rebuilt on restart, a persisted replay window would be needed to keep the guarantee across a restart.

If enforcement is on but no secret was injected, Praxis refuses every `act` intent rather than passing silently. The secret is in-process, so a full compromise of the cycle process defeats it — but such an attacker already controls Volition. The boundary holds against a compromised peripheral module.

### Effector boundaries

| Effector | What it can do | What it cannot do |
|---|---|---|
| `file_write` | Write a UTF-8 string up to `max_file_bytes` to a path inside the configured sandbox. | Write absolute paths, escape the sandbox, write binary blobs, or delete files. A path with `..` is allowed only if it still resolves inside the sandbox. |
| `notify` | Send a desktop notification via `notify-send` when present, otherwise append to a fallback log. | Read existing notifications or interact with any other system service. |
| `shell` | Run a command from the operator's `CommandWhitelist` with per-argument regex matching, a per-entry timeout, and a per-entry absolute working directory. | Run any command not in the whitelist, use shell metacharacters, or read/write arbitrary files beyond the command's own permissions. |

### Whitelist invariants

- The default whitelist ships empty. Until the operator adds entries, every shell action fails.
- Each entry pins an exact command name and one regex per argument position. The argument count must match exactly.
- Patterns should be constrained to literal alphanumeric, hyphen, dot, and underscore sets. `.*` and `[^x]*` patterns are accepted, but the operator carries the risk.
- Timeouts default to 5 seconds. Long-running commands need explicit longer timeouts.

### Audit log and bus posture

`praxis.action` events carry only `effector`, `success`, `elapsed_ms`, `error`, `blocked`, and (on a provenance rejection) `provenance_rejected`. They do not carry the request params or payload, so the operator can see that an action ran or was rejected, but not what was acted on. The audit log stores the same fields, with content fields stripped.

### What Praxis cannot do

- **Output audio.** Audio output is handled by [Vox](../09-modules/vox.md).
- **Run a Docker container, modify systemd units, or write to `/etc`.** Those actions are out of scope for v1 and would need a separately threat-modeled effector.
- **Make HTTPS calls or interact with cloud services.** KAINE is all-local at runtime.

## Key files

| File | Role |
|---|---|
| `kaine/modules/praxis/module.py` | `Praxis` class; intent loop, `act()`, audit, event publishing |
| `kaine/modules/praxis/effectors.py` | `FileWriteEffector`, `NotifyEffector`, `ShellEffector`; request/result types |
| `kaine/modules/praxis/whitelist.py` | `CommandWhitelist`, `WhitelistEntry`; per-argument regex matching |
| `kaine/modules/praxis/audit_log.py` | `ActionAuditLog`; hash-chained JSONL append |

## Tests

| File | Coverage |
|---|---|
| `tests/test_praxis_whitelist.py` | Whitelist matching, argument-count enforcement, regex patterns |
| `tests/test_praxis_effectors.py` | Sandbox path escape, file write, notify fallback, shell timeout |
| `tests/test_praxis_audit_log.py` | JSONL append, field presence, hash chain |
| `tests/test_praxis_module.py` | Intent loop, act routing, unknown effector handling |

## Spec and related

- Spec: `openspec/specs/praxis/spec.md`
- See also: [Nous](../09-modules/nous.md) for action selection, the [cognitive cycle](../08-cognitive-cycle/README.md) for how intents are produced, and [Vox](../09-modules/vox.md) for audio output.
