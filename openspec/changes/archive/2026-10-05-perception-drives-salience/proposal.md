## Why

The base thesis is that perception enters the workspace **as prediction error**,
and that a fixed reference stimulus corpus drives the competition. The first
containerized base-thesis run falsified that for the running configuration: over
a ~40-minute pass of real video-with-audio, **perception never once influenced the
workspace competition**. The evidence, measured off the bus:

- **Topos (vision) emitted its baseline salience `0.2` on all 3,830 reports** — it
  never alerted. A scene cut and a frozen frame produced the identical value.
- **Audition's general-perception path emitted baseline `0.4` on all 3,511 events** —
  it never crossed its alert threshold either.
- The workspace's winning competition scores were the recurring constant
  `0.176 = audition_baseline 0.4 × novelty 0.44` — arithmetic, not perception. The
  same value would appear watching any stimulus, or a blank screen.
- The only self-initiated utterance in the run was triggered by an internal
  **Chronos** temporal surprise, not by anything in the video.

So the reference stimulus was decoded and fed in, but did not drive the mind. Two
config defaults are the direct cause, and a third factor compounds them:

1. **`[topos].forward_prediction = false`** disables the forward-model
   prediction-error salience path — the very "perception as prediction error"
   mechanism the thesis rests on. Topos falls back to a raw change-threshold check.
2. **`[topos].change_alert_threshold = 0.005`** (and the Audition analogue
   `acoustic_change_alert_threshold = 0.35`) are **fixed thresholds calibrated for a
   different embedding space**. On the shipped InternVideo-Next 16-frame clip
   latent, consecutive clips barely differ, so `change` never reaches even 0.005 —
   the alert is structurally unreachable.
3. **Foveation is off** (forced by a stale guard: `Topos.__init__` still raises
   `foveation requires clip_len == 1 → use dinov2`, from before foveation was rebuilt
   to not depend on DINOv2), removing the peripheral-gist embedding the
   change/habituation/salience detector was designed to run on.

Lowering the workspace access threshold (as the shakedown did) does not fix this —
it only lets the constant baseline ignite. The bottleneck is upstream: perception
must produce stimulus-linked salience before any threshold or long run is meaningful.

## What Changes

Make perceptual salience genuinely stimulus-driven and prediction-error-based, so a
perceptual discontinuity in the reference corpus reaches the workspace:

- **Enable the forward-prediction salience path by default for the perceptual
  modules** (`[topos].forward_prediction`, and the Audition equivalent), so salience
  is driven by forward-model prediction error — aligning the implementation with the
  thesis's "perception enters as prediction error."
- **Replace the fixed alert thresholds with self-calibrating ones.** The
  forward-prediction path already normalises error against its rolling-window mean
  (`normalised >= 2.0`), which is embedding-agnostic; make the change-detector alert
  use the same relative-to-baseline criterion instead of an absolute constant, so it
  works regardless of encoder (InternVideo, DINOv2, foveal gist) and stimulus scale.
- **Reconcile foveation with the temporal encoder** — retire or correct the stale
  `clip_len == 1 → use dinov2` guard so foveation can run with InternVideo-Next (it
  was rebuilt off DINOv2), restoring the peripheral-gist change path and letting
  attention modulate salience.
- **Add a perceptual-discontinuity verification**: a known scene cut / acoustic onset
  in a fixture (and, operationally, in the reference corpus) MUST produce an
  alert-level perceptual event. This becomes a regression guard against silent
  regressions back to flat-baseline perception.

## Capabilities

### New Capabilities
<!-- None. -->

### Modified Capabilities

- **topos-perception** — perceptual salience becomes prediction-error-driven with a
  self-calibrating alert criterion; a perceptual discontinuity is required to raise
  salience above baseline.
- **attention-driven-audition** — the general-perception alert criterion is made
  self-calibrating on the same principle (tracked here; detailed in that spec).

## Impact

- **Config defaults**: `[topos].forward_prediction` (and Audition's) flip to enabled;
  `change_alert_threshold` / `acoustic_change_alert_threshold` semantics change from
  absolute to relative (a migration note for operators who set them).
- **Code**: the salience-decision branch in `kaine/modules/topos/module.py` and the
  Audition analogue; no bus/contract changes.
- **Methodological**: without this, no access-threshold calibration or long run is
  meaningful — the mind cannot tell the stimulus from a wall. This is prerequisite to
  the first citable base-thesis run.
