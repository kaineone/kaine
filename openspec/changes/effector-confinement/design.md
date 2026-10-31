# Design: effector confinement

## Context

The effectors module is the only place where an act of the entity changes something outside its own process. Its first layer is the operator's effector whitelist (`enabled_effectors`, empty by default) and its second is each effector's own bound. Intents reach it only signed (spec `effectors`, "Effectors acts only on provenance-verified act intents"), and every attempt is written to a hash-chained audit log. Those layers decide *whether* an act runs. Nothing decides *what the running act can touch*, except the path check in `file_write`.

What a whitelisted shell command can reach today, in the shipped compose deployment (`compose/kaine.yml`, `kaine-cycle` service):

- the environment: `KAINE_STATE_KEY`, `KAINE_QDRANT_API_KEY`, `KAINE_MODEL_SERVER_API_KEY`, inherited because `create_subprocess_exec` gets no `env` (`kaine/modules/effectors/effectors.py:203-209`);
- the filesystem: `/app/state` is the `kaine-state` volume, mounted read-write, holding the entity's memories, forks and preserved beings;
- the network: the compose bridge, which reaches Redis, Qdrant and the model server by service name, and whatever egress the host allows;
- process resources: only a wall-clock timeout (`whitelist.py:21`), so a command can fork or allocate without bound until it times out.

The operator chooses the whitelist, so the realistic failure is an innocuous-looking entry (an `echo`, a `date`, a script) whose arguments or side effects reach further than intended, or a later device effector with a bug. An entity whose acts can touch its own preserved state or the state key is also a welfare and individuation hazard: the preservation and decommission rules assume the entity's stored self is changed only by the architecture.

Prior work: `harden-security-boundaries` (archived 2026-09-08) made the audit log and sandbox owner-only and documented the security model; `authenticate-intent-provenance` added signing; `act-intent-derivation` designs a device bound (action set, value range, minimum interval) and leaves confinement open. No change has proposed process confinement (`git log -i --grep="sandbox\|bubblewrap\|landlock\|seccomp"` finds none).

## Goals and non-goals

Goals: every effector's side effect runs out of process under a declared profile; the cycle's secrets never reach an effector; no effector reaches the entity's state tree, the bus or the network unless its profile names it; the guarantees are checked on the real host before an effector can be enabled.

Non-goals: confining the cycle itself (the container does that); judging whether an operator's whitelist entry is wise; changing which acts the entity can propose.

## Decisions

### D1. Every side effect runs in a confined child process

All three built-in effectors, and every registered effector, act through one executor that spawns a child under the effector's profile, passes the request on stdin as JSON, and reads a bounded JSON result on stdout. `file_write` moves into the executor. The cycle process keeps the whitelist check, the signature check and the audit write, and does nothing else on the act's behalf.

Alternatives considered:
- Keep confinement in-process (better path checks, `openat2`-style resolution). Rejected: it can bound a file write but never a shell command, and two mechanisms for one boundary is how the present gap arose.
- Confine only `shell`. Rejected: `notify` speaks to the operator's session bus, plugin and device effectors run arbitrary code, and a shell entry can plant a symlink that the in-process `file_write` then follows. One boundary for all effectors is easier to test and to state in the paper.

Cost: one process spawn per act. Acts are rare by construction (the act refractory interval in `act-intent-derivation`), so spawn latency of a few milliseconds does not matter. It is measured in task 2.4 rather than asserted.

### D2. A profile is declared by the effector, not inferred

A `ConfinementProfile` holds: `read_paths` (executables and libraries the effector needs, read-only), `write_dir` (the sandbox; at most one), `network` (`none` or `session_bus_notifications`), `devices` (device nodes, empty for the built-ins), `env` (an allowlist of variable names and fixed values), and limits (CPU seconds, address space, process count, wall time). The built-in profiles:

| Effector | read_paths | write_dir | network | devices |
| --- | --- | --- | --- | --- |
| `file_write` | the executor's interpreter and modules | sandbox | none | none |
| `shell` | `/usr`, `/bin`, `/lib*`, `/etc/ld.so*`, the entry's command | sandbox | none | none |
| `notify` | `/usr`, `/lib*`, the notification command | none | `session_bus_notifications` | none |

