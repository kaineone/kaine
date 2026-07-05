## Why

Hypnos already orchestrates voice-alignment training during sleep
cycles: the scheduler fires the phase, `DPOPairBuilder` reads
`state/lingua/intent_expression.jsonl` and emits `DPOPair` records
(chosen = `faithful_rendering`, rejected = `generated_text`), the
trainer is invoked, and `hypnos.cycle_complete` events flow to the
evaluation sidecar. **But `UnslothDPOTrainer.train()` is a
stub.** It returns `TrainingResult(accepted=False, reason="...
intentionally a stub")` and exits. No model is loaded, no DPO step
runs, no adapter is written, no capability eval happens. KAINE
faithfully logs that training was skipped, sleep cycle after sleep
cycle.

This change is the implementation work that makes the orchestration
real. It pulls in the heavy training stack as an optional extra,
implements the DPO body, runs a capability-loss eval against the
post-training model, atomically promotes the adapter only when the
eval passes, and tells Lingua's backing service to load the new
adapter so subsequent inference reflects the alignment.

Operator-opt-in remains the load-bearing safety gate. The build
prompt §5.2 said "Do not abliterate the model automatically.
Document the process and flag for operator approval." Voice
alignment is gentler than abliteration (DPO is reversible per
adapter; abliteration mutates base weights), but it still rewrites
the language organ's behavior. Nothing about the training body fires
until the operator sets both `[hypnos.voice_alignment].enabled =
true` AND exports `KAINE_VOICE_ALIGNMENT_OPERATOR_APPROVED=1`.

## What Changes

### 1. Optional `[training]` extra

- New `[project.optional-dependencies]` group `training` in
  `pyproject.toml`:
  - `unsloth>=2024.9,<2026` — base-model loader with 4-bit quant
  - `trl>=0.11,<1` — `DPOTrainer`
  - `peft>=0.13,<1` — LoRA adapter management
  - `datasets>=2.20,<5` — the DPO dataset object
- Documented in DEPENDENCIES.md; documented in SETUP.md §2.2 as
  another optional extras group (same shape as `audio` / `vision`).
- ~3-4 GB install. Operator opts in with `pip install -e .[training]`.

### 2. Operator-opt-in safety gate

- New `[hypnos.voice_alignment].enabled` config key — default
  `false`. When `false`, `_run_voice_alignment` returns a "skipped:
  disabled in config" PhaseResult without ever constructing a real
  trainer.
- When `enabled = true` but the env var
  `KAINE_VOICE_ALIGNMENT_OPERATOR_APPROVED` is unset, the phase
  refuses to fire and logs a clear remediation line. Mirrors the
  existing `KAINE_CYCLE_OPERATOR_PRESENT` / `KAINE_FIRST_BOOT_
  OPERATOR_PRESENT` pattern.
- New `kaine/modules/hypnos/VOICE_ALIGNMENT.md` document — same
  shape as `kaine/modules/lingua/ABLITERATION.md`: process,
  consent, rollback. Updates `kaine-paper.md` cross-refs.

### 3. `UnslothDPOTrainer.train()` body

The class skeleton in `kaine/modules/hypnos/voice_alignment.py`
gains a real implementation. Pseudocode (real version honors
`VoiceAlignmentConfig.training_device`, `lora_rank`,
`learning_rate`, `dpo_beta`, `max_samples`, `seed`):

