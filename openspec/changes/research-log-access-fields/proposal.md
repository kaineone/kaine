## Why

The planned test of workspace mediation (paper §6.3) reads, per report, the
processor's alert flag, its information gain from the broadcast
(`context_gain`) and the context's age, and, per broadcast, the access
threshold. The curated research log copies only allowlisted fields, and none
of these are on the list. Audition's acoustic report, `audition.perception`,
the base-thesis hearing path, is not logged at all, and the prediction-error
observer does not read it either.

## What Changes

- Research-log taxonomy: `topos.report` and `soma.report` gain `alert`,
  `context_gain` and `context_age_s` (Soma gains `alert`; Topos already has
  it); `chronos.report` gains `alert`; `audition.perception` is added with its
  numeric fields (`prediction_error`, `normalised_error`, `change_score`,
  `energy_dbfs`, `attended_window`, `attended_seconds`, `alert`,
  `context_gain`, `context_age_s`); `thymos.drive`, `thymos.emotion` and
  `hypnos.sleep.completed` gain `alert`.
- The workspace record copies `access_threshold` from the broadcast metadata
  and the broadcast's `published_at` when present.
- The prediction-error observer reads `audition.perception`.
- The playlist item title on `audition.perception` is not logged.

## Capabilities

### Modified Capabilities

- `research-event-log`: the log carries the fields the planned test reads.

## Impact

- `kaine/evaluation/observers/research_event_observer.py`,
  `kaine/evaluation/observers/prediction_error_observer.py`, tests. All new
  fields are numbers or booleans.
