# Maternal voice, Chatterbox to Sam: phased conversion plan

Date: 2026-11-16

Status: docs only. No source, tests, manifest, or audio are changed by this document. It consolidates the readiness inventory (`docs/records/maternal-voice-sam-readiness-2026-11-16.md`), the prosody-first design (`docs/records/maternal-voice-sam-prosody-design-2026-11-16.md`), the render plan (`docs/records/maternal-voice-sam-render-plan-2026-11-16.md`), and the no-audio smoke plan (`docs/records/maternal-prosody-smoke-plan-2026-11-16.md`).

Purpose: a phased, schedulable tasklist for converting the maternal-voice repertoire from Chatterbox (CMU ARCTIC slt) rendering to Sam (`kaineone/Qwen3-TTS-Sam-0.6B`, speaker `sam`), with prosody-first content. This is a plan, not an authorization to implement. Implementation requires a separate OpenSpec proposal, feature branch, worker first-pass review, and adversarial sign-off.

## Fixed constraints (apply to every phase)

- Runtime reader and layer stay unchanged: `kaine/modules/audition/maternal_voice.py` (`MaternalVoiceRepertoire`, `MaternalVoiceLayer`, `MaternalVoiceParams`, `MANIFEST_FORMAT = 1`).
- Manifest schema stays at format 1. Readers depend on: `format`, `sample_rate`, `initial_unlocked`, `texts_sha256`, `generator`, `reference_voice`, `items`, `total_bytes`, `total_seconds`, and per-take `file`, `sha256`, `frames`, `seconds`, `seed`, `rms_dbfs`.
- Sample rate stays 8 kHz. Qwen3 TTS native output (24 kHz) must be resampled to 8 kHz before FLAC. Runtime check `file_rate * 2 == sample_rate` remains valid.
- Audio format stays mono 16-bit FLAC. Trim, target RMS, peak ceiling, and low-pass remain as documented: `TARGET_RMS_DBFS = -20.0`, `PEAK_CEILING_DBFS = -1.0`, `TRIM_TOP_DB = 40.0`, runtime low-pass default 500 Hz.
- Item ids, kinds (`passage`/`phrase`), take counts, unlock order, and `initial_unlocked = 5` remain unless a later design change deliberately changes them.
- Runtime behaviour is untouched: level_db 6, jitter_db 3, stimulus source, hearing band, unlocked count, boot wiring in `kaine/boot/perception_feed.py`.
- No source implementation happens in this document. All generator/runtime changes go through OpenSpec + PR pipeline.
- Welfare/safety constraints: no audio described as a real mother's voice; no recoverable speech in the channel; provenance honestly declared.

## Phase 0 — Baseline and evidence (no changes)

Goal: establish the regression floor and record the starting state before any implementation.

Tasks:

- [ ] P0.1 Confirm current maternal-voice tests pass against the shipped Chatterbox rendering:
  - `tests/test_maternal_voice.py` (29)
  - `tests/test_maternal_voice_build_context.py` (7)
  - `tests/test_maternal_voice_threads.py` (1)
  - `tests/test_stimulus_source_maternal_voice.py` (11)
- [ ] P0.2 Run `python tools/maintainer/generate_maternal_voice.py --verify` with exit 0 against the current manifest and audio.
- [ ] P0.3 Record baseline commit, manifest hashes (`total_bytes`, `total_seconds`, `texts_sha256`), `git status --porcelain`, and free disk on model/render storage.
- [ ] P0.4 Confirm checkpoint selection: `sam-model-v2/checkpoint-epoch-1` with `tts_model_type: custom_voice` and `spk_id["sam"] = 3000`; verify published model identifier `kaineone/Qwen3-TTS-Sam-0.6B`.
- [ ] P0.5 Confirm available Sam backend: prefer HF cache of `kaineone/Qwen3-TTS-Sam-0.6B`; fall back to local v2 checkpoint. Decide and record in provenance before coding.
- [ ] P0.6 Check storage guardrail: free space on `/run/media/erik/2TBm2Store` (or selected render storage) at least 30 GiB. Stop local models not needed for rendering.

Exit criteria: baseline commit + manifest verified; tests green; checkpoint and backend recorded.

## Phase 1 — Prosody-first content conversion (texts only, no audio)

Goal: replace lexical English in `kaine/modules/audition/maternal_voice_data/texts.toml` with prosody-first material (nonsense/glossolalic syllables) that carries intonation, rhythm, pitch, and vowel colour without recoverable words.

