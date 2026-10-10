## Why

The pre-conference audit of 2026-10-10 found that the workspace-level precision weight (`precision-weighted-selection`) stops perception from reaching the workspace. The weight is the inverse variance of the intensities each source publishes. Thymos publishes its state every second at a constant intensity, so its variance goes to zero and its weight to the maximum (1.5); Topos and Audition vary exactly because they alert, so their weight falls to the minimum (0.5). Reproduced with the real `SourcePrecision`: an alert at 0.7 or 0.8 then scores below the 0.35 access threshold at every arousal. The base thesis requires perceptual surprise to be able to win the workspace.

The quantity is also the wrong one. In predictive coding, precision is the inverse variance of a channel's prediction errors and acts as the gain on that channel's error units (Feldman and Friston 2010); the variance of a module's published intensity is not that. The revised paper (predictive-workspace-paper, 2026-10-10) settles the design: precision is local to each processor, which already scores its prediction error against its own recent errors (the running ratio, error over its expected magnitude, and the fovea's per-tile z-score); arousal is the single global, neuromodulatory gain and contrast on the competition (adaptive gain, Aston-Jones and Cohen 2005). The workspace applies no per-source weight.

The paper also fixes greedy decoding (temperature 0) for the planned runs of the base-thesis form, so the language organ's output is a deterministic function of its input; the thesis profile still samples at 0.7.

## What Changes

- **Remove the workspace precision weight.** `RuleBasedSalience` computes `priority = clip(intensity * novelty * goal)` and `score = clip(level * C_g(priority))` as before. `kaine/workspace/precision.py`, `make_source_precision`, the `precision` argument, and the `[syneidesis]` keys `precision_weighting`, `precision_sample_weight`, `precision_warmup_samples` and `precision_bounds` are removed (they shipped two days earlier; no deployment depends on them). The arousal contrast gain stays.
- **Thesis profile decodes greedily.** `config/profiles/thesis_test.toml` sets `[lingua].temperature = 0.0`. Its comments stop calling Thymos "the precision core".
- The active `precision-weighted-selection` change drops its per-source weight requirement; its arousal contrast requirement stands.
- Docs: `docs/08-cognitive-cycle/global-workspace.md`, `docs/appendix-a-configuration/core.md`.

## Capabilities

### Modified Capabilities

- `syneidesis`: no per-source precision weight in workspace selection.
- `thesis-test-configuration`: greedy decoding in the base-thesis profile.

## Impact

- **Code:** `kaine/workspace/salience.py`, `kaine/workspace/precision.py` (deleted), `kaine/boot/wiring.py`, `kaine/boot/__init__.py`, `kaine/cycle/__main__.py`, `config/kaine.toml`, `config/profiles/thesis_test.toml`.
- **Behaviour:** perceptual alerts score `level * C_g(intensity)` again, so at resting arousal an Audition alert (0.8) reaches the threshold and the 0.7 alerts need arousal of about 0.37.
