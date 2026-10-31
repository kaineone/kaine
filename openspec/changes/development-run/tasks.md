## 1. Operator decisions (before any code)

- [ ] 1.1 Workspace capacity and candidate supply: option A, B or C of the design's section, and the fallbacks of condition 2. Recommendation B.
- [ ] 1.2 Validation boot: the run's own first supervised hours, or one short validation entity first. Recommendation: the run's own first hours.
- [ ] 1.3 Reversal policy: identity-bearing components are not reversible except as a welfare-protective action or by a reviewed operator decision.
- [ ] 1.4 Stimulus schedule at the start: reference programme only, or with supplementary programmes (which).
- [ ] 1.5 Whether the stimulus-control act (W3) is pulled forward as the first architecture component.

## 2. Dependencies and other changes

- [ ] 2.1 `welfare-indicator-response`, `research-gate-supervisor` and `welfare-exposure-report` merged (branch `spec/pre-study-gates-2026-10-31`).
- [ ] 2.2 Amend `welfare-exposure-report` for per-pass records and the pass-end hold (this change's `welfare-monitoring` delta), before it is built.
- [ ] 2.3 Re-target the `module-ignition-study` deltas of `research-gate-supervisor` and `welfare-exposure-report` to `development-run`, or, if they archive first, add their requirements to this change's REMOVED list before this change archives.
- [ ] 2.4 Amend `workspace-continuous-competition` by decision 1.1: split the architecture part (before the image) from the planned-test apparatus (deferred); replace its `module-ignition-study` delta with the pool size and accessed share already in `development-run`'s analysis requirement.
- [ ] 2.5 Archive `module-ignition-study` with task 2.5 marked superseded by `development-run`.
- [ ] 2.6 Re-target the gates of `act-intent-derivation`, `active-vision`, `embodiment-motor-contingency`, `goal-directed-grasping`, `planning-act-proposals` and `world-model-action-outcomes` from `module-ignition-study` task 2.5 to the matching join in the development run; drop the study-step wording in `voice-development` and `vox-default-voice`; record in `pilot-calibration` that it gates nothing.
- [ ] 2.7 The privacy rule for latent-derived content (build-order item 2) is a `requires` entry of every content-bearing component; it does not gate the run's start.

## 3. Plan, layout and commands

- [ ] 3.1 `git mv kaine/research/ignition_study kaine/research/development_run`; check the data roots for any `study.json` first and keep `status` able to read one if found. Update `kaine/legacy_names.py`, `compose/kaine.yml` and the persisted-name tests. Tests: `tests/test_persisted_study.py`, `tests/test_container_deployment.py`.
- [ ] 3.2 Plan: one entity, one bus database, one collection prefix, the reference programme and schedule, the join order, window lengths, budgets, `min_free_gb`; refuse lines. Tests: `tests/test_development_run_plan.py::test_plan_refuses_lines`, `::test_default_join_order`, `::test_operator_bus_db_refused`, `::test_changed_manifest_refused`.
- [ ] 3.3 Commands `init`, `run`, `status`, `pause`, `plan-join`, `join`, `plan-switch`, `switch`, `ack-welfare`, `ack-change`, `accept-image`, `recover`, `analyse`; every command resolves `--run-dir` the same way and appends to the run record. Tests: `tests/test_development_run_cli.py::test_run_dir_resolution`, `::test_commands_never_edit_entity_state`.

## 4. Sessions and passes

- [ ] 4.1 The developmental phase carried over from the study's developmental step (bloom wait, maturation-reference wait, viability watch, disk guard). Tests: the existing developmental-step tests moved to `tests/test_development_run_runner.py`.
- [ ] 4.2 Sessions as plain starts on the one tree; resume after interruption; refuse a tree with another identity. Tests: `::test_session_is_plain_start_same_entity`, `::test_resume_after_interruption_records_boundary`, `::test_tree_identity_mismatch_halts`.
- [ ] 4.3 `programme_end = "continue"`: preserve without stop and loop; the stop request file; failure freezes as now. Tests: `tests/test_programme_end.py::test_continue_loops_after_preservation`, `::test_stop_request_preserves_and_stops`, `::test_continue_failure_freezes`.
- [ ] 4.4 The runner places a stop request only when a change, hold or pause is pending; nothing changes within a session. Tests: `tests/test_development_run_runner.py::test_stop_only_with_pending_change`, `::test_module_set_fixed_within_session`.
- [ ] 4.5 The transition only in the first session after maturation. Test: `tests/test_development_run_overlay.py::test_transition_first_session_only`.
- [ ] 4.6 Session and pass records. Test: `tests/test_development_run_runner.py::test_session_and_pass_records`.

## 5. Registry, switches and absence

- [ ] 5.1 `config/development_run/components.toml` with entries for the six held modules, voice alignment, and the effectors, perceptual locus and embodiment modules. Test: `tests/test_development_run_registry.py::test_registry_entries_complete`, `::test_experience_changing_needs_review_record`, `::test_readout_fields_exist`.
- [ ] 5.2 Entity-free deterministic harness and digest, `tools/development_run/harness_digest.py` (NumPy backends; deterministic fakes for the organ, encoders and services). Test: `tests/test_harness_digest.py::test_digest_reproducible`, `::test_digest_changes_with_module_set`.
- [ ] 5.3 Golden digests for the base set and for each held module off; absence tests for every registry entry. Tests: `tests/test_development_run_absence.py` (one per entry).
- [ ] 5.4 Two-layer opt-in, entity id check, review-record check, reversibility rule and protective switch-off. Tests: `tests/test_development_run_joins.py::test_one_layer_refused`, `::test_other_entity_refused`, `::test_review_record_required`, `::test_not_reversible_refused`, `::test_protective_switch_off_accepted`, `::test_voice_alignment_keeps_approval_variable`.
- [ ] 5.5 A switched-off component's stored state is untouched. Test: `::test_switched_off_state_byte_identical`.

## 6. Readouts and analysis

- [ ] 6.1 `readouts.py`: per-class readouts from the ignition log, research event log, welfare records and content-free counters; `not_computed` with reasons. Tests: `tests/test_development_run_readouts.py::test_processor_readout`, `::test_context_readout_uses_context_gain`, `::test_memory_readout`, `::test_learned_model_readout_against_persistence_baseline`, `::test_action_readout`, `::test_output_readout`, `::test_not_computed_not_zero`, `::test_readouts_content_free`.
- [ ] 6.2 Analysis: per reference pass measures, boundaries, before and after windows, baseline trend, exposure table, limits text; the line comparisons removed. Tests: `tests/test_development_run_analysis.py::test_boundaries_from_record`, `::test_window_pending_when_short`, `::test_dilated_pass_flagged`, `::test_limits_stated`, `::test_report_content_free`.
- [ ] 6.3 Ignition records carry session and pass. Test: `tests/test_ignition_log.py::test_session_and_pass_in_record`, `::test_broadcast_unchanged_by_pass_fields`.

## 7. Welfare wiring

- [ ] 7.1 Overlay forces the welfare net, the supervisor, the individuation producer and graph-only recording for every session kind; merged-config gate test. Test: `tests/test_development_run_overlay.py::test_every_session_kind_passes_config_gate`.
- [ ] 7.2 Per-pass exposure records (with 2.2) and the pass-end hold; `ack-welfare`. Tests: `tests/test_development_run_holds.py::test_crossing_holds`, `::test_missing_record_holds`, `::test_ack_continue_records_decision`.
- [ ] 7.3 Post-change hold and `ack-change`. Test: `::test_first_pass_after_join_holds`.
- [ ] 7.4 Welfare freeze surfacing; `failed:welfare`; `failed:supervisor`. Tests carried over from the study runner, plus `::test_supervisor_escalation_halts_run`.
- [ ] 7.5 The planned-test role and workspace-mediation study names refused; arm and temperature forced. Tests: `tests/test_development_run_overlay.py::test_planned_test_role_refused`, `::test_mediation_study_env_refused`, `::test_arm_and_temperature_forced`.

## 8. Persistence and images

- [ ] 8.1 `recover`: same entity, same tree, recorded boundary; no fork, merge or delete command exists. Tests: `tests/test_development_run_recover.py::test_other_entity_bundle_refused`, `::test_recovery_is_boundary`, `::test_no_delete_commands`.
- [ ] 8.2 Image admission: harness digest, model identities and configuration digest; `accept-image`; workspace supply change counts as a dynamics change. Tests: `tests/test_development_run_images.py::test_silent_update_admitted`, `::test_digest_change_needs_acceptance`, `::test_supply_change_needs_acceptance`.
- [ ] 8.3 Long-life caps audit: list every store, buffer and retention a long life could fill; raise or remove any cap that would cull the entity's memory. Record the audit under `docs/records/audits/`.

## 9. Docs

- [ ] 9.1 `docs/15-experiments/ignition-study.md` becomes `docs/15-experiments/development-run.md`; update the book summary, `docs/06-operation/development.md`, `docs/11-preservation.md`, `docs/17-research-data/README.md` and every page that names the branch, repeat or accumulate lines. Present tense, no change history.
- [ ] 9.2 Call the offline benchmark the offline mediation check in the docs.

## 10. Paper

- [ ] 10.1 The revision note drafted in the paper-audit folder (`REVISION-NOTES-draft.md`) is reviewed by the operator and applied in the paper's next revision.

## 11. Before the run

- [ ] 11.1 Dry run of the runner end to end with the stand-in cycle and a tiny stand-in programme: developmental phase, two sessions with three passes each, a join, a hold, an `ack-change`, a silent image update and an accepted one. No entity.
- [ ] 11.2 The offline welfare checks of the chosen workspace option (design, conditions 1 to 4) reported to the operator.
- [ ] 11.3 The pre-boot dry run of the full stack, shown green to the operator.
- [ ] 11.4 Independent second review of the implementation.
- [ ] 11.5 The operator starts the run.
