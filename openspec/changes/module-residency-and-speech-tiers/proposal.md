## Why

KAINE is meant to be hyper-portable and hyper-scalable. Today, when the first-run wizard meets a host that is too small, its answer is to disable modules. That is the wrong answer: it trades capability away instead of scheduling for it. The right answer is to time-multiplex a small memory budget — queue the work a module needs, load the model that does it, run it, unload it, move to the next. Capability through scheduling, not capability through amputation. Done well, speech and perception feel close to realtime even on an 8 GB board.

Unified memory is what makes this cheap rather than heroic. On an integrated-memory host — the motivating example is a Jetson Orin Nano Super (aarch64, Ampere sm_87, JetPack 7.2, CUDA 13.2, Ubuntu 24.04, Python 3.12, 915 GB NVMe, and 8 GB of unified memory shared between CPU and GPU), though the design must not be specific to it — there is no PCIe hop. "Loading onto the GPU" is just making pages resident. With mmap'd GGUF weights over fast NVMe, the cost of a swap is dominated by page-cache warmth, not bus transfer, so time-multiplexing is *cheaper* on this class of hardware than on a discrete-GPU host. NVIDIA's own Jetson guidance points the same way (run headless, prefer llama.cpp, 4-bit quantise; a full VLM pipeline fits an Orin Nano 8 GB), and published work streams a 26B MoE's routed experts off SSD on an 8 GB Orin Nano with bit-identical logits. Residency scheduling scales up as well as down: on hosts where everything fits — the dual-GPU x86_64 workstation default, and the ROCm, XPU, MPS, and CPU-only paths — the scheduler simply never needs to evict, and behaviour is unchanged.

The LLM tier needs no new machinery. `llama-swap` (v201, April 2026, 3k+ stars) is a mature OpenAI-compatible proxy: it maps model names to upstream commands, auto-unloads after a configurable TTL, exposes `POST /api/models/unload` and `POST /api/models/unload/<model>`, and uses "groups" to control which models may coexist. llama.cpp's `llama-server` now has a built-in router mode for dynamic model switching without restarts. Either fits KAINE's existing `[lingua].chat_url` key with no architectural change, because the lingua organ is already reached over an OpenAI-compatible endpoint. KAINE reuses this art; it does not build a model manager.

The speech ladder gets a correction grounded in 2026 measurements. For TTS, Kokoro-82M (82M params, ~327 MB, Apache-2.0, ONNX, RTF ~0.03 on GPU, several times realtime on CPU) is the right new default middle rung — the best quality-per-byte on the ladder. KittenTTS (nano ~15M params / ~25 MB INT8, micro ~40M, mini ~80M) is small enough for a phone or a Pi, but it is a v0.8 developer preview with reported nano INT8 issues, so it is an opt-in rung, never a silent fallback. Piper is widely assumed to be the light option; 2026 benchmarks put it at ~2.6 GB peak memory and ~1720 ms first-token latency — worse than Kokoro on both axes — so Piper is a compatibility rung, not the lightweight default, and this change declines to repeat the common assumption. For STT, Moonshine (245M params, sub-200 ms on edge, ONNX exported to the memory-mappable `.ort` flatbuffer, outperforming Whisper tiny and small at smaller size) is the strongest candidate for making the voice loop feel realtime, because it processes variable-length audio segments instead of Whisper's fixed 30-second chunks — the single biggest source of perceived lag in a streaming loop; Moonshine v2 adds a sliding-window position-free streaming encoder. whisper.cpp tiny/base remains the floor.

Sequencing. A PENDING (not yet archived) change, `portability-tiers`, already proposes the capabilities `runtime-backends` (per-component backend selection), `deployment-tiers` (named tier profiles), and `host-probe`, and its backend table currently lists Piper for TTS and whisper.cpp for STT. Because `runtime-backends` is not yet in `openspec/specs/`, this change MUST NOT emit a `## MODIFIED Requirements` delta against it. It therefore ADDs new capabilities only — `model-residency` and `speech-tiers` — and records the correction here explicitly: Kokoro and Moonshine, not Piper, are the recommended light rungs. When `portability-tiers` lands, its backend table should inherit that correction rather than the Piper assumption.