`state/`, `/app/state`, the configured data root, the bus sockets, the trainer jobs directory and every path holding a secret are outside every built-in profile. A device effector's profile names its device node and nothing writable but the sandbox.

Alternative considered: one global profile for all effectors. Rejected because `notify` needs the session bus and a device effector needs a device node, and widening every effector to the union defeats the purpose.

### D3. Backends, chosen by what the host supports

| Backend | Mechanism | Where it works | Strength |
| --- | --- | --- | --- |
| `bwrap` | bubblewrap: new user, mount, PID, IPC and network namespaces; only the profile's paths bound in, read-only except `write_dir` | bare hosts that allow unprivileged user namespaces | strongest: the child cannot see anything not bound |
| `landlock-seccomp` | Landlock filesystem rules (read-only `read_paths`, read-write `write_dir`); a seccomp filter that refuses `socket()` for every family except, for the notify profile, `AF_UNIX`; `no_new_privs`; `setrlimit`; new session and process group | Linux with Landlock, including inside containers where user namespaces are blocked | strong for the filesystem and network; the child still sees the process table |
| `systemd-run` | a transient unit with `ProtectSystem=strict`, `ReadWritePaths=<sandbox>`, `PrivateNetwork=yes`, `NoNewPrivileges=yes`, `PrivateTmp=yes`, resource properties | bare hosts with a systemd user manager | strong; listed so an operator without bubblewrap has a supported option |

Boot probes the backends in that order and uses the first that can satisfy every enabled effector's profile. A profile that no available backend satisfies makes its effector unavailable, and boot refuses to start with that effector enabled (D6).

Evidence and caveats, all to verify in the spike (task 1.1) before code: bubblewrap is the sandbox Flatpak uses and needs either setuid or unprivileged user namespaces; Docker's and Podman's default seccomp profiles restrict `clone(CLONE_NEWUSER)` in many configurations, which is why `landlock-seccomp` is expected inside the shipped containers; Landlock filesystem rules are in mainline Linux since 5.13, and its TCP rules (ABI 4) do not cover UDP, which is why network denial is done with seccomp on `socket()` rather than with Landlock; whether the container runtimes' default seccomp profiles permit the `landlock_*` system calls. The reference host runs a 7.2 kernel. The spike records each of these on the reference host and inside the `kaine` image under `docs/records/`.

Libraries are a supply-chain choice and get the adversarial vetting the project requires of any new dependency: the bubblewrap binary from the distribution, `libseccomp` through its distribution Python binding, and Landlock through a small ctypes wrapper in the repository (three system calls) rather than an unvetted PyPI package.

### D4. Environment and working directory

The child's environment is built from the profile's allowlist only: `PATH=/usr/bin:/bin`, `LANG=C.UTF-8`, `HOME=<sandbox>`, and nothing named `KAINE_*`, no `*_KEY`, `*_TOKEN` or `*_PASSWORD`. The working directory is the sandbox. A shell whitelist entry's `cwd` must resolve inside the sandbox; an entry with any other `cwd` is a configuration error at load, with the key named. The default (`None`, meaning "the process default") becomes "the sandbox".

### D5. File writes and symlinks

In the executor, `file_write` opens each path component relative to the sandbox directory descriptor with `O_NOFOLLOW` and creates the final file with `O_CREAT | O_EXCL` or `O_TRUNC | O_NOFOLLOW`. The confinement backend refuses a write that resolves outside `write_dir` regardless, so the two checks are independent. The existing `_resolve_sandbox_path` stays as an early, clear error message.

### D6. Enablement requires a passing self-test

At boot, when `enabled_effectors` is not empty, the effectors factory runs a self-test for each enabled effector inside its own profile on the chosen backend. The probes are fixed and content-free:

1. `KAINE_STATE_KEY` and every other secret variable are absent in the child.
2. Reading a file under the state tree fails with a permission or not-found error.
3. Writing outside the sandbox fails; writing inside succeeds.
4. A symlink inside the sandbox pointing outside is not followed for a write.
5. A TCP connection to the bus address and a UDP datagram to a public resolver address both fail before any packet leaves (checked by the `socket()` refusal, not by sending).
6. Spawning more processes than the limit fails, and a CPU-bound loop is stopped at its CPU limit.
7. For `notify` only: a session-bus call other than the notification method is refused by the proxy.

