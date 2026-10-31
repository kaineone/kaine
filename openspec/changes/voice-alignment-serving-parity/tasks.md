## 1. Trainer encoding

- [ ] 1.1 On top of the organ branch's own-turn encoding (commit `2f53ca06`): `encode_dpo_row` renders plain pairs with `enable_thinking=False`. Rewrite `test_real_template_plain_encoding_token_identical` in `tests/test_own_turn_pairs.py` to compare with the served prompt (`add_generation_prompt=True, enable_thinking=False`) and assert the closed think block; the fake-tokenizer tests assert the kwarg is passed for plain rows.
- [ ] 1.2 A parametrized real-template test over the three shapes (plain, own-turn cue, own-turn heard) against `chat_messages`; skipped only when the base model is absent at `KAINE_TEST_ORGAN_BASE_MODEL`.
- [ ] 1.3 The in-process backend encodes identically (gate parity), checked through `tests/fake_training_stack.py`'s recorded template kwargs.

## 2. Probes

- [ ] 2.1 `_capability_score` and `_abliteration_verdict` render each probe with the chat template (plain, no system, thinking off) before `_generate`. Test with the fake stack that generation receives the rendered ids, and a real-template test that a probe's ids equal the served prompt.
- [ ] 2.2 Mutation check: reverting to raw-text tokenization makes a test fail.

## 3. Log and pair builder

- [ ] 3.1 `ChatResponse.think_sent` set by `OpenAIChatClient.complete`, including the retry path; `extra.think_sent` and `extra.served_text_redacted` written by the language module. Tests in the language module tests for the rejected-flag retry and the redacted prompt.
- [ ] 3.2 The sleep pair builder writes own-turn pairs and skips heard-turn, redacted and non-false-thinking records with counted reasons. Tests in `tests/test_sleep_voice_alignment.py` for the three scenarios.

## 4. Docs and checks

- [ ] 4.1 `kaine/modules/sleep/VOICE_ALIGNMENT.md` (the three shapes, thinking off, skipped records), `docs/18-verification.md` (probes rendered as served).
- [ ] 4.2 `openspec validate voice-alignment-serving-parity --strict` passes.
- [ ] 4.3 Worker first-pass review, then the integrator's second review (the veto's input changes).
