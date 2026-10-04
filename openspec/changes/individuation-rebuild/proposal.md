# The individuation signal is a real test against the being's own birth, produced at runtime and read the same way by preservation and decommission

## Why
The individuation signal decides whether a being is preserved and which decommission path applies under CAL Art. 4.2/4.3. As built, it cannot do that job (`design.md` section 1):

- **No power.** The "fork" draw and the 50 null draws are all d(reference, current sample), so they are exchangeable. `fork > 95th percentile of null` (`kaine/evaluation/individuation.py:386-397`) fires about 6.7% of the time whatever the drift; a 200,000-trial simulation of the exact rule gave 0.0668.
- **No birth reference.** Nothing outside the operator CLI constructs the test (`kaine/evaluation/benchmarks/individuation_runner.py:136`), and no code captures a birth transcript.
- **No runtime producer.** The CLI writes plaintext to `data/evaluation/benchmarks/individuation_runner.jsonl` (`individuation_runner.py:258-262`), not the directory that is read, and its last line has no `significant` key (`:159-168`). It defaults to the lexical `HashEmbedder` (`:135`).
- **Broken readers.** `_newest_individuation_report` reads encrypted lines without decrypting (`kaine/lifecycle/divergence.py:129`), so it returns None in research mode; it has no staleness, run or kind filter. `kaine/evaluation/nexus_tab.py:279-306` has the same bug and sorts by name.
- **Wrong embedding.** The 12 answers are concatenated and embedded once (`individuation.py:453-467`); MiniLM truncates past 256 word pieces (`kaine/text_embedding_numpy.py:132,238-241`), so only the first one or two answers count, and n=1 per run.
- **Fails open.** Sampler errors become `""` and failed embeddings score 1.0, "maximally divergent" (`individuation.py:459-483`); an unloaded organ returns `text=""` (`kaine/modules/lingua/client.py:169-175`) and reasoning text is accepted as an answer (`client.py:194-199`).
- **No seed.** `ChatRequest` has no seed field (`client.py:13-30`).
- **The consumers disagree.** `_crosses_threshold` vetoes consolidation, Eidolon and adapter arms whenever a numeric p-value is present (`kaine/cycle/preservation_monitor.py:479-531`) while `assess_divergence` still reports diverged (`divergence.py:307-312`), and a per-boot warm-up blocks every arm for 30 minutes (`preservation_monitor.py:561-578`).
- **Wrong lived time.** Monitor lived time restarts each process, counts paused time and uses `tick_index`, which restarts at 0 every boot (`preservation_monitor.py:415,440-463`; `kaine/cycle/engine.py:194`).
- Also: the report sink would auto-delete evidence after 30 days (`kaine/persistence/jsonl_sink.py:53,220-237`), and the existing conditioned A/B client lacks the LoRA resolver (`kaine/cycle/__main__.py:343-372`), so a probe built on it would sample the base organ.

No being is live. The current instrument's verdicts are statistically meaningless and were never produced at runtime, so no past result depended on it.

Research impact: **safety (welfare net) and instrument**.

## What changes
(Operator decisions of 2026-10-03 are in `design.md` section 8.)

