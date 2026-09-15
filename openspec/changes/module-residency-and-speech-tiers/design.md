# Design: module-residency-and-speech-tiers

## Context

KAINE's portability story currently ends at "this host is too small, so the wizard disables modules." That is amputation, not portability. This change replaces it with time multiplexing: one memory budget, a residency manager that loads the model a module needs, runs the work, unloads it, and moves to the next. Capability through scheduling.

The design targets a **host class**, not a machine. The motivating host — an 8 GB unified-memory aarch64 board with fast NVMe — is the sharpest instance of the class "CPU and accelerator share one physical memory pool." Apple Silicon under MPS and CPU-only boards belong to the same class; the dual-GPU x86_64 workstation, ROCm, and XPU hosts belong to the discrete class. Nothing below keys on a specific SoC, GPU architecture, or OS image.

Two verified findings anchor everything below:

- **Unified memory inverts the swap-cost model.** With no PCIe hop, "loading onto the GPU" is making pages resident. Against mmap'd weights on NVMe, reload cost is dominated by page-cache warmth, so time multiplexing is *cheaper* on this class of host than on discrete-GPU machines — and published work streaming a 26B MoE's routed experts off SSD on an 8 GB board with bit-identical logits shows the same scheduling scales up as well as down.
- **Do not rebuild the LLM tier.** llama-swap (OpenAI-compatible proxy; per-model TTL; `POST /api/models/unload` and `POST /api/models/unload/<model>`; exclusive groups) and llama-server's built-in router mode already solve dynamic model swapping behind exactly the endpoint KAINE's `[lingua].chat_url` already abstracts.

## Sequencing relative to `portability-tiers`

`portability-tiers` is pending, not archived: `runtime-backends`, `deployment-tiers`, and `host-probe` are not yet in `openspec/specs/`. Therefore:

- Every spec delta in this change is an `## ADDED Requirements` block on new capabilities (model residency, the speech ladder, voice latency targets). This change emits **no** `## MODIFIED Requirements` against anything from `portability-tiers`.
- This change's proposal records the correction in its `## Why`: `portability-tiers`' backend table lists Piper for TTS and whisper.cpp for STT as the light rungs, but 2026 measurements contradict Piper-as-light (~2.6 GB peak, ~1720 ms first-token — worse than Kokoro-82M on both axes). **Kokoro and Moonshine are the recommended light rungs.** When `portability-tiers` archives, a small follow-up reconciles its table; until then this change's rung ids are self-contained.
- The `[residency]` config and rung ids introduced here are shaped so that `runtime-backends`' per-component backend keys can adopt the rung ids as values later, without migration.

## Semantic freeze

This change alters only **when** and **where** a model is resident, and **which engine** realises an organ. The cognitive cycle, the workspace, and every module's inputs, outputs, and organ contracts are untouched. Different engines produce different voices or transcription character — that is engine choice, surfaced as such, not a change in what an organ is or does.

## Architecture overview

Four host-local pieces:

1. **Residency manager** — one per host. Owns the budget ledger, admission control, eviction, TTL expiry, the pin, and the pressure valve. Every model residency change in KAINE goes through it.
2. **Work scheduler** — two lanes (interactive, background) with deadlines and a preemption contract.
3. **Rung catalogue** — per organ, an ordered ladder of engine rungs with calibrated peak footprints, artifact formats, licences, and a selection policy (`auto`, `opt-in`, `compat`).
4. **LLM delegation** — llama-swap or llama-server router mode behind the existing `[lingua].chat_url`; the residency manager reconciles, never owns, LLM processes.

## Residency manager

### States and transitions

Per model artifact (a "rung instance"):

| State | Meaning |
|---|---|
| `absent` | Artifact or engine not on disk; reachable only via a consent-gated install |
| `cold` | On disk, nothing resident, no process |
| `loading` | Admitted; pages faulting in / server starting; footprint reserved in the ledger |
| `resident` | Ready or serving; TTL clock running (unless pinned); footprint held in the ledger |
| `unloading` | Draining and releasing; bounded — a hard stop (default 5 s) terminates a server that will not drain |