```python
# 1. Load base model + tokenizer (4-bit quant via Unsloth)
model, tokenizer = FastLanguageModel.from_pretrained(
    base_model_path,
    load_in_4bit=True,
    device_map={"": config.training_device},
)

# 2. Attach LoRA adapter
model = FastLanguageModel.get_peft_model(
    model, r=config.lora_rank, target_modules=DEFAULT_TARGETS,
)

# 3. Build dataset from DPO pairs (chosen / rejected / prompt)
ds = Dataset.from_list([
    {"prompt": p.prompt, "chosen": p.chosen, "rejected": p.rejected}
    for p in pairs[: config.max_samples]
])

# 4. DPO training step
training_args = DPOConfig(
    output_dir=str(adapter_tmp_dir),
    learning_rate=config.learning_rate,
    beta=config.dpo_beta,
    per_device_train_batch_size=1,
    gradient_accumulation_steps=4,
    num_train_epochs=1,
    seed=config.seed,
    report_to="none",
)
trainer = DPOTrainer(model, args=training_args, train_dataset=ds, tokenizer=tokenizer)
loss = trainer.train().training_loss

# 5. Eval — capability harness + intent-expression similarity
cap_before, cap_after = await self._eval(model_before, model_after)
sim_before, sim_after = await self._intent_expression_sim(...)

# 6. Atomic adapter promotion (or rejection)
if (cap_before - cap_after) <= config.capability_loss_threshold:
    os.replace(adapter_tmp_dir, adapter_final_dir)
    accepted = True
else:
    shutil.rmtree(adapter_tmp_dir, ignore_errors=True)
    accepted = False
```

The function returns a populated `TrainingResult` with:
`accepted`, `adapter_path`, `capability_loss`, `samples_used`,
`dpo_loss`, `sim_before`, `sim_after`, `reason`.

### 4. Capability-eval harness

- New `kaine/modules/hypnos/capability_eval.py`:
  - `CapabilityEval` Protocol: `async eval(model, tokenizer) -> float`.
  - `LocalProbeSetCapabilityEval` default — ships a tiny static
    probe set (~20 multiple-choice items selected from
    permissively-licensed MMLU-style content, OR a KAINE-specific
    set written by the operator at
    `kaine/modules/hypnos/eval_probes/default.jsonl`). Returns a
    score in `[0, 1]`.
  - `NoopCapabilityEval` for tests — always returns the same score.
  - The default eval runs the model on the probe set and computes
    `correct / total`. Pre-training baseline is recomputed on every
    sleep cycle (cheap; <30 s on small models).
- The eval runs on the same device as training (`config.training_
  device`) and is invoked by `UnslothDPOTrainer` before deciding
  whether to promote the adapter.

### 5. Intent-expression similarity check

- After training, run the post-adapter model against the same
  prompts the DPO pairs were built from, and compute cosine
  similarity between the new generated text and each pair's
  `faithful_rendering`. Mean similarity goes into `TrainingResult.
  sim_after` so the evaluation sidecar's
  `voice_tracking.mean_similarity_after` is real (today it's
  whatever the trainer chooses to report — which is nothing).

### 6. Atomic adapter promotion

