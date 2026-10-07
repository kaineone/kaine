## 1. Specs
- [ ] 1.1 `inference-backend` delta (scope of the single-server requirement) and `abliterated-organ` delta (K1-Jev is not the organ); `decision-model` delta (server and client).

## 2. Client
- [x] 2.1 `kaine/decision/client.py` per the design.
- [x] 2.2 Tests against a REAL local HTTP server serving canned `/v1/systemone` responses:
  - request shape;
  - the bearer key sent;
  - parsing of each type;
  - thresholds applied;
  - digest mismatch refused;
  - every failure kind returns `None`;
  - nothing content-bearing in the logs.

## 2b. Residency and the sleep window
- [ ] 2.3 Register the `decision` organ and its rungs in the rung and footprint catalogues and the fit report (`kaine/residency`); the tier profiles' decision rung goes through the integrator (shared files).
- [ ] 2.4 Test that an organ window (`run_with_organ_window`) stops only the organ service and never the decision server, and that the client keeps answering (against a real local fake server) while the window is open.

## 3. Shared files (integrator)
- [ ] 3.1 `[decision]` in `config/kaine.toml` (shipped `enabled = false`), and its config-appendix rows.
- [x] 3.2 `kaine.decision` in the boundary-neutral import-linter contract.
- [ ] 3.3 The `kaine-decision-model` compose and quadlet service, started only with an entity when enabled.

## 4. Acceptance on the real path
- [ ] 4.1 With the exported K1-Jev GGUF on the pinned build: start the service, have the client ask all 14 questions about 20 dev items, and compare with `/completion`-based letter probabilities (the C1 parity check). Then stop the service.

## 5. Docs
- [ ] 5.1 Deployment chapter: the decision server, its lifecycle and its key.
