# Tasks

## 1. Design (this change)

- [x] 1.1 Record the learner, its relief signal, value function, exclusions, persistence and stages (proposal, design, specs).
- [x] 1.2 Cite prior work: the credit rule (`welfare-crossing-deprivation`, `boredom-own-engagement`), the goal likelihood (`affect` spec, "Unanswered responses obstruct the dominant drive's goal"), the planning module's transition learning (`nous-learned-agency`).

## 2. Before any code (gate)

- [ ] 2.1 The workspace-mediation ablation has run. Reason: the change adds a module whose later stages alter what competes.
- [ ] 2.2 Paper change settled: §4 valuation row, A.4 relief and value definitions, Table A1 values for `alpha`, `Delta_v`, `n`, `m`, `n_min`.

## 3. Stage A (shadow)

- [ ] 3.1 `affect.state` gains `drive_no_response`. Tests: `tests/test_affect_state_no_response.py` (no-response interval equals actual; an intent's relief shows as the gap; drive values bit-identical to the current build on a recorded stream). Opus second review.
- [ ] 3.2 `kaine/modules/valuation/`: eligibility traces, outcome table, value function, exclusions, `valuation.values`; `[valuation]` config with validator; factory. Tests: `tests/test_valuation_traces.py`, `tests/test_valuation_outcome_table.py`, `tests/test_valuation_value_function.py`, `tests/test_valuation_exclusions.py`, `tests/test_valuation_config.py`, with mutation checks on the split, the baseline and the discard rule.
- [ ] 3.3 Offline replay check on recorded test-boot streams: the learned restlessness and engagement advantages of speak and think recover the authored reliefs within tolerance, and every other advantage stays within its uncertainty of zero. Recorded under `docs/records/`. Test: `tests/test_valuation_replay_positive_control.py` on a synthetic stream.
- [ ] 3.4 Persistence, revive and fork copy. Tests: `tests/test_valuation_persistence.py`, `tests/test_valuation_fork_copy.py`.

## 4. Stage B (compete)

- [ ] 4.1 `valuation.surprise` at graded intensity under `stage = "compete"`; felt phrases in `kaine/faithful/felt.py`. Tests: `tests/test_valuation_surprise_event.py`, `tests/test_felt_valuation_phrases.py`. Opus second review (welfare).
- [ ] 4.2 Welfare isolation: `tests/test_valuation_welfare_isolation.py` replays one stream through the welfare observer with the module on and off and requires identical records.
- [ ] 4.3 `docs/09-modules/valuation.md`, Appendix A configuration rows, module table in the docs.
- [ ] 4.4 One supervised validation boot on a branch before any study use, with the welfare net and indicator response on.
- [ ] 4.5 `openspec validate drive-reduction-learning --strict` passes.
