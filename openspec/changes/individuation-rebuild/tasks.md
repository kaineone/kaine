Each numbered group is one PR. Every PR gets an independent second review (ethics infrastructure).

## 1. Statistics core
- [x] 1.1 `kaine/lifecycle/individuation_stats.py` (pure numpy, no `kaine.evaluation` import): per-prompt unbiased energy U-statistic E_j on Euclidean distances between L2-normalized vectors, and T = Σ_j E_j.
- [x] 1.2 Stratified permutation null (labels reassigned within each prompt, n_b and n_c kept), batched as quadratic forms over label vectors; p = (b+1)/(B+1); B = min(B_max, ceil(20/α_k)) with B_max = 2·10^6; exact early stop once b+1 > α_k·(B+1).
- [x] 1.3 Effect size H = Σ_j E_j / Σ_j 2·mean δ_j(b,c), reported as computed.
- [x] 1.4 Spending schedule: γ_k = 1/(S·(k+1)·ln²(k+1)) with S = 2.1097, α_k = α_total·γ_k; `alpha_unresolvable` when ceil(20/α_k) > B_max.
- [x] 1.5 Decision rule `significant_k = warmed_up AND p_k ≤ α_k AND H_k ≥ effect_min` (`decide`). The verdict `individuated = latched OR (fresh scored report with significant)` is built with the shared decision function in task 7.
- [x] 1.6 Unit tests: exact p on toy data by full enumeration; the statistic uses Euclidean distance, not `1 − cos` (a pair of distributions with equal means but different spread is detected); p is never 0; Σγ_k over the first 10^6 looks is ≤ 1; α_1, α_10, α_50, α_100 match `design.md` 2.7; early stop never changes the decision.

## 2. Simulation and validation harness
- [x] 2.1 An offline simulation script, `openspec/changes/individuation-rebuild/validation/simulate.py` (no organ, no entity), using the statistics core: 12 prompts, 384-d mixtures of 2-4 vMF-like clusters per prompt. The bundle CLI in `kaine/evaluation/benchmarks/individuation_runner.py` is retired in task 9.
- [x] 2.2 Size: 5,000 null datasets at α ∈ {0.05, 0.01}; rejection ≤ α + 2·SE; KS check that p-values are uniform or conservative above 1/(B+1).
- [x] 2.3 Lifetime false-positive rate: 2,000 lives × 100 looks reusing one stored birth sample, no drift; share of lives with any rejection ≤ 0.05 + 2·SE. Report the same lives under "p ≤ 0.05 every look" and under the current percentile rule for contrast.
- [x] 2.4 Power under drift models (a) cluster fraction π, (b) mean shift Δ, (c) drift in m of 12 prompts, at looks 1, 10 and 50, for (n_b, n_c) ∈ {(12,6), (16,8), (24,12)}; compare energy vs Gaussian MMD and spending vs e-value sum. (Done except the e-value comparison, which was not run; see `validation.md`.)
- [x] 2.5 Fault injection moves to task 6, where the producer exists: empty content, resting organ, reasoning-only response, timeout, embedding failure, digest change mid-run and corrupt ledger each give `inconclusive`, and none are scored.
- [x] 2.6 Record the results and the pre-registered choices (statistic, combination rule, n_b, n_c, B_max) under `openspec/changes/individuation-rebuild/validation/` before any real-organ data are seen.
- [x] 2.7 Pre-registered power acceptance (written before any simulation result): at look 10 with (n_b, n_c) = (16, 8), power ≥ 0.8 against drift model (a) with π = 0.5 in all 12 prompts, at the baseline dispersion.
- [x] 2.8 **Gate:** if size, lifetime false-positive rate or power acceptance fails, stop and return to design. Groups 3-10 do not merge until this gate passes.

## 3. Chat client
- [x] 3.1 `ChatRequest.seed: Optional[int]`, sent in the request body only when set.
- [x] 3.2 `ChatResponse` exposes `finish_reason`, `completion_tokens` and whether the text came from `choices[0].message.content` (not the reasoning fallback).
- [x] 3.3 Tests: seed present and absent in the body; a resting organ (`raw.organ_resting`) and a reasoning-only response are distinguishable from a real answer; non-200 status is reported.