Tasks:

- [ ] P1.1 Draft replacement text candidates for all 20 items (3 passage + 17 phrase, per existing distribution), preserving item ids, kinds, and take counts.
- [ ] P1.2 Apply syllable-design rules: soft consonants, open vowels, no recoverable lexical phrases; keep repeated prosodic motif for the first passage item.
- [ ] P1.3 Run no-audio smoke gate against candidates: `python tools/maintainer/check_maternal_prosody.py --texts ...` exits 0; every item satisfies syllable_density <= 1.8, transient_reduction >= 0.55, readability <= 40.0.
- [ ] P1.4 Per-item diagnostic review: `check_maternal_prosody.py --text "..."` for any edge cases; maintainer confirms no lexical phrase recoverable.
- [ ] P1.5 Back up old lexical `texts.toml` outside generated-data if operator approves; otherwise archive via git history only.
- [ ] P1.6 `texts_sha256` updates implicitly via regeneration; do not hand-edit manifest.

Prosody layer changes in this phase (content layer):

- Repertoire content becomes prosodic notation rather than sentences. `text` field may hold prosody-script material; `text_sha256` still guards reproducibility. No schema change.
- Repeat-motif property is preserved as prosodic repetition, not lexical repetition.
- The neutral, soft-consonant design prevents recognizer transcription leverage.

Exit criteria: candidate texts pass the no-audio smoke gate and maintainer confirms no recoverable phrase.

## Phase 2 — Generator conversion (offline only)

Goal: convert `tools/maintainer/generate_maternal_voice.py` (or a named sibling script) from Chatterbox to Sam, preserving post-processing and manifest contract.

Tasks:

- [ ] P2.1 Implement Sam backend loader supporting two sources in priority order: HF cache `kaineone/Qwen3-TTS-Sam-0.6B`, then local `.../sam-model-v2/checkpoint-epoch-1`. Load with speaker `sam`.
- [ ] P2.2 Implement generation of one take for one item, with deterministic seed and explicit generation parameters. Remove Chatterbox-specific model download, reference-voice download, and CMU ARCTIC dependency.
- [ ] P2.3 Maintain trim (`TRIM_TOP_DB`), target RMS (`TARGET_RMS_DBFS`), peak ceiling (`PEAK_CEILING_DBFS`), and 8 kHz resampling from 24 kHz.
- [ ] P2.4 Implement `--only ID` single-item rendering path for smoke before full regeneration.
- [ ] P2.5 Maintain reuse-existing-takes behaviour and determinism checks (`--verify`).
- [ ] P2.6 Ensure generation stays within resource guardrails: capped run (safe-run.sh 16G), free-space checks, stop unneeded local models.
- [ ] P2.7 Single-item render S2 (one representative item), then `--verify`; confirm all other items remain byte-identical by hash comparison.

Prosody layer changes in this phase (rendering layer):

- Qwen3 TTS native 24 kHz output is resampled to 8 kHz; ensure pitch/intensity extraction remains possible (second harmonic band).
- Generation parameters for Sam (temperature, repetition, instruct prosody if used) must be fixed, named in manifest, and reproducible.
- No runtime prosody filter added; runtime low-pass (default 500 Hz) and hearing-band stay as-is.

Exit criteria: single-item Sam render passes `--verify` and tests; other items unchanged.

## Phase 3 — Manifest field and provenance changes

Goal: update manifest generator/reference-voice blocks to reflect Sam rendering honestly. No per-take new columns; any new provenance lands in the existing `generator` block.

Tasks:

- [ ] P3.1 Replace `generator` fields: remove `chatterbox_tts`, `model_repo` (ResembleAI), `model_revision` (ResembleAI), `exaggeration`, `cfg_weight`, `watermark` (Chatterbox Perth). Add Sam provenance: `sam_tts`, `model_id` (`kaineone/Qwen3-TTS-Sam-0.6B` or local checkpoint path), `checkpoint_path`, `model_revision` (Sam), `speaker: sam`, `native_sample_rate: 24000`, `output_sample_rate: 8000`, `base_seed`, `temperature` or equivalent generation params, `trim_top_db`, `target_rms_dbfs`, `peak_ceiling_dbfs`, `tool`, `watermark` (explicit: none / none declared) or an honest declaration.
- [ ] P3.2 Replace `reference_voice` block: remove CMU ARCTIC `slt` files and attribution. If Sam needs no reference voice, replace with an explicit `reference_voice: none` or equivalent provenance block recording that Sam does not use a reference speaker. If a reference condition is retained, record it honestly.
- [ ] P3.3 Update `maternal_voice_data/README.md` to reflect Sam rendering and remove Perth-watermark claim; update provenance attributions and THIRD_PARTY_LICENSES only if needed.
- [ ] P3.4 Ensure manifest `format = 1`, `sample_rate = 8000`, `initial_unlocked = 5` unchanged.
- [ ] P3.5 Ensure top-level `texts_sha256` and per-take `sha256`, `frames`, `seconds`, `seed`, `rms_dbfs` types and meanings unchanged.

