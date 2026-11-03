# Design

## Model loading

The job already carries `train_precision` ("bf16" or "4bit") and `precision_load_kwargs()` maps it to load arguments. Those arguments now go to transformers directly:

- "4bit": `BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=torch.bfloat16)`.
- "bf16": `torch_dtype=torch.bfloat16`.

Loading always passes `device_map={"": training_device}` and `local_files_only=True`. For a vision-language base, the script loads only the text causal-LM, so the vision tower's weights are not loaded, and it uses the text tokenizer. When the base is a plain causal LM, `AutoModelForCausalLM` is used. The script never imports the optional `kernels` package, so transformers cannot fetch hub kernels at run time (the runtime is offline).

## LoRA

Both fresh and resumed runs enable gradient checkpointing (non-reentrant) and input gradients on the loaded base, and `prepare_model_for_kbit_training` is not used because it casts the embeddings and output layer to float32; a fresh run then calls `get_peft_model(model, LoraConfig(r=lora_rank, lora_alpha=lora_rank, lora_dropout=0.0, target_modules="all-linear", task_type="CAUSAL_LM"))`. The adapter keeps PEFT's default name, so `save_pretrained` writes the files where the promotion step already expects them. A resumed run keeps today's path: the previous adapter loads as the trainable `TRAINED_ADAPTER` and again as the frozen `REFERENCE_ADAPTER`. A previous adapter whose LoRA weights match no module of the base is refused rather than replaced by a fresh one.

## The DPO loop

For each pair (prompt, chosen, rejected), up to `max_samples`:

1. Tokenise `prompt + chosen` and `prompt + rejected` with the tokenizer's chat template where the pair carries chat roles, otherwise as plain text, truncating to `max_length` (default 768 tokens). The labels mask every prompt token and padding with -100.
2. Reference log-probability of each completion, summed over the unmasked tokens, under `torch.no_grad()`:
   - fresh run: inside `model.disable_adapter()`;
   - resumed run: with `REFERENCE_ADAPTER` active, then switching back.
3. Policy log-probability with `TRAINED_ADAPTER` (or the default adapter) active and the model in train mode with dropout off. Logits are computed only for completion positions (`logits_to_keep`), because a 248k-entry vocabulary makes full-sequence logits the largest memory cost.
4. `loss = -F.logsigmoid(beta * ((pc - pr) - (rc - rr))).mean()`, divided by the accumulation steps.
5. AdamW over parameters with `requires_grad`, learning rate `learning_rate`, an optimizer step every 4 pairs and at the end, one epoch, the seed is set before the LoRA weights are created and again before the loop.

The reported `dpo_loss` is the mean loss over the pairs; `steps` is the number of optimizer steps. An out-of-memory error keeps today's `_oom_result()` path.

## Correctness check

A test builds a tiny causal LM from a config on the CPU (random weights, nothing downloaded), attaches LoRA and runs the loop on two pairs. It checks:

- the masked log-probabilities against a direct per-token computation;
- the first-step loss against `-logsigmoid(beta * margin)` computed independently from the same log-probabilities;
- that the loss at initialisation equals `log 2` (the policy equals the reference);
- that one optimizer step changes the LoRA weights and nothing else.

## Memory

Unmeasured until a real run. By arithmetic on Qwen3.5 configs (a 248,320-token vocabulary with untied embeddings), a 9B base in 4-bit fits a 12 GB card at batch 1 with sequences of 512 to 768 tokens, and does not fit an 8 GB card. The 4B base the organ currently serves fits more comfortably. Upstream Unsloth advises against 4-bit QLoRA on Qwen3.5 for quality reasons, and that advice does not depend on the library, so the existing vetoes remain the guard.

## Licences

transformers, peft and accelerate are Apache-2.0, and bitsandbytes is MIT. All are installed by the installer or the trainer image, not vendored.
