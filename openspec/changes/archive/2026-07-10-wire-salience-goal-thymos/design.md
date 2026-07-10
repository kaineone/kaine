# Design — Wire goal and Thymos factors into live salience

> **Design-of-record only.** Plan, not implementation.

## 1. Problem restated

Operative salience is `intensity × novelty × 1.0 × 1.0`. The paper's selection
criterion depends on the affective (`thymos`) and goal factors to bias what
reaches the workspace. The affective factor's implementation already exists
(`StateModulator`); it is unwired. The goal factor has no implementation.

## 2. The Thymos factor (reconnect existing code)

`StateModulator` weights an event's salience by current arousal (and, per its
own logic, valence). Thymos already instantiates it. The design question is
**how Syneidesis reads current affect without breaking the import boundary**
(`architecture-boundaries` spec; enforced by import-linter).

Two admissible sources, in order of preference:

- **A. Broadcast-carried affect (preferred).** The workspace snapshot already
  contains an `affect-state summary` (paper §3.2; produced each broadcast). The
  salience strategy can read the last-known affect summary the engine already has
  in hand at scoring time, so the Thymos factor is a pure function of state the
  cycle already holds. No new cross-module import.
- **B. Injected modulator callable.** Construct `StateModulator` at cycle-assembly
  time (`kaine/cycle/__main__.py`) and inject it into `RuleBasedSalience` the same
  way `NoveltyTracker` is injected today, fed by an affect-state provider the
  engine updates on each `thymos.out`. Keeps the boundary clean via dependency
  injection rather than import.

Recommendation: **B for wiring, A for the value source** — inject the real
modulator, feed it from the affect summary the engine already tracks. Avoids both
a boundary violation and a second source of truth for affect.

## 3. The goal factor (new)

No goal scorer exists. The paper grounds goals as "preferred interoceptive
states" entering appraisal (§3.4.3), and drives (curiosity, boredom, social
engagement, restlessness) accumulate in Thymos. A defensible first goal scorer:
score an event's relevance to the currently-dominant drive(s) and to any active
preferred-state set, returning a bounded multiplier around 1.0.

Honesty requirement: the paper does not fully specify the goal function. Whatever
mapping is chosen is an **engineering extension**, and must be labeled as such in
this design and at the source site, exactly as the codebase labels the
affect-intensity consolidation extension and the single precision-weighted scalar.
Do not overstate it in the paper.

Open question for the operator (resolve before implementation): should the goal
factor ship **active** in the default four-factor product from day one, or ship
behind a flag (real Thymos factor on, goal factor static 1.0) until the goal
mapping has been validated against logged runs? Shipping the goal factor active
changes what reaches the workspace and therefore the research baseline; a staged
rollout (Thymos factor first, goal factor second) is the more conservative path
and is recommended unless the operator wants both at once.

## 4. Determinism and observer invariants

- Salience must remain a pure function of `(event, affect_state, goal_state)`; no
  wall-clock, no RNG. This preserves the deterministic-cycle and canonical-re-sort
  guarantees (`engine.py` re-sort, `syneidesis.py` `sorted(...)`).
- No new bus publication and no read-back into the loop; the factors are computed
  inline during selection, as the two existing factors are.
- The static placeholders stay in-tree as a dev-only fallback so the negative
  control ("two-factor / unweighted") remains runnable for comparison.

## 5. Config

New `[syneidesis]` keys (STAGED rollout — see §3):
`salience_thymos_factor = "state_modulator"` (ships real; `"static"` = dev
fallback / negative control), and `salience_goal_factor = "static"` (ships on the
staged static baseline; `"drive_relevance"` activates the real scorer once
validated). Document the fallback and the warning behavior at the config site.
The degraded-mode warning fires only on a deliberate downgrade from a factor's
shipped default (so the shipped Thymos-real + goal-static defaults are silent; an
informational boot note MAY announce the staged goal factor).

## 6. Validation

- Unit: the real Thymos modulator changes an event's score / threshold-crossing
  vs. static under a scripted affect state (the Thymos factor is a uniform
  per-tick scalar, so it shifts scores and inclusion, not the relative order of
  simultaneously-scored events); the real goal factor changes ranking between
  equal-intensity/novelty events by drive relevance; the static fallback
  reproduces today's two-factor selection bit-for-bit (negative control
  preserved).
- Determinism: same seed + same scripted affect ⇒ identical selection.
- Boundary: import-linter still passes (no new disallowed import).
