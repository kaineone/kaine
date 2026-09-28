## 1. Fixtures

- [x] 1.1 `scripts/record_phantasia_golden.py` and committed fixtures from the JAX core: deterministic forward outputs, loss and full gradients (categorical and Gaussian; free bits active and inactive; sequence lengths 1 and 16), and a five-step `sgd_update` trajectory.

## 2. Engine

- [ ] 2.1 `kaine/modules/phantasia/rssm_numpy.py`: forward pieces, loss, hand-written backpropagation through time, `sgd_update` with the non-finite guards, `rollout`, NumPy initialisation.
- [ ] 2.2 A shared checkpoint codec in `world_model.py`; `NumpyDreamerV3WorldModel`; `load_world_model` engine selection.
- [ ] 2.3 `[phantasia].engine` through boot; `engine` on every `phantasia.*` event; extras, install planner and Tier 1 profile are engine-aware.

## 3. Verification and docs

- [ ] 3.1 Parity tests against the fixtures (no JAX needed), finite-difference gradient checks, checkpoint interchange in both directions, a JAX-blocked subprocess test, and the latency budget.
- [ ] 3.2 Docs: the Phantasia module page, configuration, deployment tiers.
- [ ] 3.3 Offline suite green; `openspec validate numpy-phantasia-engine --strict`.
