## 0. Rulings (before PR 3 and PR 4)

- [x] 0.1 Open question 1 (design): the bus and Redis's append-only file. Ruled option B on 2026-11-01 (architecture decisions of 2026-11-01, item 2; reasoning in the design's "Rulings on the open questions"); recorded in the design, the proposal and the spec, and the "pending" marks dropped. The ruling also covers heard and spoken text, specified in `heard-text-volatile-bus`, which reuses decision 7's mechanism
- [x] 0.2 Open question 2 (design): a content code in episodes. Ruled option (b) on 2026-11-01 (architecture decisions of 2026-11-01, item 3; reasoning in the design's "Rulings on the open questions"); recorded in decisions 3 and 6 and the episodic delta, and the "pending" marks dropped

## 1. The rule and the record writers (PR 1)

- [x] 1.1 `kaine/privacy_filter.py`: `LATENT_DERIVED_KEY` in `VECTOR_FIELDS`, `LATENT_FIELDS`, `strip_latent()` walking mappings, lists, tuples and numpy arrays (arrays converted with `tolist()` first), `LATENT_RULE_VERSION = 1`; module docstring states the provenance rule and the worked example of design decision 1
- [x] 1.2 `kaine/persistence/jsonl_sink.py`: `_encode_line` applies `strip_latent()` before `json.dumps`, so `write`, `write_sync` and `enqueue` are all covered
- [x] 1.3 `kaine/persistence/encrypted_jsonl.py`: `encode_record` and `rewrite_encrypted` apply `strip_latent()`
- [x] 1.4 `kaine/faithful/renderer.py`, `templates.py`, `felt.py`: `strip_latent()` on the payload inside `FaithfulRenderer.render_event`, `redact_heard_speech` and the felt equivalents, before any template or fallback; a numeric template for `("audition", "audition.perception")` reading its declared scalar fields only
- [x] 1.5 `kaine/cycle/engine.py` `_snapshot_to_payload`: drop each selected member's `latent_derived` mapping
- [x] 1.6 `kaine/evaluation/observers/raw_bus_archive_consumer.py` docstring: verbatim except for the latent fields
- [x] 1.7 Tests in `tests/test_latent_content_privacy.py`: `test_strip_latent_nested_lists_tuples_arrays`, `test_strip_latent_keeps_long_reviewed_lists`, `test_diagnostics_filter_removes_latent_derived_in_dev_mode`, `test_sink_strips_latent_on_write_write_sync_and_enqueue`, `test_sink_writes_unreviewed_array_as_exact_list`, `test_encrypted_jsonl_strips_latent`, `test_trajectory_record_has_no_latent_derived`, `test_raw_archive_holds_no_latent`, `test_numeric_rendering_of_audition_perception_holds_no_latent_number` (felt and numeric mode), `test_broadcast_drops_member_latent_derived`, `test_broadcast_bit_identical_without_latent_derived`

## 2. Module state and encryption (PR 2)

- [x] 2.1 `LatentForwardModel.buffer_summary()` and `AuditoryForwardModel.buffer_summary()` return `n_frames`, `mean_norm`, `mean_variance` (the auditory count renamed from `n_utterances`); update `tests/test_vision_forward.py`, `tests/test_vision_module.py`, `tests/test_vision_normalised_change.py`, `tests/test_vision_internvideo_next.py`, `tests/test_audition_forward.py`, `tests/test_audition_module.py`, `tests/test_audition_persistence.py`, `tests/test_revive_each_module.py`, `docs/09-modules/vision.md`, `docs/09-modules/audition.md`
- [x] 2.2 `Audition.deserialize`: rewrite each carried acoustic entry's `buffer_summary` into the three-scalar form; test `test_carried_acoustic_summary_rewritten_on_restore`
- [x] 2.3 `strip_module_states` helper: scan, strip, record `latent_stripped`, log an error, never refuse; called from `ForkManager.snapshot`, `preservation._capture_module_state` and `resume_checkpoint.capture_checkpoint`; tests `test_fork_snapshot_strips_and_records_latent`, `test_preservation_strips_and_is_never_refused`, `test_resume_checkpoint_strips_latent`, `test_snapshot_keeps_forward_model_weights`
- [x] 2.4 `ForkManager.snapshot` `_serialize_error` record: the exception type and a message cut to 200 characters; test
- [x] 2.5 Encryption boot check for latent producers (effective state encryption with a resolvable key, and `require_encryption = true`), shared with `workspace-content-code`; tests `test_latent_producer_refused_without_encryption`, `test_latent_producer_refused_without_require_encryption`

## 3. The bus (PR 3; open question 1, ruled B)

- [ ] 3.1 `compose/kaine.yml`: the `kaine-redis-volatile` service with `--appendonly no --save ""`, its own `maxmemory` (`KAINE_REDIS_VOLATILE_MAXMEMORY`), password and health check, on the compose network only
- [ ] 3.2 `kaine/bus`: a companion-stream publisher and reader that take a declared field set (here `LATENT_FIELDS`): the companion entry is written first on `<stream>.companion` of the volatile instance and the main-bus entry's envelope records its id in `companion`; a failed companion write is logged and the main entry is published without the field and without the values; every main-bus publish removes the declared fields from the payload; a consumer that finds no companion entry treats the values as absent; tests `test_companion_written_before_main_entry`, `test_failed_companion_write_loses_value_not_privacy`
- [ ] 3.3 Vision publishes `latent`, `peripheral` and `foveal` only on its companion stream, and only when a declared consumer is enabled; the broadcast record removes every latent field from members and metadata; move the tests that read `latent` off a published vision report
- [ ] 3.4 `[privacy].companion_stream_maxlen = 12000` in `config/kaine.toml` with a comment; the producer declaration (a component names its companion streams and its field set); the boot check (volatile instance reachable, `appendonly no`, empty `save`, caps within the bound) in `kaine/bus/config.py` and the preboot; config-shape validation of the new table refuses unknown keys
- [ ] 3.5 `TYPICAL_EVENT_BYTES` and the preboot "Bus budget" row: the main bus without latents and the volatile instance, each against its own `maxmemory`; the soft (approximate) trimming stated in the row's text
- [ ] 3.6 Decommission flushes the volatile instance with the entity's streams
- [ ] 3.7 Entity-free check that vision novelty and salience scores are identical with and without the perceptual latents in the main-bus payload
- [ ] 3.8 Tests: `test_main_bus_publish_carries_no_latent_field`, `test_companion_join_by_entry_id`, `test_missing_companion_is_absent`, `test_latent_producer_refused_without_volatile_bus`, `test_latent_producer_refused_when_volatile_bus_persists`, `test_companion_cap_refused_above_bound`, `test_no_producer_no_check`

## 4. Episodic store (PR 4, after or with episodic-recall-content PR 1)

- [x] 4.1 Confirm `episodic-recall-content` PR 1 (the shared heard rule in `kaine/faithful/external_input.py`, applied at store time) has merged: merged in #636 (6f936088)
- [ ] 4.2 `kaine/modules/episodic_memory/module.py`: the heard, raw-perceptual and latent rules in that order; the order stated at the code site
- [ ] 4.3 Open question 2, ruled (b): the identity-bound field's rule at the code site (no writer until build item 9(d)); the store refuses to write the field without encryption at rest; recall ignores a stored code whose code id differs from the running code
- [ ] 4.4 Tests in `tests/test_latent_content_privacy.py`: `test_episodic_store_rule_order`, `test_episodic_heard_member_with_latent_removed_whole`, `test_episodic_short_latent_vector_not_stored`, `test_identity_bound_field_refused_without_encryption`, `test_identity_bound_field_never_in_trace_text`

## 5. The canary and the publisher review (PR 5)

- [ ] 5.1 `tests/test_latent_persistence_canary.py`: the entity-free harness of the spec (the language module on a fake organ, a file-backed sqlite-vec episodic store, the resume checkpoint, the trajectory, every sink), built on the existing fakeredis helpers in `tests/` named in the brief; its producer test double; the decrypting file scan at full, float32 and `_fmt` precision with the three-in-sequence structural check; the packed-float scan of binary files; the planted controls; `test_canary_clean_run`, `test_canary_detects_planted_sink_leak`, `test_canary_detects_planted_rendering_leak`, `test_canary_detects_planted_binary_leak`
- [ ] 5.2 The bus-client wrapper assertion that no main-bus `XADD` carries a latent field and that companion streams go to the volatile client (open question 1, ruled B)
- [ ] 5.3 `tests/test_publisher_numeric_keys.py` with the reviewed `NON_LATENT_NUMERIC_KEYS` set, each entry commented with its module and why it is not latent, lists, tuples and arrays all walked; `test_every_numeric_list_is_reviewed`
- [ ] 5.4 A log-capture assertion inside the canary: no recorded latent float in the captured log file
- [ ] 5.5 Both tests run in the default CI lane (they take minutes on the CPU)

## 6. Docs and records

- [ ] 6.1 Security and privacy chapter: the latent rule, the tag, the persisting-surfaces table, the strip points, the bus rule and the volatile instance, the encryption check
- [ ] 6.2 Preservation chapter: a bundle holds learned weights and content-free buffer summaries, never latents; older bundles hold the old summaries until re-preserved
- [ ] 6.3 Configuration appendix: `[privacy].companion_stream_maxlen`
- [ ] 6.4 Paper REVISION-NOTES entry (paper repo): the principle beside "no pixels reach the workspace" (§3.5) and in the privacy paragraph of §6

## 7. Review

- [ ] 7.1 Worker first-pass review of each PR
- [ ] 7.2 Lead developer's adversarial review of each PR
- [ ] 7.3 Independent second review of each PR (privacy and persistence)
