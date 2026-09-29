## 1. Prerequisites (each its own change)

- [x] 1.1 `operator-revive-and-preserve`: revive into a running cycle; operator preserve on request; the stage in the bundle.
- [x] 1.2 `faculty-relative-birth`: the birth gate judges only enabled faculties (sleep and consolidation only with Hypnos and Phantasia; a body only with Mundus); birth into the audio/video world.
- [x] 1.3 `snapshot-completeness`: Thymos goals saved; Hypnos schedule restored; the Nous posterior handed to its engine's fallback (Nous has no other belief carry-over); revive-with-extra-module tests for every module. Phantasia training and weight persistence move to the study profile (2.1).
- [x] 1.4 `film-aligned-ignition-log`: a content-free film-position event (item, offset, paused); the broadcast record keeps entry ids, the run id and the broadcast time.
- [x] 1.5 `film-end-preserve`: the programme's end publishes an event and, in study mode, freezes, preserves and stops.
- [x] 1.6 `study-confounds`: Empatheia labels media speech as media, not the operator; a gestating being's speech intents form but its outputs are held.
- [x] 1.7 `ignition-world-model-check`: the runner refuses a step with Phantasia whose bundle did not capture the world model.
- [x] 1.8 `scoped-memory-preservation`: a bundle holds only the preserved being's memories; revive restores them into the reviving line's own collections and replaces their contents; Empatheia preserves its own profiles.
- [x] 1.9 `numpy-text-embedder` task 3: every memory store, snapshot and bundle is stamped with its embedding space, and revive refuses to mix spaces.
- [x] 1.10 `honest-planning-and-training` and `nous-learned-agency`: Nous's per-action EFE is correct at any horizon; only a learning pass counts as consolidation; Nous learns what follows its actions and preserves that model.
- [x] 1.11 Operator decision: whether Nous's intents drive real actions through the existing gates. Decided 2026-09-28: yes, through the existing gates (Nous proposes; Volition disposes). Implemented by OpenSpec change `nous-drives-action`; `[nous].drive_actions` records it per run and allows an observational ablation.
- [x] 1.12 `womb-to-world-transition`: every viewing that follows birth begins with a deterministic crossfade from the womb's bloom field into the programme. Film time starts when the fade ends.
- [ ] 1.13 `run-recording`: every run persists what Nexus displays (privacy-filtered) and Lingua's external utterances. Inner speech is never recorded.

## 2. The study

- [x] 2.1 The four-film manifest (checksummed) and the study profile, which turns on Phantasia training and weight persistence.
- [x] 2.2 The study runner: line roots and isolation, the step loop, the step manifests, resumable after an interruption; it refuses a step whose preservation did not capture the world model while Phantasia is enabled.
- [x] 2.3 The ignition analysis and its report.
- [x] 2.4 A dry run of the runner end to end with a tiny stand-in programme and no entity (fakes), before the real run.
- [ ] 2.5 The real run: `init`, then `run` through the seed, branch, repeat and accumulate steps, with state encryption configured, started by the operator.
- [x] 2.6 The runner follows the seed and branch protocol (revised 2026-09-28):
  - the step order seed, branch 0, repeat, then branch k and accumulate k;
  - start bundles as specified;
  - a working directory and collection prefixes per branch step, per repeat, and per accumulate line;
  - every step on an empty, study-owned bus database, flushed by the runner. The runner refuses a plan whose database numbers include the operator's.
- [x] 2.7 The seed step's birth is automatic. The runner waits for the birth bloom to complete before preserving, and the preservation records the womb's time at birth.
- [x] 2.8 A `kaine-study` compose service built from the cycle image, with the cycle's configuration, secrets and media mounts and a durable study volume. The runner resolves `/models` and the bus by service name inside it. Operator docs.
- [x] 2.9 The analysis compares branch k against branch 0, branch 0 against the repeat, and accumulate k against branch k, and states the revised limits.
- [x] 2.10 A dry run of the revised runner end to end with the stand-in cycle, before the real run.

## 3. Hardware leg (portability program phases 1–4; paused 2026-09-28 except the desktop and, next, the Orin Nano Super)

- [x] 3.1 Phase 1: slim base dependencies into extras; native Redis and Qdrant install paths; one installer for x86-64 and aarch64 that detects the target.
- [x] 3.2 Phase 2: torch-free core backends and slip-driven automatic time dilation.
  - [x] 3.2.1 A NumPy CfC for Soma and Chronos with a persisted reservoir seed (`numpy-cfc`).
  - [x] 3.2.2 One shared NumPy text embedder for Mnemos, Empatheia and Hypnos (`numpy-text-embedder`).
  - [x] 3.2.3 sherpa-onnx speech backends.
  - [x] 3.2.4 Slip-driven automatic time dilation (`entity-clock-injection`, `slip-driven-time-dilation`).
- [ ] 3.3 Phase 3: JAX-free Nous and Phantasia; the Termux (Android arm64) install path; a Pixel 6a profile.
- [ ] 3.4 Phase 4: memory residency and swap for the Orin Nano Super; arm64 images.
- [ ] 3.5 A full entity verified on the desktop, the Orin Nano Super and the Pixel 6a.
