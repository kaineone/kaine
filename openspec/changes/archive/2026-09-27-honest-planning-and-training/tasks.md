## 1. Nous

- [x] 1.1 Per-action EFE as the best policy starting with that action; action = first action of the best policy; `nous.policy` reports the configured horizon.

## 2. Phantasia

- [x] 2.1 `TrainOutcome.learned`; DreamerV3 sets it after a successful update, the fake world model never; only learned passes count and trigger the post-train save.

## 3. Verification

- [x] 3.1 Tests: horizon-2 EFE aggregation on a model where the best two-step plan starts with a non-first action; the fake backend never increments the count; DreamerV3 does (skip without JAX).
- [x] 3.2 Offline suite green; `openspec validate honest-planning-and-training --strict`.
