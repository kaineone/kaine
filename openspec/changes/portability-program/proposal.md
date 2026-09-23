## Why

KAINE's goal is that the same mind runs on hardware from refurbished phones and single-board computers up to multi-GPU servers, at lower speed on weak hardware but with all modules present. `docs/deployment-tiers.md` says the mind "can inhabit hardware ranging from a retired phone to a datacenter" and that Tier 0 needs no torch. An audit of the code on 2026-09-22 found that this is not true today:

- **Six modules have no backend without torch or JAX.** They are Soma and Chronos (CfC networks), Mnemos, Empatheia and Hypnos (each builds its own MiniLM embedder) and Nous and Phantasia (JAX). Torch, transformers, sentence-transformers, ncps and pynvml are base dependencies, so `pip install` fails outright on 32-bit ARM and Termux.
- **Tier 0 switches off five modules and still needs torch.** It disables Topos, Audition, Vox, Empatheia and Phantasia, contradicting both "no torch" and "profiles only bound backends".
- **Slow hardware silently changes the dynamics.** When a cycle overruns, the next tick starts at once, so on slow hardware the entity simply gets fewer ticks per subjective second. `EntityClock` time dilation could preserve the dynamics, but only `time_scale` set by hand does that: no profile sets it, nothing adjusts it from measured slip, and several modules (Chronos, Nous, Lingua and others) read the wall clock directly.
- **The tier recommender and the install:**
  - The recommender ignores memory on accelerator hosts, and nothing calls it from the installer or wizard (`host-fit-provisioning` covers this).
  - The installer assumes an existing checkout and installs no services or models.
  - There is no one-command bootstrap and no GUI installer.
- **Measured edge reality.** The only full voice stack measured on a Pi Zero 2 W (512 MB) takes 37–46 s per spoken turn with each model loaded in turn. The original Pi Zero (ARMv6) cannot host the torch stack at all.

## What Changes

This change is the program of record; each phase lands as its own change once its design is approved.

- **Phase 0 — honest claims (this change implements it).**
  - Rewrite the tier capability matrix to state what runs today, including torch requirements and the modules each profile disables.
  - Correct `tier0.toml`'s comment about slowing the clock.
  - Fix the stale 3.33 Hz rate in `docs/deployment-topologies.md`.
  - Make `getting-started`, `hardware` and `deployment-tiers` agree.
  - Make two tests hermetic: the setup wizard test writes to a fixed `/tmp` path, and the import-boundary test falls back to a bare `python`.
- **Phase 1 — install anywhere Linux runs.**
  - Move torch, transformers, sentence-transformers, ncps, qdrant-client and pynvml into extras, with an `[edge]` extra carrying llama-cpp-python and sqlite-vec.
  - Bootstrap Redis without Docker.
  - A `curl | sh` bootstrap for x86_64 and aarch64 Linux that fetches a release, installs system packages and Python 3.12, installs the extras for the enabled modules, downloads models, and launches the wizard.
  - The wizard applies a tier profile and `time_scale` on operator confirmation.
- **Phase 2 — torch-free core and faithful slowness.**
  - NumPy CfC implementations for Soma and Chronos, verified against the torch path.
  - One shared ONNX (or static model2vec) embedder for Mnemos, Empatheia and Hypnos.
  - sherpa-onnx speech backends (streaming zipformer or Moonshine for input; Kokoro, Piper or KittenTTS for output).
  - A `time_scale` controller driven by measured slip, and EntityClock injection into every module, so weak hardware slows subjective time instead of distorting it.
- **Phase 3 — JAX-free reasoning and phones.** NumPy active inference for Nous, a small NumPy world model for Phantasia, ONNX vision, a Termux package, and remote-embedder and CfC offload so a Pi Zero 2 W can serve as a thin client.
- **Phase 4 — the high end and residency.** Module residency and model swapping for 8 GB unified hosts (the existing `module-residency-and-speech-tiers` proposal), arm64 container images, and multi-node/SLURM placement.
- **GUI installer.** After Phase 1: a browser-based setup served by Nexus that drives the same wizard.
- **Model ladder.** Each tier maps to a vetted model per function, with one abliterated Qwen3.5 family across tiers (2B to 397B-A17B). The research table, sources and licence red flags are in `design.md`, including avoiding the NVIDIA Open Model License streaming speech models, which terminate on guardrail removal. The original ARMv6 Pi Zero is supported only as a sensor or remote-perception peripheral.

## Capabilities

### New Capabilities
- (none)

### Modified Capabilities
- `deployment-tiers`: the capability matrix states current reality; the program's target is recorded.

## Impact

- **Phase 0:** `docs/deployment-tiers.md`, `docs/getting-started.md`, `docs/hardware.md`, `docs/deployment-topologies.md`, `config/profiles/tier0.toml` (comment), `tests/test_setup_wizard.py`, `tests/test_import_boundary_contracts.py`.
- **Later phases:** see each phase's own change.
