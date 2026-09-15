## ADDED Requirements

### Requirement: Residency state machine
KAINE SHALL route every model load, hold, and unload through a single per-host residency manager whose states are `absent`, `cold`, `loading`, `resident`, and `unloading`, and no module SHALL start or stop a model server, map weights, or release them except through the manager.

#### Scenario: Cold rung admitted and warmed
- **WHEN** a module submits work for a rung whose artifact is `cold` and admission control grants it
- **THEN** the manager reserves the rung's calibrated peak footprint in the ledger before faulting pages, moves it `cold → loading → resident` on a readiness probe that includes one warmup inference, and only then starts the job.

#### Scenario: TTL expiry releases residency
- **WHEN** a `resident` rung has served no request for its TTL and is not pinned
- **THEN** the manager moves it `resident → unloading → cold`, releases its ledger entry, and the artifact's file pages remain available to the page cache for a cheap later reload.

#### Scenario: Load failure is recorded, not swallowed
- **WHEN** the transition `loading → resident` fails (engine crash, OOM, corrupt artifact, failed warmup)
- **THEN** the manager returns the rung to `cold`, records the failure reason in the surfaced degradation log, and invokes the organ's ladder-down path rather than retrying silently or disabling the module.

### Requirement: Memory budget with a single source of truth
The system SHALL maintain exactly one memory budget per memory domain as the single source of truth for every admission, eviction, and pinning decision. On a unified-memory host, where the CPU and accelerator share one physical memory pool, there SHALL be a single budget covering that pool, derived at startup from the measured total unified memory minus a configured reserve for the operating system, the KAINE runtime, and non-model working memory; the budget SHALL NOT be a hardcoded per-host constant and SHALL be recorded and exposed in status output together with its derivation. On hosts with discrete accelerators or CPU-only execution, the system SHALL maintain one budget per memory domain — each accelerator's memory and the system RAM — using the same derivation rules. After each load the system SHALL reconcile the budget against the engine's measured usage and use the measured footprint for subsequent decisions. Individual modules and organs SHALL NOT compute or enforce their own memory budgets. On unified-memory and CPU-only hosts the system SHALL additionally derive admission headroom at decision time from the kernel's reported available system memory — clamped by any cgroup memory limit — minus the configured reserve minus the manager's ledger of resident footprints, and SHALL NOT use a device-only VRAM figure as the budget on such hosts; a resident rung's full calibrated peak footprint SHALL remain in the ledger even where its weights are mapped as page cache the kernel could reclaim, so admission never spends memory the resident model is already using.

#### Scenario: Budget derivation on a unified-memory host
- **WHEN** the residency manager starts on a host whose CPU and accelerator share one unified memory pool, such as an 8 GB integrated board,
- **THEN** it derives a single budget for that pool from the measured total memory minus the configured reserve, records it as the source of truth for all residency decisions, and exposes the budget and its derivation in status output, and no organ or module computes its own budget.

