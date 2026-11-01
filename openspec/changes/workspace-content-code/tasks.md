## 0. Before the build

- [ ] 0.1 `latent-content-privacy` merged (its two open questions were ruled on 2026-11-01, B and b, and this change's bus text follows B); confirm `LATENT_RULE_VERSION == 1` on main
- [x] 0.2 Open question 1 of this design (vision pooling): ruled option (b), mean pooling, on 2026-11-01 (architecture decisions of 2026-11-01, item 4; reasoning in the design's "Ruling on the open question"); decision 13, the pooling boot check and the spec no longer carry "pending" marks
- [ ] 0.3 `welfare-signal-unblended` merged (the welfare readers use the own-model error)
- [ ] 0.4 `fork-merge-module-weights` merged (weight-bearing module state merges by an explicit choice)
- [ ] 0.5 The two feed defects fixed, with tests: video frame selection by real timestamps on variable-frame-rate files (`kaine/modules/vision/feed.py:1122`), and playlist audio taken by its sample count, not its padded plane (`kaine/modules/audition/feed.py:1000`)
- [ ] 0.6 Rerun the decodability check at 0.5 to 3 s lags on the synchrony-specific excess (lag-k minus block-shuffle), with mean-pooled vision latents if the pooling ruling is (b); set `slot_decay_s` from it and record it, with the stimulus-suitability note and the per-film ranking, in the design and Table A1 notes; `code_dim` stays 64
- [ ] 0.7 The development run's configuration (build order item 5) sets `[vision].pooling = "mean"` per the ruling (bus option B needs no main-bus cap change)
- [ ] 0.8 `workspace-feedback` task 3.2 marked as moved to this change (done in this revision); `workspace-feedback` archived (its task 3.3 done or moved) before this change's `workspace-feedback` delta is archived

## 1. Heads (PR 1, behind `enabled = false`)

- [ ] 1.1 `kaine/modules/feedback.py`: `TopDownHead` regressor `(b, s, z, 1)` when a code width is given; widening a base-only head with zero code columns and removing the code block at switch-off; null-code, cross-code and shifted-code evaluations of the blend; the ascending error `g_j` with `m_j` as the running mean of the head's per-dimension MSE, the pre-`adapt` code block, the code and `code_tick` stored at formation, computed on every scoring tick, clipped
- [ ] 1.2 Heads persist in every arm (carries `workspace-feedback` task 3.2): serialize and restore the base block and error windows in the vision, audition and interoception modules; discard only on a context-width or input-dimension mismatch, with a warning
- [ ] 1.3 `FeedbackChannel` adopts the code and `code_tick` from accessed broadcasts only (from the companion entry, bus option B)
- [ ] 1.4 Golden trace recorded on the commit before PR 1, for the shipped configuration and every feedback arm
- [ ] 1.5 Tests: `test_content_off_matches_pre_change_golden_trace` (every feedback arm, table absent and `enabled = false`), `test_head_widened_on_switch_on_continuity`, `test_off_on_off_on_resumes_code_blocks`, `test_off_module_state_has_no_code_columns`, `test_head_persists_across_restore`, `test_head_context_mismatch_discarded`, `test_ascending_error_matches_finite_difference`, `test_ascending_error_uses_pre_adapt_weights_and_formation_code`, `test_ascending_error_clipped`, `test_no_head_learning_or_ascending_error_when_suspended`

## 2. The code (PR 2)

- [ ] 2.1 `kaine/workspace/content_code.py`: settings and validation (`shift_s >= 60`), slots, per-source standardisers with warm-up, seeded encoder init, code formation without cross-slot normalisation, the pending-code ring, per-code per-processor averaging of ascending errors, the encoder step with the finite guard and row max-norm; cite at the code site the neuroscience of the design's Context (hub and spokes, predictive coding, precision-weighted access, learned integration, `τ_z` and sustained activity, sleep-onset clearing), checking every citation against Crossref (Massimini et al. 2005 is new in this revision)
- [ ] 2.2 `kaine/workspace/core.py` and `kaine/workspace/feedback.py`: write slots from accessed members (joining companion entries, bus option B), attach the code to accessed broadcasts under the tag, read ascending errors from every tick's candidate events
- [ ] 2.3 Audition publishes the acoustic embedding inside `latent_derived` (as `latent_derived.acoustic`) only when the content code is on with audition as a source
- [ ] 2.4 `kaine/workspace/novelty.py`: the fingerprint excludes `latent_derived` at any depth
- [ ] 2.5 Boot: the opt-in layers, the feedback-arm check, `LATENT_RULE_VERSION`, the encryption conditions, the `welfare-signal-unblended` marker, `[vision].pooling == "mean"`, the bus declaration and its check; research-gate field `content_code`, absent when the table is absent
- [ ] 2.6 Bus budget: measured entry sizes for every stream or companion stream that carries the code, latents or ascending errors, entered in `TYPICAL_EVENT_BYTES` and checked by the preboot row
- [ ] 2.7 Tests: `test_slots_written_only_by_accessed_members`, `test_slot_cleared_by_age_advisory_and_sleep`, `test_code_intensity_and_age_weights`, `test_slot_expiry_continuity` (clearing a slot whose weight is below 0.01 changes `z` by less than 0.01 in every component), `test_slot_arrival_leaves_other_terms_unchanged`, `test_standardiser_warmup_then_slow`, `test_code_zero_without_slots`, `test_inhibited_broadcast_no_code`, `test_stale_ascending_error_dropped_and_counted`, `test_nonfinite_encoder_step_skipped`, `test_encoder_rows_max_norm`, `test_ascending_errors_averaged_per_code_and_processor`, `test_async_credit_matches_sync_on_synthetic_task`, `test_no_new_candidate_event_types`, `test_novelty_and_salience_identical_with_zero_code_columns`, `test_opt_in_layers`, `test_refuses_without_latent_rule`, `test_refuses_without_encryption`, `test_refuses_without_unblended_welfare_signal`, `test_refuses_attention_pooling`, `test_refuses_unbounded_latent_stream`

## 3. Identity (PR 3)

- [ ] 3.1 `kaine/lifecycle/participants.py`: the participant protocol (name, export, import, before-modules flag) and registration with `ForkManager`
- [ ] 3.2 `ForkManager.snapshot`, `restore`, `fork` and `merge`: participant export after module states, import before module `deserialize` for flagged participants, artifact copy on fork, merge from artifact directories on disk with no live participant; preservation bundle and revive (refuse a recorded-but-missing artifact; warn on a pre-code snapshot)
- [ ] 3.3 Encrypted checkpoint with atomic replace, written in the same step as every resume checkpoint, snapshot, preservation, sleep onset and shutdown, with the shared generation counter; contents per design decision 10 (no slots, pending codes, null code, past codes or shadow); encoder binding with id, pooling and dimension; `reset_sources`; `code_dim` refusal
- [ ] 3.4 Merge: `content_code_from` on `ForkManager.merge` and the Nexus merge request; the participant artifact copied whole and every processor head's base block taken from the same parent, overriding the module weight choice for those keys; choice recorded
- [ ] 3.5 `kaine/lifecycle/decommission_locations.py`: the checkpoint and participant artifacts; dry run lists them
- [ ] 3.6 Tests: `test_checkpoint_encrypted_and_atomic`, `test_checkpoint_never_holds_slots_null_code_or_shadow`, `test_checkpoint_written_with_resume_checkpoint`, `test_generation_mismatch_logged`, `test_encoder_mismatch_refused`, `test_pooling_mismatch_refused`, `test_reset_sources_one_boot`, `test_code_dim_change_refused`, `test_participant_imports_before_module_deserialize`, `test_preserve_revive_same_code`, `test_revive_refuses_missing_artifact`, `test_fork_owns_copy`, `test_merge_requires_choice`, `test_merge_from_dashboard_process_without_workspace`, `test_merge_takes_unit_and_head_blocks_exactly`, `test_decommission_removes_checkpoint_and_artifacts`

## 4. Welfare and readout (PR 4)

- [ ] 4.1 Suspension during welfare rest or freeze; the harm breaker over awake unsuspended reports with its saved latch, `resume_after_breaker`, the caretaker notice
- [ ] 4.2 Report fields `content_gain` (null until the window fills), `content_cross_gain`, `content_shift_gain` (code `shift_s` entity seconds old), `code_sources`, `code_age_s`; broadcast `workspace_feedback.content_readout` scalars
- [ ] 4.3 Research log allowlist entries; ignition log `code_sources`
- [ ] 4.4 `kaine/research/content_code_readout.py`: per processor, per film, per day and over the run; the own-content and cross-modal job readouts, dropped-modality split, slot occupancy, dropped-error count, breaker state, saturation share; content-free output
- [ ] 4.5 Tests: `test_suspended_during_rest_reads_null_code`, `test_breaker_latches_and_survives_restart`, `test_breaker_window_excludes_suspension`, `test_breaker_cleared_only_by_resume_flag`, `test_content_gain_null_until_window_full`, `test_content_gain_positive_on_predictable_synthetic`, `test_cross_gain_zero_on_own_echo_synthetic`, `test_cross_gain_positive_on_cross_modal_synthetic`, `test_shift_measured_in_entity_seconds`, `test_research_record_has_readout_no_latent`, `test_ignition_row_code_sources_only`, `test_readout_script_content_free`

## 5. Comparison arm and entity-free checks (PR 5a, 5b, 5c)

- [ ] 5.1 (5a) Translation shadow off the tick thread with a bounded queue: encoders, per-source decoders, translation, demi-cycle and cycle losses from the published equations; own and cross-modal probes on both codes; scalar probe gains
- [ ] 5.2 (5a) `test_shadow_leaves_entity_unchanged`, `test_shadow_never_on_bus_or_snapshot`, `test_probes_no_gradient_into_codes`, `test_shadow_tick_slip_unchanged`
- [ ] 5.3 (5b) `kaine/evaluation/benchmarks/content_code_welfare/`: the new entity-free harness with real vision, audition, interoception, sequence and affect on the films; pass 1 from zero code blocks, pass 2 from weights trained entity-free on cached latents and discarded afterwards (written only under the harness's scratch directory, with a test); the bounds of design decision 11 including the own-error welfare indicator, the slot-event transient and the engagement condition; the record under `docs/records/validation/`
- [ ] 5.4 (5c) Long entity-free comparison of the two objectives, and the forced dropped-modality test on the cross-modal probe gain, on the decodability check's cached film latents; results recorded per film
- [ ] 5.5 Re-run the `latent-content-privacy` persistence canary with the real content code on (its second case)

## 6. Docs and records

- [ ] 6.1 Global-workspace chapter: the content code, the slots, the standardisers, the heads as decoders, the ascending error, the readout and what each gain means, the breaker; the vision, audition and interoception chapters; the configuration appendix
- [ ] 6.2 Preservation chapter: the participant seam, `content_code_from`, restore order, revive rules
- [ ] 6.3 Paper REVISION-NOTES entries: §3.2, §9, §10, Table A1, and the vision pooling disclosure

## 7. Review and switch-on

- [ ] 7.1 Worker first-pass review of each PR
- [ ] 7.2 Lead developer's adversarial review of each PR
- [ ] 7.3 Independent second review of each PR; for PR 5a, confirmation that the shadow and probes have no path into live error, intensity or access; for PR 3, of the participant seam on every identity path
- [ ] 7.4 Entity-free welfare check passed and recorded
- [ ] 7.5 Operator opt-in for the development run (build order item 8), recorded as a run-control record
