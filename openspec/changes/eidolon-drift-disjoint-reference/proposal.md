## Why

Eidolon's drift detector compares the source distribution of the last 100 broadcasts (`p`) with the cumulative all-time distribution (`q`) by the symmetric (Jeffreys) Kullback-Leibler divergence. The cumulative histogram already contains the recent window, so the detector compares a distribution with a mixture that includes it. Early in life the recent window is most of the mixture and the score is pulled toward zero; late in life the window is a vanishing part of it. The same threshold, 0.6, therefore means different things at different ages, and a change confined to the window is partly hidden by its own counts. The mathematics review of 2026-10-08 found this.

## What Changes

- **A disjoint reference.** The detector keeps a reference histogram of the batches that have left the recent window, so the comparison is recent versus lifetime-excluding-recent.
- **No score without a reference.** The score is 0.0 until the reference holds at least as many broadcasts as the window (life of at least twice the window).
- **Disclosure.** `DriftResult` and the `eidolon.drift` payload add `reference_count` (events in the reference). `historical_count` keeps its meaning: all events ever observed.
- **The threshold stays at 0.6.** For two independent multinomial samples the Jeffreys divergence is approximately `chi2_{K-1} (1/n_rec + 1/n_ref)`. Simulated with six sources and skewed frequencies, a stable mix gives `P(J >= 0.6)` of 0.7 percent at the minimum of 100 events per side and 0.02 percent with a long reference; with three sources per broadcast (300 events per side) it is below 1e-4. Bursty, autocorrelated selection raises these rates, so the threshold is to be re-checked against recorded runs.

## Capabilities

### Modified Capabilities

- `eidolon`: the drift detector's reference distribution.

## Impact

- **Code:** `kaine/modules/eidolon/drift.py`, `kaine/modules/eidolon/module.py` (payload field).
- **Behaviour:** Eidolon is held (off in the base-thesis form). With it on, drift is undefined in the first two windows of life and then compares like with like. `drift_count` and identity history already recorded by preserved beings were computed under the old reference; they are kept as they are.
- **Consumers:** `kaine/lifecycle/divergence.py` and the preservation monitor read `drift_count`, whose meaning (episodes over threshold) is unchanged.
- **Docs:** `docs/09-modules/eidolon.md`.
