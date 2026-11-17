# Maternal voice, Sam rendering: readiness inventory

Date: 2026-11-16

Status: inventory/readiness only. No source code, tests, manifest, or generated audio changed.

Companion design: `docs/records/maternal-voice-sam-prosody-design-2026-11-16.md`.

## Source checkpoints and training inputs

Training root:
`/run/media/erik/2TBm2Store/kaine/qwen3-tts-training/`

Upstream TTS framework:
- `Qwen3-TTS/` — Qwen3-TTS source (including `finetuning/sft_12hz.py`, `finetuning/prepare_data.py`, examples).
- Upstream repo is Apache 2.0 Qwen3-TTS-12Hz-0.6B-Base materials.

Sam training data:
- `sam-data/train_raw.jsonl`
- `sam-data/train_with_codes.jsonl`
- `sam-data/wav_24k/` — 24 kHz training waveforms (1099 utterances described in checkpoint README).

Fine-tune checkpoints:
- `sam-model/checkpoint-epoch-0/`, `checkpoint-epoch-1/`, `checkpoint-epoch-2/` — first Sam training run family.
- `sam-model-v2/checkpoint-epoch-0/`, `checkpoint-epoch-1/` — second/v2 training run; includes the published model card in `checkpoint-epoch-1/README.md`.
- `sam-model-v2/checkpoint-epoch-1/config.json` declares `tts_model_type: custom_voice`, `spk_id: { "sam": 3000 }`, so `speaker="sam"` is available.
- `sam-model-v2/checkpoint-epoch-1` is the most complete v2 checkpoint (training run dated 2026-11-09; README records 2 epochs, lr 1e-7).

Published/runtime model identifier used elsewhere in KAINE:
- `kaineone/Qwen3-TTS-Sam-0.6B` (Apache 2.0), speaker `sam`.
- No local HuggingFace cache for this repo was found on this host. A generator implementation will need either an HF fetch/cache or direct use of the local checkpoint directory, e.g. `.../sam-model-v2/checkpoint-epoch-1`.

## Existing maternal voice tests

Runtime reader and layer:
- `tests/test_maternal_voice.py` — 29 tests; manifest integrity, decode, unlocked count, layer behaviour.
- `tests/test_maternal_voice_build_context.py` — 7 tests.
- `tests/test_maternal_voice_threads.py` — 1 test.

Stimulus-source maternal voice coverage:
- `tests/test_stimulus_source_maternal_voice.py` — 11 tests.
- Related: `tests/test_stimulus_source_signal.py` (20), `tests/test_stimulus_source_hearing_band.py` (13), `tests/test_stimulus_source_voice_boot.py` (7).

Runtime data and generation script:
- `kaine/modules/audition/maternal_voice.py` — reader/layer; unchanged by this inventory.
- `kaine/modules/audition/maternal_voice_data/` — 40 FLAC files + `manifest.json` + `texts.toml` + README.
- `tools/maintainer/generate_maternal_voice.py` — current Chatterbox implementation.

Manifest current state:
- format 1; sample rate 8000.
- 20 items; initial_unlocked 5.
- total takes 40 (as shipped).
- generator block declares Chatterbox 0.1.6, model repo `ResembleAI/chatterbox`, revision `5bb1f6ee...`, Perth watermark.
- reference_voice block declares CMU ARCTIC `slt` reference files.

## Config: `perception_feed.stimulus_source.voice`

Location: `config/kaine.toml`, `[perception_feed.stimulus_source.voice]`.

Current knobs:
- `enabled = true`
- `level_db = 6.0`
- `jitter_db = 3.0`
- `slot_seconds = 30.0`
- `episode_probability = 0.2`
- `repeat_share = 0.25`
- `unlock_seconds = 3600.0`
- `pause_min_seconds = 0.5`
- `pause_max_seconds = 1.5`

Related runtime contract:
- maternal voice only runs with `[perception_feed.audio].sample_rate = 16000` (voice takes are 8 kHz).
- `MaternalVoiceRepertoire.load(sample_rate=sr, lowpass_hz=...)` checks decoded FLAC rates against runtime expectations.
- Runtime low-pass and level/headroom are unchanged by rendering backend choice.

