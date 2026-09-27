## 1. Fixtures

- [ ] 1.1 `scripts/record_nous_golden.py` and the committed fixtures (live learning trajectory, benchmark task EFE, horizon 2).

## 2. Engine

- [ ] 2.1 A shared timeout and generation base for both engines.
- [ ] 2.2 `NumpyActiveInferenceEngine`: FPI, policy enumeration, EFE (utility, state and parameter information gain), learning, carried prior, cap, fixed action factor, learned-state interchange.
- [ ] 2.3 `[nous].backend`; extras, health probe, install planner and edge profiles are backend-aware.

## 3. Verification and docs

- [ ] 3.1 Parity tests against the fixtures (no JAX needed), a JAX-blocked subprocess test, cross-engine learned-state interchange, and the latency budget.
- [ ] 3.2 Docs: the Nous module page, configuration, deployment tiers.
- [ ] 3.3 Offline suite green; `openspec validate numpy-nous-engine --strict`.