| From | Trigger | To | Notes |
|---|---|---|---|
| `absent` | consented install | `cold` | wizard or `kaine install <rung>` |
| `cold` | admission granted | `loading` | admission control (below) |
| `loading` | readiness probe passes | `resident` | HTTP health for servers; for ONNX rungs, constructed session **plus one warmup inference**, so arena allocation lands before the first real request |
| `loading` | load failure | `cold` | reason recorded; ladder walks down |
| `resident` | request served | `resident` | TTL refreshed |
| `resident` | TTL expiry | `unloading` | primary release path |
| `resident` | eviction for admission | `unloading` | ordered, demand-driven (below) |
| `resident` (pinned) | last-resort eviction | `unloading` | surfaced; auto-reload queued |
| `unloading` | released | `cold` | ledger entry dropped |

### Budget: source of truth

On a unified-memory host there is no "VRAM figure" worth reading. `cudaMemGetInfo` and `nvidia-smi` report the same shared pool the CPU allocates from, so a "total VRAM: 8 GB" reading is a phantom partition; budgeting against it double-counts with CPU-side allocations. Worse is the subtler trap: `MemAvailable` counts page cache as available, and mmap'd weights **are** page cache. A naive scheduler sees "6 GB available," loads a 2.5 GB chat model, and then watches the kernel silently discard the model's clean file pages whenever anything else touches memory — the process stays "loaded" while every token re-faults from NVMe. **Page cache is not free memory.**

The budget is therefore a **ledger**, not a reading:

headroom = available_system_memory − reserve − Σ(ledger footprints)

- `available_system_memory` is the kernel's reported available memory (`MemAvailable` on Linux, the host OS equivalent elsewhere), clamped by the cgroup memory limit when KAINE runs containerised.
- `reserve` (default `max(1 GiB, 10% of physical RAM)`, configurable) protects the OS and non-KAINE processes; on the 8 GB class this leaves roughly 6–7 GB schedulable.
- Ledger footprints are **calibrated peak RSS** per rung — weights + runtime overhead + KV/activation at the configured context — measured at packaging time and refreshed from live measurements. File size is never the admission metric; Piper's ~2.6 GB peak against a small artifact is the standing counterexample.
- Discrete-accelerator hosts (dual-GPU x86_64, ROCm, XPU) budget accelerator-resident rungs against the device's free memory as reported by its runtime, and CPU-resident rungs against the same system ledger. MPS and CPU-only hosts budget entirely on system memory.
- A **pressure valve** watches available system memory: if external processes drive it toward the reserve, warm (TTL-idle) rungs are unloaded LRU-first and the event is surfaced.

### Admission control

Admission decisions are serialised through the manager, so concurrent admissions cannot double-spend headroom. Given a job `{organ, rung, class, deadline, est_footprint}` (est_footprint = calibrated peak + 10% margin for KV/activation growth):

1. Requests targeting an already-`resident` rung need no admission; they refresh the TTL.
2. If `headroom ≥ est_footprint`: admit, reserve, transition `cold → loading`.
3. Else **evict**: candidates are `resident`, unpinned, with no in-flight work — background-class residents first, then interactive-class by least-recent use.
4. Else **preempt** running background jobs (see "Preemption").
5. Else **walk the ladder down** through installed rungs; admit the first that fits and surface the substitution with its reason.
6. Else: interactive jobs take the honest-refusal path (one retry after the pressure valve evicts all warm rungs, then a truthful refusal naming the blocker); background jobs are parked in the queue with a stated wait reason and estimated fit.
7. Disabling a module happens only after every rung of the organ fails, and is surfaced prominently — the last resort, never the default.

Eviction is demand-driven: the manager never speculatively unloads anything except TTL expiry and the external-pressure valve, so there is no thrash loop.

### Pinning the always-hot organ

Exactly one organ may be pinned (`[residency].pin`, default `lingua`; `none` allowed). The pinned rung is admitted first at startup, its TTL is disabled, and it is excluded from eviction sweeps — the model every cognitive cycle needs must never pay a reload per turn. The pin is a preference, not an invariant: if a latency-critical job cannot be admitted and the pin is the sole eviction candidate, the manager unloads it, admits the job, surfaces the forced unpin with its reason, and queues an automatic background reload. If the pinned rung cannot fit alongside the reserve at startup, KAINE says so with numbers and proposes a lighter chat rung instead of silently running unpinned.

