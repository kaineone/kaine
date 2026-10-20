## 1. Implementation

- [x] 1.1 `InterestGoalScorer` in `kaine/workspace/strategies.py`; the salience product clips only the priority
- [x] 1.2 `AffectStateProvider` folds per-source learning progress; `make_salience_factors` builds the interest scorer with `[workspace].interest_gain` and `[affect].learning_progress_floor`; the cycle refreshes the provider for it
- [x] 1.3 Config: `interest_gain` in `config/kaine.toml`, `salience_goal_factor = "interest"` in the first-configuration profile
- [x] 1.4 Tests: G is exactly 1 with no interest and for non-perceptual sources, the formula and floor, priority-only clipping, static and drive-relevance unchanged, the profile selects the factor, the provider is refreshed
- [x] 1.5 Docs: global workspace, affect module, configuration reference, glossary
- [x] 1.6 Counterfactual replay of the ninth boot on the shipped scorer matches the simulation
