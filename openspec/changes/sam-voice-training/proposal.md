# Proposal

## Why

KAINE needs a neutral, inclusive narration voice for public-facing audio (paper narration, documentation read-aloud). The Sam nonbinary voice dataset (Apache 2.0, ~6 hours of ethically sourced recordings from nonbinary, trans and intersex voice actors) is a good fit: permissively licensed, purpose-built for inclusive representation, and large enough for a single-speaker fine-tune if zero-shot cloning falls short. This is a non-priority roadmap item that does not block the entity or the development run.

## What Changes

- **Phase 1 — zero-shot cloning:** select 3–5 reference clips from the Sam dataset, run Qwen3-TTS-0.6B-Base zero-shot voice cloning, evaluate intelligibility, naturalness and speaker similarity with automated metrics and a short operator listening test.
- **Phase 2 — single-speaker fine-tune (conditional):** if phase 1 quality is insufficient, fine-tune Qwen3-TTS-0.6B-Base on the full Sam dataset with a single-speaker recipe, then re-evaluate.
- **Voice asset:** a saved voice embedding (phase 1) or a fine-tuned checkpoint (phase 2) registered in the vocal module's voice catalogue so it can be selected with `[vocal].voice = "sam"`.
- **Evaluation script:** a repeatable script that scores any voice on the standard metrics, reusable for future voice work.

## Capabilities

### New Capabilities
- `voice-training`: Training and registering custom TTS voices from reference audio, including zero-shot cloning and optional single-speaker fine-tuning. Covers the dataset pipeline, evaluation harness and voice catalogue registration.

### Modified Capabilities
_None. The vocal module's runtime behavior is unchanged; this adds a new voice asset alongside the existing default._

## Impact

- **Code:** new `kaine/voice_training/` package (dataset loader, cloning script, fine-tune recipe, evaluation harness), plus a voice-catalogue entry under `config/voices/`.
- **Dependencies:** Qwen3-TTS already installed (main TTS engine per CTO directive). The fine-tune path needs the `[training]` extras (already gated by the voice-alignment-training spec). No new runtime dependencies.
- **Data:** the Sam dataset (~6 h WAV, ~3 GB) is downloaded by an explicit operator command with licence confirmation, never at runtime. Stored under `data/voice_training/sam/` on the bulk M.2.
- **Systems:** no services started or stopped; training runs as an offline script under `safe-run.sh`.
