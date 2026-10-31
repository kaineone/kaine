## 1. The rule and the strip function (PR 1)

- [ ] 1.1 `kaine/privacy_filter.py`: `LATENT_DERIVED_KEY` in `VECTOR_FIELDS`, `LATENT_FIELDS`, `strip_latent()`, `LATENT_RULE_VERSION = 1`; module docstring states the provenance rule of design decision 1
- [ ] 1.2 `kaine/persistence/jsonl_sink.py`: `AsyncJsonlSink.write` and `write_sync` apply `strip_latent()` before encoding
- [ ] 1.3 `kaine/cycle/engine.py` `_snapshot_to_payload`: drop each selected member's `latent_derived` mapping; keep the workspace's own metadata mapping
- [ ] 1.4 `kaine/evaluation/observers/raw_bus_archive_consumer.py` docstring: verbatim except for the latent fields
- [ ] 1.5 Tests in `tests/test_latent_content_privacy.py`: `test_strip_latent_nested_and_lists`, `test_strip_latent_keeps_long_reviewed_lists`, `test_diagnostics_filter_removes_latent_derived_in_dev_mode`, `test_sink_strips_latent_fields`, `test_raw_archive_holds_no_latent`, `test_broadcast_drops_member_latent_derived`, `test_broadcast_bit_identical_without_latent_derived`

## 2. Snapshots, buffer summaries and the bus bound (PR 2)

- [ ] 2.1 `VisionForwardModel.buffer_summary()` and `AuditoryForwardModel.buffer_summary()` return `n_frames`, `mean_norm`, `mean_variance`; update `tests/test_vision_forward.py`, `tests/test_audition_forward.py`, `tests/test_audition_module.py`, `tests/test_audition_persistence.py`
- [ ] 2.2 `kaine/lifecycle/snapshot.py` `save_snapshot`: strip `LATENT_FIELDS` keys from module states, record `latent_stripped`, log an error, never refuse; tests `test_snapshot_strips_and_records_latent`, `test_snapshot_keeps_forward_model_weights`, `test_preservation_never_refused_for_latent`
- [ ] 2.3 `[privacy].latent_stream_maxlen = 12000` in `config/kaine.toml` with a comment; the producer declaration (a component names the streams it publishes `latent_derived` on); the boot check in `kaine/bus/config.py` and the preboot bus-budget row; tests `test_latent_stream_cap_refused`, `test_latent_stream_cap_accepted`, `test_no_producer_no_check`
- [ ] 2.4 Config-shape validation knows the new table and refuses unknown keys in it

## 3. Episodic store order (PR 3, after or with episodic-recall-content PR 1)

- [ ] 3.1 Confirm `episodic-recall-content` PR 1 (the shared heard rule in `kaine/faithful/external_input.py`, applied at store time) has merged, or land it first as its own PR
- [ ] 3.2 `kaine/modules/episodic_memory/module.py`: the heard, raw-perceptual and latent rules in that order; the order stated at the code site
- [ ] 3.3 Tests in `tests/test_latent_content_privacy.py`: `test_episodic_store_rule_order`, `test_episodic_heard_member_with_latent_removed_whole`, `test_episodic_short_latent_vector_not_stored`

## 4. The canary and the publisher review (PR 4)

- [ ] 4.1 `tests/test_latent_persistence_canary.py`: the entity-free harness of the spec ("No latent value reaches a persisted file in an entity-free run"), its producer test double, the decrypting file scan, the planted control; `test_canary_clean_run`, `test_canary_detects_planted_leak`
- [ ] 4.2 `tests/test_publisher_numeric_keys.py` with the reviewed `NON_LATENT_NUMERIC_KEYS` set, each entry commented with its module and why it is not latent; `test_every_numeric_list_is_reviewed`
- [ ] 4.3 A log-capture assertion inside the canary: no recorded latent float in the captured log file
- [ ] 4.4 Both tests run in the default CI lane (they take minutes on the CPU)

## 5. Docs and records

- [ ] 5.1 Security and privacy chapter: the latent rule, the tag, the strip points table, the bus bound and the residual (perceptual latents in broadcast members at the broadcast cap)
- [ ] 5.2 Preservation chapter: a bundle holds learned weights and content-free buffer summaries, never latents; older bundles hold the old summaries until re-preserved
- [ ] 5.3 Configuration appendix: `[privacy].latent_stream_maxlen`
- [ ] 5.4 Paper REVISION-NOTES entry (paper repo): the principle beside "no pixels reach the workspace" (§3.5) and in the privacy paragraph of §6
- [ ] 5.5 Follow-up recorded for build order item 5: perceptual latents in broadcast members and the broadcast cap

## 6. Review

- [ ] 6.1 Worker first-pass review of each PR
- [ ] 6.2 Lead developer's adversarial review of each PR
- [ ] 6.3 Independent second review of each PR (privacy and persistence)
