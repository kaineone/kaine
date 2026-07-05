## ADDED Requirements

### Requirement: The self-model accuracy scorer is calibrated against known signals

The self-model (Eidolon) accuracy scorer SHALL compute the documented accuracy
when given known planted evaluation signals, and this calibration MUST be covered
by a test that plants controlled signal logs and asserts exact scores. Given a
planted signal that supports a claim's mapped signal key, `_score_claim` MUST
return `1.0`; given a planted signal that contradicts it, `_score_claim` MUST
return `0.0`; and the `run_once` aggregate MUST equal the arithmetic mean of the
scored (non-None) claims. The calibration validates scorer correctness only, not
self-model quality (the scorer matches trait keywords against currently derived
signals, not predicted-vs-actual next state).

#### Scenario: High-signal claim scores 1.0

- **WHEN** an `affect_correlation` log is planted with an average valence above
  the documented `valence_high` threshold and the scorer is run against a claim
  that maps to `valence_high`
- **THEN** `_signals_snapshot` reports `valence_high = 1.0`
- **AND** `_score_claim` returns `1.0` for that claim

#### Scenario: Low-signal claim scores 0.0

- **WHEN** the same high-valence signal is planted and the scorer is run against a
  claim that maps to a signal the plant contradicts (e.g. `valence_low`)
- **THEN** `_score_claim` returns `0.0` for that claim

#### Scenario: Aggregate is the mean of scored claims

- **WHEN** a self-description with several scoreable claims is run against planted
  signals that support some claims and contradict others
- **THEN** the `run_once` record's `aggregate_accuracy` equals the arithmetic mean
  of the scored (non-None) claim values
