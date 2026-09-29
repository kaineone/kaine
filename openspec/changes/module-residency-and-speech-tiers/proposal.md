## Why

KAINE is meant to be hyper-portable and hyper-scalable: the same mind on refurbished phones, single-board computers and multi-GPU servers, slower on weak hardware but with every module present. Today, a host that cannot hold every model at once has two answers, and both trade capability away:

- **The tier recommender stops at a warning.** For an accelerator host with a memory budget between the 6 GB and 16 GB floors (the 8 GB unified-memory Jetson Orin Nano Super is the motivating example), `recommend_tier()` returns "Tier 2 with module residency required". Its reason text says residency is not yet implemented, and it advises keeping the vision and voice extras off.
- **Smaller tiers list modules as unsupported.** A tier file's `[tier].unsupported_modules` makes the pre-boot `Tier fit` row FAIL until the operator disables those modules.

The right answer is to time-multiplex a memory budget. Queue the work a module needs, load the model that does it, run it, release the model when the memory is needed, and move to the next item. This is capability through scheduling, not through amputation.

Unified memory makes this cheap. With no PCIe hop, "loading onto the GPU" is making pages resident, and with memory-mappable weights on fast NVMe the cost of a swap is dominated by page-cache warmth. The design keys on that host class (CPU and accelerator share one pool), never on a board. On hosts where everything fits (the dual-GPU x86_64 workstation, ROCm, XPU, MPS, CPU-only) the scheduler never needs to evict, and behaviour is unchanged.

