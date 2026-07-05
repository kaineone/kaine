## Why

`docs/kaine-paper.md` §3.2 puts Nous as the reasoning module: "implements
Non-Axiomatic Reasoning (Wang, Li, and Hammer 2018) and operates
continuously rather than on demand, treating every module's output as
potential evidence." Build prompt §3.1 prescribes integration via
OpenNARS for Applications (ONA), the C reference implementation —
described in the paper as "written in C and was designed to run on
hardware as small as a Raspberry Pi" so it is present in nearly every
deployment profile.

Phase 3 opens with Nous because reasoning is the hub the rest of the
cognition group connects to: Mnemos consolidates beliefs Nous emits,
Eidolon observes the workspace shaped by Nous's salient derivations.
Without Nous, the cycle has perception and pacing but no inference.

## What Changes

- Add `scripts/build-ona.sh` that clones
  `https://github.com/opennars/OpenNARS-for-Applications.git` to
  `external/OpenNARS-for-Applications/`, runs the upstream `build.sh`,
  and verifies the resulting `NAR` binary launches. `external/` is
  gitignored so the upstream source and build artifacts don't pollute
  KAINE's tree.
- Add `kaine.modules.nous` package split four files:
  - `narsese.py` — pure-Python helpers for assembling Narsese
    statements (`<term --> property>. :|: %f;c%`), parsing ONA
    output lines (`Input:`, `Derived:`, `Revised:`, `Answer:`),
    and the (frequency, confidence) truth-value dataclass.
  - `process.py` — `NARProcess` asyncio wrapper that spawns the
    ONA binary, writes inputs, reads derivations off stdout, and
    cleanly shuts down. Replaceable via a `NARProcessProtocol` so
    tests inject a fake.
  - `translator.py` — `EventTranslator` turning bus events into
    Narsese statements. v1: `<source --> [type]>. :|: %salience;0.9%`,
    with the `causal_parent` carried as a `Implication` when present.
  - `module.py` — `Nous(BaseModule)` orchestrating the above.
    Subscribes to workspace broadcasts, translates each selected
    event into Narsese, feeds ONA, polls for derivations, publishes
    new beliefs to `nous.out` with `frequency, confidence`
    truth-value pairs in the payload.
- `[nous]` block in `config/kaine.toml`: NAR binary path, max
  pending derivations, polling interval, baseline/alert salience,
  optional `inference_steps_per_tick`. `modules.nous = false`.
- Tests use `FakeNARProcess` returning canned derivations so the suite
  runs without the ONA binary. One opt-in test guarded by
  `KAINE_NOUS_RUN_REAL_NAR=1` actually launches NAR and verifies a
  simple roundtrip.

## Capabilities

### New Capabilities

- `nous`: continuous Non-Axiomatic Reasoning over bus events via ONA.
  Owns the NAR subprocess lifecycle, the event-to-Narsese translation,
  and the publication of derived beliefs back to the bus as
  `nous.belief` events with `(frequency, confidence)` truth-values.

### Modified Capabilities

None.

## Impact

- **Depends on:** `event-bus`, `module-pattern`. The cognitive cycle's
  workspace broadcast is the trigger surface.
- **Repo:** adds `scripts/build-ona.sh`, `kaine/modules/nous/*.py`,
  `tests/test_nous_*`, updates `pyproject.toml` (packages list),
  `config/kaine.toml`, `.gitignore` (external/), `DEPENDENCIES.md`.
- **External:** ONA upstream lives in `external/`. The build script
  is the one-time setup; the runtime path uses the binary only,
  no network calls.
- **Hardware:** ONA is single-threaded C code, ~20 MB resident,
  runs on CPU. Suitable for every deployment profile per paper §6.2.
- **No runtime impact** on the cycle. Nous is registered in code paths
  but not auto-added to ModuleRegistry; first boot decides.
