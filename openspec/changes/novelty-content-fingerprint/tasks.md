## 1. Measure (no entity boot)

- [ ] 1.1 `scripts/measure_novelty.py`: an offline replay of the seeded feed through the real Topos, Audition, Soma and Chronos modules on a fake in-memory bus. It reports per-source novelty under the current fingerprint and under candidate content fingerprints, plus per-field value statistics. Bounded runtime, CPU only.
- [ ] 1.2 Record the results under `docs/records/` with the chosen rule and its justification.

## 2. Content fingerprint

- [ ] 2.1 `fingerprint()` hashes source, type and the vector-stripped, quantised payload under the rule from 1.2.
- [ ] 2.2 Tests:
  - the spec scenarios still pass (first sighting scores 1.0, repeats habituate);
  - two perceptual reports that differ only by small float noise share a fingerprint;
  - a change in a categorical field, or a marked scene change, does not;
  - a payload whose vectors differ but whose content is the same shares a fingerprint.

  Mutation-check each one.
- [ ] 2.3 Re-run the measurement with the new fingerprint and add the result to the record.

## 3. Paper and docs

- [ ] 3.1 Paper revision note in the paper repository's `REVISION-NOTES.md`.
- [ ] 3.2 `docs/` describes the novelty fingerprint.
- [ ] 3.3 `openspec validate novelty-content-fingerprint --strict`.
