## 1. Welfare producer
- [ ] 1.1 The cycle builds and starts `WelfareObserver` when `[preservation.welfare_response].enabled`, with `[evaluation.welfare]` thresholds and the `data/evaluation/welfare` sink, and stops it on shutdown.
- [ ] 1.2 `SidecarRegistry` accepts an externally owned welfare observer, exposes it as `welfare_observer`, and does not build one of its own in that case.
- [ ] 1.3 Tests: evaluation off and welfare response on publishes `welfare.gray_zone` and arm 2 receives it; both on runs exactly one producer (one event per condition); welfare response off and evaluation on behaves as before.

## 2. Study overlay
- [ ] 2.1 `build_overlay` sets `[evaluation].enabled = false` for every step.
- [ ] 2.2 Test: an operator config with evaluation on is overridden on every step; ignition log, research event log, external utterances and preservation monitors stay on.

## 3. Docs
- [ ] 3.1 Ignition-study chapter: a study runs no evaluation observers; the welfare net is unaffected.
- [ ] 3.2 Preservation chapter (welfare response): the gray-zone producer runs with the welfare response, independent of evaluation.
