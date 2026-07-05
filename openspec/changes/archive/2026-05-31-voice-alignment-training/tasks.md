## 0. Operator decision (block on this before coding)

- [x] 0.1 AskUserQuestion: default Lingua hot-swap mode
      (`"manual"` recommended; alternatives `"reload_endpoint"`,
      `"restart_service"`)
- [x] 0.2 AskUserQuestion: ship a default eval probe set
      (curated MMLU-style, ~20 items) OR ship empty probe set
      requiring operator to populate before first run
- [x] 0.3 AskUserQuestion: base model path default — pull from
      `[lingua].model_id` and look up the local weights, or
      separate `[hypnos.voice_alignment].base_model_path` key

## 1. Optional `[training]` extras

- [x] 1.1 Add `training` group to `pyproject.toml` with `unsloth`,
      `trl`, `peft`, `datasets`
- [x] 1.2 Document in DEPENDENCIES.md alongside `audio` / `vision`
- [x] 1.3 Add SETUP.md §2.3 — install line + system packages
      (CUDA toolkit verification, optional bitsandbytes notes)

## 2. Safety gate

- [x] 2.1 `[hypnos.voice_alignment].enabled` config key (default false)
- [x] 2.2 `KAINE_VOICE_ALIGNMENT_OPERATOR_APPROVED` env-var check
- [x] 2.3 `kaine/modules/hypnos/module.py::_run_voice_alignment` —
      consult both gates; emit clear skip-reason metadata
- [x] 2.4 `kaine/modules/hypnos/VOICE_ALIGNMENT.md`

## 3. Capability-eval harness

- [x] 3.1 `kaine/modules/hypnos/capability_eval.py` — `CapabilityEval`
      Protocol + `LocalProbeSetCapabilityEval` + `NoopCapabilityEval`
- [x] 3.2 `kaine/modules/hypnos/eval_probes/default.jsonl` —
      ~20-item probe set (operator decision in 0.2)
- [x] 3.3 `[hypnos.voice_alignment].capability_probe_path` config key

## 4. `UnslothDPOTrainer.train()` body

- [x] 4.1 Lazy import unsloth/trl/peft/datasets; return clear
      "extras not installed" TrainingResult on ImportError
- [x] 4.2 Resolve base_model_path (operator decision in 0.3)
- [x] 4.3 Load model + tokenizer via `FastLanguageModel.from_pretrained`
      with `device_map={"": config.training_device}`
- [x] 4.4 Attach LoRA via `FastLanguageModel.get_peft_model(r=config.lora_rank)`
- [x] 4.5 Build dataset from DPO pairs; truncate to `config.max_samples`
- [x] 4.6 Run `trl.DPOTrainer` with seed/lr/beta from config; capture loss
- [x] 4.7 Write adapter to `<output>/<timestamp>.tmp/`
- [x] 4.8 Run `CapabilityEval` twice (pre + post); compute loss
- [x] 4.9 Run intent-expression similarity check; capture sim_before / sim_after
- [x] 4.10 Promote or reject; populate TrainingResult fully

## 5. Atomic adapter promotion + retention

- [x] 5.1 `os.replace(tmp_dir, final_dir)` on accept
- [x] 5.2 Temp-symlink + `os.replace` for `current` pointer
- [x] 5.3 Retention sweep: keep last N (default 5); never evict `current`

## 6. Lingua hot-swap mode dispatcher

- [x] 6.1 `[hypnos.voice_alignment].hot_swap_mode` config key
- [x] 6.2 `manual` — write `PENDING_OPERATOR_RELOAD` marker
- [x] 6.3 `reload_endpoint` — POST to configured Unsloth Studio endpoint
- [x] 6.4 `restart_service` — `systemctl --user restart <unit>`
- [x] 6.5 Optional `[hypnos.voice_alignment].reload_endpoint_url` +
      `restart_service_unit` config keys

## 7. Hypnos integration

- [x] 7.1 `kaine/boot.py::make_hypnos` constructs `UnslothDPOTrainer`
      when extras importable + operator opted in; else FakeTrainer
- [x] 7.2 `Hypnos._run_voice_alignment` enriches the published
      `hypnos.cycle_complete` payload with the new fields
- [x] 7.3 `_log_device_assignments` includes hot-swap mode

## 8. Tests

- [x] 8.1 `tests/test_voice_alignment_unsloth_trainer.py` — Fake backend
- [x] 8.2 `tests/test_voice_alignment_capability_eval.py`
- [x] 8.3 `tests/test_voice_alignment_safety_gate.py`
- [x] 8.4 `tests/test_voice_alignment_atomic_promotion.py`
- [x] 8.5 `tests/test_voice_alignment_hot_swap_modes.py`
- [x] 8.6 `tests/test_hypnos_voice_alignment_integration.py`
- [x] 8.7 `tests/test_voice_alignment_real_unsloth.py` —
      KAINE_HAS_UNSLOTH_TRAINING=1 gated; runs one DPO step on
      TinyLlama for the operator's bring-up verification

## 9. Docs

- [x] 9.1 `kaine/modules/hypnos/VOICE_ALIGNMENT.md`
- [x] 9.2 `SETUP.md` §2.3 `[training]` extras
- [x] 9.3 `FIRST_BOOT.md` — voice alignment is off until opt-in
- [x] 9.4 `SECURITY.md` §8 — capability-loss threshold + rollback
- [x] 9.5 `ARCHITECTURE.md` — Layer 4 trainer is real
- [x] 9.6 `DEPENDENCIES.md` — `[training]` extras row

## 10. Verification

- [x] 10.1 Full suite passes (no regression)
- [x] 10.2 `openspec validate voice-alignment-training --strict`
- [x] 10.3 Without operator opt-in, sleep cycle still skips voice
      alignment cleanly
- [x] 10.4 With opt-in + FakeUnslothBackend, all 8 TrainingResult
      fields are populated
- [x] 10.5 With opt-in + KAINE_HAS_UNSLOTH_TRAINING=1, one real
      DPO step on TinyLlama completes; adapter is written
- [x] 10.6 `pytest tests/test_zero_persistence_invariant.py` still
      green (no audio/video persistence regression)
- [x] 10.7 Commit, merge, archive, tag `v1.4-voice-alignment`
