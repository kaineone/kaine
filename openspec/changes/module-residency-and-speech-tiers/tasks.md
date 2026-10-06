## 1. Spec deltas and sequencing

- [x] 1.1 `portability-tiers` was archived on 2026-09-17: `runtime-backends`, `deployment-tiers` and `host-probe` are living specs. The deltas are revised against them. `deployment-tiers` already specifies "Tier 2 with module residency required", so this change needs no MODIFIED delta (recorded in `design.md`, Decisions).
- [x] 1.2 `specs/module-residency/spec.md` is `## ADDED Requirements` only, and adds calibration and the fit report, reversible unload, one owner of model memory, residency waits that are not faults, the bounded perception queue, and the `Residency fit` pre-boot row.
- [x] 1.3 `specs/speech-backend-tiers/spec.md` is rewritten over the existing `[vox].backend` / `[audition].backend` values and sherpa model ids. KittenTTS, Piper and whisper.cpp are dropped (recorded in `design.md`, Decisions).
- [x] 1.4 The small-host premise is corrected. The wizard does not disable modules. The blockers are the recommender's "not yet implemented" warning and the `Tier fit` row on tiers with `unsupported_modules`. The behaviour is captured as ADDED requirements in `module-residency` (fit report, `Residency fit` row).
- [x] 1.5 `openspec validate module-residency-and-speech-tiers --strict` passes.

## 2. Measure first: calibration and the fit report

- [x] 2.1 Residency budget: available system memory (`hostmem.system_memory_pool`), clamped by any cgroup limit, minus a reserve (default `max(1 GiB, 10% of physical RAM)`). On discrete hosts, per-device free memory for accelerator-resident rungs. Unified versus discrete comes from `hostmem.classify_accelerator_memory`. No board or product-name branches.
- [ ] 2.2 `python -m kaine.setup.footprint`: with consent, load each enabled component's configured backend in isolation, run one representative inference, and measure peak resident memory (in-process RSS; the server process's RSS for external services; device memory on discrete hosts). Skip and name absent models; never download.
- [x] 2.3 Footprint catalogue at `state/residency/footprints.json`: component, backend, model id, bytes, whether the weights are mapped, host class, timestamp, KAINE version; content-free; refreshed by live observations.
- [ ] 2.4 Fit report as a pure function (budget, catalogue, enabled set, ladders → co-resides or plan with shortfall, pinned organ, multiplexed organs, rung per organ, expected feel), shown by the calibration command, `scripts/probe-host` and the wizard. (The pure function is built in `kaine/residency/fit.py`; the three surfaces come with 2.2 and 8.2.)
- [ ] 2.5 Operator step: run calibration on this desktop, the Orin Nano Super and the Pixel 6a, and commit the results under `docs/benchmarks/`. Use them to set the defaults in 3.x (reserve, TTLs, pin, which organs route through the manager first), and record any published figure they contradict.

## 3. Reversible unload

