# Tasks — Wire goal and Thymos factors into live salience

> Implemented on `feat/wire-salience-goal-thymos`. Rollout is STAGED: the Thymos
> factor ships LIVE (real `StateModulator`); the goal factor is BUILT but ships
> on the static baseline pending validation.

## 0 — Guardrails
- [x] 0.1 Confirm approval and the §3 rollout decision (STAGED: Thymos live,
      goal built-but-static by default).
- [x] 0.2 Re-read `design.md` §4: salience stays a pure function; no new bus
      writes; static fallback preserved as the negative control.

## 1 — Thymos factor (reconnect `StateModulator`)
- [x] 1.1 Add an affect-state provider the engine updates on each `thymos.out`
      (`kaine/cycle/affect_state.py` `AffectStateProvider`; engine hook in
      `kaine/cycle/engine.py`).
- [x] 1.2 Inject a real `StateModulator` into `RuleBasedSalience` at cycle assembly
      (`make_salience_factors` in `kaine/boot.py`, called from
      `kaine/cycle/__main__.py`) — dependency injection, no cross-module import
      (import-linter contract added).
- [x] 1.3 Behind `[syneidesis].salience_thymos_factor` (default `state_modulator`;
      `static` = dev fallback).

## 2 — Goal factor (new scorer)
- [x] 2.1 Implement a drive-relevance goal scorer grounded in paper §3.4.3
      (`DriveRelevanceGoalScorer` in `kaine/workspace/strategies.py`), bounded
      around 1.0.
- [x] 2.2 Label it an engineering extension in a source-site comment citing §3.4.3.
- [x] 2.3 Behind `[syneidesis].salience_goal_factor` (default `static` per the
      STAGED decision; `drive_relevance` selects the real scorer).

## 3 — Strategy + warning
- [x] 3.1 `RuleBasedSalience` computes the full `intensity × novelty × goal × thymos`
      product when real factors are selected.
- [x] 3.2 Warning fires only on a deliberate downgrade from a factor's shipped
      default (`downgraded_factors`, computed in `make_salience_factors`); shipped
      defaults are silent, an INFO note announces the staged goal factor.
- [x] 3.3 Re-labeled the static scorers as "dev-only fallback / negative control."

## 4 — Config + docs
- [x] 4.1 Add the two `[syneidesis]` keys to `config/kaine.toml` with fallback docs.
- [x] 4.2 Note in `docs/processes/global-workspace.md` that live salience is the
      four-factor product (Thymos live, goal available-but-staged/unvalidated);
      document the new workspace ⊥ modules boundary in `docs/architecture-boundaries.md`.

## 5 — Tests
- [x] 5.1 Real modulator changes score / threshold-crossing vs. static under a
      scripted affect state; real goal factor re-ranks drive-relevant events.
- [x] 5.2 Static fallback reproduces the two-factor selection bit-for-bit.
- [x] 5.3 Determinism: same events + scripted affect ⇒ identical selection.
- [x] 5.4 import-linter passes (5 contracts, incl. the new workspace ⊥ modules one).
- [x] 5.5 Integration seam: engine calls the affect observer before select with
      the sorted batch and swallows observer exceptions; `make_salience_factors`
      selection + validation covered.