**What has changed since this change was first proposed.** The change was drafted (#118) while `portability-tiers` was pending. Since then:

- `portability-tiers` was archived (2026-09-17). `runtime-backends`, `deployment-tiers` and `host-probe` are living specs, and `deployment-tiers` already names the outcome this change delivers ("Tier 2 with module residency required", including an explicit 8 GB unified Jetson scenario). This change builds on those specs; it needs no MODIFIED delta against them, because it implements a state they already describe.
- `sherpa-onnx-speech` (#260) shipped torch-free speech: Moonshine STT and Kokoro TTS as the `sherpa_onnx` backend of `[audition].backend` and `[vox].backend`, through `BackendRegistry` fallback chains, with consent-gated model downloads (`python -m kaine.setup.speech_models`). The speech ladder in this change is therefore expressed over those existing backends and model ids instead of new engines.
- The earlier draft said the first-run wizard disables modules on small hosts. It does not: the wizard keeps the selected module set and records a tier only on consent. The blockers are the recommender's warning and the `Tier fit` row, as described above.
- The earlier draft assumed facts the code does not have. Nothing records a model's resident footprint (only download sizes), the tier budget is computed from total rather than available memory, and no engine can be unloaded and reloaded: `aclose()` on the sherpa clients is terminal, and Topos, the emotion classifier and the embedders only load. The one working unload/reload is the Hypnos voice-alignment organ window.

**Measure first.** Because resident footprints are unknown, the first deliverable is measurement: a calibration tool that loads each enabled component's backend on the host, records its peak resident footprint, and reports whether the enabled set fits the budget. On an 8 GB unified host with a 2–4B organ, the measured answer may be that most of the stack co-resides, which would narrow what must be multiplexed. The scheduler is then built against measured numbers, not published figures.

The limits are stated, not hidden. Some combinations do not fit an 8 GB budget, and KAINE says which and what they would feel like: a pause while models swap, never a silently missing organ. Nothing here touches the cognitive cycle, the workspace or any module's semantics; only when and where a model is resident, and which engine realises an organ, may change.

## What Changes

- **Footprint calibration and a fit report (first).**
  - `python -m kaine.setup.footprint` loads each enabled component's configured backend on this host (with operator consent), measures its peak resident footprint (system memory and, on discrete hosts, device memory), and records it in a local, content-free footprint catalogue.
  - The fit report states the residency budget derived from available memory minus a reserve, whether the enabled set co-resides, and, if not, the shortfall and which components would be time-multiplexed.
- **Capability `module-residency` (ADDED).** One residency manager per host owns a ledger-based budget, admission control, demand-driven eviction, a keep-resident TTL, one pinned always-hot organ, two work lanes (interactive and background) with a preemption contract, and surfaced residency events. On hosts where everything fits it is passive.
- **Reversible unload.** Engine clients gain an `ensure_loaded()` / `unload()` pair that releases the model and can load it again, without closing the client: the sherpa STT and TTS clients, the Topos encoders, the emotion classifier and the text embedders. External services (the organ's `llama-server`, Chatterbox, Speaches) are stopped and started through the same controller pattern the Hypnos organ window already uses.
- **LLM residency is delegated.** `[lingua].chat_url` may point at llama-swap or llama.cpp's router mode. KAINE performs no LLM model management of its own; the manager reconciles what the proxy holds into its ledger and uses the proxy's unload API. The default (`llm_proxy = "none"`) keeps today's single `llama-server`.
- **Capability `speech-backend-tiers` (ADDED), over existing backends.**
  - TTS: `chatterbox` → `sherpa_onnx` with `kokoro-en`.
  - STT: `speaches` (faster-whisper `medium.en`) → `sherpa_onnx` with `moonshine-base-en` → `sherpa_onnx` with `moonshine-tiny-en`.
  - The host probe recommends the lightest rungs that fit on constrained budgets, and the operator decides. Downgrades are surfaced with reasons; acquisition stays consent-gated. KittenTTS, Piper and whisper.cpp are no longer part of this change (see Decisions in `design.md`).
- **Integration with what already runs.** The Hypnos organ window becomes a client of the residency manager, not a second owner of the organ's memory. Spot never reads a residency wait as a hang. Audio that arrives while STT is not resident waits in a bounded in-memory queue and is never written to disk. Slow swaps show up as cycle slip, which the existing automatic time dilation can absorb.
- **Pre-boot and wizard.** A `Residency fit` row reports the fit plan (PASS when everything co-resides, PASS with the multiplexing plan when it is scheduled, FAIL only when not even the pinned organ and the lightest rungs can be scheduled). The wizard shows the fit report and the multiplexing plan instead of the "not yet implemented" warning.
- **Unchanged.** The cognitive cycle, the workspace, every module's semantics, every existing backend, and the default `llm_proxy = "none"` path.

## Capabilities

### New Capabilities
- `module-residency`: time-multiplexed model residency within a measured memory budget, with calibration, admission, eviction, pinning, preemption, LLM delegation, surfaced events, and honest limits.
- `speech-backend-tiers`: ordered speech ladders over the existing `[audition].backend` and `[vox].backend` values and sherpa model ids, with probe recommendation, surfaced downgrades, consent-gated acquisition, and voice-latency measurement.

### Modified Capabilities
- (none) `deployment-tiers` already specifies "Tier 2 with module residency required"; `runtime-backends` already specifies fallback chains and surfaced failures; `host-probe` is unchanged. This change implements behaviour those specs anticipate.

## Impact

- **New code:** `kaine/residency/` (budget, ledger, manager, planner, lanes, events), `kaine/setup/footprint.py` (calibration and fit report), a llama-swap config generator under `kaine/setup/`.
- **Changed code:**
  - engine clients gain `ensure_loaded()` / `unload()`: `kaine/modules/audition/sherpa_stt.py`, `kaine/modules/vox/sherpa_tts.py`, `kaine/modules/topos/encoder.py`, `kaine/modules/audition/emotion.py`, `kaine/text_embedding.py`;
  - `kaine/modules/hypnos/organ_window.py` routes through the manager;
  - `kaine/cycle/spot.py` treats residency waits as liveness;
  - `kaine/modules/audition/module.py` gets the bounded audio queue;
  - `kaine/preboot.py` gets the `Residency fit` row;
  - `kaine/hardware.py` gets the recommender reason text;
  - `kaine/setup/wizard.py` shows the fit report;
  - `config/kaine.toml` gets an optional `[residency]` section whose defaults preserve today's behaviour.
- **Docs:** `docs/deployment-tiers.md`, `docs/hardware.md`, `docs/deployment-headless-host.md`, `docs/modules/audition.md`, `docs/modules/vox.md`, a new residency guide, and measured results under `docs/benchmarks/`.
- **Operator steps:** calibration and latency runs on the Orin Nano Super and the Pixel 6a, which need the devices.
