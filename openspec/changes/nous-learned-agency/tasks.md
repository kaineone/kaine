## 1. Model and engine

- [ ] 1.1 Action-dependent B for the perceptual factors with the persistence prior; `pB` from `[nous]` persistence and concentration.
- [ ] 1.2 Engine: parameter information gain, B learning after each step, carried prior; timeout and error paths unchanged.
- [ ] 1.3 Serialize and deserialize `pB`, the carried prior and the last action; older snapshots start from the prior.

## 2. Verification and docs

- [ ] 2.1 Tests: golden action diversity, learning in a synthetic loop, carried prior, preservation round trip, benchmark bars, ≤200 ms median.
- [ ] 2.2 Docs: the Nous module page, configuration, and a note for the ignition study.
- [ ] 2.3 Offline suite green; `openspec validate nous-learned-agency --strict`.
