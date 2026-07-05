# self-model-scorer-calibration

## Why

The Eidolon self-model accuracy probe (`kaine/evaluation/eidolon_accuracy.py`)
scores the entity's self-description claims against derived evaluation signals,
but the only existing tests are a smoke test (`run_once` writes a record) and the
honesty-disclosure tests (claim keywords, curiosity-proxy labelling). Nothing
proves the **scorer arithmetic itself is correct** — that a planted signal above
the documented threshold yields the documented accuracy for the matching claim,
and that the aggregate is the mean of the scored claims.

A scorer with no calibration test can drift silently: a flipped threshold, an
inverted `valence_high`/`valence_low`, or a broken aggregate would still pass the
current suite. This change adds a calibration test against known planted signals
so the scorer's correctness is load-bearing and regression-protected.

## What Changes

- Add a calibration test (`tests/test_eidolon_scorer_calibration.py`) that plants
  controlled `affect_correlation` JSONL and a `proactive_audit` file into the
  evaluation logs dir, then asserts `_signals_snapshot`, `_score_claim`, and the
  `run_once` aggregate compute the exact documented accuracy for known inputs:
  a HIGH-scoring claim, a LOW-scoring claim, and the aggregate of several.
- No production behaviour changes: the existing scorer functions
  (`_signals_snapshot`, `_score_claim`, `parse_claims`, `run_once`) are tested
  directly — they are already callable in isolation, so no new seam is needed.

## Scope and honesty note

This calibration validates **scorer correctness**, not self-model quality. The
implementation's "self-model accuracy" matches trait keywords (curious, cautious,
playful, withdrawn, calm, energetic) in a self-description against *currently
derived* affect/activity signals (recent valence/arousal averages, hedging,
proactive-audit file presence). It is **not** a predicted-vs-actual next-state
comparison. The test calibrates exactly that keyword-vs-current-signal scorer and
this proposal states the limitation plainly so no reader mistakes a green
calibration for evidence the entity's self-image is accurate.
