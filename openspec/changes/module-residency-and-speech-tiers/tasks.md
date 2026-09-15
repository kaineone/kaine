## 1. Spec deltas and sequencing guards

- [ ] 1.1 Confirm that `portability-tiers` is still PENDING (not archived) and that `runtime-backends`, `deployment-tiers`, and `host-probe` are absent from `openspec/specs/`; record the check in the change notes. If `portability-tiers` has since been archived, rebase this change's deltas against the archived specs before any other task.
- [ ] 1.2 Write `openspec/changes/module-residency-and-speech-tiers/specs/module-residency/spec.md` containing only `## ADDED Requirements` (memory budget probe; residency queue with load–run–unload and idle TTL; surfaced residency events; wizard schedules instead of disabling), and verify by grep that the file emits no `## MODIFIED Requirements` delta against `runtime-backends`, `deployment-tiers`, or `host-probe`.
- [ ] 1.3 Write `openspec/changes/module-residency-and-speech-tiers/specs/speech-tiers/spec.md` containing only `## ADDED Requirements` covering the TTS ladder, the STT ladder, opt-in and compatibility rung restrictions, downgrade-with-reason, consent-gated acquisition, and honest limits.
- [ ] 1.4 Check whether the first-run wizard's small-host behaviour is a requirement under `openspec/specs/`; if it is, emit a `## MODIFIED Requirements` delta in this change replacing disable-on-small-host with schedule-on-small-host; if it is not, capture the behaviour as an ADDED requirement inside `module-residency`. Record which path was taken.
- [ ] 1.5 Verify the proposal's `## Why` states the sequencing relationship to `portability-tiers` (this change builds on `runtime-backends`, `deployment-tiers`, and `host-probe` once they are archived, and emits no delta against them now) and records the correction that Kokoro and Moonshine — not Piper — are the recommended light rungs; leave a coordination note for the `portability-tiers` authors about its Piper backend-table row rather than editing their pending change.
- [ ] 1.6 Run `openspec validate module-residency-and-speech-tiers --strict` until it passes with zero errors and warnings.

## 2. Memory budget probe and residency scheduler

### Requirement: Memory budget probe
KAINE SHALL probe the host at startup and derive a model-residency memory budget from total memory, unified-versus-discrete memory topology, and current accelerator occupancy, using capability detection only and no host-specific names.

#### Scenario: Unified-memory probe
- **WHEN** the probe runs on a host where CPU and accelerator share one physical memory pool, such as an 8 GB unified-memory board
- **THEN** the budget is derived from the shared total minus a configurable OS reserve and no separate VRAM pool is assumed

#### Scenario: Discrete-GPU probe
- **WHEN** the probe runs on a host with discrete accelerators
- **THEN** the budget is accounted per device and existing per-backend model placement is unchanged

### Requirement: Residency queue and lifecycle
KAINE SHALL queue organ work that needs a non-resident model, load that model, run the work, and unload the model after an idle timeout, so that the set of resident models at any instant stays within the planned budget.

#### Scenario: Time-multiplexed voice turn
- **WHEN** the STT, LLM, and TTS models cannot co-reside within the budget and a voice turn needs all three
- **THEN** the work executes in queued order with at most the planned models resident at any instant, every stage completes, and no module is disabled

#### Scenario: Idle unload
- **WHEN** a loaded model receives no work for its configured idle TTL
- **THEN** it is unloaded, its memory is released, and a residency event records the unload and its duration

### Requirement: Surfaced residency state
KAINE SHALL report residency events — load, run, unload, evict, and downgrade, each with reason and duration — through operator-visible status.

#### Scenario: Operator inspects residency
- **WHEN** the operator requests status during a multiplexed voice turn on a constrained host
- **THEN** the status shows which organ models are resident, which requests are queued, and the reason and duration of the most recent load or unload

- [ ] 2.1 Implement the memory-budget probe reporting total memory, unified-vs-discrete topology, and per-accelerator free memory, deriving a residency budget minus a configurable OS reserve; capability detection only, no board or product-name branches.
- [ ] 2.2 Add an optional `[residency]` config section (OS reserve, per-organ idle-unload TTLs, per-organ rung override) whose defaults preserve today's behaviour on every existing host when unset.
- [ ] 2.3 Implement the residency planner as a pure, unit-testable function: organ demands (model sizes from the rung registries) plus budget in; plan out — which models co-reside, which time-multiplex, which rung each organ uses.
- [ ] 2.4 Implement the residency executor: per-organ job queues with ensure-load → run → record; an idle-TTL unloader; support for in-process ONNX sessions (create/free) and external services (start/stop or HTTP unload) behind one interface; prefer mmap-backed weight access (GGUF, `.ort` flatbuffers) so reload cost is dominated by page-cache warmth.
- [ ] 2.5 Emit structured residency events (load_start, load_end with duration, unload, evict, downgrade with reason) to the existing operator status surface and logs.
- [ ] 2.6 Route organ model use through the executor for the speech organs and any other heavy organ, with a recorded diff-scope review confirming no changes to cognitive-cycle, workspace, or module-semantics files — only engine wiring and scheduling.

