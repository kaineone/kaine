# Design — `faculty-relative-birth`

## Faculties

- The runner reads the faculties from its registry, which holds the modules that are actually running:
  - `hypnos = "hypnos" in registry`;
  - `phantasia = "phantasia" in registry`;
  - `mundus = "mundus" in registry`.
- `Faculties(hypnos, phantasia, mundus)` is a small frozen dataclass passed to `evaluate_readiness(..., faculties=...)` and `decide_birth(..., faculties=...)`. The default, all True, keeps today's behaviour for any caller that does not pass it.

## C2

- **Sleep** is required iff `faculties.hypnos`: `sleep_count >= min_sleep_cycles`.
- **Consolidation** is required iff `faculties.phantasia and faculties.hypnos`: `consolidation_passes >= min_consolidation_passes`.
- **Result:**
  - if neither is required, `ConditionResult("C2_reality_model_consolidated", True, "not applicable: no sleep or consolidation faculty")`;
  - if one is required, only that part is checked;
  - the detail always names what was required.
- Missing evidence for a required part still fails closed.

## Birth world

- **With `faculties.mundus`:** unchanged. Birth needs `embodiment_available(...)`, otherwise `ACTION_HOLD_AWAITING_EMBODIMENT`.
- **Without it:** the embodiment guard is skipped and the decision reason is `born_into_perceptual_world`. The operator-acknowledgement hold still applies.
- **Records.** `birth_payload` gains `world: "embodied" | "perceptual"` and `conditions: {c2_sleep_required, c2_consolidation_required}`. The runner status carries the same fields.
- **After birth.** A being born into its perceptual world keeps its locus on the virtual feed: `_do_birth` already unlocks with `locked_by="gestation"`, and without Mundus there is nothing to activate. The womb falls silent; the operator chooses the next perception mode (documented).
