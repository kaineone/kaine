# Tasks — on-device-voice-alignment

> Design-of-record from the 2026-06-18 shakedown. Build when the operator gives
> the go. Ships voice-alignment disabled; boots no entity.

## 1. Managed organ-server lifecycle

- [x] 1.1 Organ-server manager: start / stop / reload `llama-server` (or the
      managed unit) with a configurable adapter. Stop SHALL confirm VRAM released
      (poll device free memory); start SHALL confirm the organ answers a smoke
      prompt before reporting ready.
- [x] 1.2 Adapter application on reload: support `--lora <adapter>` and/or
      merge-then-requantize to a fresh GGUF (pick per trainer output). Retain the
      pre-training organ artifact for rollback.
- [x] 1.3 `restart_service` unload/reload via `systemctl --user`; `reload_endpoint`
      still performs the unload step on single-GPU; `manual` keeps the marker file.

## 2. Sleep-phase bracket

- [x] 2.1 In the voice-alignment sleep phase, bracket the existing trainer call:
      quiesce consumers → unload organ → train → reload (with adapter if accepted)
      → resume consumers. Reuse `UnslothDPOTrainer.train()` unchanged.
- [x] 2.2 Failure handling: any bracket step failure logs and the sleep cycle's
      other phases still complete (honor the existing "missing extras don't crash
      sleep" requirement). On training timeout, abort and reload the organ unchanged.
- [x] 2.3 Multi-GPU detection: if a second GPU has headroom to serve + train,
      skip the unload bracket (serve on one device, train on the other).

## 3. base_model_path wiring

- [x] 3.1 Set `[hypnos.voice_alignment].base_model_path` to the local abliterated
      Qwen3.5-4B safetensors (operator config). Trainer loads safetensors, not GGUF.
- [x] 3.2 Document that served (GGUF) and trained-from (safetensors) share one
      abliteration provenance.

## 4. Organ-absent tolerance

- [x] 4.1 Lingua client: a dead/unloaded organ endpoint yields a clean "organ
      resting" deferral, not an exception, during the window.
- [x] 4.2 A/B-divergence eval arm skips (logged as skipped, not failed) while the
      organ is unloaded.
- [x] 4.3 Tests: generation during the window defers cleanly; eval logs a skip;
      consumers resume after reload.

## 5. GPU cooperation

- [x] 5.1 Run the `gpu-preflight` headroom check before reloading the organ;
      report (never kill) if the device is short; Spot supervises the organ process.
- [x] 5.2 Test: reload blocked-and-reported when headroom insufficient; no foreign
      process is terminated.

## 6. Welfare veto + opt-in unchanged

- [x] 6.1 Confirm the capability-loss veto still blocks adapter promotion (the
      reloaded organ uses the accepted adapter only; a vetoed adapter → organ
      reloaded unchanged). Keep the gate-parity test green.
- [x] 6.2 Confirm the two-key opt-in (`enabled = true` +
      `KAINE_VOICE_ALIGNMENT_OPERATOR_APPROVED=1`) still gates the whole path.

## 7. Surface + validate

- [x] 7.1 Nexus: show the training window state (organ resting / training /
      reloading) and the last adapter accept/veto.
- [x] 7.2 `.venv/bin/pytest -q` green; `openspec validate on-device-voice-alignment --strict`.
- [x] 7.3 Confirm shipped `config/kaine.toml` keeps voice-alignment disabled and
      the all-off first-boot guard passes.