Manifest schema decision: no format bump. If a new required provenance field makes old readers fail, propose a separate schema-change task.

Exit criteria: manifest provenance honest and tests still green.

## Phase 4 — Validation gates (before full regeneration)

Goal: run the complete single-item smoke sequence (render plan S0-S7) and only then proceed.

Tasks (mapping to render plan):

- [ ] P4.1 S0 baseline: tests green, `--verify` green, only pre-existing changes.
- [ ] P4.2 S1 model load: Sam loads without network ambiguity; generated audio nonzero RMS and finite.
- [ ] P4.3 S2 single-item render using the Sam generator; `--verify` green; others byte-identical.
- [ ] P4.4 S3 output contract probe: 8 kHz PCM_16, nonzero frames.
- [ ] P4.5 S4 determinism replay: identical runs produce identical SHA-256 and manifest diff empty.
- [ ] P4.6 S5 intelligibility probe: speech recognizer output inconsistent/empty across takes; manual check no phrase recoverable.
- [ ] P4.7 S6 prosody retention: pitch/intensity contours recoverable after 8 kHz resampling; categories distinguishable.
- [ ] P4.8 S7 regression tests green without test edits.

Additional validations:

- [ ] P4.9 Hearing spectrum check: low-pass keeps energy within maternal-tissue band; no energy above open frequency that violates fetal-hearing stages.
- [ ] P4.10 Prosody-category retention measured with fixed analysis parameters; document parameters.

Exit criteria: S0-S7 all pass for one representative item, plus hearing spectrum and prosody checks.

## Phase 5 — Full regeneration

Goal: regenerate all takes with Sam, prosody-first content, and verified provenance.

Tasks:

- [ ] P5.1 Re-run baseline commands: git status, commit, `--verify`, checkpoint and storage checks.
- [ ] P5.2 Render full repertoire under capped hardware allocation (safe-run.sh 16G; monitor free space; require >= 10 GiB free during render).
- [ ] P5.3 Re-run `--verify` and all four maternal-voice test files.
- [ ] P5.4 Run full determinism replay on complete repertoire; inspect manifest generator block and top-level invariants.
- [ ] P5.5 Run intelligibility probe across all takes; record recognizer commands/parameters and outcomes.
- [ ] P5.6 Run prosody-retention probe across all takes; record contours.
- [ ] P5.7 Archive superseded Chatterbox artefacts (manifest + takes) without deleting unasked. Record render date, seed, checkpoint digest, revision, operator approval in project memory.

Exit criteria: full repertoire regenerated; all gates green; superseded data preserved.

## Phase 6 — Test impact and updates

Goal: ensure test coverage for Sam rendering while keeping runtime tests unchanged.

Runtime tests (must remain unchanged and pass):

- `tests/test_maternal_voice.py`
- `tests/test_maternal_voice_build_context.py`
- `tests/test_maternal_voice_threads.py`
- `tests/test_stimulus_source_maternal_voice.py`
- `tests/test_stimulus_source_signal.py`
- `tests/test_stimulus_source_hearing_band.py`
- `tests/test_stimulus_source_voice_boot.py`

Generation tests (add in same PR after implementation, not before):

- [ ] P6.1 Add generation tests equivalent to current maternal-voice coverage for the Sam-backed renderer: manifest integrity, decode, SHA mismatch, frame counts, 8 kHz contract, determinism.
- [ ] P6.2 Add prosody-content gate to generation test (all items pass check_maternal_prosody thresholds).
- [ ] P6.3 Add prosody-retention smoke (pitch/intensity existence) if practicable offline.
- [ ] P6.4 If any runtime test fails, treat as runtime-contract violation and revisit implementation, not tests.

