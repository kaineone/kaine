## Why

The readiness audit found that the `v1.0-ready` tag was premature.
Five concrete gaps blocked an operator from actually following
`FIRST_BOOT.md`:

1. No `kaine/cycle/__main__.py` — the doc said "python -m kaine.cycle
   if you have it built." It wasn't built.
2. No module-from-config factories — every module's `__init__` takes
   kwargs but no code read `config/kaine.toml` to construct them.
3. Nexus `metrics_snapshot()` returned a placeholder, not real cycle
   stats.
4. `SECURITY.md` and `FIRST_BOOT.md` referenced
   `state/bus/AUDIT.log` — no code writes that file.
5. Integration tests used `StreamProducerFake`, not real modules. The
   v1 claim was never verified against the real stack.

This change fills the gaps. After it lands, an operator can:
- Run `scripts/first-boot.sh` (preconditions verified).
- Run `python -m kaine.cycle` (cycle boots with real modules per
  `[modules]` toggles in `config/kaine.toml`).
- Open `http://127.0.0.1:8088/diagnostics/` (real metrics: tick
  index, processing/experiential rates, error counts).

## What Changes

- New `kaine/boot.py`:
  - `ModuleFactory` Protocol — `build(bus, config_section) -> BaseModule`.
  - Per-module factory functions for all twelve modules. Each maps
    TOML keys → constructor kwargs explicitly (no `**kwargs` splat,
    so unknown keys are caught at boot, not at runtime).
  - `build_registry(bus, kaine_config)` — reads the `[modules]`
    toggles + per-module sections and returns a populated
    `ModuleRegistry`. Hypnos is constructed last with refs to the
    already-built mnemos / nous / thymos (two-phase init).
  - `MetricsCollector` — passed the cycle + registry, exposes
    `snapshot()` that returns live values.
- New `kaine/cycle/__main__.py`:
  - Loads bus + nexus config, constructs `AsyncBus`, calls
    `build_registry`, builds `CognitiveCycle` from `[cycle]` config,
    handles SIGINT/SIGTERM gracefully, runs forever.
  - Hard-coded refusal to boot if `KAINE_CYCLE_OPERATOR_PRESENT=1`
    is unset, mirroring `first-boot.sh`'s safety gate.
- `kaine/nexus/__main__.py`:
  - Accepts optional `cycle_ref` + `registry_ref` parameters via a
    new `--connect-cycle` flag that reads a small JSON state file
    written by the cycle entrypoint (`state/cycle/runtime.json`).
    Falls back to placeholder metrics if the cycle isn't running
    yet — Nexus can boot before the cycle for inspection.
- Doc fixes: remove false `state/bus/AUDIT.log` claims from
  `SECURITY.md` and `FIRST_BOOT.md`. The bus's `audit()` method
  validates Redis config and logs to the Python logger; that's it.
  The audit trail that operators are pointed at is the Praxis one,
  which is genuine.
- Real-module smoke test: `tests/test_boot_wiring.py` builds the
  full registry from a minimal config TOML with all module heavy
  deps monkeypatched. Verifies every factory produces a registered
  module with the right `.name`.

## Capabilities

### Modified Capabilities

- `final-integration` — adds requirements for `kaine/boot.py`,
  `kaine/cycle/__main__.py`, and removes the false AUDIT.log
  references from the operator docs.

## Impact

- **No new external deps.** Pure-Python wiring.
- **Operator-facing path becomes real.** `FIRST_BOOT.md` Step 3 is
  no longer "write some Python."
- The `v1.0-ready` tag is corrected: the tag stays, but the gaps it
  hid are now actually closed. Re-tag as `v1.0.1-ready` after
  archive.
