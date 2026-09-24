## Why

KAINE's oscillatory-binding layer attaches a small LIF oscillator to each module
and uses phase coherence (PLV) to bind co-active coalitions in the workspace.
Biological neural cultures **are** oscillators — their intrinsic bursting has
rhythmic structure — so sourcing module phase from the tissue's own dynamics is
nearly a gimme, and it is the most "native" of all the conversions: we are not
forcing a computation onto neurons, we are reading a rhythm they already have.

## What Changes

- Add a `cl1` oscillator source that satisfies KAINE's `OscillatorProtocol`
  (`phase()`, `step()`, `set_frequency()`), driven by a substrate territory.
- **Drive:** periodic stim sets/entrains the territory's rhythm; `step(salience)`
  modulates drive as the silicon LIF's co-activity input does today.
- **Read:** phase is extracted from the territory's burst timing / DCT spectral
  content (`cl.analysis`), returned as `phase()` for PLV coherence.
- Honour `set_frequency(scale)` so Hypnos can slow oscillators during deep-sleep
  maintenance exactly as with the silicon oscillator (e.g. 0.5 = half speed).
- Selected per-module or globally; modules without a substrate oscillator keep the
  neutral phase (upstream behaviour), so this composes safely.

## Non-goals

- Changing the PLV coherence math or how the workspace uses phase.
- Converting the modules themselves (this is the oscillator seam only).
- Executing on real hardware in this change (the project goal, deferred until
  grant-funded access; validated on the simulator meanwhile).

## Impact

- New capability: `oscillator-wetware-backend`. Depends on `cl1-substrate`.
- New code: `kaine_cl1/backends/oscillator.py`; attached via
  `BaseModule.attach_oscillator(...)` in `kaine_cl1/boot.py` — an existing,
  clean upstream seam (no upstream change needed).
