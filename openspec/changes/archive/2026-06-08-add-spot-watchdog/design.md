# Design — Spot, the module supervisor

## Why a supervisor and not a module
Spot must keep running and take action precisely *when modules fail*. If it were a
registry `BaseModule` it would be subject to its own liveness checks (circular) and
would be torn down by the same shutdown it is supposed to orchestrate. So Spot is a
component in the cycle layer (`kaine/cycle/spot.py`), constructed and run by the
entrypoint alongside `cycle.run_forever` and the freeze-watch loop. It is named
"Spot" (the watchdog) at the operator's request; the name is branding only.

## Liveness model
Per module, per poll, combine two signals:

1. **Crash (authoritative, zero false positives).** Walk `module._tasks`: a module
   is `dead` if any task `done()` with a non-None `exception()`, or a task returned
   while `module._stopped` is not set (an organ loop that exited on its own).
   Catching this needs no per-module code — it reads the existing `_tasks` list.
2. **Hang (secondary, gated).** A centralized monotonic `last_heartbeat` on
   `BaseModule`, bumped in the existing `_workspace_loop` after each `on_workspace`
   and at the end of `publish`. `heartbeat_age()` = `monotonic() - last_heartbeat`.
   A module is `hung` only if `heartbeat_age > heartbeat_timeout_s` (default 60 s)
   AND at least one task is still running AND the entity is not sleeping. Because
   the cycle broadcasts to every initialized module's workspace loop at ~3.33 Hz,
   every live module's heartbeat is refreshed regardless of its own publishing
   activity — so "quiet" never reads as "hung." The hang signal exists only to
   catch true deadlocks (e.g. a synchronous model call wedged), and is the reason
   the timeout is generous.

**Sleep gate.** If the registry has `hypnos` and `hypnos.is_sleeping` is True,
suppress hang-only flags (modules legitimately downscale during maintenance). The
crash signal still applies — a crash during sleep is still a crash.

## Recovery — one incident at a time
```
poll every poll_interval_s (default 2.0s):
  if not enabled: return
  read control.json
  if frozen and source == "operator": return        # operator owns the freeze
  for module in registry.all_modules():
    state = assess(module)                            # alive | dead | hung
    if state == alive: clear resolved incident; continue
    inc = incidents.setdefault(module.name, Incident())
    freeze(source="spot", reason=...)                 # humane suspend + perception halt
    publish spot.status(recovery) + spot.log(...)
    if inc.attempts == 0:
      inc.snapshot = fork_manager.snapshot(label="spot-pre-restart:<m>", ...)
    inc.attempts += 1
    ok = restart_module(module.name)
    if ok and assess(registry.get(module.name)) == alive:
      publish spot.log("recovered <m> after N attempt(s)")
      incidents.pop(module.name)
      if control source == "spot": unfreeze()         # resume only our own freeze
      break
    if inc.attempts >= max_restart_attempts (5):
      escalate(module.name); return HALT
    publish spot.log("restart <m> failed (N/5); backing off")
    await sleep(restart_backoff_s); break             # stay frozen; re-poll
```

## Restart ladder
- **Light** — `BaseModule.restart()`: `await shutdown()`, reset `_stopped`/cursor,
  `await initialize()`. Valid only when construction held no external resources.
- **Heavy** — rebuild via the boot factory + `ModuleRegistry.replace(name, new)`:
  used when `module.holds_external_resources()` is True (httpx/Qdrant clients,
  model handles, perception supervisors — audition, vox, mnemos, empatheia, topos,
  nous, lingua, hypnos). Sequence: `await old.shutdown()` → rebuild
  (`SIMPLE_FACTORIES[name]` with the module's config section, or `make_hypnos` with
  sibling refs re-fetched from the registry, mirroring `build_registry`) →
  `await new.initialize()` → `registry.replace` → re-run post-build wiring via a
  `rewire_module(registry, name, config)` helper factored out of `build_registry`
  (`_wire_self_hearing_gate`, `_wire_lingua_self_model`, `_wire_oscillators`) →
  `fork_manager.restore(last_good_snapshot_id)` so the fresh instance inherits its
  pre-crash numeric state via `deserialize`.

