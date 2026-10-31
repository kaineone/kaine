# Tasks

## 1. Design (this change)

- [x] 1.1 Record the learned bar, the choice rule, the habit stage, the excluded paths and the records (proposal, design, specs).
- [x] 1.2 Cite prior work: the report rule (`self-initiated-report`), the policy wrappers (`nous-drives-action`), the bounded learned bias precedent (`interest-goal-factor`), the learner (`drive-reduction-learning`).

## 2. Before any code (gate)

- [ ] 2.1 The workspace-mediation ablation has run.
- [ ] 2.2 `drive-reduction-learning` stage A merged and its replay check passed.
- [ ] 2.3 Paper change settled: §3.3 and A.6 learned option, Table A1 values for `b_max`, `N_0`, `A_scale`, `m_theta`, `tau`, `alpha_H`.

## 3. Learned bars and choice

- [ ] 3.1 `learned_report` policy sharing the guard code with `SelfInitiatedReportPolicy`; `[action_selection.learned]` config and validator (interrupt bar above `theta_sp0 + b_max`). Tests: `tests/test_learned_report_bars.py`, `tests/test_learned_report_guards.py`, `tests/test_learned_report_config.py`, with mutation checks on the evidence weight and the floor.
- [ ] 3.2 Values provider refreshed from `valuation.values`; seeded choice. Tests: `tests/test_learned_report_choice.py` (empty tables reproduce the fixed policy on a recorded stream, seeded runs repeat).
- [ ] 3.3 Offline replay: fixed versus learned policy on recorded broadcast streams with tables learned offline; per-kind rate ratios recorded under `docs/records/`. Test: `tests/test_learned_report_replay.py` on a synthetic stream.
- [ ] 3.4 Excluded paths: `tests/test_learned_report_excluded_paths.py` (regulation rest, planning rest, developmental rest, operator response, welfare freeze identical under both policies).

## 4. Habit stage

- [ ] 4.1 Habit table in the valuation module, persisted and copied into a fork; arbitration by inverse uncertainty. Tests: `tests/test_valuation_habit_table.py`, `tests/test_learned_report_habit_arbitration.py`.
- [ ] 4.2 Perseveration check: on a synthetic stream whose relief contingency reverses halfway, the habit-on policy's selections follow the reversal within a bound fixed before the run. Recorded under `docs/records/`.

## 5. Docs and checks

- [ ] 5.1 `docs/08-cognitive-cycle/global-workspace.md` (report rule), `docs/09-modules/valuation.md`, `docs/appendix-a-configuration/core.md` rows.
- [ ] 5.2 One supervised validation boot on a branch before any study use.
- [ ] 5.3 `openspec validate learned-action-selection --strict` passes.