- Training writes to `<adapter_output_dir>/<timestamp>.tmp/`.
- Eval runs against the in-memory model.
- On accept: `os.replace(<timestamp>.tmp, <timestamp>)` then
  update symlink `<adapter_output_dir>/current` → `<timestamp>/`
  (also via `os.replace` of a temp symlink, so it's atomic).
- On reject: `shutil.rmtree(<timestamp>.tmp)` and log the capability
  loss.
- A retention policy keeps the last N accepted adapters (default
  `[hypnos.voice_alignment].adapter_retention = 5`); older ones
  are evicted to free disk.

### 7. Lingua hot-swap

This is the trickiest integration question. THREE options:

- **(a) Unsloth Studio reload endpoint** — query Unsloth Studio's
  HTTP API for a `POST /v1/internal/reload` (or whatever the
  current Unsloth Studio uses) and pass `{"adapter_path":
  "<current>"}`. Cleanest if Unsloth Studio supports it. Needs
  operator verification on their installed version.
- **(b) Systemd service restart** — `systemctl --user restart
  unsloth-studio.service` after each accepted adapter. Causes a
  brief inference outage (Lingua queues during restart). Simple
  and reliable but visible to users mid-conversation.
- **(c) In-process direct inference during sleep only** — Hypnos
  loads the model via Unsloth's Python API for the eval pass only,
  then writes the adapter and moves on. Lingua keeps talking to
  Unsloth Studio over HTTP and only picks up the new adapter at
  the operator's next manual Unsloth Studio reload.

This change SHIPS option (c) as the default (lowest risk, no live
service interruption, operator stays in the loop for the actual
deployment) plus a `[hypnos.voice_alignment].hot_swap_mode`
config key for `"manual"` / `"reload_endpoint"` / `"restart_service"`
so the operator can opt up later.

### 8. Hypnos integration

- `Hypnos._run_voice_alignment` (already exists) now consults the
  enabled gate AND the env-var gate, then calls
  `UnslothDPOTrainer.train(pairs, config)`. No structural changes;
  just the new gates and the real trainer wired through `boot.py`
  when the extra is installed.

### 9. Tests

- `tests/test_voice_alignment_unsloth_trainer.py` — unit tests against
  a `FakeUnslothBackend` that records the calls without loading a
  real model. Verifies: pair-to-dataset conversion, DPO args
  match config, adapter promotion happens iff capability loss is
  under threshold, retention evicts the oldest, no adapter dir is
  left behind on reject.
- `tests/test_voice_alignment_capability_eval.py` — exercises
  `LocalProbeSetCapabilityEval` against a fake model that always
  returns a fixed answer; asserts score computation is correct.
- `tests/test_voice_alignment_safety_gate.py` — verifies the
  operator-opt-in gate. Without env var, no training; with env var
  but `enabled = false`, no training. With both, the trainer is
  invoked.
- `tests/test_hypnos_voice_alignment_integration.py` — full Hypnos
  cycle with FakeUnslothBackend; asserts the
  `hypnos.cycle_complete` event carries real `dpo_loss`,
  `mean_similarity_before/after`, `adapter_accepted`,
  `capability_score_before/after`.
- `tests/test_voice_alignment_real_unsloth.py` — env-var-gated
  (`KAINE_HAS_UNSLOTH_TRAINING=1`) test that runs an actual tiny
  model (e.g. TinyLlama 1.1B 4-bit) through one DPO step against
  a fixed seed. Skipped by default; the operator runs it to verify
  the install end-to-end.

### 10. Docs

- `kaine/modules/hypnos/VOICE_ALIGNMENT.md` — operator-facing process
  doc mirroring `ABLITERATION.md`. Covers: what voice alignment is,
  what gets changed, opt-in, capability-loss veto, hot-swap mode
  choice, rollback (delete the latest adapter, restart Unsloth
  Studio).
- `SETUP.md` §2.3 — installation of `[training]` extra alongside
  `[audio]` / `[vision]`.
- `FIRST_BOOT.md` — note that voice alignment defaults off; even
  with Hypnos enabled, training only fires after explicit operator
  opt-in.
- `SECURITY.md` §8 — voice alignment as operator-responsibility
  area; capability-loss threshold; adapter rollback procedure.
- `ARCHITECTURE.md` — Layer 4 update noting the trainer is now
  real; cross-ref to VOICE_ALIGNMENT.md.

## Capabilities

### Modified Capabilities

- `hypnos-voice-alignment` (existing) — `UnslothDPOTrainer` body
  becomes real; capability-eval harness lands; atomic adapter
  promotion enforced; safety-gate semantics added.

### New Capabilities

- `voice-alignment-training` — owns the DPO training body, the
  capability-eval contract, atomic adapter promotion, and the
  Lingua hot-swap mode selector.

## Impact

- **New deps:** optional `[training]` extras only — `unsloth`,
  `trl`, `peft`, `datasets`. Production install
  (`pip install -e .`) is unaffected. Operators who want training
  run `pip install -e .[training]`.
- **No code changes to Lingua's chat client.** Hot-swap is handled
  by Hypnos calling out to Unsloth Studio (or via in-process load
  during eval).
- **Default behavior unchanged.** Without `[hypnos.voice_alignment].
  enabled = true` AND `KAINE_VOICE_ALIGNMENT_OPERATOR_APPROVED=1`,
  every sleep cycle still records `voice_alignment` as "skipped"
  exactly as today.
- **Tag** after merge: `v1.4-voice-alignment`.

## Open question for operator

The Lingua hot-swap default is option (c) — Hypnos writes the
adapter, but Lingua/Unsloth Studio doesn't pick it up until the
operator manually reloads. Options (a) and (b) auto-deploy. The
operator should decide before merge whether (c) is the right
default, or whether they want a more aggressive mode out of the
box. This change will ASK the question (via AskUserQuestion) at
the start of implementation and bake the answer into the shipped
default.
