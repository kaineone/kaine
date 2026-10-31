## 0. Before the build

- [ ] 0.1 `latent-content-privacy` merged; confirm `LATENT_RULE_VERSION == 1` on main
- [ ] 0.2 Read the offline cross-modal decodability check's results; set `code_dim` and `slot_decay_s` by design decision 12 and record them, with the stimulus-suitability note, in the change's design and Table A1 notes
- [ ] 0.3 The development run's configuration (build order item 5) sets the `workspace.broadcast` cap to at most 12000

## 1. Heads (PR 1, behind `enabled = false`)

- [ ] 1.1 `kaine/modules/feedback.py`: `TopDownHead` regressor `(b, s, z, 1)` when a code width is given, code columns at zero; null-code and shifted-code evaluations of the blend; the ascending error `g_j` with normalisation and clipping
- [ ] 1.2 Heads persist in every arm (carries `workspace-feedback` task 3.2): serialize and restore weights and error windows in the vision, audition and interoception modules; discard on a width mismatch with a warning
- [ ] 1.3 `FeedbackChannel` adopts `latent_derived.code` and `code_tick` from accessed broadcasts only
- [ ] 1.4 Tests: `test_content_off_bit_identical_to_absent` (every feedback arm), `test_head_code_columns_start_zero_switch_on_continuity`, `test_head_persists_across_restore`, `test_head_width_mismatch_discarded`, `test_ascending_error_matches_finite_difference`, `test_ascending_error_clipped`, `test_no_head_learning_or_ascending_error_when_suspended`

## 2. The code (PR 2)

- [ ] 2.1 `kaine/workspace/content_code.py`: settings and validation, slots, seeded encoder init, code formation, the pending-code ring, the encoder step; cite the neuroscience of the design's Context at the code site (hub and spokes, predictive coding, reliability weighting, learned integration)
- [ ] 2.2 `kaine/workspace/core.py` and `kaine/workspace/feedback.py`: write slots from accessed members, attach the code to accessed broadcasts under the tag, read ascending errors from the tick's candidate events
- [ ] 2.3 Audition publishes the acoustic embedding as `latent` only when the content code is on with audition as a source
- [ ] 2.4 Boot: the opt-in layers, the feedback-arm check, `LATENT_RULE_VERSION`, the producer stream declaration and the cap check; research-gate field `content_code`
- [ ] 2.5 Tests: `test_slots_written_only_by_accessed_members`, `test_slot_cleared_by_age_advisory_and_sleep`, `test_code_intensity_and_age_weights`, `test_code_zero_without_slots`, `test_inhibited_broadcast_no_code`, `test_stale_ascending_error_dropped_and_counted`, `test_async_credit_matches_sync_on_synthetic_task`, `test_no_new_candidate_event_types`, `test_opt_in_layers`, `test_refuses_without_latent_rule`, `test_refuses_on_uncapped_stream`

## 3. Identity (PR 3)

- [ ] 3.1 Encrypted checkpoint with atomic replace and its write schedule; encoder binding, `reset_sources`, `code_dim` refusal
- [ ] 3.2 Snapshot participant `workspace_content_code` in `ForkManager` snapshot, restore and fork; preservation bundle and revive (refuse a recorded-but-missing artifact; warn on a pre-code snapshot)
- [ ] 3.3 Merge: `content_code_from` on `ForkManager.merge` and the Nexus merge request, encoders and heads taken together, choice recorded
- [ ] 3.4 `kaine/lifecycle/decommission_locations.py`: the checkpoint; dry run lists it
- [ ] 3.5 Tests: `test_checkpoint_encrypted_and_atomic`, `test_checkpoint_never_holds_slots_or_shadow`, `test_encoder_mismatch_refused`, `test_reset_sources_one_boot`, `test_code_dim_change_refused`, `test_preserve_revive_same_code`, `test_revive_refuses_missing_artifact`, `test_fork_owns_copy`, `test_merge_requires_choice`, `test_merge_takes_encoders_and_heads_together`, `test_decommission_removes_checkpoint`

## 4. Welfare and readout (PR 4)

- [ ] 4.1 Suspension during welfare rest or freeze; the harm breaker with its saved latch, `resume_after_breaker`, the caretaker notice
- [ ] 4.2 Report fields `content_gain`, `content_shift_gain`, `code_sources`, `code_age_s`; broadcast `workspace_feedback.content_readout` scalars
- [ ] 4.3 Research log allowlist entries; ignition log `code_sources`
- [ ] 4.4 `kaine/research/content_code_readout.py`: the job readout, dropped-modality split, dropped-error count, breaker state, saturation share; content-free output
- [ ] 4.5 Tests: `test_suspended_during_rest_reads_null_code`, `test_breaker_latches_and_survives_restart`, `test_breaker_cleared_only_by_resume_flag`, `test_content_gain_positive_on_predictable_synthetic`, `test_shift_gain_below_content_gain_on_synthetic`, `test_research_record_has_readout_no_latent`, `test_ignition_row_code_sources_only`, `test_readout_script_content_free`

## 5. Comparison arm and entity-free checks (PR 5)

- [ ] 5.1 Translation shadow: encoders, per-source decoders, translation, demi-cycle and cycle losses from the published equations; probes on both codes; scalar probe gains
- [ ] 5.2 `test_shadow_leaves_entity_unchanged`, `test_shadow_never_on_bus_or_snapshot`, `test_probes_no_gradient_into_codes`
- [ ] 5.3 Workspace-mediation runner drives audition; the entity-free welfare check with the bounds of design decision 11, its record under `docs/records/validation/`
- [ ] 5.4 Long entity-free comparison of the two objectives, and the forced dropped-modality test, on the decodability check's cached film latents; results recorded
- [ ] 5.5 Re-run the `latent-content-privacy` persistence canary with the real content code on (its second case)

## 6. Docs and records

- [ ] 6.1 Global-workspace chapter: the content code, the slots, the heads as decoders, the ascending error, the readout, the breaker; the vision, audition and interoception chapters; the configuration appendix
- [ ] 6.2 Preservation chapter: the participant, `content_code_from`, revive rules
- [ ] 6.3 Paper REVISION-NOTES entries: §3.2, §9, §10, Table A1

## 7. Review and switch-on

- [ ] 7.1 Worker first-pass review of each PR
- [ ] 7.2 Lead developer's adversarial review of each PR
- [ ] 7.3 Independent second review of each PR; for PR 5, confirmation that the shadow and probes have no path into live error, intensity or access
- [ ] 7.4 Entity-free welfare check passed and recorded
- [ ] 7.5 Operator opt-in for the development run (build order item 8), recorded as a run-control record
