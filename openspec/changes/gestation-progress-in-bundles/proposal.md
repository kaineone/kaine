## Why

The paper (A.7) states that awake time is accumulated across the boots of one
entity and persisted with it. developmental progress (awake seconds, consecutive
entrainment passes, viability history) and the readout's baselines are saved
next to `stage.json` in `state/lifecycle/`, but a preservation bundle carries
only `stage.json`. An entity revived into a fresh state root therefore restarts
its developmental readout from zero.

## What Changes

- `preserve_live` copies `development_progress.json` and
  `development_readout.json`, when present beside the stage file, into the
  bundle under `development/` and includes them in the bundle tar (encrypted with
  the rest when encryption is on).
- A new `extract_bundle_development(bundle, dest_dir)` restores exactly those two
  files into the directory of the stage file, with mode 0o600; revive calls it
  before writing the stage file and refuses the revive if extraction fails.
- `development_viability.json` is not bundled: the verdict already travels inside
  the progress file, and a freshly written verdict file would look new to the
  study runner.

## Capabilities

### Modified Capabilities

- `entity-preservation`: developmental progress travels with the entity.

## Impact

- `kaine/lifecycle/preservation.py`, `kaine/cycle/revive_boot.py`, tests.