## 3. LLM residency via the existing chat endpoint

### Requirement: LLM residency through the existing chat endpoint
KAINE SHALL realise LLM model switching by delegating to an OpenAI-compatible proxy or router reached through the existing `[lingua].chat_url` configuration key, and SHALL NOT build a first-party LLM model manager.

#### Scenario: Load-on-demand through llama-swap
- **WHEN** `[lingua].chat_url` points at a llama-swap instance whose model map declares per-model upstream commands, coexistence groups, and an unload TTL, and a turn requests a model that is not resident
- **THEN** the proxy loads the model on demand, the turn completes through the unchanged lingua organ, and the model is unloaded after the TTL

#### Scenario: Router-mode alternative
- **WHEN** the operator instead points `[lingua].chat_url` at a llama.cpp `llama-server` running in router mode
- **THEN** dynamic model switching works through the same configuration key with no KAINE-side model manager and no schema change

- [ ] 3.1 Ship a generated llama-swap config template derived from KAINE config — model name → upstream llama.cpp server command, coexistence groups, TTL unload — with `[lingua].chat_url` pointed at the proxy, and document llama.cpp `llama-server` router mode as the drop-in alternative.
- [ ] 3.2 Add a config-compatibility test asserting the `[lingua].chat_url` key and schema are unchanged, plus a repository check that no first-party LLM model loader, registry, or manager was added.
- [ ] 3.3 Map organ-level exclusivity onto llama-swap groups where two LLM models must never co-reside, and surface proxy load/unload events in residency status when the proxy exposes them, degrading quietly to proxy logs when it does not.

## 4. TTS rung ladder

### Requirement: TTS rung ladder
KAINE SHALL provide text-to-speech as an ordered rung ladder — Chatterbox, Kokoro-82M, KittenTTS, Piper — and SHALL default to Kokoro-82M on hosts whose budget cannot hold Chatterbox alongside the other resident models, while leaving ample-memory defaults unchanged.

#### Scenario: Constrained host defaults to Kokoro
- **WHEN** the residency planner determines the Chatterbox service does not fit the budget alongside the LLM on a unified-memory board
- **THEN** Kokoro-82M (82M parameters, ~327 MB, Apache-2.0, ONNX) is selected as the TTS rung, the choice and its reason are surfaced, and speech output continues through the same organ interface

#### Scenario: Workstation keeps Chatterbox
- **WHEN** the host is the dual-GPU x86_64 workstation profile with ample memory
- **THEN** the default TTS rung remains Chatterbox and no downgrade is surfaced

### Requirement: Opt-in and compatibility rung restrictions
KAINE SHALL offer KittenTTS only as an explicitly opt-in rung and Piper only as a compatibility rung, and SHALL NOT auto-select either — KittenTTS because its nano INT8 build is a developer preview with known issues, and Piper because measured 2026 benchmarks place it behind Kokoro on both peak memory and first-audio latency.

#### Scenario: Downgrade skips restricted rungs
- **WHEN** the TTS ladder downgrades from Kokoro due to a load failure
- **THEN** the next automatically selectable rung is used, KittenTTS is not silently activated, and the operator sees the reason for the downgrade

#### Scenario: Explicit Piper selection
- **WHEN** the operator explicitly selects Piper
- **THEN** it runs with its measured ~2.6 GB peak memory and ~1720 ms first-audio latency surfaced before use, and it is never chosen automatically over Kokoro

- [ ] 4.1 Create the TTS rung registry with metadata used for planning and consent: `chatterbox` (top rung, GPU-served, expressive, current default), `kokoro` (82M params, ~327 MB, Apache-2.0, ONNX, RTF ~0.03 on GPU), `kitten` (nano ~15M/~25 MB INT8, micro ~40M, mini ~80M; developer preview; opt-in only), `piper` (compatibility; measured ~2.6 GB peak, ~1720 ms first audio).
- [ ] 4.2 Implement the Kokoro-82M engine behind the existing TTS organ interface, with its ONNX session created and freed by the residency executor.
- [ ] 4.3 Implement the KittenTTS engine, selectable only via explicit operator opt-in configuration and excluded from planner auto-selection and from every automatic fallback path.
- [ ] 4.4 Implement the Piper engine as a compatibility rung that is never auto-selected, surfacing its measured memory and latency when explicitly chosen.
- [ ] 4.5 Wire default selection — constrained budget selects Kokoro, ample budget (including the dual-GPU x86_64 workstation profile) keeps Chatterbox — with every selection or downgrade surfaced with its reason.

