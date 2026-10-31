## Why

The paper says the held effector module "runs only effectors on an operator-configured whitelist, empty unless filled, and logs every proposed action; file writes are confined to a sandbox directory, while whitelisted shell commands are bounded by argument patterns, a timeout, and a working directory and are not otherwise sandboxed" (§3.6). That sentence is now accurate, and it describes a gap: only one of the three built-in effectors is confined, and the confinement it has is a path check in the cycle's own process.

- `file_write` resolves the requested name inside the sandbox and refuses escapes (`kaine/modules/effectors/effectors.py:77-87`), then writes from the cycle process (`effectors.py:112-116`). The check and the write are separate steps, so a symlink planted in the sandbox between them is followed.
- `shell` runs the whitelisted command with `asyncio.create_subprocess_exec(entry.command, *request.args, cwd=entry.cwd)` (`effectors.py:203-209`). It passes no `env`, so the child inherits the cycle's environment, which carries `KAINE_STATE_KEY`, the Qdrant and model-server keys (`compose/kaine.yml`, `kaine-cycle` service). `cwd` may be any absolute path or the process default (`kaine/modules/effectors/whitelist.py:22`). Nothing limits what the command reads, writes or connects to: the entity's state tree, preserved beings under `state/forks`, the bus, the network.
- `notify` runs the host's `notify-send` (`effectors.py:130-166`), which speaks to the operator's desktop session bus.
- A plugin can register further effectors (`kaine/modules/effectors/module.py:139-140`), and the action-path designs add device effectors: a light (`act-intent-derivation`) and a pan-tilt camera (`embodiment-motor-contingency`). None of them has a confinement requirement.

The whitelist gate (`enabled_effectors = []`, `config/kaine.toml:922`), signed act intents and the hash-chained audit log are real and stay. This change adds the missing layer: every effector's side effect runs in a separate, confined process whose filesystem, network, environment and resources are limited to what that effector declares, and no effector can be enabled until a self-test on the host proves the confinement holds. The audit flagged it as B2 and the triage put it in W6, "before the effector module ever joins a study".

## What Changes

- Every effector declares a confinement profile: the paths it may read, the one directory it may write (the sandbox), its network access (none for the built-in effectors), the device nodes it may open, the environment variables it receives, and CPU, memory, process-count and wall-time limits.
- A confined executor runs each effector call out of the cycle process under that profile. File writes move into the executor. The cycle process never performs an effector's side effect itself.
- Confinement backends, strongest available first: bubblewrap (namespaces, as Flatpak uses) where unprivileged user namespaces are allowed; Landlock plus a seccomp filter where they are not, which is the expected case inside the shipped containers. A host where no backend can satisfy a profile cannot enable that effector.
- Shell children get an empty environment plus a fixed allowlist, and their working directory is always inside the sandbox. A whitelist entry with a `cwd` outside the sandbox is refused at config load.
- `notify` reaches the desktop only through a filtered session-bus proxy that allows the notification call and nothing else, or falls back to the confined log file.
- A plugin or device effector without a declared profile is refused at registration.
- A boot self-test runs escape probes for every enabled effector inside its profile. Enabling any effector requires a pass; a failure is a named boot refusal. The research gate and the unattended gate gain the condition when the effectors module is in the module set.
- Each audit record names the profile and backend that ran the act.
- Red-team cases for the escapes the self-test probes.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `effectors`: confinement profiles, the confined executor, environment scrubbing, the enablement self-test, and the registration rule for plugin and device effectors.

## Impact

- Code: `kaine/modules/effectors/` (a new `confinement.py` and executor, `effectors.py`, `whitelist.py`, `module.py`, `audit_log.py`), `kaine/boot/factories/effectors.py`, `kaine/cycle/research_gate.py`, `kaine/cycle/unattended_gate.py`, `kaine/evaluation/redteam/cases.py`.
- Config: an `[effectors.confinement]` block; the shell whitelist's `cwd` semantics.
- Container images: the bubblewrap and libseccomp packages, and the container seccomp profile only if the spike (task 1.1) shows Landlock is blocked.
- Docs: `docs/09-modules/effectors.md` (agency security model), and a paper revision note for §3.6 so the sentence can drop "not otherwise sandboxed" once this is built.
- Behaviour: none for any entity today. The effectors module ships off and is not in the module-addition study's default order.
