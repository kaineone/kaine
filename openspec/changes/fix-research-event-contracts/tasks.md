
## 1. Taxonomy and field fixes (research_event_observer.py)

- [ ] 1.1 Replace `_TAXONOMY` key `volition.intent` with prefix-matched entries for the real Volition types `intent.speak`, `intent.think`, `intent.act` (producer: kaine/workspace/volition.py:50-54); preserve the existing payload allowlist.
- [ ] 1.2 In `_WorkspaceMetadataObserver.handle`, read snapshot key `selected` (written at kaine/cycle/engine.py:802) instead of `selected_events`; keep coalition metadata population working.
- [ ] 1.3 Update `hypnos.sleep.started` taxonomy fields to `{"started_at"}` (producer: kaine/modules/hypnos/module.py:340-344).
- [ ] 1.4 Update `thymos.emotion` taxonomy fields: allowlist `emotion` instead of `category` (producer: kaine/modules/thymos/module.py:226).
- [ ] 1.5 Update `topos.report` taxonomy fields to `{prediction_error, normalised_error, change_score, habituation_score, alert}` (drop nonexistent `horizon`) and delete the producer-less `topos.scene_change` taxonomy entry (producer: kaine/modules/topos/module.py:568-611).
- [ ] 1.6 Update `audition.prosody` taxonomy fields to `f0_mean_hz`, `f0_std_hz` (producer: kaine/modules/audition/prosody.py:130-136).

## 2. Stream additions

- [ ] 2.1 Add `chronos.out` to `_CURATED_STREAMS`.
- [ ] 2.2 Add a `chronos.report` taxonomy entry with content-free allowlist `{anomaly_score, habituation_score, rumination_detected, temporal_prediction_error, time_since_last_interaction_s}`; exclude `temporal_context` and `feature_vector` (latent content) (payload: kaine/modules/chronos/module.py:184-196).

## 3. Raw bus archive fix

- [ ] 3.1 In `raw_bus_archive_consumer.py`, replace `lingua.out` in `_MODULE_OUT_STREAMS` with `lingua.external` and `lingua.internal` (producer: kaine/modules/lingua/module.py:27-28,59-61).

## 4. Canonical stream registry + drift test

- [ ] 4.1 Create a canonical module-stream registry module that derives the module-stream set from registered module names via `module_stream(name)`, with documented exclusions (e.g., Lingua's deliberate `external`/`internal` split vs. a single out stream), following the shared-logic precedent of welfare_observer.py:52-58.
- [ ] 4.2 Re-point `_CURATED_STREAMS` (research_event_observer.py:310), `_MODULE_OUT_STREAMS` (raw_bus_archive_consumer.py:54), and `DEFAULT_DIAGNOSTICS_STREAMS` (kaine/nexus/__main__.py:32) to derive from the canonical registry so the observer, archive, and monitor never drift.
- [ ] 4.3 Add a drift test asserting each of the three lists exactly matches the canonical registry-derived set, failing loudly on future drift.

## 5. Config profile threading

- [ ] 5.1 Thread the `profile` argument through `load_evaluation_config` and `load_research_event_log_config` in kaine/evaluation/config.py:482,507 so they call `load_kaine_config(profile=...)` consistently with the research gate.

## 6. Interrupt threshold wiring

- [ ] 6.1 In kaine/cycle/__main__.py:803-809, thread `[volition].interrupt_threshold` from config into the report policy (`report_policy.py:70` parameter), making the interruptible-utterance feature (PR #81) reachable.

## 7. Unused imports (CodeQL, mechanical)

- [ ] 7.1 Remove `Encoder` from tests/test_topos_internvideo_next.py:19.
- [ ] 7.2 Remove `Encoder` from tests/test_topos_encoder.py:11.
- [ ] 7.3 Remove `DECOUPLED_STIMULUS` from tests/test_workspace_mediation_runner.py:15.
- [ ] 7.4 Remove `math` from kaine/evaluation/benchmarks/workspace_mediation_ablation/stimulus.py:28.
- [ ] 7.5 Remove `WorkspaceSnapshot` from kaine/evaluation/benchmarks/workspace_mediation_ablation/runner.py:51.

## 8. Regression tests (fixtures built from real producer payload shapes)

- [ ] 8.1 Test: publish Volition `intent.speak`/`intent.think`/`intent.act` events with real payload shapes and assert intents appear in the research log.
- [ ] 8.2 Test: workspace snapshot containing `selected` (per engine.py:802) yields populated coalition metadata.
- [ ] 8.3 Test: `hypnos.sleep.started` with payload `{"started_at"}` survives the taxonomy allowlist.
- [ ] 8.4 Test: `thymos.emotion` with field `emotion` is retained in the record.
- [ ] 8.5 Test: `topos.report` with `{prediction_error, normalised_error, change_score, habituation_score, alert}` survives; assert `topos.scene_change` events are not archived and no phantom entry remains.
- [ ] 8.6 Test: `chronos.out`/`chronos.report` with the real Chronos payload fields flows through the curated stream and content-free allowlist; assert `temporal_context`/`feature_vector` never appear in the research log.
- [ ] 8.7 Test: `audition.prosody` with `f0_mean_hz`/`f0_std_hz` survives the taxonomy.
- [ ] 8.8 Test: raw bus archive subscribes to `lingua.external` and `lingua.internal` and captures a verbatim conversation; `lingua.out` is not subscribed.
- [ ] 8.9 Test: evaluation/research-event-log configs honor a profile's `[evaluation]` block identically to the gate's profile-inclusive config.
- [ ] 8.10 Test: `[volition].interrupt_threshold` from config reaches the report policy.

## 9. Docs

- [ ] 9.1 Document the canonical module-stream registry, its exclusions, and the drift-test contract.
- [ ] 9.2 Document taxonomy/allowlist conventions: consumers adapt to shipped producer payloads; research log remains content-free (no latent vectors, text, or transcripts).