- [x] 3.1 `ensure_loaded()` / `unload()` on `SherpaMoonshineSTT` and `SherpaKokoroTTS`: releasing the model keeps the client and its executor usable, `unload()` waits for in-flight inference, and `aclose()` stays terminal.
- [ ] 3.2 The same pair on the Topos encoders, the emotion classifier and the text embedders (freeing framework caches where the backend has them). (Text embedders done: NumPy, sentence-transformers and the shared wrapper.)
- [ ] 3.3 A service controller for external model servers (organ `llama-server`, Chatterbox, Speaches): stop, start and a health confirmation, generalised from `OrganServerController`.
- [ ] 3.4 Tests: unload → reload gives results identical to a never-unloaded client; unload during inference waits; memory is actually released (RSS drops, measured). (Speech engines: done with fakes, including a weakref check that the model object is freed; the RSS measurement on real models runs with the calibration command in 2.2.)
- [x] 3.5 NumPy text embedder: `read_safetensors` maps the file read-only (`numpy.memmap`) and builds tensor views; `unload()` drops the views and the map.
- [ ] 3.6 Torch engines (emotion classifier, Topos encoders) load through `safetensors.safe_open` on CPU; the Topos encoder is built lazily through `ensure_loaded()`. (Done for the Topos encoders: both load with `use_safetensors=True`, which transformers reads through `safe_open`, and never through pickle. The emotion classifier loads through funasr's own checkpoint reader, so its host copy is measured by calibration, not mapped. The lazy Topos start moves to 4.6, so behaviour with the manager off matches main (9.4).)
- [ ] 3.7 ONNX Runtime sessions KAINE creates: mapped external initializers, `session.save_external_prepacked_constant_initializers = 1`, `arena_extend_strategy = kSameAsRequested`, a per-rung `gpu_mem_limit`, and `disable_prepacking` measured per operation by the calibration tool. sherpa-onnx's limits are documented, not claimed.

## 4. Residency manager

- [ ] 4.1 `[residency]` config (enabled, reserve, `ttl_seconds` with per-rung overrides, `pin`, `prewarm`, `llm_proxy = "none"`, queue bounds). The defaults leave the manager passive on every existing host.
- [ ] 4.2 Ledger and state machine (`absent`, `cold`, `loading`, `resident`, `unloading`), with serialised admission and demand-driven eviction (TTL-expired, then background class, then least recently used; never pinned or in-flight).
- [ ] 4.3 Two lanes (interactive, background) with deadlines. Preemption uses the yield contract (grace 2 s, hard timeout 10 s, resume from checkpoint).
- [ ] 4.4 Pinning, keep-resident TTL, prewarm, and the pressure valve (unload warm rungs, least recently used first, as available memory nears the reserve).
- [ ] 4.5 Content-free residency events (`load_start`, `load_end` with duration, `unload`, `evict`, `downgrade` with reason, `queue_drop`) on the operator status surface and in logs.
- [ ] 4.6 Route the speech organs, the Topos encoder, the emotion classifier and the embedder through the manager. Record a diff-scope review showing no changes to cognitive-cycle, workspace or module-semantics files.

## 5. Integration

- [ ] 5.1 Hypnos organ window: release and re-admit the organ through the manager, and hold the training footprint in the ledger for the window's duration; behaviour is unchanged when the manager is passive.
- [ ] 5.2 Spot: a module whose model is loading within its measured bound is alive; an over-bound load is a residency failure (ladder-down, surfaced), not a restart. Test this with the Spot self-test harness.
- [ ] 5.3 Audition: bounded in-memory queue (count and age) for audio that arrives while STT is not resident; oldest dropped first; drops counted and surfaced; never persisted. Test that no queued audio reaches disk.
- [ ] 5.4 The fit report recommends `[cycle].auto_time_scale = true` on hosts whose plan multiplexes an interactive organ; the operator decides.

## 6. LLM residency via the existing chat endpoint

- [ ] 6.1 Generate a llama-swap config from KAINE config (model name → `llama-server` command, TTLs, exclusive groups) with `[lingua].chat_url` pointed at the proxy. Document llama.cpp router mode as the alternative. Installing either is consent-gated.
- [ ] 6.2 Reconcile the proxy's loaded models into the ledger, and call the proxy's unload endpoint when admission needs the footprint. `llm_proxy = "none"` makes no reconciliation or unload calls.
- [ ] 6.3 A config-compatibility test showing `[lingua].chat_url` is unchanged, plus a repository check that no first-party LLM model manager was added.

## 7. Speech ladder

- [ ] 7.1 Rung catalogue for the TTS ladder (`chatterbox`, `sherpa_onnx`/`kokoro-en`) and the STT ladder (`speaches`, `sherpa_onnx`/`moonshine-base-en`, `sherpa_onnx`/`moonshine-tiny-en`), with footprints from the catalogue.
- [ ] 7.2 Automatic selection of the heaviest installed rung that fits. Model-id changes happen within `sherpa_onnx`; backend changes go through the existing `BackendRegistry` fallback. Absent models give a hint that names `python -m kaine.setup.speech_models`, and nothing is downloaded.
- [ ] 7.3 Downgrades and disablements surfaced with reasons through `backend_state` and residency status.
- [ ] 7.4 Per-turn voice latency breakdown (warm and cold paths recorded separately), with persistent misses surfaced.

## 8. Pre-boot, wizard and recommender

- [ ] 8.1 `Residency fit` pre-boot row: PASS when the set co-resides, PASS with the plan when it is schedulable, FAIL naming the shortfall when it is not, SKIP naming the calibration command when there is no catalogue.
- [ ] 8.2 Wizard: show the fit report and the speech recommendation. Apply a recommendation only on consent. When a heavier choice is kept, state its cost.
- [ ] 8.3 `recommend_tier()` residency branch: replace the "not yet implemented" reason with the fit-report pointer.

## 9. Tests and no-regression

- [ ] 9.1 Unit tests: budget (fixture `/proc/meminfo`, cgroup limit, unified vs discrete), fit report, admission and eviction order, pin, TTL, lanes and preemption, ladder selection, consent gate.
- [ ] 9.2 Integration test "small unified host": with the budget mocked to an 8 GB unified pool (or a cgroup cap), a full voice turn that needs STT, organ and TTS completes, peak resident memory stays under budget, no module is disabled, and residency events fire.
- [ ] 9.3 (needs group 12) Invariant test: the cognitive-cycle trace and workspace contents are identical between an all-resident run and a multiplexed run on the same inputs in deterministic mode, excluding timing.
- [ ] 9.4 No-regression: with `[residency]` unset, the resolved backends, endpoints and behaviour match main, and the full offline suite is green.
- [ ] 9.5 Network-isolated consent test: nothing is downloaded without consent; with consent, a download happens once and is idempotent.

## 10. Measurement, documentation and validation

- [ ] 10.1 Latency harness: cold and warm load time per rung; STT segment latency; TTS time-to-first-audio and real-time factor; organ first token including swap-in; end-to-end voice turn; peak resident memory. Output is JSON plus a markdown table.
- [ ] 10.2 Operator step: run the harness on the Orin Nano Super, the Pixel 6a and this desktop; commit results under `docs/benchmarks/`, with a table of combinations that do not fit, their shortfalls and their feel.
- [ ] 10.3 Docs: a residency guide (budget, calibration, TTLs, pin, llama-swap, what multiplexing feels like, honest limits), plus updates to `docs/07-deployment/README.md`, `docs/03-hardware/README.md`, `docs/07-deployment/headless-host.md`, `docs/09-modules/audition.md` and `docs/09-modules/vox.md`.
- [ ] 10.4 Final validation: `openspec validate module-residency-and-speech-tiers --strict` passes, and every task is checked or deferred with its reason.

## 11. Quantization ladder fixed before launch

- [ ] 11.1 Rung and footprint catalogues record each rung's quantization and the SHA-256 of its weights file.
- [ ] 11.2 Tier profiles name one rung per organ and encoder (`config/profiles/tier*.toml`, sequenced through the integrator); the fit report shows the ladder.
- [ ] 11.3 `RunContext.model_rungs`: backend, model id, quantization and weights hash per component, as loaded at boot.
- [ ] 11.4 Deterministic and study runs freeze rung selection at boot. A later failure to load is a surfaced residency failure and an incident, the run's admissibility check marks it inadmissible, and no other rung is substituted. Tests cover all three.

## 12. Dilation that sees modules, and the lockstep barrier (engine semantics, high-risk)

- [ ] 12.1 Stall indicator into `TimeScaleController.observe`; identical behaviour when `[residency]` is passive (test).
- [ ] 12.2 `Event.tick` and `Event.seq` optional fields; older events parse (test).
- [ ] 12.3 `BaseModule`: tick context variable around `on_workspace`, `publish` stamps `tick` and `seq`, `self.track(task)`, `module.tick_done` emission; the `seq` counter travels in snapshots.
- [ ] 12.4 Lingua tracks its generation tasks; Soma and the perception sources gain a tick-driven lockstep mode fed by the seeded feed.
- [ ] 12.5 Engine (`kaine/cycle/engine.py`, shared file, integrator told first): `cycle.tick_start`, the barrier, intake by `(tick, source, seq)`, logical `entry_id` and `timestamp` in the broadcast payload.
- [ ] 12.6 Logical `EntityClock` for the registry in lockstep.
- [ ] 12.7 Boot refuses lockstep without deterministic mode or with an unsupported module (names them); `lockstep_timeout_s` freezes the cycle, records an incident and marks the run inadmissible.
- [ ] 12.8 Spot: alive while loading within bound or waiting at the barrier for another module.
- [ ] 12.9 Tests: two lockstep runs on the same scripted inputs, one with random injected load delays per model call, give identical normalised traces and workspace contents; every existing determinism test stays green with lockstep off; module-aware dilation lowers the scale under sustained stalls and not under one short stall.
- [ ] 12.10 Docs: the entity-time chapter and the residency guide describe dilation, lockstep, its cost, and that lockstep is a study mode.
