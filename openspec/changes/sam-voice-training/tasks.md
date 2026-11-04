# Tasks

## 1. Dataset pipeline

- [ ] 1.1 Download script (`scripts/voice_training/download_sam.py`): display dataset name, size (~3 GB) and licence (Apache 2.0), prompt for confirmation, fetch from GitHub, verify SHA-256, extract under `data/voice_training/sam/`. Tests: mock download with a small archive; SHA mismatch refused; decline exits non-zero.
- [ ] 1.2 Reference-clip selector (`kaine/voice_training/select_refs.py`): filter Sam clips by SNR (> 20 dB) and duration (10–30 s), select 3–5 clips covering diverse prosody, write the selection list. Tests: synthetic clips with known SNR; too-short clips excluded.

## 2. Zero-shot cloning (phase 1)

- [ ] 2.1 Cloning script (`scripts/voice_training/clone_voice.py`): load Qwen3-TTS-0.6B-Base, extract voice embedding from the selected reference clips, write the embedding atomically under `config/voices/sam/embedding.pt`. Tests: embedding file written; `--force` required to overwrite; vocal module can load the embedding.
- [ ] 2.2 Synthesise evaluation sentences (20 held-out sentences) with the Sam embedding and write WAV files under a temp directory for the evaluation harness.

## 3. Evaluation harness

- [ ] 3.1 CER scorer (`kaine/voice_training/eval_cer.py`): transcribe synthesised audio with Whisper (via Speaches or sherpa-onnx), compute character error rate against ground-truth text. Tests: known-good audio scores CER < 1%; garbled audio scores CER > 50%.
- [ ] 3.2 MOS predictor (`kaine/voice_training/eval_mos.py`): score naturalness with UTMOS (pin model by digest, download with operator consent). Tests: real speech scores > 3.0; silence scores < 2.0.
- [ ] 3.3 Speaker similarity (`kaine/voice_training/eval_similarity.py`): compute cosine similarity of speaker embeddings (WeSpeaker or ECAPA-TDNN via sherpa-onnx) between synthesised and reference audio. Tests: same-speaker pair > 0.9; different-speaker pair < 0.7.
- [ ] 3.4 Report aggregator (`scripts/voice_training/evaluate.py`): run all three scorers, write a JSON report with CER, MOS and similarity, and print a pass/fail summary against the thresholds (CER < 5%, MOS > 3.5, similarity > 0.85).

## 4. Single-speaker fine-tune (phase 2, conditional)

- [ ] 4.1 Data preparation (`kaine/voice_training/prepare_dataset.py`): select speaker(s) from the Sam metadata, split into train/val (90/10), write a manifest compatible with Qwen3-TTS fine-tuning. Tests: manifest well-formed; no audio file missing; val set has no overlap with train.
- [ ] 4.2 Fine-tune script (`scripts/voice_training/finetune_sam.py`): LoRA rank 16 on the speech decoder, frozen text encoder, 3 epochs, checkpoint after every epoch, resume from latest checkpoint on restart. Runs under `safe-run.sh` with `kaine-heavy.slice`. Tests: checkpoint written after epoch 1; resume skips epoch 1; GPU memory high-water mark logged.
- [ ] 4.3 Re-evaluate the fine-tuned voice with the same harness (task 3.4) and write a comparison report.

## 5. Voice catalogue and integration

- [ ] 5.1 Voice catalogue entry (`config/voices/sam/voice.toml`): name, backend (`qwen3-tts`), asset type (`embedding` or `checkpoint`), asset path, dataset licence (Apache 2.0), evaluation report path. The vocal module reads the catalogue at boot when `[vocal].voice` is set.
- [ ] 5.2 Vocal module integration: when `[vocal].voice = "sam"` is configured, load the Sam voice asset and use it for synthesis. Tests: vocal module boots with the Sam voice and synthesises audio; an unknown voice name is a configuration error.

## 6. Documentation and validation

- [ ] 6.1 `docs/appendix-a-configuration/modules.md`: document `[vocal].voice` and the voice catalogue format.
- [ ] 6.2 Operator listening test: synthesise 5 representative sentences, present to the operator for a subjective quality check before declaring the voice ready.
- [ ] 6.3 `openspec validate sam-voice-training --strict` passes.
