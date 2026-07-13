<!-- Fixes the finding that perception never influenced the workspace in the first
     base-thesis run (Topos 3830/3830 at baseline 0.2; Audition general path
     3511/3511 at baseline 0.4). Sequence the salience path first, verify, then
     re-enable attention. -->

## 1. Make vision salience prediction-error-driven and self-calibrating

- [ ] 1.1 Default `[topos].forward_prediction = true` so the forward-model
  prediction-error path is used (perception-as-prediction-error). Confirm the
  forward model steps on the InternVideo clip latent when foveation is off.
- [ ] 1.2 Replace the absolute `change_alert_threshold` alert test with the same
  relative criterion the prediction-error path uses (error/change normalised
  against its rolling-window baseline, alert when ≥ k·baseline). Keep an absolute
  floor only as a guard. The criterion must be embedding-scale-agnostic.
- [ ] 1.3 Unit test: a synthetic embedding sequence with a step-change produces an
  alert-level salience; a steady sequence stays at baseline (both encoders /
  foveation on and off).

## 2. Make general-audition salience match

- [ ] 2.1 Apply the same self-calibrating alert criterion to the Audition
  general-perception path (`acoustic_change_alert_threshold` → relative), and enable
  its forward-prediction path by default.
- [ ] 2.2 Unit test: an acoustic onset raises salience above baseline; steady sound
  stays at baseline.

## 3. Reconcile foveation with the temporal encoder

- [ ] 3.1 Retire/correct the stale `Topos.__init__` guard that raises
  `foveation requires clip_len == 1 → use dinov2`; foveation was rebuilt off DINOv2,
  so it must run with the InternVideo-Next encoder.
- [ ] 3.2 Confirm foveation-on routes the peripheral-gist embedding into the
  change/habituation/salience detector, and that attention (arousal-sized fovea)
  modulates salience as intended.

## 4. Perceptual-discontinuity regression guard

- [ ] 4.1 Systems test: a fixture clip with a hard scene cut and an audio onset MUST
  produce at least one alert-level `topos.report` and one alert-level
  `audition.perception` event — a standing guard against silent regression to
  flat-baseline perception.
- [ ] 4.2 Operational check: on the reference corpus, log/report the rate of
  alert-level perceptual events per minute so a run's "perception actually fired N
  times" is visible (ties into the Nexus perception panel).

## 5. Validate on a live short run

- [ ] 5.1 Boot the base-thesis form on the reference corpus and confirm perceptual
  discontinuities produce alert-level events that reach the workspace competition —
  i.e. the winning competition score now varies with the stimulus rather than
  sitting at the `intensity × novelty` constant.
- [ ] 5.2 Only after 5.1 passes, revisit access-threshold calibration and the full
  ~38h run (separate change).