### When a request cannot be admitted

Ladder-down first, always with a surfaced reason ("TTS: Kokoro-82M → Kitten micro; consolidation job held 1.1 GB"). If no installed rung fits, an interactive request is refused **honestly**: the voice loop speaks a short truthful message ("I can't load speech right now — memory is held by the consolidation job") and the same reason appears in the text surface; a background job is parked with its queue position and wait reason. A module is disabled only after every rung fails, the disablement is announced with reasons and recovery conditions, and it re-enables itself automatically when headroom returns. Nothing degrades silently.

## Work queue and priority classes

| Class | Contents | Contract |
|---|---|---|
| `interactive` | STT, TTS, the chat turn itself, perception invoked mid-exchange | deadline-bounded; targets in "Latency targets" |
| `background` | sleep-phase consolidation, memory reindexing, training, prewarm loads | throughput; yieldable at safe units |

Two lanes, one per class. An `interactive` job is dispatched the moment budget allows and **never queues behind queued or running background work**: lane order provides the bypass for queued work, and preemption (below) handles running work. Interactive jobs carry deadlines derived from the latency targets; a job admitted after its deadline still runs, but the miss is recorded and surfaced. Background jobs run only when the interactive lane is empty and — for sleep-phase consolidation — inside the operator's configured sleep window if one is set.

### Preemption

Background jobs are written against a **yield contract**: they proceed in safe units (a consolidation segment, a training step, one chunked LLM request), checkpoint at every boundary, and observe a cancellation flag. Preemption is:

1. The manager signals cancellation on the background job(s) holding the needed budget, largest footprint first.
2. Each job finishes its current safe unit, checkpoints, and releases residency. Grace window: **2 s** default.
3. Hard timeout: **10 s** default. A job that ignores cancellation is terminated at the next safe point, marked misbehaving in the surfaced log, and resumed later from its checkpoint.

On unified memory this is cheap: releasing residency is `munmap`/process stop, and the checkpoint makes preemption invisible to the job's results.

## Warm path

Reload cost is the whole game, so the warm path is a set of obligations:

