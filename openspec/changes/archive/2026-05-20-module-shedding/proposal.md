## Why

Paper §4.3 and build prompt §7.3 require KAINE to degrade gracefully
as modules are shed (full stack → no-Lingua → no-Topos → cognition-
only). Phase 7.2's `ForkManager.fork(shed=...)` exposes shedding at
the snapshot level. Phase 7.3 proves the runtime actually tolerates
shed combinations: the cognitive cycle continues to tick, Syneidesis
continues to compose workspaces from whatever streams are still
publishing, and modules that subscribe to absent collaborators don't
crash — they just don't get input.

The risk we're guarding against is a module that registered for
another module's stream and now keeps its workspace consumer task
alive but errors out repeatedly because the subscription target
never materializes. The fix in code (already shipped) is that every
module subscribes via Redis streams' "$" cursor and falls silent
when no events arrive. Phase 7.3 is the test layer that proves it.

## What Changes

- Add a test-only `StreamProducerFake` module helper under
  `tests/_module_shedding.py` that mimics each named real module's
  publishing surface (publishes one event to its `<name>.out` stream
  on demand) without dragging in any heavyweight dependency. Each
  real module's actual integration is already covered by its
  per-module tests — Phase 7.3 only needs to test the *composition*.
- Add `tests/integration/test_module_shedding.py` covering:
  - full stack (all 12 module names registered with fakes)
  - no-Lingua (omit `lingua`)
  - no-Topos (omit `topos`)
  - cognition-only (only `nous`, `mnemos`, `eidolon`)
  - perception-only (only `soma`, `chronos`, `topos`)
  - lone-Soma (only `soma`)
  - empty registry (no modules at all)
- For each combination, run the cycle for at least 10 ticks with
  events published from each registered fake; verify
  `cycle.error_counts` stays empty, the workspace broadcast fires on
  experiential ticks, and Syneidesis selects events only from
  registered streams.
- Add a documented requirement that the cycle SHALL run cleanly
  against any subset of module names without per-tick errors.

## Capabilities

### New Capabilities

- `module-shedding`: graceful-degradation guarantee at the runtime
  level. Owns the cycle/registry/Syneidesis composition contract
  under partial module sets.

### Modified Capabilities

None — no module is changed; this is a test-and-spec change that
documents and verifies an invariant the code already (we believe)
upholds.

## Impact

- **Tests:** `tests/_module_shedding.py` helper +
  `tests/integration/test_module_shedding.py` integration suite.
- **No new runtime deps, no production code changes.**
