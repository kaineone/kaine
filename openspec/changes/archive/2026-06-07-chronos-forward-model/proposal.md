## Why

`KAINE_Paper_v4.md` §3.3.1 frames Chronos as publishing **temporal prediction
errors**: anomalies in event timing, habituation (expected events stop arriving),
and rumination (the same event recurring unexpectedly). Chronos already runs a
CfC (~32 units) and computes habituation + rumination, but its "anomaly" signal
is a rolling z-score of the hidden-state norm — a deviation statistic, not a
forward-model prediction error. The CfC is used only as an encoder, not as a
next-state predictor.

This change makes Chronos genuinely predictive: the CfC predicts the next
temporal feature vector, and anomaly salience is driven by the error between
prediction and observation. Habituation and rumination detectors are retained.

## What Changes

- Add a forward-prediction head to `kaine/modules/chronos/network.py` (or a
  sibling `forward.py`): predict the next temporal feature vector from the CfC
  hidden state; publish `temporal_prediction_error` on `chronos.report`.
- Anomaly salience switches from z-score-of-norm to the forward-model prediction
  error; the z-score `anomaly_score` is retained on the payload for diagnostics
  continuity.
- The CfC adapts online (small step per tick) so "expected rhythm" tracks the
  actual event cadence; adaptation suspended during Hypnos.
- `[chronos]` config gains: `forward_prediction` (bool), `prediction_error_window`.

## Capabilities

### New Capabilities

- `chronos-predictive`: forward-model temporal prediction with error-driven
  salience, retaining habituation and rumination.

### Modified Capabilities

None (habituation/rumination/diagnostics retained).

## Impact

- **Depends on:** `chronos` (shipped). No new package (CfC via `ncps` already
  present).
- **Repo:** updates `kaine/modules/chronos/`, tests, `config/kaine.toml`.
- Smallest of the Phase-1 forward-model changes — the CfC already exists; this
  adds a prediction head and reweights salience.