Finally, the limits are stated, not hidden. Some combinations do not fit an 8 GB unified budget, and KAINE will say which ones and what they would feel like — a pause while models swap, not a silently missing organ. Nothing here touches the cognitive cycle, the workspace, or any module's semantics; only when and where a model is resident, and which engine realises an organ, may change. No heavy download or install happens without operator consent, every downgrade is surfaced with its reason, and disabling a module remains the last resort.

## What Changes

- **ADD capability `model-residency`.** A scheduler that time-multiplexes a configurable memory budget (auto-sized on first run, operator-overridable) across modules: queue the work, load the model that serves it, run it, release it when the memory is needed next, admit the following item. On hosts where everything fits, it is a no-op.
- **ADD capability `speech-tiers`.** Ordered engine ladders for the speech organ. TTS: Chatterbox (top) → Kokoro-82M (new default middle rung) → KittenTTS (opt-in only) → Piper (compatibility only). STT: Speaches/faster-whisper `medium.en` (current default) → Moonshine (recommended light rung) → whisper.cpp tiny/base (floor). Automatic degradation stops at Kokoro and Moonshine; the rungs below require explicit operator choice.
- **Delegate LLM residency.** `[lingua].chat_url` may point at llama-swap (groups, TTL, unload endpoints) or llama.cpp router mode; KAINE performs no LLM model management of its own, but its scheduler accounts for what the proxy holds resident.
- **Surface every decision.** Each engine selection, downgrade, and disablement is reported with the chosen rung and the reason, in first-run wizard output and runtime status. Disabling a module happens only after every rung of its ladder has failed.
- **Consent and honesty.** No model or engine is downloaded or installed without operator consent, and the wizard states which combinations do not fit and what the resulting experience feels like.
- **The wizard's answer changes.** On a small host, the first-run wizard now produces a schedule — a budget, ladders, and surfaced trade-offs — not a list of amputated modules.
- **Unchanged.** The cognitive cycle, the workspace, every module's semantics, and all existing backends (dual-GPU x86_64 default, ROCm, XPU, MPS, CPU-only). Only when and where models are resident, and which engine realises an organ, may change.
- **Sequencing.** Spec deltas are `## ADDED Requirements` only (`openspec/specs/model-residency/spec.md`, `openspec/specs/speech-tiers/spec.md`), with no MODIFIED deltas against the pending `portability-tiers` change.

The change ADDs the following capabilities and requirements:

### Requirement: Time-multiplexed model residency
KAINE SHALL satisfy a module's need for a model by scheduling residency within a configurable memory budget — queueing the work, loading the model that serves it, running it, and releasing the model when the memory is needed for the next queued item — and SHALL NOT disable a module merely because its model cannot remain permanently resident.

#### Scenario: Small host multiplexes organs
- **WHEN** a module submits work whose model is not resident and the memory budget cannot hold that model beside what is already resident
- **THEN** KAINE queues the work, makes room by unloading per its eviction policy, loads the required model, executes the work, returns the result, and continues with the next queued item — with no module disabled

#### Scenario: Large host never churns
- **WHEN** the host's budget can hold every requested model at once, as on the dual-GPU x86_64 workstation default or on ROCm, XPU, MPS, or CPU-only hosts where nothing needs evicting
- **THEN** KAINE keeps all models resident and inserts no queue-then-unload churn, preserving today's behaviour exactly

### Requirement: Disabling a module is the last resort
KAINE SHALL disable a module only after every rung of that organ's engine ladder has failed to load or execute within the memory budget, and SHALL surface the disablement together with its reason.

#### Scenario: No rung fits
- **WHEN** every backend for an organ, from heaviest to lightest, fails to load or execute within the budget
- **THEN** KAINE disables only that module, records and surfaces the reason in wizard output and runtime status, and every other module continues to operate

### Requirement: LLM residency is delegated to the existing endpoint
KAINE SHALL obtain LLM load and unload behaviour from the OpenAI-compatible endpoint configured at `[lingua].chat_url` — for example llama-swap with groups, a TTL, and its unload endpoints, or llama.cpp server router mode — and SHALL NOT implement its own LLM model manager.

#### Scenario: llama-swap behind the existing key
- **WHEN** `[lingua].chat_url` points at a llama-swap proxy that maps model names to upstream commands, auto-unloads after a TTL, and exposes `POST /api/models/unload`
- **THEN** KAINE issues chat requests to that endpoint unchanged, the proxy performs all loading and unloading, and the lingua organ's architecture is unchanged