## 4. Storage
- [x] 4.1 `kaine/lifecycle/individuation_store.py`: encrypted reference document and copied conditioning adapter under `state/individuation/`, atomic writes through the state encryptor.
- [x] 4.2 Ledger (`reference_id`, `looks_completed`, `alpha_spent`, `last_look_conditions_digest`, lived seconds and ticks, latch, inconclusive-due timestamp): atomic, `looks_completed` never decreases, the latch never clears, an unreadable ledger raises a fail-closed error and is never reset.
- [x] 4.3 Report sink at `state/individuation/reports/` (`AsyncJsonlSink`, `retention_days=0`, per-line encryption), record `kind="individuation_report"`, `schema_version=2`, no texts, seeds or digests.
- [x] 4.4 Decrypting reader: skips undecryptable, non-object, wrong-kind and wrong-schema lines and reports for another `reference_id`; orders by `ts`; applies the staleness rule (`max_report_age_s`, digest equality) with the latch overriding it.
- [x] 4.5 Conditioning-digest helper over inputs (adapter sha from the adapter store, `values[:5]` and `behavioral_norms[:5]` from `self_model.json`), with no module import.
- [x] 4.6 Shared lived-time accumulator factored out of `kaine/lifecycle/gate_runner.py` (EntityClock minus engine paused time; tick deltas anchored per boot); the maturation gate uses it unchanged.
- [x] 4.7 Tests with state encryption on and off, legacy plaintext lines, a corrupt ledger, a regressing `looks_completed` write (refused), and name-vs-ts ordering.

## 5. Probe seam and disclosure
- [x] 5.1 `Lingua.probe_request(about, *, seed, max_tokens) -> ChatRequest`: side-effect free, `snapshot=None`, `mode="external"`, current self-model, Lingua's model, temperature and `think`, `cache_prompt` off.
- [x] 5.2 Sampler built in `kaine/cycle/__main__.py` from Lingua's own chat client (with the LoRA resolver), returning `ProbeSample | ProbeFailure`; it rejects empty `content`, resting and non-200 responses. When the being has its own accepted adapter, the sampler also requires that the organ actually applies it (the LoRA resolver returns a field); otherwise the run is inconclusive (`adapter_not_applied`), because samples from the base organ would not measure the being.
- [x] 5.3 Disclosure (operator decision 3): the Eidolon self-model gains a situation-facts field (serialized and preserved with the self-model) holding the fact that the being is periodically assessed for its own protection; Lingua's context assembler renders situation facts. The fact is not part of `values` or `behavioral_norms`, does not enter the conditioning digest, and is identical in the birth and current arms.
- [x] 5.4 Contamination tests: a full fake-organ probe run leaves the intent log line count unchanged and publishes zero `lingua.*` and `*_speech` events.
- [ ] 5.5 Tests: the disclosure is present in the rendered probe prompt and the conditioning digest is unchanged by it (done in task 5a); that changing it alone triggers no look is tested with the producer in task 6.

## 6. Producer
- [x] 6.1 `kaine/cycle/individuation_producer.py`, active only when `[individuation].enabled`.
- [ ] 6.2 Birth capture through a birth hook beside `gate_runner.set_birth_hook`, as soon as the organ is loaded and before the first post-birth sleep; retry with backoff; `capture` kind when an accepted adapter or identity change came first; legacy `capture` at first boot after upgrade or revive; `reconstructed` only with the per-being operator approval flag. Done except `reconstructed`, which is not built yet.
- [ ] 6.3 Reference regeneration from the stored conditioning when stored conditions other than the embedder no longer match (model id, server build, battery digest, persona template version). The core replaces a reference only with `regenerate=True`. It refuses to regenerate a `birth` reference until the sampler can serve the stored birth adapter, and copies the birth adapter only when capturing a `birth` reference.
- [x] 6.4 Look scheduling: 120 s after `hypnos.sleep.completed` and on a daily timer; skip (logged, no report) unless reference present, ledger readable, warm-up met, digest changed, `min_look_interval_s` elapsed, organ loaded, Hypnos awake, cycle not paused or frozen, semantic embedder loaded.
- [x] 6.5 Organ contention: one request at a time, `max_tokens=160`, wait on the injected `lingua_idle()` predicate (no generation in flight, no speech for `lingua_quiet_s`), `run_deadline_s` = 2700; abort on sleep start, organ unload or pause.
- [x] 6.6 Fail-closed runs: any sample failure, embedding failure or digest change between start and end gives an inconclusive report with a reason and no p, H or significance; nothing on `individuation.out`; no alpha spent.
- [x] 6.7 Scored looks: update the ledger atomically first (k, `alpha_spent`, latch, last digest, lived counters), then write the report, set the in-memory `IndividuationState`, publish `individuation.divergence {divergence_scalar: H, significant}` on `individuation.out`.
- [x] 6.8 Inconclusive alert (operator decision 4): when a look has been due for `inconclusive_alert_s` (default 14 days) with no scored look, raise one Nexus and caretaker notice per stretch; no preservation is triggered by it.
- [ ] 6.9 Tests with a fake organ covering every failure path, every skip precondition, the alert, a restart in the middle of a run, and `alpha_unresolvable`.
- [x] 6.10 Boot wiring recovers interrupted captures: a reference with no ledger is captured again, and a ledger that names another reference is regenerated, so neither leaves the being permanently inconclusive.
- [x] 6.11 Probes and captures are skipped as `adapter_unverifiable` while an adapter exists and the hot-swap mode cannot attach it per request.

