## Why

`docs/kaine-paper.md` §3.4 names Praxis as the agency module —
"effectors through which the system acts on the world." Build prompt
§5.5 specifies the v1 effector set: file write, notifications, vetted
shell command whitelist. Audio output is explicitly NOT Praxis
(Chatterbox handles that in §5.3). Every action gets logged with full
context, and the whitelist gets a careful security audit.

Praxis is the difference between perception-only (locked-in
syndrome, per the paper's failure-modes section) and a system that
can act. Even a tiny effector surface lets the architecture close the
perceive→reason→affect→act loop.

## What Changes

- Introduce `kaine.modules.praxis` package split four files:
  - `effectors.py` — `Effector` protocol + three implementations:
    `FileWriteEffector` (writes to a sandboxed directory under
    `state/praxis/files/`), `NotifyEffector` (uses `notify-send` when
    available, falls back to writing a notification line to a log
    file), `ShellEffector` (runs a command from a vetted whitelist).
  - `whitelist.py` — `CommandWhitelist` dataclass + matching logic.
    A whitelist entry pins a command, allowed arg patterns (regex),
    a working-directory whitelist, env-var allowlist, and a timeout.
    Anything not exactly matched is rejected.
  - `audit_log.py` — `ActionAuditLog` writing JSONL records to
    `state/praxis/audit.log` (atomic append). Every action attempt
    is logged with timestamp, effector, request payload, result,
    and any error.
  - `module.py` — `Praxis(BaseModule)` exposing `act(request) ->
    ActionResult` for callers (Lingua in 5.2, future planners),
    publishing `praxis.action` events on the bus with diagnostics-
    only payload (effector name, success bool, elapsed_ms, error
    type — never the contents of files written or the stdout of
    shell commands).
- `[praxis]` block in `config/kaine.toml`: sandbox path, whitelist
  entries, max file size, notification command, audit log path.
  `modules.praxis = false`.
- Security audit baked into a separate `kaine/modules/praxis/AUDIT.md`
  describing the threat model, what each effector does and does NOT
  expose, and the whitelist invariants.
- Tests: per-effector behavior, whitelist rejection cases,
  audit-log JSONL roundtrip, module integration.

## Capabilities

### New Capabilities

- `praxis`: minimal agency surface with three effectors (file write,
  notifications, shell whitelist), a strict command whitelist, and a
  durable JSONL audit log. Audio output is explicitly excluded — it
  lives in Phase 5.3.

### Modified Capabilities

None.

## Impact

- **Depends on:** `event-bus`, `module-pattern`. All shipped.
- **Repo:** adds `kaine/modules/praxis/*.py`, `tests/test_praxis_*`,
  updates `pyproject.toml`, `config/kaine.toml`, gitignored
  `state/praxis/`.
- **No new external deps.** `notify-send` is the only optional
  system dep and the fallback handles its absence.
- **Security:** the shell whitelist is intentionally tiny and
  per-deployment configurable. v1 ships with no commands enabled —
  the operator opts in.
- **No runtime impact** on the cycle. Praxis is registered in code
  paths but not auto-added to ModuleRegistry; first boot decides.
