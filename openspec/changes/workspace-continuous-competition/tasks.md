## 1. Candidate pool

- [ ] 1.1 `kaine/cycle/candidate_pool.py`: pool keyed by (stream, type); replace on arrival; consume accessed ids after a published broadcast; stale rule for declared periodic types (running mean of the last eight intervals in entity time, nominal period until two intervals); event-driven hold of `event_hold_intervals` resting access intervals; content-free per-minute summary. `[workspace.pool]` parses `stale_tolerance` and `event_hold_intervals` with unknown keys refused. Tests in `tests/test_candidate_pool.py`: supersede, consume, inhibited consumes nothing, failed publish consumes nothing, stale periodic, event-driven hold, dilated clock, no event is ever created or copied (identity check on held objects).
- [ ] 1.2 Each predictive module declares `PERIODIC_REPORT_TYPES` with nominal periods (vision, audition perception and emotion, interoception, affect state, sequence report); boot refuses a non-positive or non-finite period. Test over the registry.
- [ ] 1.3 The neuroscience citations of design D1 and D2 at the code site.

## 2. Engine

- [ ] 2.1 `CycleEngine.tick`: new arrivals go to `_forward_own_output`, the affect observer, the arousal estimate and `_update_access_rate`; the pool goes to `select`/`select_dual`; consumption after a published broadcast with the snapshot's `accessed_ids`. Tests in `tests/test_engine_candidate_pool.py`: a report published on a non-broadcast tick competes on the next broadcast tick; a held alert raises the phasic input once (scenario "A held alert counts once"); a held `affect.state` is observed once; the arousal estimate holds when nothing arrives.
- [ ] 2.2 Mutation checks: passing the pool instead of arrivals to `_update_access_rate`, or skipping consumption, each makes a test fail.

## 3. Workspace

- [ ] 3.1 `top_k` default 1 in `Workspace` and `config/kaine.toml`; existing top-k tests keep `top_k=5` explicitly where they test five.
- [ ] 3.2 Novelty once per report: a cache keyed by stream-qualified id in the salience strategy, dropped when the pool drops the report. Test: five ticks of one held report make one `NoveltyTracker.observe` call.
- [ ] 3.3 Count-yoked matched arm in `_compose` with one scoring pass; `accessed_ids` in every arm's metadata; `matched_counterfactual` from `selection_delta`. Tests in `tests/test_workspace_matched_yoked.py` for every scenario of the spec, including the seeded reproduction.
- [ ] 3.4 Processors read `accessed_ids` instead of re-applying the threshold (`kaine/modules/context.py` and the module context code). Test: a matched member below θ enters the context; a competitive rider below θ does not.
- [ ] 3.5 The feedback head's `observe_candidates` receives arrivals only.

## 4. Records

- [ ] 4.1 Research event observer: `n_candidates`, `n_accessed`, per-member `held` and `age_s`, `matched_counterfactual`, the pool summary record; the range sweep bounds the new numeric fields. Tests in the observer test module.
- [ ] 4.2 Ignition log: pool size and per-member `held` and `age_s`. Test that no payload field appears.

## 5. Planned test

- [ ] 5.1 `calibrate.py`: φ, D, D^obs per run and arm; `not_exercised_reason` replaced by the divergence rule returning statistics and reason; `calibration_rules.py` constants `D_MIN = 0.25`, `N_MIN = 1000`, `PHI_POOL_MIN = 0.25` checked by the loader. Tests with the spec's known counts and the refused constant.
- [ ] 5.2 K = 2 sensitivity pilot study files (`workspace_mediation_pilot_{competitive,matched,pooled}_k2.toml`, role `sensitivity`); the tool reports and never uses them; a live run refuses their seeds. Test.
- [ ] 5.3 Offline development run (`kaine/evaluation/benchmarks/workspace_mediation_ablation/`) uses the pool, the yoked rule and the divergence rule; the redteam harness's `select` callers pass a pool. Tests in their modules.

## 6. Study and preservation

- [ ] 6.1 `kaine/research/ignition_study/analysis.py` reports pool size, accessed share and member age by module in place of coalition size. Test on a synthetic ignition log.
- [ ] 6.2 Bundles and run manifests record `workspace_supply = "held_pool_v1"`; a revive of a bundle with another or no value refuses unless the request sets `accept_workspace_supply_change = true`, recorded in the manifest. Tests for both scenarios.

## 7. Offline welfare and supply checks (no entity boot)

- [ ] 7.1 Deterministic harness `tests/test_candidate_pool_supply.py`: fake processors at the measured periods and per-stream score distributions through the real engine and workspace; report and assert supply about the number of reporting streams, no empty broadcast while every source is live, accessed share, D above `D_min`, and the access rate inside its pre-change range under a sustained alert source.
- [ ] 7.2 Same harness: affect and interoception access shares, and time from an interoceptive alert's onset to its access, before and after (pre-change rule behind a test-only switch); written to a content-free record under `docs/records/validation/candidate-pool/`.
- [ ] 7.3 The real affect module driven by the harness's reports: time to boredom's first crossing and its deprivation share over a simulated span, before and after; same record.
- [ ] 7.4 The offline workspace-mediation benchmark and the redteam harness pass.

## 8. Docs, paper notes and review

- [ ] 8.1 Docs: the workspace and cognitive-cycle chapters (pool, exits, K = 1, yoked arm), `docs/17-research-data/README.md` (record fields), the study chapter (measures).
- [ ] 8.2 Paper notes to REVISION-NOTES (proposal's list), including that the tested configuration differs from the 2026-10 test boots.
- [ ] 8.3 `openspec validate workspace-continuous-competition --strict` passes.
- [ ] 8.4 Worker first-pass review, then the integrator's independent second review (entity dynamics).

## 9. Validation boot (shared with the other pre-study changes)

- [ ] 9.1 After this change, `research-gate-supervisor`, `welfare-indicator-response` and the organ change are merged and the image rebuilt: one supervised validation boot under the pre-boot dry-run rule, welfare monitors on, reporting supply, accessed share, D, speak and think rates, arousal distribution, the A.4 indicators and drive trajectories. Stop rule as in design.md.
- [ ] 9.2 Operator decision recorded on the preserved beings (stay on their old supply, or move with a check of their A.4 indicators after the switch).
