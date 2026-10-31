# Tasks

## 1. Trainer

- [x] 1.1 `_train` loads the base with transformers and `BitsAndBytesConfig` (4-bit) or bf16, with `local_files_only` and the configured device, and attaches LoRA with PEFT; a resumed run keeps the two-adapter path. Verify with the fake-stack tests.
- [x] 1.2 A DPO loop replaces `DPOConfig`/`DPOTrainer`: masked completion log-probabilities, reference under `no_grad`, the logsigmoid loss, AdamW with accumulation 4. Verify with the CPU correctness test (task 2.2).
- [x] 1.3 The Unsloth import and its import-order comment are gone, and `trl` and `datasets` are no longer imported. Verify by grepping the script.

## 2. Tests

- [x] 2.1 `tests/fake_training_stack.py` fakes transformers/peft/bitsandbytes instead of unsloth/trl/datasets; the existing trainer tests pass unchanged in what they assert.
- [x] 2.2 A CPU test on a tiny randomly initialised model checks the log-probabilities, the loss formula, the `log 2` loss at initialisation, and that a step changes only LoRA weights.

## 3. Packaging and docs

- [x] 3.1 The `[training]` extra is `transformers>=5.3.0`, `peft` and `bitsandbytes`; the trainer image builds with it. Verify by building the trainer image.
- [x] 3.2 docs/10-sleep/voice-alignment.md and the licence notes no longer describe Unsloth or TRL as the trainer stack.
- [x] 3.3 `openspec validate trainer-without-unsloth --strict` passes.
