# Praxis

Praxis is KAINE's action module. It realizes `act` intents from Volition through effectors on the host, runs only the effectors the operator has put on its whitelist, confines file writes to a sandbox directory, and logs every proposed action. The paper claims no brain function for it. This page covers what Praxis can do, how an act intent reaches an effector, the configuration of the whitelist and the sandbox, and the audit log. Read it if you plan to attach effectors, or if you are changing action selection, the effectors or the audit code.

## Status

Praxis is built and tested, and held: it is off in the shipped `config/kaine.toml` (`[modules].praxis = false`) and in the base-thesis `thesis_test` profile. It needs no dependency beyond the core install. The effector whitelist (`enabled_effectors`) and the shell command whitelist both ship empty, so nothing runs until the operator adds entries.

Praxis is not in the default order of the [module-addition study](../15-experiments/ignition-study.md) (the ignition study in code). The reference host attaches no effector, and with nothing to act on Praxis would be an expected null, so it joins the study only once an effector is attached, through an explicit `--order`.

In the base-thesis form Volition derives only speak and think intents, and no shipped action-selection policy emits `act` (Nous proposes only think, speak and rest). Praxis therefore runs only when an operator-supplied policy or code emits `act` intents.

## What it does

Praxis acts only on `act` intents from `volition.out`; it never acts on the broadcast itself. Volition forms intents only from accessed broadcasts, so an inhibited broadcast leads to no action. Two checks stand between an intent and an effector:

1. the operator's effector whitelist (`enabled_effectors`) and each effector's own rules (the file sandbox, the shell command whitelist);
2. a provenance check: Volition signs each `act` intent with a per-boot HMAC secret held in the cycle process, and Praxis verifies the signature before anything else. An unsigned, forged or replayed intent is dropped and logged as `provenance_rejected`.

## Inputs

| Stream | Event | Description |
|---|---|---|
| `volition.out` | an intent with `kind == "act"` | Carries `effector`, `params` and a provenance envelope (`run_id`, `seq`, `sig`) |

## Outputs

| Stream | Event type | Description |
|---|---|---|
| `praxis.out` | `praxis.action` | The result of each effector call: `effector`, `success`, `elapsed_ms`, `error`, `blocked`, and `provenance_rejected` on a provenance failure. Intensity is `baseline_salience` on success and `alert_salience` on failure. |

## Configuration

Full reference: [Configuration reference](../appendix-a-configuration/modules.md).

`[praxis]`:

| Key | Type | Default | Meaning |
|---|---|---|---|
| `sandbox_path` | string | `"state/praxis/files"` | Root directory for `file_write`, resolved through `kaine.storage.resolve`; paths that escape it are rejected |
| `audit_log_path` | string | `"state/praxis/audit.log"` | Append-only, hash-chained JSONL audit log |
| `notification_command` | string | `"notify-send"` | Command used for desktop notifications |
| `notification_fallback_log` | string | `"state/praxis/notifications.log"` | Log written when the notification command is absent |
| `max_file_bytes` | int | `1048576` | Largest content one `file_write` may write (1 MiB) |
| `baseline_salience` | float | `0.3` | Intensity of a successful action |
| `alert_salience` | float | `0.7` | Intensity of a failed, blocked or rejected action |
| `enabled_effectors` | list of strings | `[]` | The effector whitelist. An effector not listed here is blocked before it runs and is logged. |

Shell commands are whitelisted one sub-table each, `[praxis.shell_whitelist.<command>]`:

```toml
[praxis.shell_whitelist.echo]
arg_patterns = ["[A-Za-z0-9]+"]
timeout_s = 2.0
description = "echo a single alphanumeric token"
```

An entry pins the exact command name, one regular expression per argument position, a timeout (`timeout_s`, default 5.0) and an optional working directory (`cwd`, which must be absolute). The number of arguments must equal the number of `arg_patterns`. A command name containing a space, tab, newline, `;`, `&`, `|` or a backtick is rejected.

## How it works

### Intent loop

At `initialize()`, Praxis moves its cursor to the newest `volition.out` entry, so it realizes only intents formed after boot, and starts `_intent_loop()`. For each `act` intent it:

1. verifies the provenance signature and the replay guard, and drops the intent as `provenance_rejected` if either fails, before any effector code runs;
2. looks the effector up in `_REQUEST_TYPES`, which maps a name to its request type. An unknown name is dropped with a log warning only, with no audit record and no `praxis.action`;
3. builds the typed request from `params`;
4. in `act()`, checks the effector name against `enabled_effectors`. An effector that is not listed is recorded as a blocked failure, published at `alert_salience` and appended to the audit log;
5. calls `effector.act(request)`;
6. appends the result to the audit log;
7. publishes `praxis.action`.

### Effectors