`Spot` is given a `rebuild_module` closure by the entrypoint (it owns `bus`,
`kaine_config`, and the registry); Spot itself imports no module factories.

## Freeze integration
Spot freezes by writing the operator-freeze control file with `source="spot"`. The
existing `_freeze_watch_loop` then pauses the cycle and halts perception — one
source of truth, and the Nexus freeze banner already reflects it. Spot resumes only
when `source == "spot"`; it never clears an operator freeze, and an operator freeze
short-circuits Spot's recovery actions so the two never fight.

## State-save timing
Snapshot **before the first restart attempt** (preserve last-good state — the
safety-first choice and the seed of fork-at-any-point) AND **again at escalation**.
`ForkManager.snapshot` already deep-copies each module's `serialize()`, tolerates
per-module serialize errors, encrypts at rest, and enforces retention — all reused
as-is. Snapshots are numeric/derived-only; the zero-raw-sense-data invariant holds.

## Escalation
After the 5th failed attempt: final `fork_manager.snapshot`, `shutdown()` every
module, write `state/cycle/escalation.json` (operational fields only:
`escalated`, `module`, `attempts`, `snapshot_id`, `escalated_at`, operator
`message`), publish a final `spot.status(critical)`, log CRITICAL, and signal the
entrypoint to exit non-zero. The process exits frozen; a clean boot calls
`clear_escalation()` (next to the existing `unfreeze()`), so a wrapper that simply
restarts the process without an operator reboot still sees the prior escalation
cleared only on a deliberate fresh launch. Spot never reboots the host — it only
asks (operator-supervised scope).

## Cross-process Nexus feedback (the operator's view)
The Nexus server is a separate process from the cycle; they share files and the
Redis bus. So:
- **Authoritative state** for the alert border/banner is derived in `health.py`
  from `control.json` (`frozen` && `source == "spot"` ⇒ `recovery`) and
  `escalation.json` (`escalated` ⇒ `critical`), exposed as a `spot` block on the
  health snapshot and `/diagnostics/health.json`. This paints correctly on page
  load and SSE reconnect.
- **Live updates** ride the existing bus→SSE bridge: Spot publishes `spot.status`
  and `spot.log` events to a `spot.out` stream; `spot.out` is added to
  `DEFAULT_DIAGNOSTICS_STREAMS`; the browser flips the border/banner on
  `spot.status` and appends `spot.log` lines to the incident console. (A logging
  ring-buffer in the Nexus process would NOT see Spot's logs — they originate in
  the cycle process — so the bus is the correct transport.)
- The border overlay lives in `_base.html` so it wraps every page; the pulse is
  gated behind `@media (prefers-reduced-motion: reduce)` (static border, no pulse).

## Risks / mitigations (ranked)
1. **False-positive restart of a quiet module** → crash signal is primary; hang
   needs stale-heartbeat AND running-task AND not-sleeping; generous timeout;
   heartbeat refreshed by the cycle broadcast for every live module.
2. **Heavy restart leaks an external handle** → always `await old.shutdown()`
   first; cap at 5 attempts; shutdown-all on escalation.
3. **Hypnos sibling refs go stale after restarting a sibling** → one incident at a
   time; the rebuild closure re-fetches siblings from the registry each time.
4. **Re-wiring forgotten after heavy restart** → `rewire_module` helper + a test
   asserting the SpeakingGate/oscillator re-attach.
5. **Spot vs operator freeze fighting** → `source` attribution; Spot only resumes
   its own freeze; operator freeze short-circuits Spot.
6. **Who watches Spot** → its `run()` body is wrapped so an internal error logs
   CRITICAL and signals halt rather than dying silently; the task is awaited in the
   entrypoint `finally` like the freeze-watch task.
