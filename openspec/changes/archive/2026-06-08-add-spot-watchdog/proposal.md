## Why

Today nothing watches the modules. A module's asyncio task can raise and exit
silently (`BaseModule._workspace_loop` logs and returns; subclass loops likewise),
and the cognitive cycle just reads an empty stream for that module and keeps
ticking — an entity running with a dead organ, unnoticed. There is no liveness
signal, no restart, and no operator alert. For an operator-supervised system whose
first boots are deliberate and rare, a silent partial failure is exactly the
failure mode we cannot afford.

We add **Spot** — an always-on supervisor that watches every module and, on a
stall or crash, freezes the entity (humane suspend), tries to restart the failed
module, and — if it cannot recover after five attempts — saves the entity's state,
brings the modules down cleanly, and asks the operator to reboot the machine
before retrying. Spot deliberately reuses machinery that already exists: the
`ForkManager` snapshot/restore lifecycle for state-save (which also seeds the
future fork-at-any-point capability), and the operator-freeze control file for the
freeze. The operator gets clear, real-time feedback in Nexus (a starship-style
alert border, a status banner, and a live incident console).

## What Changes

- A new supervisor **Spot** (`kaine/cycle/spot.py`) SHALL run as a task in the
  cycle entrypoint (outside the module registry — it must act when modules die, so
  it cannot be a module that would have to watch itself). Each poll it SHALL
  assess every registered module's liveness and drive recovery for at most one
  incident at a time.
- Liveness SHALL combine an authoritative **crash signal** (a module task that
  finished with an exception, or returned while the module was not stopping) with
  a secondary **hang signal** (a stale heartbeat while a task is still running),
  gated so legitimately-quiet modules and modules quiescing during Hypnos sleep
  are never flagged.
- `BaseModule` SHALL gain a centralized liveness/restart contract: a monotonic
  heartbeat bumped from the existing workspace loop and on every `publish`, a
  `health()` snapshot, a `heartbeat_age()`, a light `restart()` (recreate own
  tasks), and a `holds_external_resources()` hint (default False) that tells Spot
  to use a heavy rebuild instead.
- On a detected failure Spot SHALL: freeze the entity via the operator-freeze
  control file tagged `source="spot"` (so perception halts through the existing
  freeze-watch loop and Spot never clears an operator's freeze); take a **last-good
  snapshot** before the first restart attempt; attempt restart (light, then heavy
  rebuild via the boot factory + `ModuleRegistry.replace` for resource-holding
  modules); and on success resume only its own freeze.
- After **5** failed restart attempts Spot SHALL escalate: take a final snapshot,
  shut down all modules cleanly, write an `state/cycle/escalation.json` record with
  an operator-facing message, and cause the cycle process to exit non-zero so it
  does NOT auto-retry — the operator must reboot the machine and restart. Spot
  never reboots the machine itself.
- Nexus SHALL surface the incident to a watching operator: a `spot` block in the
  health snapshot (state `ok` / `recovery` / `critical`), a full-window alert
  border (yellow on recovery, red on critical; pulse gated by
  `prefers-reduced-motion`), a status banner with the human message, and a live
  console panel fed by a new `spot.out` bus stream that the diagnostics SSE bridge
  fans out.
- The `[spot]` config section SHALL ship **disabled** (`enabled = false`),
  consistent with the first-boot all-off guard.
- Snapshots remain numeric/derived-only (zero raw sense data); the escalation
  record holds only operational fields.

## Capabilities

### New Capabilities

- `spot-supervisor`: module liveness detection, freeze-during-recovery, the
  restart ladder, snapshot-before-restart and at-escalation, and the 5-failure
  operator-reboot escalation.

### Modified Capabilities

- `module-pattern`: `BaseModule` gains the heartbeat / `health()` /
  `heartbeat_age()` / `restart()` / `holds_external_resources()` liveness contract,
  and `ModuleRegistry` gains `replace(name, module)`.
- `cognitive-cycle`: the freeze control gains a `source` attribution
  (`operator` | `spot`); the entrypoint constructs and runs Spot, clears any stale
  escalation at clean boot, and propagates an escalation exit code.
- `nexus-observability`: the health surface gains the `spot` incident block, the
  alert border + banner, and the live incident console over the `spot.out` stream.

## Impact

- **Code (new)**: `kaine/cycle/spot.py`, `kaine/cycle/escalation_state.py`.
- **Code (edit)**: `kaine/modules/base.py`, `kaine/modules/registry.py`,
  `kaine/cycle/control_state.py`, `kaine/cycle/__main__.py`, `kaine/boot.py`
  (factor a `rewire_module` helper out of `build_registry`), `kaine/nexus/health.py`,
  `kaine/nexus/__main__.py` (add `spot.out` to the diagnostics streams), the Nexus
  templates/static (`_base.html`, `_spot_banner.html`, `diagnostics.html`,
  `style.css`, `nexus.js`), and ~8 resource-holding modules (one-line
  `holds_external_resources` override each).
- **Config**: new `[spot]` section in `config/kaine.toml`, shipped disabled.
- **Tests**: Spot liveness/restart/escalation/freeze, BaseModule heartbeat/restart,
  Spot config, the zero-persistence invariant extended to `escalation.json`, the
  shipped-config all-off guard extended, and Nexus router/UI coverage.
- **Operator**: a watched recovery is visible in real time; an unrecoverable
  failure halts the entity with state saved and a clear reboot instruction.
