## RENAMED Requirements

- FROM: `### Requirement: The self-model accuracy scorer is calibrated against known signals`
- TO: `### Requirement: The self-model accuracy scorer is a fixed-threshold heuristic behaving as specified`

## MODIFIED Requirements

### Requirement: The self-model accuracy scorer is a fixed-threshold heuristic behaving as specified

The self-model (Eidolon) accuracy scorer SHALL behave as a **fixed-threshold
heuristic** — NOT a calibrated instrument: it matches trait keywords against
currently derived signals and cuts each derived signal at FIXED, hand-chosen
thresholds that are NOT fitted against a labelled set. It SHALL compute the
documented score when given known planted evaluation signals, and this behaviour
MUST be covered by a test that plants controlled signal logs and asserts exact
scores. Given a planted signal that supports a claim's mapped signal key,
`_score_claim` MUST return `1.0`; given a planted signal that contradicts it,
`_score_claim` MUST return `0.0`.

The scorer MUST distinguish "no evidence" from "wrong": a claim whose mapped signal
is unavailable scores `None` (excluded from the aggregate). When at least one claim
is scorable, the `run_once` aggregate MUST equal the arithmetic mean of the scored
(non-None) claims; when NO claim is scorable, the aggregate MUST be `None`, NOT
`0.0` — so an unscoreable run never masquerades as a maximally-wrong self-model.

This validates scorer correctness only — the behaviour of a fixed-threshold
heuristic — NOT calibration and NOT self-model quality (the scorer matches trait
keywords against currently derived signals, not predicted-vs-actual next state).

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

#### Scenario: No scorable claim is not-scorable (None), not wrong (0.0)

- **WHEN** a self-description carries trait claims but NO mapped signal is available
  (e.g. a fresh boot with no planted signals), so every claim scores `None`
- **THEN** the `run_once` record's `aggregate_accuracy` is `None` ("no evidence"),
  NOT `0.0`
- **AND** the record's `scorable_claims` count is `0`