## 5. STT rung ladder

### Requirement: STT rung ladder
KAINE SHALL provide speech-to-text as an ordered rung ladder — Speaches/faster-whisper `medium.en`, Moonshine, and whisper.cpp tiny/base — and SHALL default to Moonshine on constrained hosts because its variable-length segment processing removes the fixed 30-second chunking lag.

#### Scenario: Constrained host defaults to Moonshine
- **WHEN** the residency planner cannot hold the Speaches `medium.en` service within the budget
- **THEN** Moonshine (245M parameters, ONNX `.ort` flatbuffer) is selected, audio is processed as variable-length segments rather than fixed 30-second chunks, and the selection is surfaced

#### Scenario: Workstation keeps whisper medium
- **WHEN** the host has ample memory for the existing defaults
- **THEN** Speaches/faster-whisper `medium.en` remains the default STT rung

- [ ] 5.1 Create the STT rung registry: `speaches` (faster-whisper `medium.en`, heavy, current default), `moonshine` (245M params, ONNX `.ort`, variable-length segments, sub-200 ms target), `whispercpp` (tiny/base floor).
- [ ] 5.2 Implement the Moonshine engine behind the existing STT organ interface, feeding variable-length audio segments with no fixed 30-second chunking, and add the Moonshine v2 sliding-window streaming encoder as an opt-in flag.
- [ ] 5.3 Implement the whisper.cpp tiny/base floor rung for hosts where even Moonshine cannot be scheduled.
- [ ] 5.4 Wire default selection — constrained budget selects Moonshine, ample budget keeps Speaches `medium.en` — with selections and downgrades surfaced with reasons.

## 6. Degradation, consent, and first-run scheduling

### Requirement: Downgrade with surfaced reason
KAINE SHALL, when a selected engine fails to load or exceeds its budget, automatically downgrade to the next lighter selectable rung with the reason surfaced, and SHALL disable a module only when no rung can run, never silently.

#### Scenario: Engine fails to load
- **WHEN** the selected TTS or STT engine fails to initialise on a constrained host
- **THEN** the organ downgrades to the next selectable rung, the voice loop continues, and the operator sees the failed engine, the reason, and the rung now in use

#### Scenario: No rung fits
- **WHEN** no rung of an organ can run within the budget
- **THEN** the module is disabled only after the reason is surfaced and recorded, as the last resort after all lighter rungs have been offered

### Requirement: Consent-gated acquisition
KAINE SHALL NOT download or install any model or engine without operator consent, and SHALL present each artifact's name, size, and license before acquisition.

#### Scenario: First Kokoro download
- **WHEN** the scheduler first needs Kokoro-82M and it is not present on disk
- **THEN** the operator is prompted with its ~327 MB size and Apache-2.0 license, the download proceeds only on consent, and without consent the ladder downgrades with the reason surfaced

### Requirement: Wizard schedules instead of disabling
On hosts that cannot co-reside the default models, the first-run wizard SHALL propose a residency schedule of lighter rungs plus time multiplexing, and SHALL NOT disable modules as the primary answer to a small host.

#### Scenario: Small-host onboarding
- **WHEN** the wizard runs on a host whose budget cannot hold the current defaults
- **THEN** it proposes a schedule with expected latencies, requests consent for downloads, and completes with all modules enabled unless the operator explicitly declines

### Requirement: Honest limits
KAINE SHALL state which engine combinations do not fit a probed host, quantify the shortfall, and describe what the scheduled alternative feels like, in wizard output and documentation.

#### Scenario: Combination that does not fit
- **WHEN** the operator requests Chatterbox, whisper `medium.en`, and a large LLM together on an 8 GB unified-memory host
- **THEN** the wizard states the combination does not fit, quantifies the shortfall against the budget, and offers the scheduled alternative with measured or estimated latencies

### Requirement: Cognitive semantics unchanged
The residency and speech-tier mechanisms SHALL NOT alter the cognitive cycle, the workspace, or any module's semantics, and SHALL only change when and where a model is resident and which engine realises an organ.

#### Scenario: Identical cycle under multiplexing
- **WHEN** the same voice turn is run with all models co-resident and with time-multiplexed models on a constrained host
- **THEN** the sequence of cognitive-cycle steps and the workspace contents are identical, differing only in timing