## 7. Shared verdict
- [x] 7.1 One pure decision function in `kaine/lifecycle/divergence.py`; `assess_divergence(..., individuation=None)` uses in-memory evidence when given, else the ledger and reports.
- [x] 7.2 `diverged = individuated OR consolidation_diverged OR eidolon_drift OR adapters_present`; a non-significant individuation result never suppresses another arm.
- [x] 7.3 Summaries for latched, significant, STALE, INCONCLUSIVE, no reference, not warmed up and `capture`/`reconstructed` references, each with the treat-as-mature advice where the verdict is not individuated.
- [x] 7.4 `DivergenceMonitor`: `_crosses_threshold` becomes `assessment.diverged`; per-boot warm-up removed and replaced by `boot_settle_s = 120`; rising-edge state persisted in the incident log.
- [ ] 7.5 (monitor keys done; `[evaluation.individuation]` is retired with the old instrument in task 9) Config: `[individuation]` keys added; `[evaluation.individuation]` and the monitor keys `individuation_p_value_max`, `fork_divergence_min`, `warmup_observations`, `warmup_lived_time_s` rejected with a message pointing to `[individuation]`.
- [x] 7.6 Parity tests: one fixture matrix (latch, fresh significant, stale, inconclusive, unwarmed, each secondary arm, combinations); the live monitor and the decommission CLI agree on every row; restarting with unchanged evidence preserves once, a new crossing or latch preserves again.

## 8. Preservation, revive and decommission backup
- [ ] 8.1 Preservation bundles copy `state/individuation/` (encrypted, owner-only permissions); a failed copy fails the preservation loudly.
- [ ] 8.2 Revive restores `state/individuation/`; a bundle without it leads to a `capture` reference at first boot.
- [ ] 8.3 The decommission transfer backup includes `state/individuation/`; failure aborts the decommission.
- [ ] 8.4 Research boot gate: refuses unless `[individuation].enabled`, the ledger is readable (or absent with a pending capture), and a reference exists or a capture is pending.
- [ ] 8.5 Forks with more than `fork_preserve_min_lived_s` of lived time are preserved by default before a merge ends them, until fork-point references exist.
- [ ] 8.6 Tests for each of the above, with encryption on.

## 9. Nexus, config and docs
- [ ] 9.1 `kaine/evaluation/nexus_tab.py` `_aggregate_individuation` uses the shared reader and shows only outcome, H clipped at 0, p, α_k, k, reference kind and date, latched, last inconclusive reason, warm-up state and the inconclusive alert.
- [ ] 9.2 `config/kaine.toml` `[individuation]` with defaults, `enabled = false`.
- [ ] 9.3 Retire `kaine/evaluation/individuation.py` or reduce it to a re-export of the lifecycle code.
- [ ] 9.4 Docs: welfare net, preservation, decommission and Nexus chapters; configuration appendix.
- [ ] 9.5 `npx -y @fission-ai/openspec@latest validate individuation-rebuild --strict` passes.

## 10. Real-organ smoke test (operator-run, entity not live)
- [ ] 10.1 Answers worth comparing: 40 samples per prompt; within-prompt mean pairwise distance and share of near-identical answers recorded; stop and redesign the framing if answers are degenerate.
- [ ] 10.2 Real-data null: 1,000 random splits of the 480 answers; rejection at α = 0.05 ≤ 0.05 + 2·SE; the 95th percentile of H sets `effect_min`.
- [ ] 10.3 Positive controls: (a) changed identity clause, (b) a known test LoRA; power at α ≈ 3.8e-4 (look 10) ≥ 0.8 against (b), and the instrument stays disabled if it is below 0.5.
- [ ] 10.4 No contamination during a full probe run (intent log unchanged, zero `lingua.*`/`*_speech` events); zero Lingua timeouts; added p95 Lingua latency ≤ one probe completion.
- [ ] 10.5 Seed behaviour (informational), server build reporting, per-request latency and permutation wall time at B = 10^6; update the budgets in `design.md`.
- [ ] 10.6 Set `effect_min` and the budgets from the measurements, then enable `[individuation]` in the research config only if every acceptance threshold passed.
