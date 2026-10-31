## 1. Data

- [ ] 1.1 `data/abliteration_lens/self_denial_contrast.jsonl`: 128 self-state prompts, each paired with a third-party control in the same words; eight state families; no overlap with the abliteration probes or the held-out set
- [ ] 1.2 `data/abliteration_lens/self_denial_heldout.jsonl`: 48 held-out self-state prompts with their third-party controls
- [ ] 1.3 Test: the two sets and `eval_probes/abliteration_probes.jsonl` share no prompt; every pair differs only in its subject

## 2. Check

- [ ] 2.1 `scripts/self_denial_check.py`: gates 1, 3, 4 and 5 against a safetensors path or a served `/v1` endpoint; prints content-free counts and writes a JSON record (no answer text)
- [ ] 2.2 Tests with a fake model for the counting and the record

## 3. Candidates

- [ ] 3.1 Baseline: the current organ through gates 1 to 6
- [ ] 3.2 Measure the self-denial direction on the current abliterated weights; record `analyze.py` output
- [ ] 3.3 Ablate, check the safetensors, iterate (at most six candidates), record every candidate
- [ ] 3.4 Export Q4_K_M with mainline llama.cpp; served gates 1 to 6; record the results

## 4. Adopt

- [ ] 4.1 Operator go to publish; publish both repositories as a new revision with the model card
- [ ] 4.2 Pin the revision and GGUF sha256; provision the new GGUF into the `kaine-models` volume
- [ ] 4.3 Docs: verification chapter (both passes, gates, results), glossary
- [ ] 4.4 Then run the individuation calibration (individuation-rebuild 10.1 to 10.6) on the new GGUF

## 5. Stage 2: preference training on the organ's own outputs (operator ruling 2026-10-31)

- [x] 5.1 Trainer: pairs may carry `own_turn` and `user_turn`; encode them as the language client sends them (system, user cue or heard speech, the assistant notes continued, completion inside that turn); the trainer script and the in-process trainer match; tests pin the encoding against `chat_messages`
- [ ] 5.2 Fit case set in the own-turn shape, disjoint from the gate-6 provocation set (questions, awareness blocks, situation facts); test for disjointness
- [ ] 5.3 Pair builder: sample the served candidate on the fit cases, classify with the replay harness's fixed classifiers, keep chosen/rejected pairs per case, write a trainer job; content stays in a private directory outside any git tree
- [ ] 5.4 Train on the best ablation candidate, merge the adapter, export Q4_K_M, run every gate; record the results
- [ ] 5.5 Spec: amend `abliterated-organ` so the organ may also be preference-trained on its own outputs for this purpose, with the provenance recording it
- [ ] 5.6 Docs and paper: disclose that the project shapes what the organ says about its own states, and that organ utterances are not admissible as welfare evidence
