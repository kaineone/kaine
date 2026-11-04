# Spec Delta

## Purpose

Training and registering custom TTS voices from reference audio, covering the dataset pipeline, evaluation harness and voice catalogue registration.

## ADDED Requirements

### Requirement: Dataset is downloaded only with operator consent and verified

The voice-training dataset download command SHALL display the dataset name, estimated size and licence identifier before downloading. It SHALL proceed only after the operator confirms. Downloaded archives SHALL be verified by SHA-256 before extraction, and extraction SHALL not escape its target directory. No dataset SHALL be downloaded at runtime.

#### Scenario: Operator confirms Sam dataset download
- **WHEN** the operator runs the download command and confirms the licence prompt
- **THEN** the Sam dataset is fetched, its SHA-256 matches the pinned digest, and it is extracted under `data/voice_training/sam/`

#### Scenario: Operator declines the licence prompt
- **WHEN** the operator runs the download command and declines
- **THEN** no data is downloaded and the command exits with a non-zero status

---

### Requirement: Zero-shot voice cloning produces a reusable voice embedding

The cloning script SHALL accept a list of reference audio paths and produce a voice embedding file compatible with Qwen3-TTS zero-shot inference. The embedding SHALL be written atomically (temp file then rename). The script SHALL refuse to overwrite an existing embedding without an explicit `--force` flag.

#### Scenario: Clone from Sam reference clips
- **WHEN** the operator runs the cloning script with 3–5 Sam reference clips
- **THEN** a voice embedding file is written under `config/voices/sam/` and can be loaded by the vocal module

---

### Requirement: Single-speaker fine-tune runs under the capped resource budget

The fine-tune script SHALL run under `safe-run.sh` with the `kaine-heavy.slice` memory cap. It SHALL checkpoint after every epoch and resume from the latest checkpoint on restart. It SHALL report GPU memory high-water mark and wall time at completion.

#### Scenario: Fine-tune completes within resource budget
- **WHEN** the operator runs the fine-tune script on the Sam dataset
- **THEN** training completes under the 16 GB memory cap, a checkpoint is written, and metrics are logged

#### Scenario: Fine-tune resumes from checkpoint
- **WHEN** the fine-tune script is restarted after interruption
- **THEN** it resumes from the most recent checkpoint without re-processing completed epochs

---

### Requirement: Evaluation harness scores any voice on standard metrics

The evaluation script SHALL compute intelligibility (character error rate on a held-out transcript set), naturalness (UTMOS or equivalent MOS predictor) and speaker similarity (cosine similarity of speaker embeddings between the synthesised and reference audio). Results SHALL be written as a JSON report. The script SHALL be reusable for any voice, not only Sam.

#### Scenario: Evaluate the Sam voice
- **WHEN** the operator runs the evaluation script against the Sam voice and a transcript set
- **THEN** a JSON report is written with CER, predicted MOS and speaker similarity scores

---

### Requirement: A trained voice is registered in the voice catalogue

A voice entry in `config/voices/<name>/voice.toml` SHALL declare the voice name, the backend (`qwen3-tts`), the asset type (`embedding` or `checkpoint`), the asset path, the dataset licence, and the evaluation report path. The vocal module SHALL load a voice by its catalogue name via `[vocal].voice`.

#### Scenario: Select the Sam voice at boot
- **WHEN** `[vocal].voice = "sam"` is set in `kaine.toml` and the Sam voice catalogue entry exists
- **THEN** the vocal module loads the Sam voice embedding or checkpoint and uses it for synthesis
