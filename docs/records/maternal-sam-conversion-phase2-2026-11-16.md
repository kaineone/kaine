# Maternal voice Sam conversion — phase 2 adapter architecture

Date: 2026-11-16

Status: design only. No source, tests, manifest, or audio changed. Allowed edit is this document only.

Purpose: define a small adapter architecture that lets `tools/maintainer/render_maternal_voice_sam.py` (plan emitter) drive `tools/maintainer/generate_maternal_voice.py` (manifest/audio authoring engine) without either script absorbing the other's responsibilities, while preserving the format-1 manifest contract and the runtime in `kaine/modules/audition/maternal_voice.py`.

## Problem

Two scripts currently exist with overlapping but distinct contracts:

- `render_maternal_voice_sam.py` is a **plan emitter only**: no torch, no synthesis, no manifest write. It publishes the Sam model identity, prosody-muffling profile, and render-plan steps. It already carries a stable JSON shape via `build_render_plan()` (aliases: `build_plan`, `build_plan_json`, `get_render_plan`, `get_plan`, `render_plan_fn`, `make_plan`).
- `generate_maternal_voice.py` is the **heavy authoring engine**: validation, reference download, Chatterbox generation, trim/RMS/peak/8 kHz write, manifest assembly, `--verify`, `--only`.

Goal of phase 2: swap the engine's voice backend from Chatterbox to Sam **without** rewriting either script in place, and without coupling the plan schema to torch. The swap happens behind an adapter so the engine keeps owning disk I/O, hashing, and manifest assembly, while Sam owns waveform synthesis.

## Target architecture (small, three components)

```
  render_maternal_voice_sam.py      generate_maternal_voice.py
        (PlanEmitter)                    (ManifestAuthor)
              |                               |
              |  RenderPlan (JSON, frozen)    |
              v                               v
       +----------------+            +----------------+
       |  SamAdapter     | <-------- |  VoiceBackend   |
       |  (new, small)   |           |  (protocol)     |
       +----------------+            +----------------+
              |
              v
       Qwen3 TTS (HF cache or local v2 checkpoint), speaker="sam"
```

### Component A — `VoiceBackend` protocol (interface)

A minimal protocol defined in the generator namespace (documentation-level; no code yet). Conceptual methods:

- `load(device: str) -> None` — materialise the model; lazy imports live here.
- `speaker() -> str` — must return `"sam"`.
- `native_sample_rate() -> int` — must be `24000` for Sam.
- `render(text: str, *, seed: int) -> np.ndarray` — return float64 mono waveform at native SR; no trim/RMS/normalisation. Determinism owned by adapter (seed passed in).
- `provenance() -> dict` — model id/path, checkpoint, revision, speaker, native rate, generation params (temperature etc.). Used verbatim by manifest `generator` block.
- `watermark() -> str` — explicit declaration (`"none declared"` for Sam; must not claim Perth).

Engine calls ONLY these methods. No Chatterbox symbols leak past the adapter.

### Component B — `SamAdapter` (implements `VoiceBackend` for Sam)

- Constrains backend selection to the documented priority order: HF cache `kaineone/Qwen3-TTS-Sam-0.6B`, then local `/run/media/erik/2TBm2Store/kaine/qwen3-tts-training/sam-model-v2/checkpoint-epoch-1`.
- Records the **selected** backend + checkpoint path into provenance before any synthesis.
- Passes `speaker="sam"`; asserts `spk_id["sam"] == 3000` at load when inspectable (config.json).
- Exposes no reference-voice / CMU-ARCTIC download surface.
- Keeps generation parameters fixed, named, and reproducible (`temperature`, repetition penalties, etc.) — constants at module top, not inline.

### Component C — `ChatterboxBackend` (legacy, retained temporarily)

The **existing** Chatterbox behaviour wrapped behind the same `VoiceBackend` protocol. Purpose: rollback and byte-for-byte regression comparison during phase 2 only. It keeps `REFERENCE_FILES`, CMU-ARCTIC download, watermark declaration. Removed only after a full Sam run passes S4/S6/S7.

### Engine (generator) changes under the adapter

Engine keeps all non-voice responsibilities:
- arg parsing (`--texts`, `--out`, `--reference-dir` deprecation, `--device`, `--only`, `--verify`);
- `load_texts` validation + `_ID_RE`;
- output dir creation, `reuse_existing_takes`, `verify_manifest`;
- seed scheme `BASE_SEED + 1000*index + take` (preserved);
- post-processing pipeline exactly: trim (`TRIM_TOP_DB`), 24 kHz→8 kHz resample (soxr_hq), RMS normalise to `TARGET_RMS_DBFS`, peak limit to `PEAK_CEILING_DBFS`, int16 PCM, FLAC write;
- manifest assembly except voice-specific keys, which come from `backend.provenance()` and `backend.watermark()`.

Engine gains:
- `--renderer {chatterbox,sam}` (default `chatterbox` until smoke passes; flip to `sam` after full run) for rollback-by-flag.
- Selection of backend class based on flag; backend loaded after reference step (Sam needs none).
- Deprecation (not deletion) of Chatterbox-only paths until they are unused; PR pipeline removes them after Sam full green.

### Plan emitter (`render_maternal_voice_sam.py`) as the contract owner

The plan emitter becomes the **single source of truth** for:
- model identity (`sam_model()`),
- prosody profile (`prosody_profile()`),
- render steps.