- **mmap-able artifacts only.** GGUF for llama.cpp; ONNX or the memory-mappable `.ort` flatbuffer for speech rungs (Moonshine ships exactly this). A rung whose loader copies the artifact into anonymous memory is flagged in the catalogue and admitted on measured peak RSS with a warning.
- **Calibrated footprints.** Admission budgets peak RSS measured on a reference workload at packaging time and refreshed live — never file size.
- **Keep-resident TTL.** After a job completes, the rung stays `resident` for `[residency].ttl_seconds` (default 120 s; per-rung override; the LLM tier's TTL is delegated to the proxy, below). A conversational exchange is a burst of turns seconds apart: within the TTL, the next turn reuses the live STT/TTS/LLM processes and pays **zero** load cost — the conversational turn does not pay the load cost twice. TTL refreshes on every use; expiry unloads; pressure may evict earlier.
- **Page-cache warmth after unload.** Once TTL-unloaded, file-backed pages often remain cached, so a reload re-faults from cache rather than NVMe. The manager may estimate warmth with `mincore()` and report it in status output, while admission always budgets the cold number — warmth is a bonus, never a budget.
- **Warmup on load.** `loading` includes one dummy inference so ONNX arena allocation and CUDA module load land before the readiness probe, keeping first-real-request latency honest.
- **Prewarm.** `[residency].prewarm` lists rungs to load at idle at background priority (e.g., the voice loop's STT+TTS pair), so the first turn after boot is warm instead of cold.

## Speech ladder

Selection policies: `auto` (eligible for automatic selection when installed and fitting), `opt-in` (never selected automatically, never a silent fallback), `compat` (for compatibility with existing deployments; explicit configuration required).

**TTS, heaviest to lightest:**

| Rung | Engine | Figures | Policy | Notes |
|---|---|---|---|---|
| `tts-expressive` | Chatterbox | heaviest of the ladder; GPU-served | `auto` | current default top rung; expressive |
| `tts-standard` | Kokoro-82M | 82M params, ~327 MB; ONNX; RTF ~0.03 on GPU, several× realtime on CPU; Apache-2.0 | `auto` | **new default middle rung**; best quality-per-byte |
| `tts-nano` | KittenTTS micro / mini | micro ~40M params / ~41 MB; mini ~80M / ~80 MB; ONNX; CPU-only; 8 English voices | `opt-in` | |
| `tts-pico` | KittenTTS nano | ~15M params / ~25 MB INT8; ONNX; CPU-only | `opt-in` | v0.8 developer preview; nano INT8 has reported issues — never a silent fallback |
| `tts-compat` | Piper (VITS/ONNX) | ~2.6 GB peak memory; ~1720 ms first-token latency (2026 benchmarks) | `compat` | compatibility with existing Piper assets only; **not** the lightweight default — the common assumption is wrong |

**STT, heaviest to lightest:**

| Rung | Engine | Figures | Policy | Notes |
|---|---|---|---|---|
| `stt-heavy` | Speaches / faster-whisper `medium.en` (CPU) | heavy | `auto` | current default; retained as the quality rung where it fits |
| `stt-standard` | Moonshine | 245M params; sub-200 ms latency on edge; ONNX exported to memory-mappable `.ort`; variable-length segments; v2 sliding-window position-free streaming encoder | `auto` | **new default**; variable-length segments remove Whisper's fixed 30-second chunks — the single biggest source of perceived lag in the streaming voice loop |
| `stt-light` | whisper.cpp tiny/base | the floor | `auto` | last automatic rung |

Traversal rules: automatic selection considers only installed `auto` rungs that fit the budget; the highest such rung wins. On a workstation that is the current default pair (Chatterbox, Speaches `medium.en`) — unchanged. On an 8 GB unified host, where Chatterbox cannot coexist with the pinned chat model, it lands on Kokoro + Moonshine — derived from the budget, not from a host table. `opt-in` and `compat` rungs are skipped by automatic traversal and the skip is noted in the surfaced reason. Traversal never downloads: a missing best-fit rung yields a surfaced install hint (`kaine install tts-standard`, ≈327 MB) and the next installed rung serves. All weight downloads and engine installs, at wizard time or later, are explicit and consent-gated.

## Latency targets

Targets for the reference budget class — 8 GB unified memory, Kokoro + Moonshine + a 3–4B 4-bit chat model, all TTL-resident:

| Metric | Definition | Warm | Cold (one rung loads) |
|---|---|---|---|
| **TTFA** (time-to-first-audio) | end of user speech → first audio sample at the speaker | **≤ 1.5 s** | ≤ 4 s |
| STT final | end of speech → final transcript (utterance ≤ 10 s) | ≤ 300 ms | ≤ 1.5 s |
| LLM first token | prompt ready → first token | ≤ 800 ms | ≤ 8 s incl. load |
| TTS first chunk | sentence ready → first audio chunk | ≤ 150 ms | ≤ 2 s incl. load |
| Preemption grace | preempt signal → background residency released | ≤ 2 s (hard 10 s) | — |
| First turn after boot | all rungs cold | — | ≤ 15 s (prewarm removes this) |

The warm TTFA budget composes: 300 ms STT + 800 ms first token + 150 ms first chunk ≈ 1.25 s ≤ 1.5 s. It works because TTS is fed sentence-by-sentence from the streaming LLM, so TTFA does not wait for full generation, and because Moonshine's variable-length segments mean STT latency tracks the utterance rather than a fixed 30-second chunk. These are targets, not guarantees: every turn is measured into a breakdown `{queue_wait, preempt_wait, load, stt, llm_first_token, tts_first_chunk}`, cold-path turns are recorded separately from warm-path turns, and persistent misses surface as degradation reports naming the offending segment.

## LLM tier: llama-swap or llama-server router behind `[lingua].chat_url`

The lingua organ is already reached over an OpenAI-compatible endpoint; that contract does not change. Adoption is delegation, not construction:

- **`[residency].llm_proxy = none` (default).** Today's behaviour exactly: one server behind `chat_url`, no dynamic swap, no reconciliation calls. This is the non-regression path for the workstation and every existing backend.
- **`llama-swap`.** KAINE generates the proxy config from the rung catalogue: each LLM rung maps to its upstream command; per-model TTLs come from `[residency]`; the chat rung and any batch LLM rung share an exclusive group so at most one LLM is resident and requesting one unloads the other. `[lingua].chat_url` points at the proxy; modules select a rung via the request's `model` name. The residency manager **reconciles**: it queries the proxy's loaded-model status before admission decisions, holds the loaded model's calibrated footprint in the ledger, and calls `POST /api/models/unload/<model>` when admission needs the footprint and the TTL policy agrees. Batch LLM jobs are submitted as chunked, resumable requests under the batch model name, so a mid-job swap costs one chunk, not the job.
- **`llama-server` router mode.** Same shape against llama-server's built-in router (dynamic model switching without restarts): `chat_url` points at it; the manager uses its load/unload API for reconciliation.

Illustrative generated shape (exact keys follow llama-swap's documented schema):

models:
  chat-4b-q4:
    cmd: llama-server -m /var/lib/kaine/models/chat-4b-Q4_K_M.gguf -c 8192 --port 8901
    ttl: 300
  batch-4b-q4:
    cmd: llama-server -m /var/lib/kaine/models/chat-4b-Q4_K_M.gguf -c 32768 --port 8902
    ttl: 60
groups:
  llm:
    swap: true                                  # members evict each other
    members: [chat-4b-q4, batch-4b-q4]

Installing llama-swap or enabling router mode is a wizard step and, like every heavy install, consent-gated. A remote `chat_url` (cloud endpoint) has zero local footprint; the ledger simply excludes the LLM tier and the residency machinery governs speech and perception alone.

## Non-regression and semantic freeze

The dual-GPU x86_64 workstation default, ROCm, XPU, MPS, and CPU-only hosts are preserved by construction: `llm_proxy` defaults to `none`; discrete hosts budget on device memory as before; automatic ladder selection lands on the highest fitting installed `auto` rung, which on a workstation is the current default pair. No module's semantics move; only timing and engine realisation vary.

## Honest limits

A scheduler that lies about its envelope is amputation with extra steps:

- **What fits on the 8 GB class.** A 3–4B 4-bit chat model (~2–2.5 GB) pinned, plus Kokoro (~327 MB) and Moonshine, plus the reserve — comfortable, with room for a background job. This is the intended sweet spot and the basis of the warm TTFA target.
- **Chatterbox on 8 GB does not coexist** with a useful chat model. Selecting it means per-turn swapping (chat out, Chatterbox in, back again): TTFA becomes load-dominated — seconds, not 1.5 s — and the voice loop feels pause-y. The plan says so when Chatterbox is chosen on a small budget.
- **Larger chat models are borderline.** A 7–8B Q4 model (~4.5–5 GB) plus both speech rungs is tight on 8 GB; KAINE will run it but surfaces tightness and more frequent pin evictions.
- **Training does not fit small hosts.** Fine-tuning the chat LLM is workstation-class background work; on an 8 GB board the planner refuses the schedule with an explanation. Sleep-phase consolidation (summarisation, indexing) does fit — it is chunked and yields.
- **Piper is not the small-host answer.** ~2.6 GB peak and ~1720 ms first-token latency are worse than Kokoro on both axes; it exists as a compatibility rung, full stop.
- **KittenTTS nano is a preview.** v0.8 developer preview with reported nano INT8 issues: opt-in, surfaced, never a silent fallback.

## Risks and mitigations

- **Ledger drift** (calibrated footprint ≠ live peak): footprints are re-measured from live RSS per run; the ledger uses the larger of calibrated and observed, and drift beyond a threshold re-calibrates the catalogue entry.
- **Kernel reclaim under external pressure**: the pressure valve unloads warm rungs as available memory nears the reserve; partial kernel reclaim of a resident model's pages is detected via `mincore()` sampling and reported rather than silently re-faulting.
- **Proxy version coupling**: llama-swap's unload endpoints and group semantics are pinned as a minimum version in setup; llama-server router mode is the fallback path for operators who prefer stock llama.cpp.
- **ONNX runtime arenas** inflating peak RSS: rung configurations bound arena sizes so calibrated footprints stay honest.

Normative requirements for this design live in the spec deltas: `specs/module-residency/spec.md` and `specs/speech-backend-tiers/spec.md`.