# Tasks

## 1. Design (this change)

- [x] 1.1 Record the deficit factor, derived preferences, horizon, imagination, sleep-span rule and benchmark (proposal, design, specs).
- [x] 1.2 Cite prior work: `honest-planning-and-training`, `numpy-nous-engine`, `nous-learned-agency`, `nous-drives-action`, `planning-act-proposals`, `world-model-action-outcomes`.

## 2. Before any code (gate)

- [ ] 2.1 The module-addition study's first round has finished (its planning branch ran model version 1).
- [ ] 2.2 Paper change settled: §4 row and paragraph, §9 and §10 lines, Table A1 (`H`, `kappa`, `w_im`, `p_min`, `Delta_G`), the open items of the design.

## 3. Model version 2

- [ ] 3.1 Deficit factor, modality and encoding from `affect.state`; envelope check. Tests: `tests/test_planning_deficit_factor.py`, golden fixtures regenerated for both engines in `tests/test_numpy_planning_engine.py`.
- [ ] 3.2 Derived preferences with the code-site citation; salience preference removed in version 2 only. Tests: `tests/test_planning_derived_preferences.py`, with a mutation check that restoring the salience preference fails.
- [ ] 3.3 Sleep-span rule. Tests: `tests/test_planning_sleep_span.py`.
- [ ] 3.4 Horizon 3 shipped for version 2; latency benchmark at the new envelope; proposal-rate replay on recorded streams recorded under `docs/records/`. Tests: `tests/test_planning_horizon3.py`.
- [ ] 3.5 Learned-state migration from version 1. Tests: `tests/test_planning_state_migration.py` (existing counts kept, deficit factor at prior, log line).

## 4. Benchmark

- [ ] 4.1 Deficit-relief task, matched Q-learning baseline and horizon ablation in `kaine/evaluation/benchmarks/active_inference/`. Tests: `tests/test_ai_benchmark_deficit_task.py`.

## 5. After dependencies

- [ ] 5.1 After `world-model-action-outcomes`: imagined transitions at weight `w_im` in the scenario window. Tests: `tests/test_planning_imagined_transitions.py`, including the contradicting-lived-experience check.
- [ ] 5.2 After `planning-act-proposals`: pruned sophisticated inference in both engines with parity fixtures and the pruned-branch count. Tests: `tests/test_planning_sophisticated_inference.py`, `tests/test_numpy_planning_engine.py`.

## 6. Docs and checks

- [ ] 6.1 `docs/09-modules/planning.md` (version 2, horizon, preferences and their basis, what "planning" covers).
- [ ] 6.2 One supervised validation boot on a branch before study use.
- [ ] 6.3 `openspec validate multi-step-planning --strict` passes.
