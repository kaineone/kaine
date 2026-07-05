## Why

`docs/kaine-paper.md` §3.1 puts Chronos as the temporal-flow perception
module: "Closed-form Continuous-time network dynamics over event
streams, providing genuine temporal flow perception rather than the
tokenized sequence prediction that transformers offer." Soma's first
report is *now* — a single moment of body-state. Chronos extends that
into a sense of how moments connect: anomaly when rhythms break,
habituation when patterns persist, rumination when activation loops,
and time-since-last-interaction as a first-class signal feeding the
motivation layer.

Build prompt §2.2 names the `ncps` package (Hasani et al. 2022's
CfC reference implementation) as the integration target. CfC was
sanity-checked during the dynamic-torch-install commit at units=16 →
11,456 parameters, well under the 100K cap.

## What Changes

- Introduce `kaine.modules.chronos` package with five files split by
  responsibility:
  - `featurizer.py` — `SnapshotFeaturizer` turning each
    `WorkspaceSnapshot` into a fixed-dimension feature vector.
    Features: number of selected events, salience statistics (mean,
    max, std), top-source one-hots, inter-snapshot delta time
    (log-scaled), inhibited bit, is-experiential bit.
  - `network.py` — `CfCNetwork`, a thin wrapper around `ncps.torch.CfC`
    that owns the persistent hidden state and exposes a per-step
    `tick(feature_vec) -> hidden_state` API. CPU-only by default
    (`select_device("cpu")`).
  - `anomaly.py` — `AnomalyDetector` protocol + `RollingZScoreAnomaly`
    default. Computes anomaly as the z-score of the current hidden
    state's norm against a rolling window of recent norms.
  - `rumination.py` — `RuminationDetector` protocol +
    `RecurrenceRuminationDetector` default. Buckets hidden states by
    coarse fingerprint; flags rumination when one bucket recurs more
    than N times in a window of K snapshots.
  - `module.py` — `Chronos(BaseModule)` orchestrating the above. On
    each workspace broadcast it featurizes, steps the CfC, scores
    anomaly, updates habituation and rumination, and publishes
    `chronos.report`.
- Track `time_since_last_interaction_s` against any event whose source
  matches a configured set (default `{"audio.in", "user", "lingua"}`).
  Updated by the cycle-out-style subscriber pattern Soma already
  established.
- Add `[chronos]` block to `config/kaine.toml` and a `modules.chronos = false`
  flag so first boot remains operator-supervised.
- Tests inject fake featurizers / detectors / CfC networks so the suite
  stays portable and fast.

## Capabilities

### New Capabilities

- `chronos`: temporal-flow perception. Owns the CfC-driven temporal
  context vector, anomaly detection (rolling z-score over hidden state
  norms), rumination detection (hidden-state-bucket recurrence),
  habituation signal (inverse novelty over hidden states), and the
  `time_since_last_interaction_s` clock against configured user-input
  sources.

### Modified Capabilities

None — Chronos is purely additive.

## Impact

- **Depends on:** `event-bus`, `cognitive-cycle`, `module-pattern`,
  `dynamic-hardware`. All shipped.
- **Repo:** adds `kaine/modules/chronos/*.py`, `tests/test_chronos_*`,
  updates `pyproject.toml` (packages list), `config/kaine.toml`,
  `DEPENDENCIES.md` (ncps role updated to "in use by Chronos").
- **Compute:** Chronos pins to CPU. CfC at default units=32 with a
  ~24-dim feature vector → roughly 3K params. Negligible.
- **No runtime impact** on the cycle itself. Chronos is registered in
  code paths but not auto-added to the registry; first boot decides.