The adapter reads the plan JSON produced by `build_render_plan()` to validate engine configuration before rendering (assert that `output_sample_rate == 8000`, `output_format == FLAC`, `pcm == PCM_16`, `spectral_ceiling_hz == 300`, `synthesizes_audio` flag handling). It does **not** re-implement the plan; it consumes it as a frozen contract (`mode == "dry-run"` accepted; no audio implied).

## Boundaries

1. **No synthesis in the plan emitter.** It never imports torch librosa or soundfile. Adapter breaks this boundary if it lets synthesis leak into the plan module.
2. **No manifest assembly in the adapter.** Adapter returns waveforms + provenance; engine assembles. Adapter code lives only under `tools/maintainer/` (or a future `kaine/.../maternal_voice_render/` if a package is later justified).
3. **Runtime contract immutable**: manifest `format == 1`, `sample_rate == 8000`, fields `format, sample_rate, initial_unlocked, texts_sha256, generator, reference_voice, items, total_bytes, total_seconds`, per-take `file, sha256, frames, seconds, seed, rms_dbfs`. `MaternalVoiceRepertoire.load()` checks `file_rate * 2 == sample_rate`. Adapter engine must not change any of these.
4. **No runtime/test changes** in phase 2 source work. Adapter is offline tooling only.
5. **No mixing backends in one manifest.** Every take in a manifest was produced by one backend, named in `generator`. Mixed-source manifests are forbidden (rollback boundary).
6. **Resource guardrails**: capped run (`safe-run.sh` 16 G), free space >= 10 GiB during render, >= 30 GiB before.

## Rollback

- **Flag rollback**: `--renderer chatterbox` reverts authoring to the legacy path with no code change; manifest provenance correctly labels Chatterbox.
- **Data rollback**: preserve baseline Chatterbox manifest+FLAC from Phase 0 (archive, do not delete). Restore atomically: manifest + all take files together. Never repair mixed-source manifests.
- **Manifest rollback**: if determinism fails post-swap, revert to last verified render commit, then fix in a separate proposal. Do not hand-patch manifest.
- **Removal order**: only after a full Sam run passes S2–S7 and full regeneration passes determinism, may `ChatterboxBackend` and the CMU-ARCTIC/reference-download code be deleted in a separate PR.
- **No partial repairs**: if a Sam run fails late, restore verified baseline, record failure, do not attempt in-place fix.

## Test plan (add in phase-2 implementation PR, not before)

### Unit tests (no torch, no model)

1. `test_render_plan_contract` — assert `build_render_plan()` output has required keys, sample rate 8000, format FLAC, PCM_16, ceiling 300 Hz, synthesizes_audio False; `--dry-run --json` round-trips.
2. `test_adapter_selector` — mock filesystem: HF cache present → HF backend selected; absent → local checkpoint; neither → clear error, no silent fallback.
3. `test_adapter_provenance` — provenance includes model id/path, checkpoint, revision, speaker="sam", native_sample_rate=24000, output_sample_rate=8000, generation params; watermark != Perth; no `watermark: chatterbox`.
4. `test_post_processing_pipeline` — fixed input waveform → trim/RMS/peak/resample/FLAC round-trip deterministic bytes (can mock renderer).
5. `test_manifest_assembly_sam` — engine assembles manifest with `generator` from backend; format 1; all required fields.

### Integration tests (model, offline, capped)

6. `test_sam_load_offline` — load with selected checkpoint; no network ambiguity; speaker resolution.
7. `test_single_take_sam` (S2) — render one item, `--verify` green; others byte-identical.
8. `test_output_contract` (S3) — probe 3 files: 8 kHz, PCM_16, nonzero frames.
9. `test_determinism_replay` (S4) — rerun identical invocation → identical SHA-256 + manifest diff empty.
10. `test_intelligibility` (S5) — recognizer unstable/empty; no recoverable phrase.
11. `test_prosody_retention` (S6) — pitch/intensity contours recoverable after resampling; categories distinguishable.
12. `test_regression_runtime` (S7) — the four runtime test files unchanged and green.

### Contract / gate tests

13. `test_plan_engine_agreement` — engine refuses to run if plan-vs-engine rates/formats diverge (adapter validates).
14. `test_no_mixed_source` — engine rejects a partial reuse that would mix backend labels in one manifest.

## Open decisions (record in provenance, not in code)

- Backend priority confirmation (HF cache vs local v2) — already decided in render-plan; adapter honours it.
- Whether `--reference-dir` is retained as no-op/deprecated or removed; default behaviour documented before deletion.
- exact Sam generation params (`temperature`, repetition, etc.) — must be fixed and recorded.
- position of adapter module (keep under tools or promote to a small package) — decide after smoke.
- determinism of Qwen3 TTS on GPU across identical seeds — verify S4 before full run.

## References

- `docs/records/maternal-voice-sam-conversion-plan-2026-11-16.md`
- `docs/records/maternal-voice-sam-render-plan-2026-11-16.md`
- `docs/records/maternal-voice-sam-readiness-2026-11-16.md`
- `docs/records/maternal-voice-sam-prosody-design-2026-11-16.md`
- `tools/maintainer/render_maternal_voice_sam.py`
- `tools/maintainer/generate_maternal_voice.py`
- `kaine/modules/audition/maternal_voice.py`