## Runtime backend switching hooks

Finding: maternal voice has no runtime TTS backend and no runtime backend-switching hook. It is an offline-file, read-only runtime module:
- `MaternalVoiceRepertoire.load(...)` reads the shipped manifest and FLAC files only.
- `MaternalVoiceLayer` plays from pre-rendered files; nothing is synthesized at runtime.
- Boot wiring in `kaine/boot/perception_feed.py` enables/disables it through `MaternalVoiceParams.enabled`.
- No BackendRegistry entry exists for maternal voice; sampler switching hooks seen elsewhere are for vocal TTS, not maternal voice.
- Optional speech recognizer tests in `tests/test_stimulus_source_maternal_voice.py` only (intelligibility/readiness coverage), not runtime synthesis.

Runtime switching-like entry points that determine behaviour:
- `[perception_feed.stimulus_source.voice].enabled`
- `[perception_feed.stimulus_source.hearing].enabled` determines voice low-pass at load (`HEARING_TOP_TONE_HZ` vs soundscape `lowpass_hz`).
- ` MaternalVoiceRepertoire.load(sample_rate=...)`, where a mismatch fails boot unless voice is disabled.
- Shuffle/provenance occurs in generation, not runtime.

## Blockers / inputs for a Sam-based implementation

1. Design-only state: no implementation has landed; source and tests still describe Chatterbox rendering.
2. Generator rewrite needed: `tools/maintainer/generate_maternal_voice.py` currently renders through Chatterbox and records Chatterbox-specific metadata and the Perth watermark.
3. Prosody-first content decision required: `texts.toml` still contains lexical English sentences; implementation must replace or transform them into nonsense/prosodic material and validate unrecoverable speech.
4. Intelligibility test absent: need runtime/generator validation that speech recognizer output is not consistent; currently no recognizer test in the maternal voice suite.
5. Prosody retention test absent: need pitch/intensity contour recoverability check after 8 kHz resampling.
6. Checkpoint selection: choose between `sam-model` and `sam-model-v2`; v2 has the published Sam model card and complete README. Local checkpoints are HF-format and likely direct-loadable.
7. Model provenance must be honest: manifest generator block must record selected checkpoint path/repo and revision; must remove or replace CMU ARCTIC reference dependency if Sam replaces it.
8. License/watermark declaration must be updated from Chatterbox Perth watermark to an honest Sam/no-watermark declaration.
9. Determinism must be revalidated with a fixed seed and metadata set for Qwen3 TTS.
10. GPU/runtime resource guardrails apply: rendering should follow disk/container build rules and check free space before large operations.
11. Output sampling: Qwen3 TTS native output is 24 kHz; must resample to 8 kHz before FLAC; existing `file_rate * 2 == sample_rate` contract depends on 8 kHz.
12. Tests must continue passing against unchanged runtime module and schema; any runtime behaviour changes should be a separate proposal.

## Proposed next implementation step

First slice should be generator-only, with runtime, manifest schema, and existing tests untouched:

1. Add a generator path in `tools/maintainer/generate_maternal_voice.py` (or a clearly named sibling maintainer script) that synthesizes through Qwen3 TTS using speaker `sam`, with an explicit model selector:
   - prefer `kaineone/Qwen3-TTS-Sam-0.6B` if HF cache is available, otherwise local `.../sam-model-v2/checkpoint-epoch-1`.
2. Implement offline generation for one representative item/take first, at 8 kHz output, with manifest-compatible metadata.
3. Run SHA/minifest/decode verification (`--verify`) on that subset.
4. Add prosody-first content to the texts source and an intelligibility/sanity validation step before full regeneration.
5. Only after subset validation, add an OpenSpec proposal for full rendering and regeneration; regenerate all takes; then add or extend generation tests covering Sam-backed rendering while keeping `test_maternal_voice*.py` and stimulus-source maternal voice tests unchanged.

Return changed path: `/var/home/erik/Projects/kaineone/kaine/docs/records/maternal-voice-sam-readiness-2026-11-16.md`.