#### Scenario: The scheduler accounts for what the proxy holds
- **WHEN** the endpoint is holding an LLM resident and a speech or perception request needs the remaining budget
- **THEN** the scheduler treats the proxy's resident footprint as occupied and multiplexes only the remainder, using the proxy's unload endpoints or TTL rather than managing LLM memory itself

### Requirement: Scheduling changes timing, not semantics
KAINE SHALL confine this change to when and where models are resident and which engine realises each organ; the cognitive cycle, the workspace, and every module's semantics SHALL remain unchanged.

#### Scenario: Delayed organ, identical behaviour
- **WHEN** residency scheduling makes an organ wait for its model to load before it can answer
- **THEN** the module's outputs and the cognitive cycle's behaviour are unchanged — only that turn's latency and the residency timing differ

### Requirement: Ordered TTS ladder with Kokoro as the default light rung
KAINE SHALL realise TTS through an ordered ladder — Chatterbox (expressive, GPU-served) at the top, Kokoro-82M as the default middle rung, KittenTTS as an opt-in rung, and Piper as a compatibility rung — and SHALL select the heaviest rung that fits the host's memory budget.

#### Scenario: Downgrade to Kokoro
- **WHEN** the host cannot keep Chatterbox resident within the memory budget
- **THEN** KAINE degrades TTS to Kokoro-82M, surfaces the downgrade with its reason, and speech continues at several times realtime on CPU or GPU

### Requirement: Ordered STT ladder with Moonshine as the recommended light rung
KAINE SHALL realise STT through an ordered ladder — Speaches/faster-whisper `medium.en` (the current default), Moonshine as the recommended light rung, and whisper.cpp tiny/base as the floor — and SHALL prefer Moonshine on constrained hosts because it transcribes variable-length audio segments rather than Whisper's fixed 30-second chunks.

#### Scenario: Downgrade to Moonshine
- **WHEN** the host cannot keep the Whisper `medium.en` backend resident within the memory budget
- **THEN** KAINE degrades STT to Moonshine (or whisper.cpp tiny/base beneath it), surfaces the downgrade with its reason, and the voice loop's perceived latency improves because transcription no longer waits on 30-second chunk boundaries

### Requirement: KittenTTS and Piper require explicit operator choice
KAINE SHALL offer KittenTTS and Piper only when the operator explicitly selects them — KittenTTS because it is a v0.8 developer preview with reported nano INT8 issues, Piper because at ~2.6 GB peak memory and ~1720 ms first-token latency it is worse than Kokoro on both axes and serves as a compatibility rung only — and SHALL NOT reach either rung by silent fallback.

#### Scenario: Automatic degradation stops before them
- **WHEN** the scheduler walks the TTS ladder downward and the next rung would be KittenTTS or Piper without an explicit operator selection
- **THEN** automatic degradation stops at Kokoro-82M and KAINE surfaces the situation with the reasons and the opt-in choices, instead of silently landing on a developer-preview or compatibility engine

### Requirement: Surfaced degradation with reasons
KAINE SHALL surface every engine selection, downgrade, and disablement with the chosen rung and the reason, in first-run wizard output and in runtime status; degradation SHALL never be silent.

#### Scenario: The wizard reports the ladder position
- **WHEN** the first-run wizard or the runtime scheduler selects a rung below the top for any organ
- **THEN** the operator sees the from-rung, the to-rung, and the reason — for example, "Chatterbox → Kokoro-82M: the 8 GB unified budget cannot hold Chatterbox alongside the LLM"

### Requirement: Consent-gated acquisition
KAINE SHALL NOT download or install any model or engine without operator consent.

#### Scenario: Weights missing locally
- **WHEN** a selected rung's weights or runtime are not present on the host
- **THEN** KAINE asks the operator before acquiring anything, proceeds only on approval, and offers the next lighter rung already on disk as an alternative

### Requirement: Honest statement of limits
KAINE SHALL state which engine combinations do not fit a given host and what the resulting experience would feel like, rather than claiming capability the hardware cannot deliver.

#### Scenario: Queue waits are predicted, not discovered
- **WHEN** the wizard determines that time-multiplexing will make a full voice turn wait on a model load or unload round-trip
- **THEN** it reports the expected feel — for example, that the first spoken reply may pause while models swap — and lists the combinations it rejected, so the operator can decide with open eyes