Test impact summary:

- Runtime module contract is unchanged; no test edits required if contract preserved.
- Generation tests must be added or updated to reference Sam provenance and remove Chatterbox-specific assertions (watermark, ARCTIC, model repo).
- `check_maternal_prosody.py` gates text quality and is not an audio test.

## Phase 7 — Rollback and preservation

Goal: define recovery paths without partial repairs.

Rules:

- Keep original Chatterbox manifest and takes verified until full Sam generation passes `--verify` and tests.
- Do not delete or overwrite superseded data without operator instruction; archive instead.
- If Sam rendering fails late, restore the verified Chatterbox set and manifest atomically; do not repair mixed-source manifests.
- If decoding or determinism fails after changes, revert to last verified render, then correct generator/tests in a separate proposal.
- If resource limits are hit (disk < 10 GiB, OOM), stop, preserve partial data, clean only regenerable artefacts after operator instruction.
- Rollback boundary is the git commit + preserved manifest/audio from Phase 0 and Phase 5; do not mix pre- and post-conversion audio in one manifest.

Rollback checklist:

- [ ] R1 Restore manifest.json and FLAC files from the pre-conversion archive/commit.
- [ ] R2 Re-run `--verify` and the four runtime tests; all green.
- [ ] R3 Confirm Chatterbox README/provenance restored where applicable.
- [ ] R4 Record rollback reason and date in project memory.

## Resource constraints (all phases)

Disk:

- Check free space before and during render: minimum 30 GiB before start, 10 GiB throughout; stop if below.
- Build/caching stays on the KAINE M.2 and bulk M.2, not OS drive. Follow `/home/erik/.claude/CLAUDE.md` resource guardrails.
- No target/build directory exceeds 20 GB; run cleanup after phase completion.
- Archive superseded artefacts on bulk storage, not system drive.

Containers/compute:

- Run renders under capped allocation (`tools/maintainer/safe-run.sh`, 16G inside kaine-heavy.slice) and `--rm` for any containers.
- Stop local models not needed before GPU render (organ/decoder conflicts on GPU 0).
- Prefer the 3070 (GPU 1) for local/Qwen3.8 work; GPU 0 hosts the language organ when an entity runs.

Licensing/provenance:

- Sam model and training data are Apache 2.0 (`kaineone/Qwen3-TTS-Sam-0.6B`; Sam non-binary voice dataset: Accenture Labs/CereProc). Confirm license notices.
- Remove or replace Chatterbox Perth watermark claim; do not present absence of watermark as erasure of a required marker.
- Keep THIRD_PARTY_LICENSES accurate: CMU ARCTIC notice removed if reference voice removed; add Sam/Apache 2.0 if not already present.

Scope guards:

- No changes to runtime perception, hearing band, stimulus source signal, MaternalVoiceLayer, boot wiring, stimulus-source config, or tests beyond regeneration needs.
- Any runtime change is a separate OpenSpec proposal with security review.
- Paper section 7 / appendix A.7 changes are not required for renderer conversion; update only if content claims change.

## Sequencing summary

1. Phase 0 baseline.
2. Phase 1 content replacement + no-audio smoke.
3. Phase 2 generator conversion (single item).
4. Phase 3 provenance/manifest updates (with implementation).
5. Phase 4 full validation gates on one item.
6. Phase 5 full regeneration.
7. Phase 6 generation tests.
8. Phase 7 rollback rules remain available throughout; invoke only on failure.

Implementation should stop at audio + manifest. Wiring, runtime, and paper changes are separate proposals.

## References

- `docs/records/maternal-voice-sam-readiness-2026-11-16.md`
- `docs/records/maternal-voice-sam-prosody-design-2026-11-16.md`
- `docs/records/maternal-voice-sam-render-plan-2026-11-16.md`
- `docs/records/maternal-prosody-smoke-plan-2026-11-16.md`
- `kaine/modules/audition/maternal_voice.py`
- `kaine/modules/audition/maternal_voice_data/README.md`, `texts.toml`, `manifest.json`
- `tools/maintainer/generate_maternal_voice.py`
- `tools/maintainer/check_maternal_prosody.py`
- `docs/09-modules/vocal.md`
- `/home/erik/.claude/CLAUDE.md` (resource guardrails)

Changed path: `/var/home/erik/Projects/kaineone/kaine/docs/records/maternal-voice-sam-conversion-plan-2026-11-16.md`
