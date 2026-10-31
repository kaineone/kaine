## Why

The voice-alignment trainer (`scripts/sleep_external_train.py`, used by the in-process, subprocess and job-queue backends) encodes a plain pair as a system turn, a user turn and `apply_chat_template(..., add_generation_prompt=True)` with no thinking flag. The organ's chat template (Qwen3.5) then appends `<|im_start|>assistant\n<think>\n`: an open think block, so the chosen and rejected completions are trained as the opening of a chain of thought. The organ is never served that way. The language client sends `chat_template_kwargs.enable_thinking = false`, which renders `<think>\n\n</think>\n\n`, an empty closed block, before the answer. Training and serving disagree for every plain pair.

Three more mismatches sit next to it:

- The language module sends every request in the own-turn layout (the notes as an assistant message the organ continues). The sleep pair builder writes plain pairs from its intent log, so pairs built from the entity's own utterances would be trained as user-turn requests the organ never received. The own-turn encoding exists on the organ branch (`organ-self-denial-ablation` task 5.1, commit `2f53ca06`), but nothing tells the pair builder to use it.
- The intent log stores heard speech only as a placeholder (paper §5.4), so the user turn and sometimes the prompt of a served request cannot be rebuilt from the log.
- The trainer's capability and abliteration probes are tokenized as raw text with no chat template at all, so the veto that decides whether an adapter is promoted scores the organ on input it is never served.

The KAINE-only LoRA adapter (operator decision, 2026-10-31) is trained with this trainer before the development run (the converted module-ignition study) and is loaded in the entity's own-turn context during it. Its own-turn pairs are already encoded as served on the organ branch; its veto probes are not. Voice adaptation in sleep idles today (no validated preference source), so no entity has trained on the mismatched plain encoding.

## What Changes

- Every pair shape the trainer accepts is encoded exactly as the organ is served, with thinking off:
  - plain: system turn, user turn, generation prompt with `enable_thinking=False`;
  - own-turn with the fixed cue: as on the organ branch;
  - own-turn with a heard user turn: as on the organ branch.
- The capability and abliteration probes are rendered as a plain served request (no system turn, the probe as the user turn, generation prompt with `enable_thinking=False`) before generation, matching the served check in `kaine/setup/abliteration_gate.py`.
- The sleep pair builder writes own-turn pairs for intent-log records of the language module, with `user_turn` absent when the cue was sent. It skips, and counts, records whose served text cannot be rebuilt from the log (a heard turn or a prompt with a placeholder applied) and records whose sent thinking flag was not exactly false.
- The language module's intent log records `think_sent` (the thinking flag actually sent, after any fallback for a server that rejected it) and `served_text_redacted` (the logged prompt or heard turn differs from what was sent).
- Tests render each shape through the organ's real chat template from the local base model and assert that the trained prompt tokens equal the served prompt tokens.

## Capabilities

### New Capabilities

### Modified Capabilities

- `voice-alignment-training`: every pair shape and every probe is encoded as served, thinking off.
- `voice-alignment`: the pair builder writes the served shape and skips records it cannot rebuild.
- `language`: the intent log records the thinking flag sent and whether the logged text was redacted.

## Impact

- Code: `scripts/sleep_external_train.py` (`build_dataset_rows`, `encode_dpo_row`, `_generate` callers), `kaine/modules/sleep/voice_alignment.py` (pair builder), `kaine/modules/language/module.py` and `intent_log.py` (two `extra` fields), `kaine/modules/language/client.py` (expose the flag actually sent on `ChatResponse`).
- Tests: `tests/test_own_turn_pairs.py` (the plain real-template test changes from "identical to the legacy encoding" to "identical to the served prompt"), new probe-encoding tests, pair-builder tests.
- Docs: `kaine/modules/sleep/VOICE_ALIGNMENT.md`, `docs/18-verification.md` (how the veto renders probes).
- Any adapter trained before this change was trained and vetoed on mismatched encodings; the KAINE-only adapter is trained after it.
