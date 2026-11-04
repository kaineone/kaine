# Design

## Context

Qwen3-TTS-0.6B-Base is the main TTS engine (CTO directive 2026-11-03). It supports both zero-shot voice cloning from reference audio and single-speaker fine-tuning. The Sam nonbinary voice dataset (~6 h, Apache 2.0) is available on GitHub. The vocal module already has a backend abstraction; this work adds a voice asset alongside the existing default, not a new backend.

## Goals / Non-Goals

**Goals:**
- Produce a usable Sam voice for public-facing narration (paper, docs)
- Establish a reusable voice-training pipeline for future voices
- Keep the operator in control of dataset download and training

**Non-Goals:**
- Multi-speaker training or voice mixing
- Runtime voice switching (the voice is selected at boot)
- Modifying the vocal module's synthesis path or affect-driven prosody
- Training on proprietary or non-permissive datasets

## Decisions

**D1. Two-phase approach (zero-shot first, fine-tune if needed).**
Zero-shot cloning is fast (~minutes) and non-destructive. Fine-tuning takes hours and GPU budget. Try the cheap option first. The evaluation harness gates the decision: if CER < 5%, MOS > 3.5 and speaker similarity > 0.85, the zero-shot voice is good enough.
_Alternative: skip straight to fine-tuning. Rejected because it wastes GPU time if zero-shot suffices._

**D2. Reference clip selection: 3–5 clips, 10–30 s each, diverse prosody.**
Qwen3-TTS zero-shot quality depends on reference clip quality more than quantity. Select clips covering declarative, interrogative and emphatic prosody from different Sam speakers. The selection script filters by SNR (> 20 dB) and duration.
_Alternative: use all clips. Rejected because Qwen3-TTS embedding extraction is not designed for hundreds of clips._

**D3. Fine-tune recipe: LoRA on the speech decoder, frozen text encoder.**
Consistent with the voice-alignment-training spec's approach. Rank 16, learning rate 1e-5, 3 epochs. The text encoder stays frozen because we want voice quality, not language capability changes.
_Alternative: full fine-tune. Rejected: 0.6B is small but the dataset is only 6 h; LoRA reduces overfitting risk and keeps the checkpoint small (~50 MB)._

**D4. Voice catalogue: TOML entries under `config/voices/<name>/`.**
A voice entry is a TOML file naming the asset, backend and licence. The vocal module reads the catalogue at boot. This is simpler than a database and version-controllable.
_Alternative: embed voice metadata in `kaine.toml`. Rejected: voices are independent assets that may be added or removed without touching the main config._

**D5. Evaluation harness: CER + UTMOS + speaker similarity.**
CER measures intelligibility (via Whisper transcription of synthesised audio compared to the input text). UTMOS predicts mean opinion score without human raters. Speaker similarity uses a speaker-verification embedding model (e.g. WeSpeaker or ECAPA-TDNN via sherpa-onnx). All three are automatable and reproducible.
_Alternative: human listening test only. Rejected as primary gate because it is not reproducible, but the operator listening test remains as a final sanity check._

**D6. Dataset storage: `data/voice_training/sam/` on the bulk M.2.**
Follows the existing pattern for large data assets. Never on the OS drive (memory: OS drive nearly full). The download script writes to this path and the fine-tune script reads from it.

## Risks / Trade-offs

- **Zero-shot quality may be insufficient for narration.** → Mitigated by phase 2 fine-tuning.
- **Sam dataset has multiple speakers; single-speaker fine-tune needs speaker selection.** → The dataset metadata includes speaker IDs. Select the speaker with the most data and best SNR, or combine the top 2–3 if they are acoustically similar.
- **UTMOS and speaker-similarity models need download.** → Pin by digest, download with operator consent alongside the dataset, same verification pattern.
- **Fine-tuning on 12 GB VRAM (RTX 4070 Super) may require gradient checkpointing.** → LoRA rank 16 on 0.6B should fit; if not, reduce batch size or enable gradient checkpointing. The `safe-run.sh` cap catches OOM before the system swaps.

## Open Questions

- Which Sam speaker(s) to use for fine-tuning: defer to phase 1 evaluation (listen to zero-shot clones of each and pick the best baseline).
- Whether UTMOS or PESQ is the better MOS predictor for this voice: defer to evaluation harness implementation; support both and compare.
