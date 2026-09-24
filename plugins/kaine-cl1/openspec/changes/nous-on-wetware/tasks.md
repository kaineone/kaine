## 1. Backend

- [ ] 1.1 Implement `WetwareActiveInference` satisfying Nous' generative-model
      client interface, in `kaine_cl1/backends/nous.py`.
- [ ] 1.2 Encoder: belief-over-states vector → population code; observations →
      evidence stim.
- [ ] 1.3 Decoder: sub-population firing balance → selected policy; entropy/
      criticality → expected-free-energy proxy.
- [ ] 1.4 Closed-loop coupling: chosen policy conditions the next tick's stim
      (the substrate participates in the inference loop, not just read-out).

## 2. Wiring & gating

- [ ] 2.1 `[backends].nous = "cl1"` ⇒ construct stock `Nous`, inject the backend,
      allocate a Nous territory from the remaining budget.
- [ ] 2.2 Keep default `"silicon"` until §3.3 passes.

## 3. Acceptance (simulator)

- [ ] 3.1 `nous.out` schema-equality between `cl1` and silicon.
- [ ] 3.2 Runs within the ~300 ms cognitive tick budget (or via the non-blocking
      background aggregate).
- [ ] 3.3 **Decode-reliability gate:** on a fixed generative model, decoded policy
      selection agrees with the intended argmin-EFG choice above a stated
      threshold across seeds; below threshold the backend stays disabled.
- [ ] 3.4 Benchmark against KAINE's `active-inference-benchmark` (vs the RL
      baseline) and report whether the biological loop does predictive work.
- [ ] 3.5 `openspec validate nous-on-wetware --strict` passes.