A failed probe is a boot refusal with its own refusal code (spec `cognitive-cycle`, distinct boot refusal codes), naming the effector, the backend and the probe. A pass is written to the research event log with the backend and a digest of the profiles. The research gate (`kaine/cycle/research_gate.py`) and the unattended gate gain `effector_confinement_verified`, which holds when the effectors module is off or when every enabled effector passed in this boot.

Alternative considered: test confinement only in CI. Rejected: confinement depends on the host's kernel, container runtime and seccomp profile, so a CI pass says little about the reference host. CI runs the same probes as unit tests where the runner supports a backend and skips with a visible reason where it does not.

### D7. Notifications

On a host with a desktop session, `notify` runs under `landlock-seccomp` or `bwrap` with access only to a filtering session-bus proxy (`xdg-dbus-proxy`, the tool Flatpak uses, with a rule that allows the notification service's notify call). Without a session bus, which is the case in the shipped containers, it writes to the confined fallback log as today. Whether `xdg-dbus-proxy` can filter to a single method, rather than to a whole service name, is to verify in the spike; if it filters only by name, the profile allows the notification service and the design records that limit.

### D8. Plugin and device effectors

`register_effector` requires the effector to carry a `confinement_profile`. Registration of an effector without one raises at boot, naming the plugin. `act-intent-derivation`'s device bound (action set, value range, minimum interval) stays the within-effector bound; this change adds the process bound underneath it, so the light and the pan-tilt camera run their device protocol in the executor with only their device node.

### D9. Audit

Each audit record gains `confinement_backend` and `profile_digest`. The audit log stays in the cycle process (the child never writes it), so a confined act cannot rewrite its own record.

## Risks

- A backend is unavailable in the shipped container: handled by the fallback order and the boot refusal; the spike settles which backend the image uses before code is written.
- A profile is too narrow for a legitimate whitelist entry (a command needs a library path not listed): the act fails with a clear error and the audit records it. The operator widens `read_paths` explicitly; there is no automatic widening.
- Seccomp filter differences across architectures (x86-64 and aarch64 for the Orin host): the filter is built per architecture by libseccomp, and the self-test runs on each host.
- An act that succeeded before now fails under confinement. That is the intended outcome, and the failure is reported truthfully to the entity as the effector's result.

## Migration and ordering

1. Spike on the reference host and in the image (task 1.1); record results.
2. Profiles and the executor with the `landlock-seccomp` backend; `file_write` moves into it.
3. `bwrap` and `systemd-run` backends.
4. Environment and `cwd` rules; the config-load error for an outside `cwd`.
5. `notify` through the proxy.
6. The self-test, boot refusal and gate conditions.
7. Red-team cases and docs.

Steps 2 to 7 may land as three or four pull requests. Until step 6 merges, `enabled_effectors` keeps its current behaviour; after it, a non-empty list requires a pass.

Timing: off the study path. The effectors module is off in the first configuration and is not in the module-addition study's default order (spec `module-ignition-study`, "The first round adds six held modules by default"). This change can be built now and must merge before any effector is enabled anywhere, and before the effectors module joins the study at its hardware stage. It does not need to wait for the study, and nothing in it changes a running study.

## Welfare and admissibility notes

No entity's experience changes: the module is off in every configuration that runs today. When it is first enabled, an act the confinement blocks returns a failed result, which the entity can learn from as from any other failed act; no act is silently dropped or faked. Keeping the entity's acts away from its own preserved state protects the preservation and individuation guarantees. This is a security-boundary change, so each pull request gets the worker first-pass review, Claude's adversarial review and an independent second review by Claude.

## Implementation estimate (LLM-agent terms)

Size M. One spike (a probe script and a records file; one worker call and a Claude run on the host and in the image, no GPU). Then three or four pull requests of roughly 300 to 600 lines each including tests, about 10 to 14 worker calls in total, a Claude adversarial review on each and an independent second review on the executor and self-test pull requests. About two to three working days of wall time with workers in parallel. No entity boots, no GPU.
