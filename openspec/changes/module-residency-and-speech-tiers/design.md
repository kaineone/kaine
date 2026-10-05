# Design: module-residency-and-speech-tiers

## Context

KAINE's portability story currently ends at a warning. For an accelerator host between the 6 GB and 16 GB budget floors the tier recommender returns "Tier 2 with module residency required" and says residency is not implemented; smaller tiers list modules as unsupported, and the pre-boot `Tier fit` row fails until the operator disables them. That is amputation, not portability. This change replaces it with time multiplexing: one memory budget, a residency manager that loads the model a module needs, runs the work, unloads it, and moves to the next. Capability through scheduling.

The design targets a **host class**, not a machine. The motivating host — an 8 GB unified-memory aarch64 board with fast NVMe — is the sharpest instance of the class "CPU and accelerator share one physical memory pool." Apple Silicon under MPS and CPU-only boards belong to the same class; the dual-GPU x86_64 workstation, ROCm, and XPU hosts belong to the discrete class. Nothing below keys on a specific SoC, GPU architecture, or OS image.

Two verified findings anchor everything below:

- **Unified memory inverts the swap-cost model.** With no PCIe hop, "loading onto the GPU" is making pages resident. Against mmap'd weights on NVMe, reload cost is dominated by page-cache warmth, so time multiplexing is *cheaper* on this class of host than on discrete-GPU machines — and published work streaming a 26B MoE's routed experts off SSD on an 8 GB board with bit-identical logits shows the same scheduling scales up as well as down.
- **Do not rebuild the LLM tier.** llama-swap (OpenAI-compatible proxy; per-model TTL; `POST /api/models/unload` and `POST /api/models/unload/<model>`; exclusive groups) and llama-server's built-in router mode already solve dynamic model swapping behind exactly the endpoint KAINE's `[lingua].chat_url` already abstracts.

## What this builds on

`portability-tiers` was archived on 2026-09-17, so its capabilities are living specs:

- `deployment-tiers` already specifies the recommender's "Tier 2 with module residency required" outcome for a 6–16 GB accelerator budget, including an 8 GB unified Jetson scenario. This change implements that state; it needs no MODIFIED delta.
- `runtime-backends` already specifies `[<module>].backend` selection through fallback chains, with failures surfaced instead of crashing boot. The speech ladder is expressed in those terms.
- `host-probe` is unchanged; the residency budget is derived by the manager at run time (below), not by the probe.

Existing code the design reuses rather than rebuilds:

| Need | Reuse |
|---|---|
| Unified vs discrete detection, total and available memory with provenance | `kaine/hostmem.py`: `classify_accelerator_memory`, `system_memory_pool` (`MemTotal`/`MemAvailable`) |
| Per-device free memory on discrete hosts | `describe_host().cuda_devices` in `kaine/hardware.py` |
| The trigger | `recommend_tier().residency_required` and `memory_budget_gb` |
| Engine ladders and fallback | `BackendRegistry` in `kaine/modules/backends.py` (`register(name, factory, fallback=)`, `resolve_backend`) |
| The surfaced-reason channel | `kaine/backend_state.py` (`record_backend_failure`) and the Nexus health block that shows it |
| Lazy engine load | the sherpa clients' idempotent `warm_up()` |
| Consent-gated model acquisition | `kaine/setup/speech_models.py` (`MANIFEST`, `describe()`, `fetch`) and `kaine/setup/provision.py` |
| Stopping and starting an external model server | `OrganServerController` in `kaine/modules/hypnos/organ_window.py` and `kaine/setup/model_server.py` (`cmd_start`, `cmd_stop`, `health_check`) |
| Consumers that defer while the organ is absent | `kaine/organ_window_state.py` and the `organ_resting` path in `kaine/modules/lingua/client.py` |
| Accounting what an LLM server holds | `GET /v1/models`, as `kaine/cycle/preflight.py` already does |

What is new: a budget from available memory with a reserve; resident-footprint measurements; reversible unload on engine clients; the manager, planner and lanes; residency events; the llama-swap template and unload calls; the `Residency fit` pre-boot row; and the wizard's fit report.

