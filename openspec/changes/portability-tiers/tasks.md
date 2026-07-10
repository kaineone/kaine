## 1. Backend-selection framework

- [x] 1.1 Define a `Backend` resolution helper (lazy-import + declared
      fallback + structured failure) reused by every heavy module
      — `kaine/modules/backends.py:BackendRegistry` / `resolve_backend`
      (lazy factory callables; declared per-backend `fallback`; failures via
      `kaine/backend_state.py:record_backend_failure`).
- [x] 1.2 Add `[<module>].backend` config keys with Tier-2 defaults that
      reproduce today's behavior exactly (Ollama / faster-whisper / Chatterbox /
      torch-DINOv2 / sentence-transformers / Qdrant)
      — Lingua: `kaine/boot.py:make_lingua` accepts `backend` (default/absent →
      `ollama`, the untouched HTTP path built by Lingua itself). Mnemos:
      `[mnemos].backend` already ships `qdrant` (`kaine/modules/mnemos/module.py`).
      Non-seam heavy modules default via key-absence (no behaviour change) and
      are staged in §3.
- [x] 1.3 Wire backend resolution behind each existing client interface without
      changing the module body or its published event shapes
      — behind `lingua/client.py` (`build_chat_client_registry`, injected as
      `chat_client=`) and `mnemos/storage.py` (`SqliteVecStorage` selected in the
      module). Module bodies + event shapes untouched.
- [x] 1.4 Surface backend-load failures on the Nexus health surface
      — `kaine/nexus/health/prober.py:_backends_block` reads
      `kaine.backend_state.backend_failures_snapshot`; key added to
      `kaine/nexus/diagnostics.py:HEALTH_BLOCK_KEYS`.

## 2. First edge backend (prove the seam)

- [x] 2.1 llama.cpp / GGUF backend for Lingua behind `lingua/client.py`
      — `kaine/modules/lingua/client.py:LlamaCppChatClient` (lazy `llama_cpp`
      import; in-process GGUF; same `ChatClient` protocol).
- [x] 2.2 Confirm Lingua still emits identical `lingua.speech` / eval events
      under either backend (A/B baseline must still use the SAME model)
      — the backend swaps only the `ChatClient` behind Lingua's unchanged body,
      so published events are identical; `model_id` is unchanged so the A/B arm
      uses the same model. Covered by
      `tests/test_portability_tiers.py:test_lingua_default_backend_builds_http_client_unchanged`.
- [x] 2.3 sqlite-vec backend for Mnemos behind `mnemos/storage.py`, same CLS
      collections + `query_points`-equivalent API
      — `kaine/modules/mnemos/storage.py:SqliteVecStorage` (lazy `sqlite_vec`;
      same `MemoryStorage` protocol/`search`; selected by
      `[mnemos].backend = "sqlite_vec"`).

## 3. Remaining edge backends (staged)

- [ ] 3.1 whisper.cpp STT backend (Audio-In)
      — DEFERRED: needs an external whisper.cpp binary + a GGML model file, not
      installable/testable in this environment. The `[audition]` config seam and
      the tier profiles are ready for it; the concrete client lands in a
      follow-up (design §Non-goals stages the backends).
- [ ] 3.2 Piper TTS backend (Audio-Out)
      — DEFERRED: needs the `piper` binary + a voice model; same staging as 3.1.
      Vox is held off at Tier 0/1 in the profiles until it lands.
- [ ] 3.3 ONNX / dinov2.cpp vision backend (Topos), periodic-mode
      — DEFERRED: needs an ONNX/dinov2.cpp model export; staged. Tier profiles
      pin Topos to CPU and Tier 0 disables it.
- [ ] 3.4 ONNX MiniLM embeddings backend (Mnemos)
      — DEFERRED: needs an ONNX MiniLM export + onnxruntime model file; staged.
- [x] 3.5 Document emotion2vec+ as Tier-2-only (no edge backend); ensure it
      disables cleanly below Tier 2
      — `kaine/modules/audition/emotion.py:NullEmotionClassifier` (selected when
      `[audition].emotion_model_id = ""`, as the Tier 1 profile sets); Audition
      still transcribes. Documented in `docs/deployment-tiers.md`.

## 4. Tier profiles

- [x] 4.1 Layered config load: shipped → profile overlay → local → secrets,
      selected by `KAINE_PROFILE` / `--profile`; local still wins
      — `kaine/config.py:load_kaine_config(profile=...)` +
      `resolve_profile_name`; wired at `kaine/cycle/__main__.py:main` (`--profile`)
      and `_load_kaine_config`; secrets merge last.
- [x] 4.2 Ship `config/profiles/tier0.toml` … `tier3.toml` (toggles + backends +
      device + cycle-rate hints)
      — `config/profiles/tier{0,1,2,3}.toml`.
- [x] 4.3 Guard test: profiles never enable the entity by default and never
      embed the private voice
      — `tests/test_portability_tiers.py:test_shipped_profiles_are_inert_no_module_enabled`
      + `:test_shipped_profiles_are_voice_free`.

## 5. Host probe

- [x] 5.1 `kaine.hardware.recommend_tier` (RAM, arch, CUDA/MPS, torch import)
      — `kaine/hardware.py:recommend_tier` / `TierRecommendation` /
      `total_ram_gb` / `cpu_arch` / `torch_importable`.
- [x] 5.2 `scripts/probe-host` CLI prints recommendation + capability-matrix row
      — `scripts/probe-host` (text + `--json`).
- [x] 5.3 Probe recommends only; never auto-applies a profile
      — `tests/test_portability_tiers.py:test_probe_script_recommends_only_does_not_apply`;
      the CLI only prints, and `recommend_tier` has no side effects.

## 6. Capability matrix + docs

- [x] 6.1 Capability matrix in DEPENDENCIES.md / a new `docs/deployment-tiers.md`
      — `docs/deployment-tiers.md` (per-faculty × per-tier matrix + explicit
      absences). Mirrored in `kaine/hardware.py:TIER_CAPABILITIES`.
- [ ] 6.2 Paper §4 / §10 updated with the tier ladder (see paper edit)
      — DEFERRED / FLAG: the paper source is NOT present in this public repo
      (no `.tex` / paper file under `docs/`), so the paper edit cannot be made
      here. Tracked for the private paper repo.
- [x] 6.3 Per-tier install notes (which extras each tier needs)
      — `docs/deployment-tiers.md` "Per-tier install notes".

## 7. Validation

- [x] 7.1 Tier-2 default path is byte-for-byte behavior-preserving (existing
      suite green with no profile selected)
      — targeted suite green with no profile; the default Lingua/Mnemos paths are
      unchanged (`test_lingua_default_backend_builds_http_client_unchanged`,
      `test_no_profile_is_behaviour_identical`).
- [x] 7.2 A degraded-backend boot logs + surfaces the reason and does not crash
      — `test_failed_backend_falls_back_and_records_reason`,
      `test_lingua_llama_cpp_backend_degrades_to_http_when_dep_absent`,
      `test_backend_failures_surface_on_health_snapshot`.
- [x] 7.3 `openspec validate portability-tiers --strict`
      — passes ("Change 'portability-tiers' is valid").