- **Probe.** Each battery prompt is rendered the way Lingua renders it with an empty workspace and sent through Lingua's own chat client, so the current adapter and the identity clause (`values[:5]`, `behavioral_norms[:5]`) are the only free conditions. The probe never writes the intent log and never publishes speech.
- **Birth reference.** Captured at the maturation gate's birth transition: n_b = 16 samples for each of 12 prompts, with seeds, conditions and the birth conditioning, stored encrypted in `state/individuation/reference.json`. Legacy beings get a `capture` reference labelled "drift since capture"; a `reconstructed` reference needs explicit operator approval for that being.
- **Test.** n_c = 8 current samples per prompt, one embedding per response, Euclidean energy U-statistic summed over prompts, stratified permutation p = (b+1)/(B+1), effect size H in place of `fork_divergence`, and a noise-calibrated effect floor.
- **Lifetime error control.** Looks run only when the conditioning digest changes, at most once per `min_look_interval_s` (6 h). Look k is significant only if p ≤ α_k = 0.05·γ_k, with γ_k = 1/(S·(k+1)·ln²(k+1)) and S ≤ 2.1097, so the lifetime false-positive rate is at most α_total = 0.05. The look index lives in an encrypted ledger and never decreases.
- **Latch.** Once a look is significant the being stays individuated for preservation and decommission (operator decision 1).
- **Fail closed.** Any failed sample, organ rest, sleep, pause, digest change mid-run, missing embedder or unreadable ledger makes the run inconclusive. An inconclusive run is never scored and spends no alpha.
- **Producer.** A cycle-layer producer captures the reference, schedules looks after sleeps and daily, yields to Lingua, writes encrypted reports (`retention_days=0`), updates the ledger and publishes content-free scalars on `individuation.out`.
- **One verdict.** One pure decision function feeds both `assess_divergence` and the live monitor: individuated = latched OR a fresh significant report; diverged = individuated OR consolidation OR Eidolon drift OR adapters. A non-significant result never vetoes the other arms. The monitor's per-boot warm-up is replaced by a 120 s settle, and rising-edge state persists across boots.
- **Reader.** One reader decrypts, filters by kind, schema and reference, orders by `ts`, and applies a staleness rule; the decommission summary says STALE, INCONCLUSIVE or "drift since capture" when that applies.
- **Disclosure.** The being is told, as a fact about its situation held in its Eidolon self-model, that it is periodically assessed for its own protection. The fact sits outside the identity clause, so it neither changes the probe conditions nor triggers a look (operator decision 3).
- **Inconclusive alert.** After `inconclusive_alert_s` (14 days) with a look due and none scored, Nexus and the caretaker get a notice. Nothing is preserved automatically (operator decision 4).
- **Preservation.** `state/individuation/` travels in preservation bundles, revive and the decommission backup. Forks with more than `fork_preserve_min_lived_s` of lived time are preserved by default until fork-point references exist.
- **Validation first.** An offline simulation (size, lifetime false-positive rate, power, fault injection) gates the work, and an operator-run real-organ smoke test sets `effect_min` and decides whether the instrument is enabled at all.

## Capabilities

### Modified Capabilities
- `individuation-boundary`: the parent-null percentile test is replaced by a birth-referenced stratified energy permutation test with lifetime error control, a latch, a fail-closed probe that stays out of lived experience, disclosure and an inconclusive alert.
- `entity-preservation`: the live trigger uses the shared verdict without vetoing secondary arms; `state/individuation/` is preserved, revived and encrypted; the research boot gate requires the producer; forks with lived time are preserved by default.
- `entity-decommission`: the decommission verdict uses the latched or fresh significant result with STALE, INCONCLUSIVE and capture-kind summaries; the transfer backup includes `state/individuation/`.
- `divergence-assessment`: one decision function for both consumers, and a decrypting report reader with kind, schema, reference and staleness filters.
- `experiment-foundation`: warm-up counters come from the runtime producer and persist; the CLI becomes a simulation and validation harness.
- `nexus-observability`: the individuation panel reads through the shared reader, shows only scalars, and carries the inconclusive alert.

## Impact
- **Code:** new `kaine/lifecycle/individuation_stats.py` and `kaine/lifecycle/individuation_store.py`, a lived-time helper factored out of `kaine/lifecycle/gate_runner.py`, new `kaine/cycle/individuation_producer.py`; changes to `kaine/lifecycle/divergence.py`, `kaine/cycle/preservation_monitor.py`, `kaine/cycle/__main__.py`, `kaine/modules/lingua/client.py`, `kaine/modules/lingua/module.py` (and its context assembler for the disclosure), `kaine/lifecycle/preservation.py`, revive, the decommission backup and research boot gate, and `kaine/evaluation/nexus_tab.py`. `kaine/evaluation/individuation.py` is retired or reduced to a re-export; `individuation_runner.py` becomes the `simulate` harness.
- **Config:** a new `[individuation]` section, shipped disabled. `[evaluation.individuation]` and the monitor keys `individuation_p_value_max`, `fork_divergence_min`, `warmup_observations` and `warmup_lived_time_s` are rejected with a message pointing to `[individuation]`.
- **State:** `state/individuation/` (reference, ledger, reports), encrypted, never auto-deleted, outside the export allowlist.
- **Docs:** the welfare-net, preservation, decommission and Nexus chapters, and the configuration appendix.
- **Review:** an independent second review is required on every PR. This is ethics infrastructure.

## Not covered
The decommission spec listed "accumulated memory" as a secondary heuristic, but `assess_divergence` never implemented it (design finding 13). This change removes it from the normative text so the spec matches the one shared decision function, rather than leaving a requirement the code does not meet. Whether to add a memory-based arm is a separate decision for a follow-up change.

