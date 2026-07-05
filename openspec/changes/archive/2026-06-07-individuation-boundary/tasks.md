## 1. Preference battery

- [x] 1.1 `kaine/evaluation/preference_battery.py` — default preference-elicitation prompts; loadable from `battery_path` for operator extension

## 2. Individuation test

- [x] 2.1 `kaine/evaluation/individuation.py` — `IndividuationTest`: build parent-vs-parent null over `null_samples` varied seeds; compute fork-vs-parent divergence (reuse A/B embedding metric); permutation test vs `significance_percentile`
- [x] 2.2 Emit an evidence report (JSONL + summary): divergence, p-value, null summary, significant flag

## 3. Config

- [x] 3.1 `[evaluation.individuation]`: `null_samples`, `significance_percentile`, `metric`, `battery_path`

## 4. Tests

- [x] 4.1 `tests/test_individuation.py` — identical-to-parent fork is NOT significant; a clearly divergent fork exceeds the 95th percentile; report shape; deterministic with fixed seeds
- [x] 4.2 Edge cases: empty battery rejected; null with zero variance handled

## 5. Verification

- [x] 5.1 Full unit suite green
- [x] 5.2 `openspec validate individuation-boundary --strict` clean
- [x] 5.3 Commit (Kaine.One), branch-per-change, merge, archive