- [ ] 6.1 Implement the shared downgrade manager: on load failure or budget miss, move to the next selectable lighter rung, record and surface the reason; skip preview rungs (KittenTTS) automatically and never prefer Piper over Kokoro automatically; disable a module only when no rung runs, after surfacing and recording the reason.
- [ ] 6.2 Implement consent-gated acquisition: an engine/model manifest with name, size, and license; a prompt before any first download or install; recorded decisions; and downgrade-with-reason when consent is declined.
- [ ] 6.3 Rework the first-run wizard small-host path: propose a residency schedule (rungs, multiplexing plan, expected latencies), request consent for downloads, keep modules enabled, and reduce module disabling to an explicit, reasoned last resort.
- [ ] 6.4 Add honest-limits output: when a requested combination does not fit the probed budget, state that it does not fit, quantify the shortfall, and describe the scheduled alternative's expected feel.
- [ ] 6.5 Add a scope guard to the change checklist and CI: the diff touches only scheduler, engine adapters, config, wizard, and docs — no cognitive-cycle, workspace, or module-semantics files.

## 7. Tests and no-regression matrix

- [ ] 7.1 Unit tests: budget probe (fixture `/proc/meminfo`, mock accelerators, unified vs discrete), planner (tight budget yields a multiplex plan, ample budget yields co-residency), executor lifecycle (ensure-load, run, idle-TTL unload), downgrade ordering (including KittenTTS and Piper exclusion from automatic selection), and the consent gate.
- [ ] 7.2 Integration test "small unified host": with the probe mocked to an 8 GB unified budget (or under a cgroup memory cap), run a full voice turn needing STT + LLM + TTS that cannot co-reside; assert every stage completes, the peak resident set matches the plan and stays under budget, no module is disabled, and residency events fire for each load and unload.
- [ ] 7.3 Contract tests against a mocked llama-swap: a request for a non-resident model triggers load-on-demand; `POST /api/models/unload` and `POST /api/models/unload/<model>` unload; exclusive groups swap models; all exercised through the unchanged `[lingua].chat_url`.
- [ ] 7.4 Invariant test: the cognitive-cycle trace and workspace contents are identical between an all-resident run and a multiplexed run on the same inputs, excluding timing.
- [ ] 7.5 No-regression, x86_64 CUDA dual-GPU workstation: existing defaults (Chatterbox TTS, Speaches `medium.en` STT, existing LLM path) unchanged, the scheduler no-ops when everything co-resides, and the full suite is green on the CUDA CI job.
- [ ] 7.6 No-regression, ROCm: backend selection and defaults unchanged and the full suite green (CI runner where available, otherwise a documented manual run with results recorded in the change notes).
- [ ] 7.7 No-regression, Intel XPU: same criteria as 7.6.
- [ ] 7.8 No-regression, Apple MPS: same criteria as 7.6.
- [ ] 7.9 No-regression, CPU-only: same criteria as 7.6, plus verification that the CPU-viable rungs (Kokoro, Moonshine, whisper.cpp, KittenTTS) are selectable with no GPU present.
- [ ] 7.10 Consent test in a network-isolated environment: with consent unset, first use of a non-downloaded rung prompts or downgrades and performs zero network downloads; with consent recorded, the download proceeds once and is idempotent on subsequent runs.

## 8. Latency measurement, documentation, and validation

- [ ] 8.1 Build a latency-measurement harness that records, per rung: cold and page-cache-warm model load time; STT segment latency (Moonshine variable-length vs whisper fixed 30-second chunk); TTS time-to-first-audio and RTF; LLM time-to-first-token including swap-in; end-to-end voice-turn latency; and peak resident memory — emitting structured JSON plus a markdown table.
- [ ] 8.2 Run the harness on the 8 GB unified-memory reference board (the motivating Jetson Orin Nano Super class host) and on the dual-GPU x86_64 workstation; commit results under `docs/benchmarks/`; include a table of combinations that do not fit with quantified shortfalls and a qualitative description of the resulting feel; flag any published figure the measurement contradicts (Kokoro RTF ~0.03 on GPU, Moonshine sub-200 ms, Piper ~2.6 GB / ~1720 ms).
- [ ] 8.3 Write operator documentation: the speech ladder page (stating explicitly that Piper is a compatibility rung, not the lightweight default, and KittenTTS is opt-in), the residency scheduling guide (budget, TTLs, llama-swap groups, what multiplexing feels like), and the honest-limits section.
- [ ] 8.4 Final validation: `openspec validate module-residency-and-speech-tiers --strict` passes; the change contains no `## MODIFIED Requirements` delta against `runtime-backends`, `deployment-tiers`, or `host-probe`; and every checkbox above is checked or explicitly deferred with a reason in the change notes.