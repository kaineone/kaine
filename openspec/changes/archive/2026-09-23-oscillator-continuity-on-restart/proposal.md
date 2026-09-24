## Why

When Spot rebuilds one failing module (the heavy restart path), `rewire_module` calls `_wire_oscillators`, which builds a new oscillator for every module in the registry, including the healthy ones. That has three costs for a running entity:

- Every healthy module loses its oscillator's phase history at each restart, so the coherence factor measures synchrony from a cold start across the whole mind, not just for the module that failed.
- The rebuilt module also starts a fresh rhythm, although nothing about its oscillator failed.
- A plugin's `make_oscillator` is called again for every declared oscillator seam. If that call raises, the rebuilt module is already registered without an oscillator and reports the neutral phase while Spot retries, so the run briefly departs from the substitution the manifest records.

## What Changes

- On a heavy restart, the rebuilt module receives the oscillator object its predecessor held. It is the same object, with its phase history intact, whether it was the default snnTorch oscillator or a plugin's. Nothing is re-created, so the restart has no oscillator failure path.
- `rewire_module` no longer rebuilds oscillators. Modules that were not restarted keep theirs untouched.
- A plugin's `make_oscillator` is therefore called once per declared seam, at boot. `docs/plugins.md` states this.
- Light (in-place) restarts already keep the module object and its oscillator; they are unchanged.

## Capabilities

### New Capabilities
- (none)

### Modified Capabilities
- `oscillatory-binding`: add a requirement that module restarts keep oscillators continuous.

## Impact

- `kaine/cycle/spot.py` (heavy restart hands the predecessor's oscillator to the rebuilt module), `kaine/boot.py` (`rewire_module` stops rebuilding oscillators).
- `docs/plugins.md`.
- Tests for both restart paths, the default and plugin oscillators, and untouched healthy modules.
- No entity boot needed.
