## Why

Two findings of the mathematics review of 2026-10-08 about Topos foveation, which is on in the base-thesis profile.

- **The precision weighting is trivial.** The design selects the fovea by a precision-weighted combination of bottom-up saliency and a top-down bias. The code multiplies the bottom-up map (each tile's absolute grey-level change since the previous clip tick) by a weight of 1, and no top-down map is wired, so the fovea goes to whichever tile changed most. A tile that flickers all the time (a screen, foliage, water) wins as easily as a stable region that suddenly changes. In predictive coding, precision is the inverse variance of a channel's error, and attention weights each error by its precision (Feldman and Friston 2010).
- **The video encoder sees no motion.** With foveation on, the peripheral gist and the foveal crop are each encoded as a 16-frame clip made of one still view repeated 16 times, so the clip encoder's temporal modelling is wasted and motion enters only through the sequence of clip embeddings.

The top-down channel stays unwired, as the foveation design decided ("no pretend source").

## What Changes

- **Per-tile precision.** `SpatialSaliency` keeps, for every tile, an exponential running mean `mu` and variance `v` of its change (weight 0.05 per clip tick, about six seconds at the resting rate). The bottom-up map is the precision-weighted error `max(0, d - mu) / sqrt(v + s0^2)`, computed against the statistics before this observation, where `s0` floors the standard deviation at a tenth of the mean change across tiles so no tile is treated as infinitely reliable. Until a tile has five observations the raw change is used. A tile that always flickers has a large `v` and is down-weighted; a stable tile that changes is up-weighted.
- **Real clips.** The peripheral and foveal views are derived from every frame in the clip buffer, using the fovea chosen on the latest frame, so the encoder receives the last 16 frames of motion for both views. A per-frame encoder (clip length 1) is unaffected.

## Capabilities

### New Capabilities

- `topos-foveation`: precision-weighted bottom-up saliency and real foveated clips.

## Impact

- **Code:** `kaine/modules/topos/{foveation,module}.py`.
- **Behaviour:** the fovea favours surprising change over habitual change; the peripheral and foveal latents now carry motion, so Topos's change and prediction-error statistics, and the arousal startles they drive, change. The womb prediction-error marker reads Topos's error and is re-validated in the follow-up validation step.
- **Cost:** 32 crops and resizes per clip tick instead of 2, with the same two encodes; `scripts/bench_foveation.py` is to be re-run on the host before the next study.
- **Docs:** `docs/09-modules/topos.md`.
- **Paper:** §3.5 (the fovea) and the foveation figure caption.
