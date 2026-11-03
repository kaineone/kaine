# Spec Delta

## ADDED Requirements

### Requirement: The trainer loads the base and attaches LoRA without Unsloth
The voice-alignment trainer SHALL load the base model with transformers from local files only, in 4-bit (NF4 through bitsandbytes) or bf16 as `train_precision` selects, and SHALL attach a LoRA adapter sized by `lora_rank` with PEFT. Resuming SHALL keep the previous adapter as the trainable adapter and a frozen copy as the reference.

#### Scenario: 4-bit load
- **WHEN** `train_precision` is "4bit"
- **THEN** the base loads through `BitsAndBytesConfig` with NF4 quantization, from local files only, on the configured training device

#### Scenario: Resumed run
- **WHEN** a previous adapter exists
- **THEN** it loads as the trainable adapter and again as the frozen reference adapter

### Requirement: The trainer runs a real DPO step without TRL
The trainer SHALL score each chosen and rejected completion over its completion tokens only, under the policy and under the reference (the adapter disabled, or the frozen reference adapter when resuming), and SHALL minimise the DPO loss `-logsigmoid(beta * margin)`. It SHALL write the adapter to `<adapter_output_dir>/<timestamp>.tmp/` before any evaluation and report `dpo_loss`, `steps` and `samples_used`.

#### Scenario: Real training writes a tmp adapter
- **WHEN** the trainer runs with two valid DPO pairs and a base model path
- **THEN** it records optimizer steps, and a `<adapter_output_dir>/<timestamp>.tmp/` directory exists with the serialized LoRA weights before either veto runs

#### Scenario: The loss is DPO's
- **WHEN** the trainer runs one step on a tiny model whose adapter starts as an identity (policy equal to reference)
- **THEN** the loss is `log 2`, and the per-pair loss equals `-logsigmoid(beta * margin)` computed independently from the same log-probabilities

#### Scenario: Only the adapter trains
- **WHEN** the trainer takes an optimizer step
- **THEN** the LoRA weights change and the base model's weights do not

## MODIFIED Requirements

### Requirement: Optional `[training]` extras gate failures loudly
The trainer SHALL lazy-import `transformers`, `peft` and `bitsandbytes` inside `train()`. When any is missing, `train()` SHALL
return `TrainingResult(accepted=False, reason="<extras name> not
installed — pip install -e .[training]")` rather than raising. The
phase SHALL log the message and continue the rest of the sleep
cycle.

#### Scenario: Missing extras don't crash sleep
- **WHEN** `[sleep.voice_alignment].enabled = true` and the env
  var is set but `peft` is not installed
- **THEN** `train()` returns a TrainingResult with `accepted=False`
  and `reason` naming the `training` extras group, and the sleep
  cycle's other phases (light consolidation, deep consolidation,
  associative replay, affective reset) still complete

## REMOVED Requirements

### Requirement: UnslothDPOTrainer.train executes a real DPO step
**Reason**: The trainer no longer uses Unsloth or TRL; the requirements "The trainer loads the base and attaches LoRA without Unsloth" and "The trainer runs a real DPO step without TRL" replace it.
**Migration**: None for operators. The `[training]` extra installs the new dependencies.