## Measure first

No registry records how much memory a loaded model occupies. `speech_models.SpeechModel.size_bytes` is the archive download size, and the only hard-coded footprints are the organ window's constants. File size is not a usable admission figure. Admission must budget peak resident memory, which includes runtime arenas, KV cache and activations.

So the first deliverable is calibration:

- **`python -m kaine.setup.footprint`.** For each enabled component with a model (the Lingua organ via its server, the Audition STT backend, the Vox TTS backend, the Topos encoder, the emotion classifier, the text embedder), it loads the configured backend in isolation and runs one representative inference. It records peak resident memory: RSS for in-process engines, the server process's RSS for external services, and device memory on discrete hosts. Loading is consent-gated, because it may pull weights; it never downloads anything itself, and it skips a component whose model is absent, saying so.
- **The footprint catalogue.** A local file (`state/residency/footprints.json`, content-free: component, backend, model id, measured bytes, host class, timestamp, KAINE version). Live measurements refresh it, and the ledger uses the larger of the catalogued and observed figures.
- **The fit report.** The report takes the budget (available memory minus the reserve), the catalogue and the enabled set, and states:
  - whether the set co-resides;
  - if it does not, the shortfall, the plan (what is pinned, what is multiplexed, which rung each organ would use) and the expected feel.

  The wizard, the pre-boot row and `scripts/probe-host` all show the same report.

Calibration is the first task and gates the rest of the order. The measured Orin and Pixel numbers decide the defaults (reserve, TTLs, pin, which organs route through the manager first), and they replace the published figures quoted below wherever the two differ.

## Semantic freeze

This change alters only **when** and **where** a model is resident, and **which engine** realises an organ. The cognitive cycle, the workspace, and every module's inputs, outputs, and organ contracts are untouched. Different engines produce different voices or transcription character — that is engine choice, surfaced as such, not a change in what an organ is or does.

## Architecture overview

Four host-local pieces:

1. **Residency manager** — one per host. Owns the budget ledger, admission control, eviction, TTL expiry, the pin, and the pressure valve. Every model residency change in KAINE goes through it.
2. **Work scheduler** — two lanes (interactive, background) with deadlines and a preemption contract.
3. **Rung catalogue** — per organ, an ordered ladder of `(backend, model id)` rungs with calibrated peak footprints from the footprint catalogue, whether the weights are mapped, and licences.
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
| `absent` | consented install | `cold` | the wizard or `python -m kaine.setup.speech_models` / provisioning |
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
- Ledger footprints are **calibrated peak RSS** per rung — weights + runtime overhead + KV/activation at the configured context — measured on the host by the calibration tool and refreshed from live measurements. File size is never the admission metric: runtime arenas, KV cache and activations routinely exceed the artifact's size.
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

Ladder-down first, always with a surfaced reason ("STT: moonshine-base-en → moonshine-tiny-en; consolidation job held 1.1 GB"). If no installed rung fits, an interactive request is refused **honestly**: the voice loop speaks a short truthful message ("I can't load speech right now — memory is held by the consolidation job") and the same reason appears in the text surface; a background job is parked with its queue position and wait reason. A module is disabled only after every rung fails, the disablement is announced with reasons and recovery conditions, and it re-enables itself automatically when headroom returns. Nothing degrades silently.

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

