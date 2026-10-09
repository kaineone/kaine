## 1. Precision-weighted bottom-up saliency

- [x] 1.1 `SpatialSaliency` keeps per-tile EMA mean and variance of the change and returns `max(0, d - mu) / sqrt(v + s0^2)` against the prior statistics, raw change for the first five observations.

## 2. Real clips

- [x] 2.1 `Topos.process_frame`: with foveation on, derive peripheral and foveal views from every buffered frame at the fovea chosen on the latest frame, and encode those clips.

## 3. Tests, docs

- [x] 3.1 Tests: a constantly flickering tile loses to a stable tile with a smaller but unusual change once the statistics have warmed; raw change during the first five observations; the clip passed to the encoder holds distinct frames; mutation-check.
- [x] 3.2 Docs: `docs/09-modules/topos.md`.
- [x] 3.3 `openspec validate topos-tile-precision-real-clips --strict`.
