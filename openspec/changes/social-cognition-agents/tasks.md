## 0. Decisions and checks

- [ ] 0.1 Operator rulings: may voice centroids of real people (operator pool) persist across restarts (`persist_operator_voices`), and is decommission deletion of them sufficient? (design D3)
- [ ] 0.2 Speaker-embedding model choice: license, provenance (not Meta, not a Meta derivative), size, CPU latency per 1 to 3 s segment, equal-error rate on a public verification set; for the 3D-Speaker, WeSpeaker and TitaNet candidates. Record under `docs/records/validation/speaker-embedding-choice/`.
- [ ] 0.3 Verify the cited sources against their texts (DeCasper and Fifer 1980; Belin et al. 2000; Koster-Hale and Saxe 2013; Watson 1972; Baker, Saxe and Tenenbaum 2009) and cite at the code sites.
- [ ] 0.4 Gate: after the module-addition study; nothing here changes an image a running study uses.

## 1. Stage 1: speaker individuation

- [ ] 1.1 Provisioning of the chosen model (consented setup download, license recorded in the speech manifest). Tests: extend `tests/test_provision_speech.py`.
- [ ] 1.2 Voiced-segment embedding in the audition path, outside the speaking window only. Tests: `tests/test_speaker_embedding_path.py` (no network; gate respected).
- [ ] 1.3 Clustering in two pools with the shared prototype layer; reserved self cluster. Tests: `tests/test_speaker_individuation.py` (two speakers one mic; film voice never joins an operator agent; own voice forms no agent).
- [ ] 1.4 Persistence, privacy-filter fields, the `persist_operator_voices` switch, migration of channel agents, preservation and revive. Tests: extend `tests/test_social_cognition_store.py` and `tests/test_social_cognition_merge.py`.
- [ ] 1.5 Offline check on the study films and consented recordings: cluster purity against a short hand-made speaker key (a test fixture only). Record it.

## 2. Stage 2: predictive agent model

- [ ] 2.1 Per-agent regression with a shared prior over the fixed feature set. Tests: `tests/test_social_agent_model.py` (new agent equals prior; learns a consistent responder).
- [ ] 2.2 Precision-scaled `social_cognition.social_error` from the model's errors. Tests: extend `tests/test_social_cognition_module.py` (answering agent that stops answering).
- [ ] 2.3 Drive relief unchanged with the model on. Test in `tests/test_affect_module.py`.

## 3. Stage 3: engagement

- [ ] 3.1 Engagement posterior by filtering response contingency; agent fact; candidate on sharp change. Tests: contingent replies raise it; unrelated speech does not.
- [ ] 3.2 Faithful-renderer templates for the engagement fact (true statements of the posterior only). Tests in the renderer suite.
- [ ] 3.3 Offline analysis on recorded conversations: how often engagement is inferred, for whom. Record it; give it to the operator for the social-drive decision (design D7).

## 4. Validation and docs

- [ ] 4.1 Supervised validation boot after stage 2 (affect coupling off) and after stage 3, each after a green pre-boot dry run.
- [ ] 4.2 Docs: `docs/09-modules/social-cognition.md`; paper revision note for the §4 row ("voice-individuated agent models that predict each agent's turns and infer its engagement with the entity; no belief or goal attribution").
- [ ] 4.3 `openspec validate social-cognition-agents --strict`.