#### Scenario: Discrete and CPU-only hosts keep their existing shape
- **WHEN** the residency manager starts on a host with one or more discrete accelerators or with CPU-only execution,
- **THEN** it maintains one budget per memory domain (each accelerator's memory and the system RAM) under the same derivation rules, and existing dual-GPU workstation defaults and ROCm, XPU, MPS, and CPU-only configurations continue to operate without change.

#### Scenario: Unified host budgets on system memory
- **WHEN** KAINE starts on a host whose accelerator reports a unified pool, or on a CPU-only host
- **THEN** admission decisions use available system memory (clamped by any cgroup limit) minus the reserve minus ledger footprints, and any "free device memory" reading is ignored for admission.

#### Scenario: Resident mmap'd weights count as spent
- **WHEN** a rung is `resident` with its weights mapped as page cache
- **THEN** its full calibrated peak footprint stays in the ledger even though the kernel could reclaim those pages, so admission never spends memory the resident model is already using.

### Requirement: Admission control and eviction
The system SHALL admit a model load only when the sum of pinned models, currently resident models, and the candidate's estimated footprint fits within the target domain's budget, and SHALL NOT overcommit the budget. When a candidate does not fit, the system SHALL evict resident models — it MUST NOT evict the pinned always-hot organ or a model with in-flight work — choosing victims in order: keep-resident TTL expired first, then lowest priority class, then least recently used. If the candidate still does not fit and no evictable model remains, the system SHALL hold the job in its priority-class queue and surface the budget shortfall instead of dropping the work. Every eviction SHALL be recorded with the victim, the reason, and the job that motivated it. Admission, eviction, and reload SHALL be transparent to organ semantics: whether a job's model was warm or cold SHALL NOT change the job's result. The system SHALL make eviction demand-driven: no resident model SHALL be speculatively unloaded outside TTL expiry, admission pressure, preemption, or external memory pressure.

#### Scenario: Admission without pressure
- **WHEN** a job's model is not resident and its estimated footprint fits within the budget alongside every pinned and resident model,
- **THEN** the model is loaded immediately, the job is dispatched, and the load is recorded against the budget.

#### Scenario: Admission evicts the coldest eligible victim
- **WHEN** a candidate model does not fit and one resident model's keep-resident TTL has expired while another resident model is still warm within its TTL,
- **THEN** the manager evicts the TTL-expired model first, records the eviction with its reason, loads the candidate, and leaves the warm model resident.

#### Scenario: Eviction never races an in-flight request
- **WHEN** a model is selected for eviction — by TTL expiry, admission pressure, or preemption — while a request to that model is still in flight,
- **THEN** the unload is deferred until the in-flight request completes, the request finishes normally with no eviction-induced error, and the unload proceeds immediately afterwards, and the manager never force-unloads a model with in-flight work.

#### Scenario: Budget shortfall queues work instead of overcommitting
- **WHEN** a job's model cannot fit even after every evictable model has been evicted,
- **THEN** the job is held in the queue at its priority class, the shortfall is surfaced with the reason that pinned and in-flight models exhaust the budget, and the budget is never overcommitted.

#### Scenario: In-flight and pinned rungs are protected
- **WHEN** every eviction candidate is either pinned or currently serving a request
- **THEN** the manager does not evict and proceeds to preemption, ladder-down, or refusal instead.

### Requirement: Pinning the always-hot organ
The system SHALL pin exactly one organ as the always-hot organ — by default the organ that realises the cognitive core — making its model exempt from every eviction and preemption decision and permanently accounting its footprint against the budget. The pin SHALL be operator-configurable. If the pinned model's footprint exceeds what the budget can hold, the system SHALL surface a degradation reason naming the organ and the shortfall, and SHALL continue with that organ time-multiplexed at the highest priority — loaded on demand, evicting other work first — rather than failing startup, silently dropping the pin, or disabling the organ.

#### Scenario: Pinned organ survives competing admissions
- **WHEN** speech or perception work needs the budget while the always-hot organ's model is resident,
- **THEN** no admission, eviction, or preemption decision unloads the pinned model, and competing work queues and time-multiplexes around it.

#### Scenario: Pinned model does not fit the budget
- **WHEN** the always-hot organ's model footprint exceeds what the budget can hold on a small host,
- **THEN** the manager surfaces a degradation reason naming the organ and the shortfall and continues with that organ time-multiplexed at the highest priority instead of failing startup or silently unpinning it.

### Requirement: Priority-class work queue with preemption
The system SHALL route all model work through a single priority-class work queue in which every job carries a class from at least a latency-critical class for interactive work such as the speech loop and user-facing chat, and a batch class for background work such as perception indexing, summarisation, and memory consolidation. The system SHALL dispatch jobs in priority-class order before arrival order, so a latency-critical job takes precedence over queued batch work. When a latency-critical job arrives while batch work occupies the budget, the system SHALL preempt the batch work: stop the batch job at a safe point or immediately where the engine allows, return the interrupted batch item to the queue without loss, evict the batch model, load the latency-critical model, and run the latency-critical job, and the batch job SHALL resume afterwards. Preemption SHALL NOT drop, truncate, or fail the interrupted batch item, and the manager SHALL begin making budget available immediately upon a latency-critical job's arrival rather than waiting for batch work to drain. Interactive and background work SHALL run in separate lanes within the queue, one per class; interactive jobs SHALL carry deadlines, and a job admitted after its deadline SHALL still run with the miss recorded and surfaced; sleep-phase consolidation and training SHALL run only as background work when no interactive job is runnable, and inside the operator's configured sleep window when one is set. Background jobs SHALL be written against a yield contract, proceeding in safe units, checkpointing at every boundary, and observing a cancellation flag. To admit latency-critical work the system SHALL signal cancellation on the background jobs holding the needed budget, largest footprint first, SHALL require residency release within a configurable grace window (default 2 s), and SHALL escalate to termination at the next safe point, with a surfaced misbehaviour report, when a job exceeds the hard timeout (default 10 s); a job terminated this way SHALL resume later from its checkpoint.

#### Scenario: Latency-critical speech preempts a batch holder
- **WHEN** a batch job's model occupies most of the budget and a latency-critical speech job arrives,
- **THEN** the manager begins making budget available immediately, stops the batch job at a safe point, returns its interrupted item to the queue without loss, evicts the batch model, loads the speech model, and runs the speech job without waiting for the batch job to finish, and the batch job resumes afterwards.

#### Scenario: Queue order follows priority class, not arrival
- **WHEN** a batch job is queued first and a latency-critical job is queued second while the budget is occupied,
- **THEN** the latency-critical job is dispatched first and the batch job waits.

#### Scenario: Sleep-phase work respects the window and the lane
- **WHEN** a sleep window is configured, interactive work is idle, and consolidation is pending
- **THEN** consolidation runs inside the window and yields per the preemption contract the moment interactive work arrives.

#### Scenario: Misbehaving batch job is contained
- **WHEN** a background job ignores cancellation beyond the hard timeout
- **THEN** the manager terminates it at the next safe point, surfaces the preemption failure and the interactive job's actual delay, and the interactive job proceeds.

### Requirement: Keep-resident TTL and warm-path guarantees
The system SHALL keep each model resident for a configurable keep-resident TTL (a global default with per-organ override) measured from its most recent job, and SHALL refresh the TTL on every job dispatched to it. While a model is resident and within its TTL, jobs targeting it SHALL be served on the warm path — dispatched to the resident model with no unload and no reload — and eviction SHALL prefer expired, lower-priority, or older models over a model warm within its TTL. When the TTL expires with no in-flight and no queued work for that model, the system SHALL unload it using the mechanism the engine provides (in-process release or an unload endpoint), confirm the unload before reclaiming, return its footprint to the budget, and record the unload. Unloading SHALL preserve fast-reload conditions — weights remain on disk and mapped or page-cached where the platform allows — so a later job reloads the model automatically without operator action. The system SHALL require every rung's artifact to be memory-mappable, and SHALL budget every admission on the rung's calibrated peak footprint rather than its file size.

#### Scenario: Warm path serves back-to-back work
- **WHEN** a job targets a model that is resident and within its keep-resident TTL,
- **THEN** the job is dispatched to the resident model with no unload and no reload, and the TTL is refreshed from this job.

#### Scenario: TTL expiry returns budget
- **WHEN** no in-flight or queued job has targeted a resident model for the duration of its keep-resident TTL,
- **THEN** the model is unloaded, its confirmed footprint is returned to the budget, the unload is recorded, and a later job reloads it automatically without operator action.

#### Scenario: Warm latency-critical model is not the eviction victim
- **WHEN** a batch job needs budget and both a warm latency-critical model within its TTL and an expired batch-class model are resident,
- **THEN** the manager evicts the expired batch-class model first and keeps the warm latency-critical model resident.

#### Scenario: Cold reload is budgeted honestly
- **WHEN** a rung is admitted after TTL expiry, whether its pages are cache-warm or cache-cold
- **THEN** admission had reserved the full calibrated footprint, and the turn's breakdown reports the actual load segment actually paid.

### Requirement: Graceful degradation with surfaced reasons
When a model fails to load — the engine crashes, memory is exhausted, the engine is missing, or the model files are absent — the system SHALL release whatever the failed load reserved, reconcile the budget, and attempt the next lighter rung for that organ, surfacing a degradation event that names the organ, the rung that failed, the reason, the rung now serving, and the expected effect on the operator experience. The system SHALL NOT silently disable a module: disabling an organ is the last resort, taken only when no rung can be admitted or every rung fails, and even then the system SHALL surface the reason with the rungs attempted and SHALL re-attempt admission automatically when the budget frees or the operator changes configuration. A rung whose model files are absent SHALL be treated as unavailable with that reason surfaced, and the residency manager SHALL NOT download, install, or acquire models on its own; acquisition follows the operator-consent path. When a request cannot be admitted for budget reasons, the system SHALL walk the organ's ladder down through installed rungs with each substitution surfaced, and SHALL deliver an honest refusal naming the blocking holder when no rung fits, retrying or parking the request per policy rather than dropping it silently.

#### Scenario: A model fails to load
- **WHEN** a model load fails because the engine process exits or memory is exhausted during load,
- **THEN** the manager releases whatever the failed load reserved, reconciles the budget, records the failure with its reason, attempts the next lighter rung for the same job, completes the job on that rung, and surfaces a degradation event naming the failed rung, the reason, and the rung now serving, while queued work continues without wedging.

#### Scenario: A host where only the smallest rung fits
- **WHEN** the budget can admit only the smallest rung of each on-demand organ and cannot admit the larger rungs even with every evictable model unloaded,
- **THEN** the manager serves those organs through their smallest rung, time-multiplexing queued work around the pinned always-hot organ, surfaces that the larger rungs are unavailable with the budget as the reason and what that means for responsiveness, and keeps every module enabled.

#### Scenario: Disabling an organ is the surfaced last resort
- **WHEN** even the smallest rung of an organ cannot be admitted or every rung fails to load,
- **THEN** only then is the organ disabled, the disablement is surfaced with the reason and the rungs attempted, and the manager re-attempts admission automatically when the budget frees or the operator changes configuration, without requiring a restart.

#### Scenario: Absent model files are surfaced, never downloaded silently
- **WHEN** the selected rung's model files are absent from the host,
- **THEN** the manager treats that rung as unavailable with the reason surfaced, degrades to a lighter installed rung where one exists, and does not download or install anything without operator consent.

#### Scenario: TTS downshifts with a surfaced reason
- **WHEN** Kokoro cannot be admitted on a loaded host and Kitten micro is installed and fits
- **THEN** the turn runs on Kitten micro and the operator sees "TTS downgraded Kokoro-82M → Kitten micro: insufficient memory while \<holder\> resident".

#### Scenario: Honest refusal instead of silence
- **WHEN** no STT rung can be admitted for a voice turn
- **THEN** the loop responds with a spoken and written message naming the blocker, and retries or parks per policy — it never drops the turn silently.

### Requirement: LLM tier delegation via the existing chat endpoint
KAINE SHALL adopt llama-swap or llama-server router mode for the LLM tier strictly behind the existing `[lingua].chat_url` OpenAI-compatible endpoint without changing any module's calling contract, SHALL reconcile the proxy's loaded models into the residency ledger and request unloads through the proxy's unload API when admission requires it, and SHALL default `llm_proxy = none` so existing hosts keep today's single-server behaviour.

#### Scenario: Chat model unloads after TTL and returns transparently
- **WHEN** `llm_proxy = llama-swap`, the chat model has been idle past its TTL, and a later chat turn arrives
- **THEN** the proxy has released the model's footprint (or the manager requested it via `POST /api/models/unload/<model>` when admission needed it), and the turn transparently reloads it through the same `chat_url`.

#### Scenario: Batch job swaps through an exclusive group
- **WHEN** a background consolidation job needs the LLM while the chat model is resident
- **THEN** the job is submitted under the batch group's model name, the group's exclusivity swaps the chat model out and back, and the manager's ledger tracks both transitions via reconciliation.

#### Scenario: Default preserves today's behaviour
- **WHEN** `llm_proxy = none` on an existing workstation
- **THEN** KAINE issues no reconciliation or unload calls, and behaviour is identical to before this change.

### Requirement: Non-regression and semantic freeze
KAINE SHALL preserve the dual-GPU x86_64 workstation default and ROCm, XPU, MPS, and CPU-only behaviour, and SHALL NOT change the cognitive cycle, the workspace, or any module's input/output semantics — this change SHALL alter only when and where models are resident and which engine realises an organ.

#### Scenario: Existing workstation configuration upgrades cleanly
- **WHEN** a pre-change workstation configuration is used with this change enabled
- **THEN** the resolved engines, endpoints, and module behaviour match the pre-change defaults, with the residency manager passive because nothing approaches the budget.

#### Scenario: Organ contracts unchanged under scheduling
- **WHEN** a module runs under the new scheduling on any host
- **THEN** its inputs, outputs, and workspace interactions are identical to its contract; only latency, residency timing, and — where the ladder substituted an engine — voice or transcription character differ, with any substitution surfaced.

### Requirement: Honest statement of limits
KAINE SHALL state at plan time and at runtime which requested configurations do not fit the budget and what the consequence feels like — including Chatterbox plus a chat model on an 8 GB host (per-turn swapping, load-dominated TTFA), on-device chat-LLM training (workstation-class, refused on small budgets), and Piper's measured disadvantage — and SHALL refuse a schedule that would thrash rather than run it silently.

#### Scenario: Infeasible pairing is named at plan time
- **WHEN** the operator selects Chatterbox plus a 7–8B chat model on an 8 GB host
- **THEN** the plan surfaces that these cannot be resident together, that per-turn swapping will make TTFA load-dominated, and offers Kokoro or a larger host as the remedy.

#### Scenario: Unschedulable work is refused, not thrashed
- **WHEN** a requested combination exceeds even time multiplexing, such as training the chat model while serving voice on an 8 GB board
- **THEN** the planner refuses the schedule with an explanation of the envelope and runs nothing that would silently degrade the interactive class.