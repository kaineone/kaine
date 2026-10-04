# Turn `_boot_and_run` into ordered phases

## Why

The complexity audit of 2026-10-03 (W5) found the cycle's boot in one 1,126-line function, `_boot_and_run`. About sixty local variables carried state from one stretch of it to another, so a reader could not tell which part produced what a later part used, and a change anywhere risked a later section.

## What changes

- **Phases.** `_boot_and_run` becomes a runner over `_BOOT_PHASES`, 26 phase functions in boot order. Each takes a `BootContext` and returns an exit code to stop the boot, or `None` to continue.
  - The phases are: stage, preconditions, run_identity, gates, bus, womb_hold, registry, maturation_gate, workspace, volition, cycle, supervision, runtime_state, sidecar, ignition_log, preview, remote_bridge, signals, spot, safety_net, launch, birth, womb_watch, caretaker, gestation, watchers.
  - After the phases, the runner calls `_run_until_stopped(ctx)` inside `try:` and `_shutdown(ctx)` in `finally:`, then returns 70 if Spot escalated, else 0.
- **`BootContext`** (`kaine/cycle/boot_context.py`) is a slotted dataclass with one field per value that a phase sets and a later phase, the run loop or shutdown reads (58 fields). Each field's comment names the phase that sets it. Because it is slotted, a mistyped field name raises instead of creating a new attribute.
- **The bodies move verbatim.** A tool in the operator's tooling lifted each run of statements into its phase and rewrote only the cross-phase variables to `ctx.<name>`. Inlining the result back reproduces the original function's AST, with one exception: a redundant re-import of `PreservationConfig`, which the safety-net phase no longer needs.
- **The phases follow boot order, not concern.** The audit proposed grouping by concern (gates, gestation, safety net, optional components). The mapping showed that gestation and the safety net are interleaved with everything else because their tasks must start in a fixed order: for example, the welfare producer starts before any module exists, and its supervision lives in the run loop. Reordering them to group by concern would change the boot. So each phase is a contiguous stretch of the original, named for what it does.
- **The phases stay in `kaine/cycle/__main__.py` for now.** The import contracts allow `kaine.evaluation` and `kaine.remote.bridge` only from this file, and several phases need them. Moving the other phases to their own modules is a follow-up.
- **Tests.**
  - The phase order and each phase's possible exit codes are pinned.
  - Every `ctx.<name>` in a phase is a declared field.
  - The runner stops at a refusal, always runs shutdown, and returns 70 on escalation.
  - The two tests that pinned the boot's call order now walk the phases in `_BOOT_PHASES` order through `tests/_boot_sequence.py`.

## Found while mapping the boot (not changed here)

- **Cleanup on construction failures.** Shutdown cleanup runs only once the run loop starts. An exception while building (after the bus opens, before the run loop) leaves the bus, the welfare producer and any initialized modules unclosed. The process exits immediately after, but module state is not shut down cleanly. Fixing this changes failure-path behaviour, so it is its own change.
- **Inconsistent early-exit cleanup.** The revive-refusal exit closes the bus before stopping the welfare producer. The womb-hold exit does the opposite.
- **Late validation of `[empatheia].operator_sources`.** A bad value raises `ValueError` only after the registry is built. It belongs in config validation.
- **Construction never read.** `MetricsCollector` is constructed and discarded, though its comment says it makes metrics reachable by Nexus. Nothing reads it, because Nexus gets its metrics from the runtime state file. Under the no-pretend-processes rule it should go.
- **Repeated work.** `MaturationConfig` is built three times from the same table, and `[cycle]` and the organ model id are each read twice.
- **Exit codes.** The organ gate shared exit code 5 with the research gate, and the individuation refusal shared 3. The `distinct-boot-refusal-codes` change fixes this.

## Impact

- **Behaviour:** none. The statements, their order, the exit codes and the shutdown order are unchanged.
- **Research:** none. No study is running.
