## Context

KAINE Phase 1.4 — the last Phase 1 piece. The bus, cycle, and Syneidesis
are in place but there is no contract that every later module (Soma,
Chronos, Topos, Nous, Mnemos, Eidolon, Thymos, Lingua, Praxis, Hypnos)
will share. This change ships the contract — a `BaseModule` class, a
`ModuleRegistry`, and an `EchoModule` that exists only to verify the
plumbing end-to-end and stays in the repo as Phase 1's
regression-prevention canary.

Constraints:
- The cycle already exists with a `ModuleRegistryProtocol` that returns
  active stream names. Module pattern's registry must satisfy that
  protocol so the cycle picks up registered modules transparently.
- Modules consume the workspace broadcast via the bus, not via cycle
  callback. This preserves the cycle's stateless-with-respect-to-modules
  property and matches the paper's "every module reads the broadcast
  from the workspace" line (§2.4) literally — modules read from the
  stream, not from a passed argument.
- Serialize/deserialize must round-trip so Phase 7 fork/merge can
  snapshot and restore module state.

Stakeholders: every later module (consumer of the contract), Phase 7
fork/merge (state ser/de), Phase 6 Hypnos (pause/shutdown lifecycle).

## Goals / Non-Goals

**Goals:**
- `BaseModule` abstract class with `initialize`, `shutdown`, `publish`,
  `on_workspace`, `serialize`, `deserialize` async hooks plus a default
  workspace-consumer background task.
- `ModuleRegistry` tracking active modules by name with `register`,
  `unregister`, `get`, `all_modules`, plus `active_streams()` to satisfy
  `kaine.cycle.protocols.ModuleRegistryProtocol`.
- `EchoModule` that records every workspace snapshot it sees and can
  publish a single event on demand. Used by the end-to-end test and
  excluded from default config.
- End-to-end integration test wiring bus + cycle + Syneidesis + Echo
  + Registry that publishes an event, runs a tick, and verifies the
  echo module received the snapshot containing that event.

**Non-Goals:**
- A producer-loop framework. Modules with periodic work (Soma every N
  ticks, Chronos every cycle) implement their own producer task; the
  base class does not impose one.
- Network-attached modules. Single-host single-process for now.
- Hot-reloading modules.

## Decisions

**Workspace consumption via background task in `BaseModule`.**
`BaseModule.initialize()` starts an `asyncio.Task` that iterates the
bus's `subscribe_workspace` async generator and awaits
`on_workspace(snapshot)` for each broadcast. Cancellation propagates
through the generator on shutdown. The alternative — having the cycle
call `module.on_workspace` directly — would couple the cycle to the
registry's module instances and force a registry interface change.
Background-task consumption keeps the cycle pure and matches the bus
architecture.

**WorkspaceSnapshot reconstruction from the broadcast payload.** The
broadcast publishes a JSON-serialized dict. The base module
reconstructs a `WorkspaceSnapshot` instance (with a list of `(entry_id,
Event)` tuples) before invoking the subclass's `on_workspace`. Doing
this once in the base class spares every subclass from parsing.

**Registry is in-process and synchronous.** Module add/remove are
plain Python list mutations under no lock — the registry assumes
single-threaded access (the asyncio event loop owns it). The cycle
reads `active_streams()` at the top of each tick so additions and
removals take effect on the next tick.

**Module name is class-level (`name: ClassVar[str]`).** A subclass that
omits it fails at registry-time. Keeps the bus's source → stream mapping
unambiguous and pins identity at type level.

**`serialize` returns a plain dict; `deserialize` mutates the instance.**
Plain dicts roundtrip through JSON for fork/merge state files in
Phase 7. The contract is intentionally minimal — subclasses decide what
state matters.

**EchoModule is permanent test infrastructure, not a production module.**
It is `enabled = false` in the default `[modules]` config and is opted
into only by tests. It exists in the repo because regression tests on
the bus + cycle + Syneidesis path use it as the ground-truth observer.

## Risks / Trade-offs

- **Workspace consumer background task lag.** If a tick publishes a
  broadcast at time T, the module's `on_workspace` runs slightly
  later (one `xread` round-trip). → Acceptable: at fakeredis speed
  it is sub-millisecond; at real Redis on loopback it is single-digit
  ms. The bus is the source of truth, not the cycle's wall clock.
- **Unhandled exceptions in `on_workspace` are swallowed.** The
  background task logs and continues. → Better than crashing the
  module silently because of one bad snapshot; integration tests
  verify the path works.
- **`active_streams()` rebuilds on every cycle tick.** O(N) where N
  is module count. → Negligible (N ≤ 12).

## Migration Plan

First implementation. Module-pattern is the close of Phase 1; tag
`v0.1-scaffolding` ships once this change validates and the end-to-end
test passes.

## Open Questions

- Whether `ModuleRegistry` should also expose an aggregate
  `dispatch_workspace(snapshot)` for callers that prefer push-mode
  (Nexus might want this for its diagnostics view of "which modules
  saw which snapshot"). Defer until Phase 8.