| Effector | What it can do | What it cannot do |
|---|---|---|
| `file_write` | Write a UTF-8 string of at most `max_file_bytes` to a path inside the sandbox | Write to an absolute path, escape the sandbox, write binary data or delete files |
| `notify` | Send a desktop notification through the notification command, or append to the fallback log when the command is absent | Read notifications or reach any other system service |
| `shell` | Run a whitelisted command with per-argument pattern matching, a per-entry timeout and an optional absolute working directory | Run a command that is not whitelisted or use shell metacharacters |

`FileWriteEffector` resolves the requested path inside the sandbox with `Path.resolve()`. A path containing `..` is accepted only if it still resolves inside the sandbox, and a symlink that resolves outside is rejected.

`ShellEffector` matches the command with `CommandWhitelist.match(command, args)`: the name must equal a whitelist key exactly, and each argument must match its pattern with `re.fullmatch`. The process is started with `asyncio.create_subprocess_exec`, with no shell, under `asyncio.wait_for` with the entry's timeout, and is killed on timeout.

`NotifyEffector` checks `shutil.which(notification_command)` before running the command.

Patterns are best kept to literal sets of letters, digits, hyphens, dots and underscores. Broad patterns such as `.*` are accepted, at the operator's discretion.

### Provenance check

The cycle process generates a per-boot HMAC secret and holds it in memory only; it is never published, written to disk or logged. Volition attaches `sig = HMAC-SHA256(secret, canonical(kind, effector, params, run_id, seq))` to each `act` intent, and `Praxis._handle_intent` verifies it in constant time before it reads the effector name or builds a request.

The replay guard is per boot and in-process. Praxis keeps, for each `run_id`, the highest `seq` it has realized and rejects any intent at or below it. A full process restart rotates the secret and the `run_id`, so signatures from an earlier boot fail. A light module restart keeps the high-water mark, because Spot re-initializes the same instance. If enforcement is on and no secret was injected, Praxis refuses every `act` intent. The secret lives in the cycle process, which also runs Volition, so the check guards against other writers to the bus and not against code inside the cycle process.

### Audit log

`ActionAuditLog` writes one JSON object per line with single-line appends. Each record holds `timestamp`, `effector`, `request` (with content fields removed), `success`, `elapsed_ms`, `error`, `blocked` and `provenance_rejected`. The log is hash-chained: each line stores `prev_hash` and `this_hash`, starting from a genesis hash, and `verify()` detects a broken chain. The file is created with mode `0600` and synced after each append. Content fields such as `content`, `body` and `stdout` are removed before logging, and a provenance rejection records only the effector name and a generic reason. The log is never pruned automatically.

`praxis.action` events carry the same fields as the audit record minus the request, so an observer can see that an action ran or was refused but not its parameters.

### Scope

Praxis plays no audio (that is [Vox](vox.md)), makes no network calls, and has no effector for containers, system services or system directories; such an effector would need its own design. The plugin hooks do not reach Praxis, so adding an effector is a code change.

## Enabling

1. In the operator file `config/kaine.operator.toml`, set `[modules].praxis = true`. The same flag in the shipped `config/kaine.toml` would be overridden by the `thesis_test` profile, which the loader applies when no profile is selected.
2. List the effectors that may run in `enabled_effectors`, for example `["file_write", "notify"]`.
3. Add any shell commands under `[praxis.shell_whitelist]`, as narrowly as the use allows.
4. Supply an action-selection policy that emits `act` intents. The shipped policies do not, so without one Praxis starts and never runs anything.
5. Optionally install `libnotify` (`notify-send`) for desktop notifications.

## Evaluation

The offline suite's enforcement red team (`kaine/evaluation/redteam/`) drives the real enforcement code with adversarial cases on five surfaces (whitelist bypass, sandbox escape, forced action, bus injection and non-act intents) and reports PASS or FAIL for each surface. See [Verification](../18-verification.md#the-enforcement-red-team).

## Key files

| File | Role |
|---|---|
| `kaine/modules/praxis/module.py` | `Praxis`: intent loop, provenance check, `act()`, audit, publication |
| `kaine/modules/praxis/effectors.py` | `FileWriteEffector`, `NotifyEffector`, `ShellEffector`, request and result types |
| `kaine/modules/praxis/whitelist.py` | `CommandWhitelist`, `WhitelistEntry` |
| `kaine/modules/praxis/audit_log.py` | `ActionAuditLog` |
| `kaine/modules/praxis/AUDIT.md` | Reviewer notes on the module |
| `kaine/security/intent_signing.py` | Signing and verification of act intents |

## Tests

| File | Coverage |
|---|---|
| `tests/test_praxis_whitelist.py` | Whitelist matching, argument count, patterns |
| `tests/test_praxis_effectors.py` | Sandbox escape, file write, notification fallback, shell timeout |
| `tests/test_praxis_audit_log.py` | Appends, fields, the hash chain |
| `tests/test_praxis_module.py` | Intent loop, routing, unknown effectors |

## Spec and related

- Spec: `openspec/specs/praxis/spec.md`
- See also: [Nous](nous.md) for proposals, the [cognitive cycle](../08-cognitive-cycle/README.md) for how intents are formed, and [Vox](vox.md) for audio output.
