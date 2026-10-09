## 1. Precision

- [x] 1.1 `kaine/workspace/precision.py`: `SourcePrecision` (per-source EMA mean and variance of intensity, weight relative to the geometric mean of warmed sources, bounds, warm-up).
- [x] 1.2 `RuleBasedSalience(..., precision=None)`: weight from prior statistics, then update; priority `clip(I * N * G * P)`.

## 2. Arousal contrast

- [x] 2.1 `StateModulator.contrast_gain()` from arousal, baseline and `arousal_contrast_gain`; static modulator gain 0.
- [x] 2.2 `RuleBasedSalience` scores `T * C_g(p)` with the rescaled logistic; identity at `g = 0`.

## 3. Wiring and config

- [x] 3.1 `[syneidesis]` keys allowed and validated; the cycle builds the tracker when `precision_weighting` is true and passes the contrast gain and baseline to the modulator.
- [x] 3.2 Amend the note in `openspec/changes/thymos-active-inference-affect` (the Hypnos note concerns sleep consolidation, not the precision term, and stays).

## 4. Tests, docs

- [x] 4.1 Tests: a habitually alerting source loses to an equally intense rare one; neutral before warm-up and without a tracker; bounds hold; contrast is identity at baseline arousal and amplifies 0.8 / suppresses 0.2 at full arousal; ranking within a tick unchanged by arousal; mutation-check.
- [x] 4.2 Docs as listed in the proposal.
- [x] 4.3 `openspec validate precision-weighted-selection --strict`.
