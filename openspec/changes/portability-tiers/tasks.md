## 1. Backend-selection framework

- [ ] 1.1 Define a `Backend` resolution helper (lazy-import + declared
      fallback + structured failure) reused by every heavy module
- [ ] 1.2 Add `[<module>].backend` config keys with Tier-2 defaults that
      reproduce today's behavior exactly (Ollama / faster-whisper / Chatterbox /
      torch-DINOv2 / sentence-transformers / Qdrant)
- [ ] 1.3 Wire backend resolution behind each existing client interface without
      changing the module body or its published event shapes
- [ ] 1.4 Surface backend-load failures on the Nexus health surface

## 2. First edge backend (prove the seam)

- [ ] 2.1 llama.cpp / GGUF backend for Lingua behind `lingua/client.py`
- [ ] 2.2 Confirm Lingua still emits identical `lingua.speech` / eval events
      under either backend (A/B baseline must still use the SAME model)
- [ ] 2.3 sqlite-vec backend for Mnemos behind `mnemos/storage.py`, same CLS
      collections + `query_points`-equivalent API

## 3. Remaining edge backends (staged)

- [ ] 3.1 whisper.cpp STT backend (Audio-In)
- [ ] 3.2 Piper TTS backend (Audio-Out)
- [ ] 3.3 ONNX / dinov2.cpp vision backend (Topos), periodic-mode
- [ ] 3.4 ONNX MiniLM embeddings backend (Mnemos)
- [ ] 3.5 Document emotion2vec+ as Tier-2-only (no edge backend); ensure it
      disables cleanly below Tier 2

## 4. Tier profiles

- [ ] 4.1 Layered config load: shipped → profile overlay → local → secrets,
      selected by `KAINE_PROFILE` / `--profile`; local still wins
- [ ] 4.2 Ship `config/profiles/tier0.toml` … `tier3.toml` (toggles + backends +
      device + cycle-rate hints)
- [ ] 4.3 Guard test: profiles never enable the entity by default and never
      embed the private voice

## 5. Host probe

- [ ] 5.1 `kaine.hardware.recommend_tier` (RAM, arch, CUDA/MPS, torch import)
- [ ] 5.2 `scripts/probe-host` CLI prints recommendation + capability-matrix row
- [ ] 5.3 Probe recommends only; never auto-applies a profile

## 6. Capability matrix + docs

- [ ] 6.1 Capability matrix in DEPENDENCIES.md / a new `docs/deployment-tiers.md`
- [ ] 6.2 Paper §4 / §10 updated with the tier ladder (see paper edit)
- [ ] 6.3 Per-tier install notes (which extras each tier needs)

## 7. Validation

- [ ] 7.1 Tier-2 default path is byte-for-byte behavior-preserving (existing
      suite green with no profile selected)
- [ ] 7.2 A degraded-backend boot logs + surfaces the reason and does not crash
- [ ] 7.3 `openspec validate portability-tiers --strict`
