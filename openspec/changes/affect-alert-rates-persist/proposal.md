## Why

A live test boot of main e266aa88 (2026-10-17) showed that a plain restart or a revive relieves boredom. The perceptual alert rates `r_f` and `r_s` (paper A.4, the boredom alert excess) are not in the affect module's saved state, so a restored module starts with `r_s = 0`. The first alerts after the boot then look like a large excess over the floor `r_0`: boredom fell from 0.89 to 0.02 within seconds, and the boredom goal restored from the checkpoint was abandoned `without_response` about 15 s after each boot. Paper A.7 says all module state persists with the entity, so a restart must neither reset nor repeat it.

The same gap drops the other running estimates that feed the drives and the appraisal: the per-module fast and slow error means behind learning progress (curiosity relief and the pleasantness check), the intent rate `r_int` (restlessness), the last wellness `w` (valence), and whether an interaction has been seen (the social drive's build signal).

## What Changes

- `Affect.serialize()` adds `alert_rates` (`fast`, `slow`), `error_means` (per source: fast and slow sums and counts), `intent_rate`, `wellness` and `interaction_seen`.
- `Affect.deserialize()` restores each of them when present and valid, and leaves the constructor defaults when a key is missing or malformed, so state written before this change still restores.
- Entity time does not pass while the entity is down, and the entity clock restarts with each process, so no timestamp is saved: a restored error mean takes the restore time as its latest report time, and the alert rates decay from the restore onward.
- The transient pieces stay transient: response windows, stall timers, the held obstruction, the intent count since the last broadcast, the last interaction gap, and a speaker's perceived emotion.

## Capabilities

### Modified Capabilities

- `affect`: the module's saved state carries the alert rates, the error means, the intent rate, the wellness and the interaction flag, so a restart or revive resumes the drives and the appraisal where they were.

## Impact

- `kaine/modules/affect/module.py`, `docs/09-modules/affect.md`, a new affect persistence test.
- Behaviour: after a restart or revive, boredom is relieved only by alerts in excess of the habituated rate the entity had before it stopped, so a restored boredom goal is no longer abandoned by the boot itself. Saved state grows by a few numbers per perceptual source and holds no sense data.
