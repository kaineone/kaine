## Why

The integration test boot of main 3ce0bbfa (2026-10-16/17) restarted a revived entity with the same state tree and no `--revive`. The developmental readout logged "ignoring progress from another being", and its awake time fell from 3209 s to 0, while `stage.json` kept counting lived seconds (3241 to 4139).

The readout keys `development_progress.json` and `development_readout.json` by `"<perception seed>:<self-rhythm identity>"`. The identity is a fresh `uuid4` drawn in the `SelfRhythmOscillator` constructor (`kaine/oscillator/module_oscillator.py`). Module state, and with it the stored identity, is restored only by a revive, so every plain start draws a new identity and the key never matches. `docs/06-operation/development.md` ("Progress across restarts") promises that the file is keyed by the perception seed and "the self-rhythm's stored identity" and that the developmental phase spans restarts; the paper (Appendix A.7) states that awake time, the consecutive-pass count, the marker flag, the pull history and the frequency baseline persist with the entity, so a restart neither resets nor repeats them. The module-addition study's seed step runs 14 hours or more and has to survive a restart or a retry.

## What Changes

- The developmental readout stores the self-rhythm identity in the state tree, in `self_rhythm_identity.json` beside its readout file (by default `state/lifecycle/`).
- On a plain start the readout adopts the stored identity into the self-rhythm before it builds its key, so the key matches the saved progress and baseline. On a revive the identity the revive restored from the bundle wins and overwrites the stored one. With no stored file, the current identity is kept and written. An unreadable or malformed file is ignored with a warning and rewritten.
- The cycle tells the readout whether the boot is a revive.
- Decommission backs up and deletes the new file with the other developmental files.
- Progress saved for another entity is still ignored with a log line.

Nothing else is restored on a plain restart; that is unchanged and out of scope (see Impact).

## Capabilities

### Modified Capabilities

- `developmental-stimulus`: the self-rhythm identity persists in the state tree, so developmental progress survives a plain restart.

## Impact

- **Code:** `kaine/cycle/development.py`, `kaine/cycle/__main__.py` (`_start_development_owner`), `kaine/lifecycle/decommission_locations.py`.
- **Tests:** `tests/test_development_owner.py`, decommission location tests.
- **Docs:** `docs/06-operation/development.md`, `docs/appendix-a-configuration/perception-and-sleep.md`.
- **Not changed:** on a plain restart every module still starts from fresh in-memory state, including the self-rhythm's adapted recovery time constant, drives and outcome counts. Only the readout's progress and baselines carry over. This is what the docs and the paper promise today.