- **Prefer memory-mapped artifacts.** GGUF for llama.cpp is mapped. sherpa-onnx loads its ONNX models into process memory, so a speech reload pays a read from disk (from page cache when warm) rather than a page fault. The catalogue records whether each rung maps its weights, and admission budgets the measured peak either way.
- **Calibrated footprints.** Admission budgets the peak resident memory measured on this host by the calibration tool (see "Measure first") and refreshed live, never file size.
- **Keep-resident TTL.** After a job completes, the rung stays `resident` for `[residency].ttl_seconds` (default 120 s; per-rung override; the LLM tier's TTL is delegated to the proxy, below). A conversational exchange is a burst of turns seconds apart: within the TTL, the next turn reuses the live STT/TTS/LLM processes and pays **zero** load cost — the conversational turn does not pay the load cost twice. TTL refreshes on every use; expiry unloads; pressure may evict earlier.
- **Page-cache warmth after unload.** Once TTL-unloaded, file-backed pages often remain cached, so a reload re-faults from cache rather than NVMe. The manager may estimate warmth with `mincore()` and report it in status output, while admission always budgets the cold number — warmth is a bonus, never a budget.
- **Warmup on load.** `loading` includes one dummy inference so ONNX arena allocation and CUDA module load land before the readiness probe, keeping first-real-request latency honest.
- **Prewarm.** `[residency].prewarm` lists rungs to load at idle at background priority (e.g., the voice loop's STT+TTS pair), so the first turn after boot is warm instead of cold.

## Mapped weights and lazy loading

Reversible unload is cheap only when a reload does not copy weights again. The in-process engines change as follows.

- **NumPy text embedder.** `read_safetensors` in `kaine/text_embedding_numpy.py` reads the whole file with `read_bytes()`, a private copy. It maps the file read-only with `numpy.memmap` and builds each tensor as a view at its header offset, so the pages are shared with the page cache and with any other process using the same file. `unload()` drops the views and the map; a reload maps again. Tensors that need a dtype conversion are converted once on load, and the conversion is recorded in the footprint.
- **Torch engines** (the emotion classifier, the Topos encoders). Weights load through `safetensors.safe_open` on CPU. On a GPU the device copy still costs memory; the map only removes the host copy, and the footprint records which.
- **Lazy Topos.** The Topos encoder is built on first use through `ensure_loaded()`, not when the module starts, so a host that multiplexes Topos does not pay for it until a frame needs encoding.
- **ONNX Runtime sessions KAINE creates.**
  - External initializers are memory-mapped on CPU.
  - `session.save_external_prepacked_constant_initializers = 1` maps prepacked weights too.
  - The CPU arena uses `arena_extend_strategy = kSameAsRequested`; a CUDA session gets `gpu_mem_limit` from its rung.
  - `disable_prepacking` trades speed for memory, so it is measured per operation by the calibration tool and set per rung, never globally.
- **sherpa-onnx** bundles its own ONNX Runtime. It accepts `SessionConfig` keys but not arena caps or shared allocators, so its footprint is measured, not bounded. The design says so instead of claiming a cap.

## Quantization ladder fixed before launch

A quantization change is a model change: a Q4 organ and a Q8 organ are different organs, and an int8 encoder perceives differently from a float one.

- **Every rung carries its quantization** (`bf16`, `Q8_0`, `Q4_K_M`, `int8`, `int4`) and the SHA-256 of its weights file, in the rung catalogue and the footprint catalogue.
- **Each tier names one rung per organ.** The tier profiles (`config/profiles/tier*.toml`, a shared file sequenced through the integrator) name the rung, and with it the quantization, for the organ, the speech engines and each encoder. The fit report shows the chosen ladder.
- **The run manifest records what really loaded.** `RunContext` gains `model_rungs`: for each component, the backend, model id, quantization and weights hash that loaded at boot.
- **No substitution during a run.**
  - In deterministic mode, and in any run started by a study runner, rung selection is frozen at boot. A rung that later fails to load is a surfaced residency failure; the manager does not ladder down to a different rung.
  - The failure is recorded as an incident, and the run's admissibility check marks the run inadmissible.
  - Outside studies, automatic ladder-down stays as designed, with the reason surfaced.

## Speech ladder

The ladder uses the backends and models that exist today (`runtime-backends`, `sherpa-onnx-speech`). A rung is a `(backend, model id)` pair:

**TTS (`[vox].backend`), heaviest to lightest:**

| Rung | Backend | Model | Notes |
|---|---|---|---|
| `tts-expressive` | `chatterbox` | Chatterbox (served over HTTP) | the current default top rung; expressive; GPU-served |
| `tts-standard` | `sherpa_onnx` | `kokoro-en` (Kokoro-82M, int8 ONNX, Apache-2.0 model; espeak-ng data GPL-3.0-or-later, operator-installed, never redistributed) | the light rung; CPU-capable |

**STT (`[audition].backend`), heaviest to lightest:**

| Rung | Backend | Model | Notes |
|---|---|---|---|
| `stt-heavy` | `speaches` | faster-whisper `medium.en` (served over HTTP) | the current default; the quality rung where it fits |
| `stt-standard` | `sherpa_onnx` | `moonshine-base-en` (MIT) | variable-length segments instead of Whisper's fixed 30-second chunks, which is the biggest source of perceived lag in a streaming loop |
| `stt-light` | `sherpa_onnx` | `moonshine-tiny-en` (MIT) | the floor |

Traversal rules:

- Automatic selection considers only installed rungs that fit the budget; the heaviest such rung wins. On a workstation that is the current default pair, unchanged. On an 8 GB unified host, where the measured Chatterbox footprint cannot co-reside with the pinned organ, it lands on the sherpa rungs. The outcome is derived from the budget, not from a host table.
- Traversal never downloads. When the best-fitting rung is absent, the next installed rung serves, with a surfaced hint to run `python -m kaine.setup.speech_models` (which shows name, size and licence, and asks for consent).
- A rung change between `sherpa_onnx` models is a model-id change within one backend; a change between `chatterbox` and `sherpa_onnx`, or `speaches` and `sherpa_onnx`, is a backend change through the existing `BackendRegistry` fallback.

## Latency targets

Targets for the reference budget class — 8 GB unified memory, the `sherpa_onnx` Kokoro and Moonshine rungs + a 2–4B 4-bit organ, all TTL-resident:

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

## Dilation that sees modules, and the lockstep barrier

### Why the earlier assumption fails
The integration notes below assumed that automatic dilation absorbs model loads. It cannot.
- The time-scale controller observes only the cycle's own busy time: control intake, Soma regulation and `tick()`. A model load happens inside a module, off the event loop, so the controller never sees it.
- Each tick reads whatever has reached the module streams by then, with a non-blocking read. How module output splits across ticks therefore depends on wall-clock arrival.
- No event carries the tick that caused it. `Event` has `causal_parent`, but no module sets it. Module events carry wall timestamps and time-based Redis entry ids, and both reach the broadcast payload.
- Deterministic mode today fixes the engine's own timestamps and turns the controller off, but it changes neither intake nor pacing.

So task 9.3, identical traces between an all-resident run and a multiplexed run, cannot pass without a barrier.

### Part A: module-aware dilation (outside deterministic mode)
The controller gains one input beside busy time: the **stall indicator**. A tick is stalled when an interactive-lane rung that an enabled module depends on is in the residency ledger's `loading` state, or when a model-backed module's output is overdue by more than its calibrated load bound. Per tick, the controller observes `max(busy / period, stalled ? 1.0 : 0.0)` through the same EMA, hysteresis and dwell as today.

The effect: a host that keeps swapping models runs at a lower `time_scale`, so subjective time slows instead of perception going stale. A single short load inside the 10 s dwell does not change the scale. That is intended: dilation answers sustained multiplexing, not one swap. With `[residency]` passive, nothing is ever stalled, and the controller behaves exactly as today.

### Part B: the opt-in lockstep barrier (deterministic mode only)
`[cycle].lockstep = true` is accepted only with `deterministic = true`. It is off by default and never on in a shipped profile. It makes the cycle's trace a function of its inputs alone, whatever the wall time.

1. **Causal tick on every module event.**
   - `Event` gains two optional fields: `tick` (int) and `seq` (int). Older events without them still parse.
   - `BaseModule._workspace_loop` sets a context variable to the broadcast's `tick_index` while it runs `on_workspace`.
   - `BaseModule.publish` stamps `tick` from that variable and `seq` from a per-module counter. The counter resets only at boot and travels in the module's snapshot.
2. **Tracked follow-on work.**
   - A task a module starts while handling broadcast k (for example Lingua's generation task) is registered with `self.track(task)`, and its events carry tick k.
   - A module has **finished tick k** when `on_workspace(k)` has returned and every task tracked for k has completed.
3. **Tick-driven producers.**
   - Modules that produce on their own loops (Soma's interoception, the perception sources) gain a lockstep mode. The engine publishes `cycle.tick_start` with k, and each producer emits its sample for k and reports done.
   - In lockstep, perception comes from a seeded, scripted feed (the perception-feed playlist or the womb), advanced one step per tick, never from live devices.
4. **The barrier.**
   - After broadcasting tick k, and on non-experiential ticks after `cycle.tick_start`, the engine waits until every participating module has published `module.tick_done` for k on its stream.
   - The next intake then reads all events whose `tick` ≤ k, ordered by `(tick, source, seq)` rather than by Redis entry id.
   - The broadcast payload's `entry_id` and `timestamp` for each selected event are replaced with the logical values `"<tick>-<source>-<seq>"` and the logical time of its causal tick.
5. **Logical time everywhere.** In lockstep, the registry's shared `EntityClock` is driven by the engine's logical clock, the pattern `workspace_mediation_ablation` already uses with an injected monotonic. Module timers (Chronos, Hypnos, Mnemos, Soma, Thymos, Topos, Vox) then advance with ticks, not wall time. Infrastructure timers (Spot, network timeouts) stay on wall time.
6. **Pacing.** The engine still sleeps to its real budget when a tick finishes early. When a barrier waits longer, wall time passes and logical time does not, which is how a model load appears to a lockstep entity.
7. **Fail closed.**
   - Boot refuses lockstep when any enabled module lacks lockstep support, and names the modules. A run never becomes silently non-deterministic.
   - A participant that does not finish within `[cycle].lockstep_timeout_s` (default 300 s, above every calibrated load bound) pauses the cycle with the existing freeze, records an incident naming the module and tick, and marks the run inadmissible. It never kills the entity.
8. **Spot.** A module waiting on the barrier, or on a model load inside `on_workspace`, does not beat its heartbeat. Spot therefore treats a module as alive while the residency ledger shows its rung `loading` within the bound (task 5.2), and while the engine is waiting at the barrier for a reason other than that module's own timeout.

**Cost.** Lockstep throughput is capped by the slowest module on every tick. It is a research mode for reproducible studies and for task 9.3, not the way an entity lives day to day. A study that uses it fixes `time_scale` before launch and records `lockstep = true` in the run identity.

**This is an engine-semantics change.** It touches `kaine/cycle/engine.py` and `kaine/bus/schema.py` (shared files), `kaine/modules/base.py`, the producers, and Lingua's task tracking. It ships in its own PRs with the integrator's second review. Every existing determinism test must stay green with lockstep off.

## Integration with what already runs

- **The Hypnos organ window.** Voice-alignment training unloads the organ, trains, and reloads it (`run_with_organ_window`). There must be one owner of the organ's memory. The window therefore requests the organ's release and re-admission through the manager, and the manager counts the training footprint in the ledger for the window's duration. The window's shared state file and the consumers' `organ_resting` deferral stay as they are. When the manager is passive (everything fits, or a second GPU has room), the window behaves exactly as today.
- **Spot.** Spot calls a module hung when its heartbeat is older than `heartbeat_timeout_s` while a task runs and the entity is not sleeping. A residency wait must never look like a hang:
  - a module awaiting admission or a load keeps its heartbeat;
  - the manager publishes its `loading` state, and Spot treats a module whose model is loading within the load's measured bound as alive;
  - a load that exceeds its bound is a residency failure (ladder-down, surfaced), not a Spot restart.
- **Cycle timing.** Organ calls are asynchronous, so a load delays that organ's output, not the tick. Outside lockstep, a load changes which tick the output lands in. Module-aware dilation (Part A above) slows subjective time on hosts that multiplex all the time, and the fit report recommends `[cycle].auto_time_scale = true` on them. Only the lockstep barrier (Part B) makes a multiplexed run reproduce an all-resident one.
- **Perception while STT is not resident.** Audio segments that arrive while the STT rung is loading wait in a bounded in-memory queue: bounded by count and age, oldest dropped first, with the drop counted and surfaced. They are never written to disk; zero raw-sense-data persistence is unchanged. With `[audition].transcription_enabled = false` (the shipped default) there is nothing to queue.
- **Privacy.** Residency events and the footprint catalogue are content-free: component, backend, model id, bytes, durations, reasons. No text, audio or latent ever appears in them.

## Decisions

- **KittenTTS, Piper and whisper.cpp are dropped from this change.**
  - `moonshine-tiny-en` (about 30 MB archive) gives the STT ladder a floor inside the backend that already ships, so a separate whisper.cpp engine is not needed.
  - KittenTTS is a developer preview.
  - Piper measures worse than Kokoro on both memory and latency, and KAINE has no existing Piper voices to be compatible with.

  Any of them can return later as its own change if a measured host needs it.
- **Calibration before scheduling.** The planner and its defaults are built against measured footprints, not published ones.
- **No MODIFIED deltas.** The archived `deployment-tiers` already specifies the residency-required recommendation, and `runtime-backends` already specifies fallback. This change adds two capabilities and implements what those specs anticipate. The recommender's reason text, which today says residency is not implemented, is code, not spec.
- **Tier 0's `unsupported_modules` list is out of scope.** It was written when those modules had no torch-free backend. Revisiting it is a separate change once the torch-free backends are measured.

## Non-regression and semantic freeze

The dual-GPU x86_64 workstation default, ROCm, XPU, MPS, and CPU-only hosts are preserved by construction: `llm_proxy` defaults to `none`; discrete hosts budget on device memory as before; automatic ladder selection lands on the highest fitting installed `auto` rung, which on a workstation is the current default pair. No module's semantics move; only timing and engine realisation vary.

## Honest limits

A scheduler that lies about its envelope is amputation with extra steps:

- **What is expected to fit on the 8 GB class.** A 2–4B 4-bit organ (about 2–2.5 GB) pinned, plus Kokoro and Moonshine through sherpa-onnx, plus the reserve, with room for a background job. This is the intended sweet spot and the basis of the warm TTFA target. The calibration run confirms or corrects it.
- **Chatterbox on 8 GB does not coexist** with a useful chat model. Selecting it means per-turn swapping (chat out, Chatterbox in, back again): TTFA becomes load-dominated — seconds, not 1.5 s — and the voice loop feels pause-y. The plan says so when Chatterbox is chosen on a small budget.
- **Larger chat models are borderline.** A 7–8B Q4 model (~4.5–5 GB) plus both speech rungs is tight on 8 GB; KAINE will run it but surfaces tightness and more frequent pin evictions.
- **Training does not fit small hosts.** Fine-tuning the chat LLM is workstation-class background work; on an 8 GB board the planner refuses the schedule with an explanation. Sleep-phase consolidation (summarisation, indexing) does fit — it is chunked and yields.
- **Published figures are not measurements.** The sizes and latencies quoted in this design come from upstream publications and are placeholders until the calibration and latency runs on the reference hosts replace them.

## Risks and mitigations

- **Ledger drift** (calibrated footprint ≠ live peak): footprints are re-measured from live RSS per run; the ledger uses the larger of calibrated and observed, and drift beyond a threshold re-calibrates the catalogue entry.
- **Kernel reclaim under external pressure**: the pressure valve unloads warm rungs as available memory nears the reserve; partial kernel reclaim of a resident model's pages is detected via `mincore()` sampling and reported rather than silently re-faulting.
- **Proxy version coupling**: llama-swap's unload endpoints and group semantics are pinned as a minimum version in setup; llama-server router mode is the fallback path for operators who prefer stock llama.cpp.
- **ONNX runtime arenas** inflating peak RSS: rung configurations bound arena sizes so calibrated footprints stay honest.

Normative requirements for this design live in the spec deltas: `specs/module-residency/spec.md` and `specs/speech-backend-tiers/spec.md`.