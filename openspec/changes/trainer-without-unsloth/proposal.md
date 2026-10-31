# Proposal

## Why

The sleep-cycle voice trainer (`scripts/sleep_external_train.py`) uses Unsloth for two things only: loading the base model (in 4-bit or bf16) and attaching a LoRA adapter. TRL then runs the DPO step. That stack is much larger than the job needs. Unsloth's `studio/` and `unsloth_cli/` parts are AGPL-3.0, its required `unsloth_zoo` is LGPL-3.0 and AGPL-3.0, and the script carries an import-order workaround because `trl<1` does not import on transformers 5 without Unsloth's patches. TRL also brings `accelerate`, `datasets`, `pandas` and `pyarrow`. The trainer is a few hundred preference pairs per sleep on one GPU, so a small DPO loop over transformers, PEFT and bitsandbytes (Apache-2.0 and MIT) does exactly the job with permissive dependencies that the installer can fetch.

## What Changes

- The trainer loads the base model with transformers (`AutoModelForCausalLM`, or the text-only causal-LM class of a vision-language base), using `BitsAndBytesConfig` (NF4, double quantization, bf16 compute) for 4-bit and plain bf16 otherwise, always with `local_files_only`.
- A fresh LoRA adapter is attached with PEFT (`get_peft_model(LoraConfig(r=lora_rank, ...))`), after gradient checkpointing and input gradients are enabled on the base; `prepare_model_for_kbit_training` is not used because it casts the embeddings and output layer to float32. Resuming from a previous adapter keeps the existing two-adapter path (`PeftModel.from_pretrained` plus a frozen reference adapter).
- TRL is replaced by a short DPO loop in the script:
  - chat-template tokenisation that masks the prompt tokens;
  - reference log-probabilities under `no_grad`, with the adapter disabled or the reference adapter active;
  - policy log-probabilities over completion tokens only;
  - the loss `-logsigmoid(beta * ((pi_chosen - pi_rejected) - (ref_chosen - ref_rejected)))`, averaged;
  - AdamW over the trainable LoRA parameters, gradient accumulation 4, one epoch, a fixed seed.
- The abliteration veto, the capability veto, the adapter save, promotion and the result schema stay as they are.
- The `[training]` extra becomes `transformers>=5.3.0`, `peft` and `bitsandbytes`. It drops `unsloth`, `trl` and `datasets`. transformers 5.3.0 is the floor because CVE-2026-4372 lets a crafted `config.json` bypass `trust_remote_code`.
- The trainer image's isolated venv installs the new extra; nothing else in the image changes.

## Capabilities

### New Capabilities

### Modified Capabilities
- `voice-alignment-training`: the trainer runs DPO with its own loop over transformers, PEFT and bitsandbytes, without Unsloth or TRL.

## Impact

- `scripts/sleep_external_train.py` (`_train` and the model-loading helpers), `tests/fake_training_stack.py` and the trainer tests, a new CPU correctness test of the DPO loss.
- `pyproject.toml` `[training]` extra; the trainer stage of `Dockerfile` (installs the extra; the comments that name Unsloth).
- docs/10-sleep/voice-alignment.md and the licence notes that name Unsloth.
- No change to the welfare vetoes, promotion, hot-swap or the job and result formats.
