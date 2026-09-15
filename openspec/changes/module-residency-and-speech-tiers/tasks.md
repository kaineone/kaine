## 1. Spec deltas and sequencing guards

- [ ] 1.1 Confirm that `portability-tiers` is still PENDING (not archived) and that `runtime-backends`, `deployment-tiers`, and `host-probe` are absent from `openspec/specs/`; record the check in the change notes. If `portability-tiers` has since been archived, rebase this change's deltas against the archived specs before any other task.
- [ ] 1.2 Write `openspec/changes/module-residency-and-speech-tiers/specs/module-residency/spec.md` containing only `## ADDED Requirements` (memory budget probe; residency queue with load–run–unload and idle TTL; surfaced residency events; wizard schedules instead of disabling), and verify by grep that the file emits no `## MODIFIED Requirements` delta against `runtime-backends`, `deployment-tiers`, or `host-probe`.
- [ ] 1.3 Write `openspec/changes/module-residency-and-speech-tiers/specs/speech-tiers/spec.md` containing only `## ADDED Requirements` covering the TTS ladder, the STT ladder, opt-in and compatibility rung restrictions, downgrade-with-reason, consent-gated acquisition, and honest limits.
- [ ] 1.4 Check whether the first-run wizard's small-host behaviour is a requirement under `openspec/specs/`; if it is, emit a `## MODIFIED Requirements` delta in this change replacing disable-on-small-host with schedule-on-small-host; if it is not, capture the behaviour as an ADDED requirement inside `module-residency`. Record which path was taken.
- [ ] 1.5 Verify the proposal's `## Why` states the sequencing relationship to `portability-tiers` (this change builds on `runtime-backends`, `deployment-tiers`, and `host-probe` once they are archived, and emits no delta against them now) and records the correction that Kokoro and Moonshine — not Piper — are the recommended light rungs; leave a coordination note for the `portability-tiers` authors about its Piper backend-table row rather than editing their pending change.
- [ ] 1.6 Run `openspec validate module-residency-and-speech-tiers --strict` until it passes with zero errors and warnings.

## 2. Memory budget probe and residency scheduler

- [ ] 2.1 Implement the memory-budget probe reporting total memory, unified-vs-discrete topology, and per-accelerator free memory, deriving a residency budget minus a configurable OS reserve; capability detection only, no board or product-name branches.
- [ ] 2.2 Add an optional `[residency]` config section (OS reserve, per-organ idle-unload TTLs, per-organ rung override) whose defaults preserve today's behaviour on every existing host when unset.
- [ ] 2.3 Implement the residency planner as a pure, unit-testable function: organ demands (model sizes from the rung registries) plus budget in; plan out — which models co-reside, which time-multiplex, which rung each organ uses.
- [ ] 2.4 Implement the residency executor: per-organ job queues with ensure-load → run → record; an idle-TTL unloader; support for in-process ONNX sessions (create/free) and external services (start/stop or HTTP unload) behind one interface; prefer mmap-backed weight access (GGUF, `.ort` flatbuffers) so reload cost is dominated by page-cache warmth.
- [ ] 2.5 Emit structured residency events (load_start, load_end with duration, unload, evict, downgrade with reason) to the existing operator status surface and logs.
- [ ] 2.6 Route organ model use through the executor for the speech organs and any other heavy organ, with a recorded diff-scope review confirming no changes to cognitive-cycle, workspace, or module-semantics files — only engine wiring and scheduling.

## 3. LLM residency via the existing chat endpoint

- [ ] 3.1 Ship a generated llama-swap config template derived from KAINE config — model name → upstream llama.cpp server command, coexistence groups, TTL unload — with `[lingua].chat_url` pointed at the proxy, and document llama.cpp `llama-server` router mode as the drop-in alternative.
- [ ] 3.2 Add a config-compatibility test asserting the `[lingua].chat_url` key and schema are unchanged, plus a repository check that no first-party LLM model loader, registry, or manager was added.
- [ ] 3.3 Map organ-level exclusivity onto llama-swap groups where two LLM models must never co-reside, and surface proxy load/unload events in residency status when the proxy exposes them, degrading quietly to proxy logs when it does not.

## 4. TTS rung ladder

- [ ] 4.1 Create the TTS rung registry with metadata used for planning and consent: `chatterbox` (top rung, GPU-served, expressive, current default), `kokoro` (82M params, ~327 MB, Apache-2.0, ONNX, RTF ~0.03 on GPU), `kitten` (nano ~15M/~25 MB INT8, micro ~40M, mini ~80M; developer preview; opt-in only), `piper` (compatibility; measured ~2.6 GB peak, ~1720 ms first audio).
- [ ] 4.2 Implement the Kokoro-82M engine behind the existing TTS organ interface, with its ONNX session created and freed by the residency executor.
- [ ] 4.3 Implement the KittenTTS engine, selectable only via explicit operator opt-in configuration and excluded from planner auto-selection and from every automatic fallback path.
- [ ] 4.4 Implement the Piper engine as a compatibility rung that is never auto-selected, surfacing its measured memory and latency when explicitly chosen.
- [ ] 4.5 Wire default selection — constrained budget selects Kokoro, ample budget (including the dual-GPU x86_64 workstation profile) keeps Chatterbox — with every selection or downgrade surfaced with its reason.

## 5. STT rung ladder

- [ ] 5.1 Create the STT rung registry: `speaches` (faster-whisper `medium.en`, heavy, current default), `moonshine` (245M params, ONNX `.ort`, variable-length segments, sub-200 ms target), `whispercpp` (tiny/base floor).
- [ ] 5.2 Implement the Moonshine engine behind the existing STT organ interface, feeding variable-length audio segments with no fixed 30-second chunking, and add the Moonshine v2 sliding-window streaming encoder as an opt-in flag.
- [ ] 5.3 Implement the whisper.cpp tiny/base floor rung for hosts where even Moonshine cannot be scheduled.
- [ ] 5.4 Wire default selection — constrained budget selects Moonshine, ample budget keeps Speaches `medium.en` — with selections and downgrades surfaced with reasons.

## 6. Degradation, consent, and first-run scheduling

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