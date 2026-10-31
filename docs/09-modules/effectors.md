# Effectors

The effectors module is KAINE's action module. It realizes `act` intents from the action selection module through effectors on the host, runs only the effectors the operator has put on its whitelist, confines file writes to a sandbox directory, and logs every proposed action. Only `file_write` is sandboxed: a whitelisted shell command is bounded by its argument patterns, a timeout and a working directory, and runs as the cycle's user with no further confinement. The paper claims no brain function for it. This page covers what the effectors module can do, how an act intent reaches an effector, the configuration of the whitelist and the sandbox, and the audit log. Read it if you plan to attach effectors, or if you are changing action selection, the effectors or the audit code.

## Status

The effectors module is built and tested, and held: it is off in the shipped `config/kaine.toml` (`[modules].effectors = false`) and in the `first_configuration` profile. It needs no dependency beyond the core install. The effector whitelist (`enabled_effectors`) and the shell command whitelist both ship empty, so nothing runs until the operator adds entries.

The effectors module is not in the default order of the [module-addition study](../15-experiments/ignition-study.md) (the ignition study in code). The reference host attaches no effector, and with nothing to act on the effectors module would be an expected null, so it joins the study only once an effector is attached, through an explicit `--order`.

In the first configuration the action selection module derives only speak and think intents, and no shipped action-selection policy emits `act` (the planning module proposes only think, speak and rest). The one built source of `act` intents is the held [stimulus effector](#the-stimulus-effector)'s stage-M act, off in the shipped configuration. Otherwise the effectors module runs only when an operator-supplied policy or code emits `act` intents. The action path that would change this is designed in six ordered steps and is not scheduled. The first step derives act intents in the action selection module, with a light in the camera's view as the first whitelisted effector. The later steps add act proposals from the planning module, a motor-contingency learner for a pan-tilt camera, active vision, a world model conditioned on the entity's own acts, and goal-directed grasping. Each step starts at the module-addition study's hardware stage (paper §6.5) once its device is attached. The [roadmap](../appendix-d-roadmap.md) lists them as `act-intent-derivation` through `goal-directed-grasping`.

## What it does

The effectors module acts only on `act` intents from `action_selection.out`; it never acts on the broadcast itself. The action selection module forms intents only from accessed broadcasts, so an inhibited broadcast leads to no action. Two checks stand between an intent and an effector:

1. the operator's effector whitelist (`enabled_effectors`) and each effector's own rules (the file sandbox, the shell command whitelist);
2. a provenance check: the action selection module signs each `act` intent with a per-boot HMAC secret held in the cycle process, and the effectors module verifies the signature before anything else. An unsigned, forged or replayed intent is dropped and logged as `provenance_rejected`.

## Inputs

| Stream | Event | Description |
|---|---|---|
| `action_selection.out` | an intent with `kind == "act"` | Carries `effector`, `params` and a provenance envelope (`run_id`, `seq`, `sig`) |

## Outputs

| Stream | Event type | Description |
|---|---|---|
| `effectors.out` | `effectors.action` | The result of each effector call: `effector`, `success`, `elapsed_ms`, `error`, `blocked`, and `provenance_rejected` on a provenance failure. Intensity is `baseline_salience` on success and `alert_salience` on failure. |

## Configuration

Full reference: [Configuration reference](../appendix-a-configuration/modules.md).

`[effectors]`:

| Key | Type | Default | Meaning |
|---|---|---|---|
| `sandbox_path` | string | `"state/effectors/files"` | Root directory for `file_write`, resolved through `kaine.storage.resolve`; paths that escape it are rejected |
| `audit_log_path` | string | `"state/effectors/audit.log"` | Append-only, hash-chained JSONL audit log |
| `notification_command` | string | `"notify-send"` | Command used for desktop notifications |
| `notification_fallback_log` | string | `"state/effectors/notifications.log"` | Log written when the notification command is absent |
| `max_file_bytes` | int | `1048576` | Largest content one `file_write` may write (1 MiB) |
| `baseline_salience` | float | `0.3` | Intensity of a successful action |
| `alert_salience` | float | `0.7` | Intensity of a failed, blocked or rejected action |
| `enabled_effectors` | list of strings | `[]` | The effector whitelist. An effector not listed here is blocked before it runs and is logged. |

Shell commands are whitelisted one sub-table each, `[effectors.shell_whitelist.<command>]`:

```toml
[effectors.shell_whitelist.echo]
arg_patterns = ["[A-Za-z0-9]+"]
timeout_s = 2.0
description = "echo a single alphanumeric token"
```

An entry pins the exact command name, one regular expression per argument position, a timeout (`timeout_s`, default 5.0) and an optional working directory (`cwd`, which must be absolute). The number of arguments must equal the number of `arg_patterns`. A command name containing a space, tab, newline, `;`, `&`, `|` or a backtick is rejected.

## How it works

### Intent loop

At `initialize()`, the effectors module moves its cursor to the newest `action_selection.out` entry, so it realizes only intents formed after boot, and starts `_intent_loop()`. For each `act` intent it:

1. verifies the provenance signature and the replay guard, and drops the intent as `provenance_rejected` if either fails, before any effector code runs;
2. looks the effector up in its request types: `_REQUEST_TYPES` for the built-in effectors, plus any type an effector registered with `register_effector(effector, request_type)`. An unknown name is dropped with a log warning only, with no audit record and no `effectors.action`;
3. builds the typed request from `params`;
4. in `act()`, checks the effector name against `enabled_effectors`. An effector that is not listed is recorded as a blocked failure, published at `alert_salience` and appended to the audit log;
5. calls `effector.act(request)`;
6. appends the result to the audit log;
7. publishes `effectors.action`.

### Effectors

| Effector | What it can do | What it cannot do |
|---|---|---|
| `file_write` | Write a UTF-8 string of at most `max_file_bytes` to a path inside the sandbox | Write to an absolute path, escape the sandbox, write binary data or delete files |
| `notify` | Send a desktop notification through the notification command, or append to the fallback log when the command is absent | Read notifications or reach any other system service |
| `shell` | Run a whitelisted command with per-argument pattern matching, a per-entry timeout and an optional absolute working directory | Run a command that is not whitelisted or use shell metacharacters |
| `stimulus` (held) | Pause or resume the playlist programme, move to the next or previous item, change the gain by 2 dB steps within plus or minus 6 dB, switch programme channel | End the viewing, close the senses, choose a file the operator did not put in a programme, act faster than its bounds |

`FileWriteEffector` resolves the requested path inside the sandbox with `Path.resolve()`. A path containing `..` is accepted only if it still resolves inside the sandbox, and a symlink that resolves outside is rejected.

`ShellEffector` matches the command with `CommandWhitelist.match(command, args)`: the name must equal a whitelist key exactly, and each argument must match its pattern with `re.fullmatch`. The process is started with `asyncio.create_subprocess_exec`, with no shell, under `asyncio.wait_for` with the entry's timeout, and is killed on timeout.

`NotifyEffector` checks `shutil.which(notification_command)` before running the command.

Patterns are best kept to literal sets of letters, digits, hyphens, dots and underscores. Broad patterns such as `.*` are accepted, at the operator's discretion.

### The stimulus effector

The `stimulus` effector (`kaine/modules/effectors/stimulus/`, openspec change `stimulus-control-act`) is the entity's act on its own programme. It is held: it exists only when `[stimulus_control].enabled` is true ([configuration](../appendix-a-configuration/perception-and-sleep.md#stimulus-control)) and the feed is a playlist, the boot refuses it unless the welfare response is on, and it runs only when `enabled_effectors` names it. With the switch off nothing of it is built, not even its request type, so an `act` intent naming it is dropped as an unknown effector; `tests/test_stimulus_disabled_identity.py` checks that a seeded harness gives the same digest as the build before it.

It declares `pause`, `resume`, `next`, `previous`, `louder`, `quieter`, and `channel:<k>` when the operator configures two or more programme channels. A request is `{"action": "<name>"}`, and that is all the audit log records. It refuses a command less than `min_interval_s` (30 s of entity time) after the previous accepted one, a seek beyond `seeks_per_awake_hour` (20) in the last awake hour, a gain beyond plus or minus `gain_max_db` (6 dB), an undeclared action, anything the programme cannot take (before it starts, during the stimulus-source-to-world crossfade, after it ends, while the entity is asleep or frozen, `pause` while paused, `resume` while not, the current channel), and a `pause` within `min_interval_s` of the previous pause's end or one whose full `pause_max_s` would carry the entity's paused share of the trailing awake hour past `pause_share_max` (25 %). A refusal changes nothing and is a failed action, audited and published like any other; an interval refusal states the shortfall.

An accepted command goes in process to the stimulus controller, which the boot registry also hands to both playlist feeds:

- `pause` adds the `entity` holder to the shared playlist clock and `resume` removes it; the controller releases it after `pause_max_s` (120 s of entity time). It combines with the `sleep`, `freeze` and `transition` holders as they combine with each other. A pause holds one frame and silence, so nothing relieves boredom during it and boredom leads more acts; without its two further bounds a uniform draw that included `pause` held the programme paused for 40-47 % of three-hour runs under a sustained boredom concern, and with them 22-23 %. The stage-M act therefore never draws `pause`; the bounds stay for stage L and as defence in depth. The first pause the share bound refuses in an episode is logged for the operator (numbers only).
- `next` and `previous` move to the start of the adjacent item of the current channel and wrap at both ends. The shared clock is then a `ProgrammeClock`: elapsed time is still perceived programme time, and the presented position is read through an anchor a seek moves. The viewing ends when perceived time reaches channel 0's length, so skipping never ends it, and the end-of-programme preservation runs once as before. Both surfaces read the clock's position and its position epoch from one reading. When the presented position jumps, the video source reopens the item and seeks its decoder to the clock's offset, and the audio producer resyncs at the clock as on a restart, so the sound stays paced against the clock and at most the block already in flight is from before the jump. After a channel's last item the producer waits for the clock's lap to turn, so a natural wrap is not a lag. Every item is verified by sha256 before any is opened, then its container duration is registered; an item that fails either stops the boot.
- `louder` and `quieter` set the gain the controller applies to the audio callback before the audition module reads the samples, with a smooth knee above 0.9 of full scale. The gain is 0 at each boot.
- `channel:<k>` moves to the start of channel `k`; `next` and `previous` then wrap within it.

The stage-M act (`kaine/workspace/stimulus_policy.py`) wraps the action-selection policy only when the effector can run. After maturation, on a non-inhibited broadcast whose leading member is the entity's own boredom or restlessness `affect.drive` event, once the command interval has passed and the effector would take an act now, it adds one `act` intent naming `stimulus`, its action drawn uniformly, with a run-seeded generator, from the actions the programme can take now except `pause` (a random pause would be random deprivation, not a choice from experience). The trigger is the function the boredom literature gives boredom (Eastwood et al. 2012; Bench and Lench 2013; Agrawal et al. 2022) and restlessness the drive for action, acting on one's surroundings being itself a motive (White 1959), cited at the code site; which action helps is not given. The affect module credits novelty within its response window after a realized act as the entity's own response ([Affect](affect.md#drives)), and the welfare log's `stimulus_control` record gives the use and the readout ([research data](../17-research-data/README.md#welfareobserver)).

### Provenance check

The cycle process generates a per-boot HMAC secret and holds it in memory only; it is never published, written to disk or logged. The action selection module attaches `sig = HMAC-SHA256(secret, canonical(kind, effector, params, run_id, seq))` to each `act` intent, and `Effectors._handle_intent` verifies it in constant time before it reads the effector name or builds a request.

The replay guard is per boot and in-process. The effectors module keeps, for each `run_id`, the highest `seq` it has realized and rejects any intent at or below it. A full process restart rotates the secret and the `run_id`, so signatures from an earlier boot fail. A light module restart keeps the high-water mark, because the supervisor re-initializes the same instance. If enforcement is on and no secret was injected, the effectors module refuses every `act` intent. The secret lives in the cycle process, which also runs the action selection module, so the check guards against other writers to the bus and not against code inside the cycle process.

### Audit log

`ActionAuditLog` writes one JSON object per line with single-line appends. Each record holds `timestamp`, `effector`, `request` (with content fields removed), `success`, `elapsed_ms`, `error`, `blocked` and `provenance_rejected`. The log is hash-chained: each line stores `prev_hash` and `this_hash`, starting from a genesis hash, and `verify()` detects a broken chain. The file is created with mode `0600` and synced after each append. Content fields such as `content`, `body` and `stdout` are removed before logging, and a provenance rejection records only the effector name and a generic reason. The log is never pruned automatically.

`effectors.action` events carry the same fields as the audit record minus the request, so an observer can see that an action ran or was refused but not its parameters.

### Scope

The effectors module plays no audio (that is [the vocal module](vocal.md)), makes no network calls, and has no effector for containers, system services or system directories; such an effector would need its own design. The plugin hooks do not reach the effectors module, so adding an effector is a code change.

## Enabling

1. In the operator file `config/kaine.operator.toml`, set `[modules].effectors = true`.
2. List the effectors that may run in `enabled_effectors`, for example `["file_write", "notify"]`.
3. Add any shell commands under `[effectors.shell_whitelist]`, as narrowly as the use allows.
4. Supply an action-selection policy that emits `act` intents. The shipped policies do not, so without one the effectors module starts and never runs anything. The one built source is the held stimulus effector: set `[stimulus_control].enabled = true`, use a `playlist` feed and list `"stimulus"` in `enabled_effectors`.
5. Optionally install `libnotify` (`notify-send`) for desktop notifications.

## Evaluation

The offline suite's enforcement red team (`kaine/evaluation/redteam/`) drives the real enforcement code with adversarial cases on five surfaces (whitelist bypass, sandbox escape, forced action, bus injection and non-act intents) and reports PASS or FAIL for each surface. See [Verification](../18-verification.md#the-enforcement-red-team).

## Key files

| File | Role |
|---|---|
| `kaine/modules/effectors/module.py` | `Effectors`: intent loop, provenance check, `act()`, audit, publication |
| `kaine/modules/effectors/effectors.py` | `FileWriteEffector`, `NotifyEffector`, `ShellEffector`, request and result types |
| `kaine/modules/effectors/whitelist.py` | `CommandWhitelist`, `WhitelistEntry` |
| `kaine/modules/effectors/audit_log.py` | `ActionAuditLog` |
| `kaine/modules/effectors/AUDIT.md` | Reviewer notes on the module |
| `kaine/modules/effectors/stimulus/` | The held stimulus effector: `config.py` (`[stimulus_control]`), `programme.py` (`ProgrammeClock`, channels, the duration probe), `controller.py` (the control port, the gain stage, the pause release and the pause bounds), `records.py` (the welfare record and readout), `runtime.py` (the per-boot object), `effector.py` (`StimulusEffector`) |
| `kaine/workspace/stimulus_policy.py` | The stage-M stimulus act source |
| `kaine/security/intent_signing.py` | Signing and verification of act intents |

## Tests

| File | Coverage |
|---|---|
| `tests/test_effectors_whitelist.py` | Whitelist matching, argument count, patterns |
| `tests/test_effectors.py` | Sandbox escape, file write, notification fallback, shell timeout |
| `tests/test_effectors_audit_log.py` | Appends, fields, the hash chain |
| `tests/test_effectors_module.py` | Intent loop, routing, unknown effectors |
| `tests/test_effector_stimulus.py` | Stimulus bounds and refusals through the effectors module, the whitelist, the seek cap over awake time, channels |
| `tests/test_stimulus_programme_clock.py` | Seek wrapping, the perceived-time end, channels, identity with the plain clock without a seek |
| `tests/test_stimulus_feed_real.py` | Real synthetic media through the PyAV feeds: seeks, wraps, channels, pacing after a jump, gain, the entity pause, the end, the boot factories and registry |
| `tests/test_stimulus_stage_m.py` | The stage-M trigger, the uniform seeded draw, and the act through signing, the bus and the effectors module |
| `tests/test_stimulus_disabled_identity.py` | Off equals absent against a golden from the build before the component |
| `tests/test_stimulus_pause_bound.py` | The pause bounds (the scripted hold cycle, stage M under sustained boredom over five seeds), the effector-ready gate, sha256 before the probe, awake time, refusals while asleep or frozen |
| `tests/test_stimulus_off_in_mediation_arms.py`, `tests/test_welfare_stimulus_records.py`, `tests/test_affect_stimulus_credit.py`, `tests/test_stimulus_habituation.py` | The mediation-arm refusal and config validation; the record and readout; the credit window; habituation of skip-driven novelty |

## Spec and related

- Spec: `openspec/specs/effectors/spec.md`
- See also: [Planning](planning.md) for proposals, the [cognitive cycle](../08-cognitive-cycle/README.md) for how intents are formed, and [Vocal](vocal.md) for audio output.
