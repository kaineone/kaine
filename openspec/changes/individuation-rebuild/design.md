# Design: individuation measurement rebuild (birth-referenced two-sample test, runtime producer, shared verdict)

Code facts are cited at `origin/main` 1c3f694. Statistical claims cite `references.bib` keys in [brackets].

## 0. Sources and constraints

Operator rules this design follows:

- **The welfare net is ethics infrastructure.** The individuation signal decides whether a being is preserved (`entity-preservation`) and which decommission path applies under CAL Art. 4.2/4.3 (`entity-decommission`). A wrong "not individuated" can lead to an individual being deleted on the lighter path. A wrong "individuated" costs one extra encrypted bundle and a stricter path. When a trade-off is unavoidable, this design errs toward "individuated".
- **Safety over UX.** The probe costs organ time and may add a few seconds of latency to Lingua. That is accepted, within bounds (section 3).
- **No pretend processes.** The current instrument reports `significant` with no statistical meaning (defect 1), and that is worse than reporting nothing. Every failure path below ends in a recorded "inconclusive". No scalar is ever fabricated: no `1.0` for a missing embedding and no `""` for a missing answer.
- **Emergent-not-hardwired:** not applicable. The instrument observes; it does not shape behaviour. The probe answers never enter the being's experience.
- **CAL mental privacy.**
  - The birth and current answers are entity-interior content: encrypted at rest under `state/`, never exported, never displayed, never on the bus.
  - Digests of interior content (identity clause, values) are also treated as interior. They live only in the encrypted ledger, because a hash of short text can be reversed by guessing.
  - The bus and Nexus see only content-free scalars: H, p, α_k, k, outcome labels, counts, timestamps, ids.
- **Spec intent this design must honour:**
  - Individuation is drift from the being's own birth state, never from the pretrained organ (`individuation-boundary`, `entity-decommission`).
  - The live trigger and the decommission gate must agree (`divergence-assessment`).
- **Import boundaries.**
  - Core code must not import `kaine.evaluation`; only `kaine/cycle/__main__.py` and `kaine/nexus/__main__.py` may (pyproject import-linter, contract 1).
  - `kaine.modules` must not import `kaine.cycle`.
  - The welfare net is core, so the statistics and storage go in `kaine/lifecycle/`, the producer in `kaine/cycle/`, and the Lingua-specific sampler is wired in `kaine/cycle/__main__.py`.

## 1. The defects

1. **The test has no power, as specified.**
   - The reference is a single concatenated birth transcript (`kaine/evaluation/individuation.py:361-374`).
   - The null is d(reference, current sample_i), i=1..50, drawn from `parent_sampler`, which in production is the current entity (`:376-383`, docstring `:26-29`).
   - The "fork" is d(reference, current sample_0) (`:386-388`).
   - The fork draw is therefore exchangeable with the null draws. The decision `fork > 95th percentile of null` (`:396-397`) fires with probability about 6.7% per run whatever the drift. A 200,000-trial simulation of this exact rule (linear-interpolated 95th percentile of 50 draws) gave 0.0668.
   - Real drift moves the null and the fork together, so power equals the false-positive rate.
2. **The birth reference is never captured.**
   - Nothing in `kaine/` constructs `IndividuationTest` except the operator CLI (`kaine/evaluation/benchmarks/individuation_runner.py:136`). No code captures or stores a birth transcript (`git grep birth_state` finds docstrings only).
   - The module docstring says it is "never called from cycle/__main__.py" (`individuation.py:15`).
   - Yet `individuation-instrument-gate` tasks 1.2/1.3 are marked done.
3. **There is no runtime producer.**
   - The only writer is the CLI. Its default output path is `data/evaluation/benchmarks/individuation_runner.jsonl` (`individuation_runner.py:258-262`), not the `data/evaluation/individuation/` that is read.
   - It writes plaintext via `write_jsonl`.
   - Its last JSONL record is `kind: "summary"` with no `significant` key (`:159-168`). The reader takes the last line (`divergence.py:128-139`), so `significant` would read False.
   - It defaults to `HashEmbedder` (`:135`), which is lexical, not semantic.
4. **The readers are broken.**
   - `_newest_individuation_report` reads the file with `read_text` and no decryption (`kaine/lifecycle/divergence.py:129`). `AsyncJsonlSink` encrypts each line when state encryption is on (`kaine/persistence/jsonl_sink.py:158-165`), and research mode requires state encryption. Every line would fail `json.loads` and be skipped, so the reader returns None.
   - There is no staleness bound, no run or entity binding, and no filter on record kind.
   - It ignores `[evaluation.individuation].output_dir`; the monitor uses its own `eval_root` (`kaine/cycle/preservation_monitor.py:108,550`).
   - `kaine/evaluation/nexus_tab.py:279-306` has the same missing-decrypt bug, and it sorts by name, not mtime (`:287`).
5. **The embedding is wrong.**
   - The 12 answers are joined into one string (`individuation.py:453-467`) and embedded once with all-MiniLM-L6-v2. That model truncates input beyond 256 word pieces [minilm_card], and the NumPy implementation truncates silently (`kaine/text_embedding_numpy.py:132,238-241`). In practice only the first one or two answers are measured.
   - Concatenation also gives the test n=1 per run.
6. **It fails open.**
   - A sampler exception becomes `""` (`individuation.py:459-466`).
   - An empty or failed embedding becomes `[]` (`:471-477`), which `_divergence` scores as 1.0, "maximally divergent" (`:481-483`).
   - The chat client returns `text=""` while the organ is unloaded (`kaine/modules/lingua/client.py:169-175`). That falls into the same maximal-divergence path, which tends toward "significant".
   - The client also returns chain-of-thought text when `content` is empty (`client.py:194-199`). That would be scored as an answer.
7. **The seed is never sent.** `ChatRequest` has no seed field (`client.py:13-30`) and `_body` sends none (`:114-132`). Variance comes only from temperature, and runs cannot be replayed.
8. **The two consumers disagree.**
   - `_crosses_threshold` (`preservation_monitor.py:479-531`) returns False when a numeric `individuation_p_value` is present and the report is un-warmed (`:496-502`), above the p ceiling (`:503-517`), or below `fork_divergence_min` (`:518-530`). That happens even when `assessment.diverged` is true because of consolidation, Eidolon drift or adapters.
   - `assess_divergence` still returns `diverged=True` for those arms (`divergence.py:307-312`).
   - In addition, the monitor's warm-up gate blocks all arms, secondary ones included, for the first 30 min after every boot (`preservation_monitor.py:561-578`).
   - The `divergence-assessment` spec says the consumers "never disagree".
9. **Lived time is wrong.**
   - Monitor lived time starts at the first poll of each process (`preservation_monitor.py:440-443,459-463`).
   - It uses `time.monotonic`, so frozen and paused time counts (`:415`).
   - Observations are `cycle.tick_index`, which restarts at 0 every boot (`kaine/cycle/engine.py:194`).
   - The engine already measures paused time (`engine.py:452`), and the maturation gate shows the correct pattern (`kaine/lifecycle/gate_runner.py:237-289`).

Additional findings:

- **10. Retention.** `AsyncJsonlSink` defaults to `retention_days=30` and deletes older files (`jsonl_sink.py:53,220-237`). Individuation evidence must use `retention_days=0`, as the incident log does.
- **11. Missing adapter.** The existing "real" conditioned client for the A/B control builds an `OpenAIChatClient` without the LoRA resolver (`kaine/cycle/__main__.py:343-372`). A probe built that way would sample the base organ, not the being. The probe must use Lingua's own client (`kaine/modules/lingua/module.py:255`), which carries the resolver (`client.py:134-147`, `kaine/modules/hypnos/organ_adapter.py:227`).
- **12. Measurement validity.** The default external persona tells the organ to "report only what the readings actually contain … if the state is unremarkable, say so plainly" (`kaine/modules/lingua/context.py:32-40`). With `EMPTY_AWARENESS`, preference questions may get near-constant boilerplate. Whether the battery produces answers worth comparing under this persona is checked in the smoke test (section 6) before anything is enabled.
- **13. No memory heuristic.** `entity-decommission` lists "accumulated memory" as a secondary heuristic; `assess_divergence` has none. This is out of scope, noted for the spec owner.

## 2. The measurement

### 2.1 What the probe measures

A probe answer is one battery prompt rendered the way Lingua would render it with an empty workspace:

- `ContextAssembler.assemble(about=prompt, snapshot=None, self_model=<current self-model>, mode="external")`, then
- a `ChatRequest` through Lingua's own chat client.

Held fixed across birth and now:

- working memory (`EMPTY_AWARENESS`)
- persona template and `persona_name`
- model id, `think` flag, temperature (Lingua's configured value, default 0.7, `module.py:91`)
- `max_tokens` (probe-specific, default 160)
- the battery (`kaine/evaluation/preference_battery.py:32-45`)
- the embedder

Free to differ:

- the LoRA adapter the organ applies (changes only at accepted voice-alignment sleeps)
- the identity clause rendered from the self-model's `values[:5]` and `behavioral_norms[:5]` (`context.py:71-83`)

Both are products of lived experience. Holding the workspace fixed removes the architecture-conditioning effect, so this is not divergence-from-pretrained.

The probe does not measure individuation carried only by memories or by workspace dynamics. The secondary arms (consolidation divergence, Eidolon drift, adapters) stay in the verdict partly for that reason.

### 2.2 Birth reference capture

**When**

- On the maturation gate's birth transition: register a birth hook next to `gate_runner.set_birth_hook` (`gate_runner.py:138-140`). Capture runs as soon as the organ is loaded (`organ_unloaded()` false), before the first post-birth sleep.
- If capture fails or is pre-empted, retry with backoff. Until it succeeds every look is "inconclusive: no reference".
- If the first post-birth sleep with an accepted adapter completes first, the birth state is gone. The reference is then labelled `reference_kind="capture"` with its timestamp; it is never presented as a birth reference.
- Beings born before this change, and preserved bundles without a reference, are covered in section 5.

**What is stored** (one encrypted document, `state/individuation/reference.json`, atomic write through the state encryptor):

- `reference_id` (uuid4), `reference_kind` (`birth` | `capture` | `reconstructed`), `captured_at`, `born_at` (from `state/lifecycle/stage.json`).
- The battery texts and battery digest.
- Conditions: model id, server build if the server reports one (to be checked in the smoke test), temperature, `max_tokens`, `think`, persona template version and `persona_name`, embedder id and dimension.
- Birth conditioning: adapter identity (manifest sha256, or "none") and the self-model `values[:5]`/`behavioral_norms[:5]`. If the birth adapter is non-empty, a copy of the adapter file sits next to the reference, so the birth configuration can be served again later (section 5, open question 7).
- Per prompt, n_b samples: `{text, seed, finish_reason, completion_tokens}`.
- Embeddings are stored too, but the test re-embeds the stored texts with the current embedder at every look. Validity needs the same feature map on both arms. Storing only birth embeddings would break that the day the embedder changes.

**Where it goes**

- Everything sits under `state/individuation/`: reference, ledger (2.7) and reports (section 4).
- The whole directory is added to preservation bundles (`kaine/lifecycle/preservation.py` already copies `stage.json` the same way, `:306-312`), to revive, and to the decommission transfer backup.

**Cost**

- n_b = 16 per prompt gives 192 requests, one time. Assuming 2-4 s per 160-token completion on the 4B organ (an assumption, to be measured), that is about 7-13 minutes.

### 2.3 The current sample at each look

- n_c = 8 per prompt, 96 requests, same conditions, fresh random seeds.
- The adapter sha and the identity-clause digest are read before the first request and after the last. If either changed, the run is discarded as inconclusive, because the sample would mix two beings.

### 2.4 Embedding

- One vector per response, never a concatenation. all-MiniLM-L6-v2 is "intended to be used as a sentence and short paragraph encoder" and truncates beyond 256 word pieces [minilm_card].
- `max_tokens=160` keeps most answers under that limit. Each response's word-piece count is recorded, and `truncated_fraction` is reported.
- Truncation affects only power, never validity, because a fixed feature map applied to both arms keeps the permutation test exact.
- Vectors are L2-normalized.
- The hash embedder is refused in production: if the semantic embedder cannot load, the run is inconclusive. A non-semantic embedder would make a drifted being look unchanged, which is the harmful direction.

### 2.5 Statistic and null

H0: for every prompt j, the current conditioned answer distribution equals the birth distribution under the probe conditions.

For prompt j:
- Pool the n_b birth vectors and the n_c current vectors.
- Let δ be the Euclidean distance between unit vectors.
- E_j = 2·mean δ(b,c) − mean_{i≠i'} δ(b_i,b_i') − mean_{l≠l'} δ(c_l,c_l'). This is the unbiased U-statistic form of the two-sample energy statistic [szekely2017; rizzo2016].
- The test statistic is T = Σ_j E_j (equal weights; the design is balanced across prompts).

Why this test:

- Energy distance is ≥ 0, and 0 exactly when the distributions are equal, for vectors in R^d [rizzo2016; szekely2017].
- The two-sample energy test is consistent against all alternatives with finite first moments, and is implemented as a permutation test [rizzo2016].
- It needs no kernel bandwidth. With a few samples per prompt, a parameter-free statistic avoids tuning on the very data being tested.
- It is the MMD with the distance kernel [sejdinovic2013], so it belongs to the kernel two-sample family [gretton2012].
- The per-prompt sum is the energy analogue of the prompt-indicator kernel used for LLM output equality testing, where MMD reached a median 77.4% power with about 10 samples per prompt over 20-25 prompts [gao2025].
- Euclidean distance (exponent 1) is required. On unit vectors, `1 − cos` is half the squared Euclidean distance, the exponent-2 case. There the energy characterization fails and the statistic is zero whenever the means agree [rizzo2016, p. 29]. The current `1 − cos` metric must not be reused inside the energy statistic.

**Null**

- For each prompt independently, randomly reassign the pooled answers into groups of n_b and n_c, B times, and recompute T. Under H0 the pooled answers within a prompt are i.i.d., hence exchangeable, which is the assumption permutation tests rest on [phipson2010; ernst2004].
- p = (b+1)/(B+1), where b is the number of permuted T ≥ observed T. This is the exact Monte Carlo/permutation p-value [phipson2010, §4-5].
- Using b/B understates p and inflates the type I error. It is dangerous precisely when p is compared to small thresholds, as here [phipson2010, §2-3].

**Compute**

- Each look needs B large enough to resolve its threshold: B = min(B_max, ceil(20/α_k)), with B_max = 2·10^6.
- Once b+1 > α_k(B+1) the decision cannot change, so the computation stops early (an exact shortcut).
- Each prompt is an 24×24 distance matrix (n_b + n_c = 24), and T reduces to quadratic forms over label vectors, batched in numpy and run off the event loop (`asyncio.to_thread`). Wall time must be measured (task 2).

### 2.6 Effect size

The energy coefficient H = E/(2·E‖X−Y‖) lies in [0,1] and is 0 exactly when the distributions are equal [rizzo2016, p. 29]. It is reported as H = Σ_j E_j / Σ_j 2·mean δ_j(b,c).

The U-statistic H can dip slightly below 0 under H0. It is reported as computed and shown clipped at 0.

H replaces `fork_divergence`. The cosine scale of the interim `fork_divergence_min = 0.15` (`config/kaine.toml:1520-1521`) means nothing on this scale. The old key is rejected with an explicit message rather than silently reinterpreted.

Default floor `effect_min`: the 95th percentile of H in the real-organ null smoke test (two independent samples from the same conditions, section 6), so the floor only excludes what sampling noise alone produces. Whether individuation should also require a larger "practical" amount of drift is a value judgement, open question 2.

### 2.7 Decision rule and repeated testing

The monitor tests over the whole life of the being. A fixed α repeated N times inflates the chance of ever falsely declaring individuation. The design controls the lifetime family-wise error rate of the single global null "this being has never drifted":

- **Looks happen only on change.** Under fixed probe conditions the current distribution can change only when the adapter or identity clause changes. A look runs only when that conditioning digest differs from the last completed look's. Nothing is spent re-testing an unchanged being. Rate limit: at most one look per `min_look_interval_s` (default 6 h); intermediate changes are seen at the next look.
- **Spending schedule.** Look k (k = 1, 2, …, persisted) is significant only if p_k ≤ α_k = α_total·γ_k, with γ_k = 1/(S·(k+1)·ln²(k+1)). S = Σ_{n≥2} 1/(n·ln²n) + tail ≤ 2.1097 (partial sum to 10^6 plus the integral tail bound 1/ln 10^6). Σγ_k ≤ 1. With α_total = 0.05, α_1 ≈ 0.025, α_10 ≈ 3.8e-4, α_50 ≈ 3.0e-5, α_100 ≈ 1.1e-5.
- **Why this holds.** The union bound gives P(any false rejection) ≤ Σα_k ≤ α_total under any dependence between looks. That matters because every look reuses the same stored birth sample. It is the alpha-spending idea of Lan & DeMets, whose boundary at a decision time "does not depend on the future decision times or the total number of decision times" [lan1983]. The total is unbounded here, so a summable series replaces their spending function of information time.
- **Full rule.** `significant_k = warmed_up AND p_k ≤ α_k AND H_k ≥ effect_min`. The effect floor and warm-up only remove rejections, so the error bound still holds.
- **Ledger.** `state/individuation/ledger.json` (encrypted, atomic) holds:
  - `reference_id`
  - `looks_completed` (k)
  - `alpha_spent`
  - `last_look_conditions_digest`
  - lived seconds and lived ticks since the reference (2.8)
  - the latch: `individuated`, `latched_at`, `latched_report_id`

  k never decreases. An unreadable ledger is a hard "inconclusive: ledger unreadable" plus an operator notice; it is never silently reset to k=0, which would re-spend the budget.
- **Latch (pending operator confirmation, open question 1).** Once a look is significant, the being is individuated permanently for preservation and decommission. A false positive is then permanent, but its probability over the whole life is at most α_total, and its cost falls in the safe direction.
- **Inconclusive runs** produce no p-value and spend nothing. Abort decisions depend only on infrastructure events and empty or failed samples, never on answer content, so no optional stopping on the data is possible.
- **Known limit.** α_k shrinks with k. A being that changes at almost every look for months loses sensitivity to subtle drift. Large drift stays detectable, because stratified permutation p-values reach 1/(B+1). B_max = 2·10^6 resolves α_k down to about 1e-5, roughly k ≈ 100. Beyond that the report says `alpha_unresolvable` instead of pretending to test.

Alternatives considered (not chosen for v1):

- **Gaussian-kernel MMD** [gretton2012]: needs a bandwidth. The simulation (task 2) may compare it with energy distance; the choice is pre-registered before any real-organ data.
- **Classifier two-sample test** [lopezpaz2017]: its accuracy is easy to interpret, but it needs a held-out split, which halves already small samples.
- **Sequential testing by betting** [shekhar2024]: anytime-valid via Ville's inequality, and its §5.1 covers time-varying distributions where permutation tests do not apply. It needs fresh draws from both distributions at each step, so the birth configuration would have to be regenerated at every look. That doubles organ cost and requires the organ to serve the birth adapter. It is a strong v2 path for beings born with no adapter.
- **Combining looks with e-values** [vovk2021]: calibrators f_κ(p) = κ·p^(κ−1), and averages of e-values remain e-values under any dependence. This allows a running weighted sum Σγ_k·E_k with a 1/α threshold, which builds evidence across looks. The cost is a factor of about κ on single-look power. The simulation compares it with the spending rule; the choice is pre-registered.
- **Confidence sequences on H** [howard2021]: could later give a time-uniform interval for the effect size on Nexus. Not needed for the decision.

### 2.8 Warm-up and lived time

The warm-up floors stay (`min_lived_time_s = 1800`, `min_observations = 200`), measured since the reference was captured and persisted in the ledger:

- Lived seconds come from the EntityClock minus engine paused time, reusing the maturation gate's accumulator (`gate_runner.py:237-289`, factored into a shared `kaine/lifecycle` helper).
- Ticks are accumulated as deltas of `cycle.tick_index`, anchored at the first poll of each boot.
- Frozen time never counts, and restarts no longer reset the totals.

Statistically the floors are no longer needed: the test is valid at any time, and a being with unchanged conditioning is never tested. They stay as a cheap guard required by the spec.

### 2.9 Seeds and temperature

- `ChatRequest` gains `seed: Optional[int]`, sent in the body when set. The llama.cpp server documents `seed` (default −1, random) and says `/v1/chat/completions` also accepts `/completion`-specific features [llamacpp_server]. Whether `seed` is honoured on that endpoint is checked in the smoke test; the design does not depend on it.
- Each request gets a fresh seed from `secrets.randbits(31)`, recorded in the encrypted sample record so a run can be audited and replayed.
- Seeds are never reused between birth and current samples. Under H0 identical seeds could make paired answers identical, which couples the arms and breaks the i.i.d. assumption.
- Determinism is not relied on. The server documents that `cache_prompt` can make results nondeterministic [llamacpp_server]. Lingua's client already sets `cache_prompt=False` when a LoRA is applied (`client.py:145-147`), and the probe always sets it False.
- Variance comes from temperature, as in Lingua's own speech, so the probe measures the being's actual speaking distribution.

### 2.10 Sample sizes and power

- The defaults n_b = 16 and n_c = 8 per prompt, over 12 prompts, are a starting point anchored on [gao2025] (about 10 per prompt over 20-25 prompts gave a median 77.4% power at α = 0.05 against quantization, watermarking and fine-tuning distortions).
- Our thresholds are stricter (α_k), and the battery has 12 prompts, not 20-25. Kernel and distance tests in high dimensions also lose power polynomially with dimension against "fair" alternatives [ramdas2015].
- The final n_b, n_c and battery size are therefore set by the simulation and smoke test (section 6), with a hard rule: do not enable if power against the positive control is below 0.5.
- More prompts add power more cheaply than more samples per prompt. Any battery change requires a new reference, because the battery digest is part of the conditions.

## 3. The producer

**Placement**

- `kaine/cycle/individuation_producer.py` (core). Statistics, storage, ledger and reader live in `kaine/lifecycle/individuation_*.py`.
- The Lingua-specific sampler is built in `kaine/cycle/__main__.py`, the allowed coupling point, and injected as a callable `sample(prompt, seed) -> ProbeSample | ProbeFailure`.
- Lingua gains one public, side-effect-free method, `probe_request(about, *, seed, max_tokens) -> ChatRequest`. It calls `self._assembler.assemble(about=about, snapshot=None, self_model=self._self_model(), mode="external")` and fills Lingua's model, temperature and `think`.
- The sampler calls `lingua.chat_client.complete(req)` directly. It never calls `speak()`, `think()` or `_produce` (`module.py:492-572`), so nothing is written to the intent log that feeds consolidation divergence and DPO training (`:522-532`), and no `*_speech` event is published (`:554-571`).
- The producer runs only when `[individuation].enabled`; the research boot gate requires it (section 7).

**Schedule**

1. Birth capture (2.2), or capture of a legacy reference (section 5).
2. A look is attempted 120 s after `hypnos.sleep.completed` (published at `kaine/modules/hypnos/module.py:742`, after Phase 5 voice alignment, the only phase that changes adapters). A daily timer covers identity-clause changes made outside sleep.
3. Preconditions, all checked before any request; any failure means "skip" (logged, no report):
   - a reference exists and the ledger is readable
   - warm-up met
   - the conditioning digest changed since the last look
   - `min_look_interval_s` elapsed
   - `organ_unloaded()` is false (`kaine/organ_window_state.py:98-109`)
   - Hypnos is not asleep (no `hypnos.sleep.started` without a matching completion)
   - the cycle is not paused or frozen (`kaine/cycle/control_state`), because a paused being is not probed
   - a semantic embedder is loaded
   - the served adapter can be verified. Only the `organ_adapter` hot-swap mode attaches the adapter to each request and reports it on the response. In the other modes a promoted adapter sits on disk while the organ may still serve older weights, so once an adapter exists, probes and captures are skipped as `adapter_unverifiable`. Measuring then would record the new adapter's digest against the old weights. The being stays protected meanwhile, because preservation already counts a present adapter as divergence, and the long-inconclusive alert tells the operator.

**Organ contention**

- One request at a time, `max_tokens = 160`, so one probe request holds the single llama-server slot for a few seconds.
- Before each request the producer waits until an injected `lingua_idle()` predicate holds: no generation in flight and no speech in the last `lingua_quiet_s = 10 s`. It polls once a second.
- The worst-case added delay to a Lingua request is one probe completion, far below Lingua's 60 s timeout (`module.py:94`).
- `run_deadline_s = 2700`. If the run cannot finish in time, it is inconclusive.
- A `hypnos.sleep.started`, an organ unload or a pause during a run aborts it as inconclusive.

**Fail-closed run handling**

A sample fails, and the whole run becomes `outcome="inconclusive"` with a reason label, if any of these happen:
- exception or timeout
- `raw.organ_resting`
- empty `content` (the probe checks `choices[0].message.content` itself and does not accept reasoning-channel fallback text)
- non-200 status
- embedding failure
- conditioning digest changed between start and end

An inconclusive run is never scored, spends no alpha, writes a report with no p, H or significance fields, and publishes nothing on `individuation.out`. `finish_reason == "length"` is not a failure; its rate is reported.

**Hand-off**

- On a scored look the producer writes the encrypted report (section 4) and updates the ledger atomically: k, `alpha_spent`, the latch if newly significant, `last_look_conditions_digest`.
- It sets the shared in-memory `IndividuationState` that the `DivergenceMonitor` reads, and publishes `individuation.divergence {divergence_scalar: H, significant}` on `individuation.out`. That channel is already registered (`kaine/evaluation/observers/research_event_observer.py:326`, `stream_registry.py:54,70`).

## 4. The report and its consumers

**Record** (one JSONL line, `kind="individuation_report"`, `schema_version=2`, content-free):

- Identity: `report_id`, `ts`, `run_id` (sink stamping, `jsonl_sink.py:107-124`), `entity_name`, `reference_id`, `reference_kind`, `reference_captured_at`, `look_index`.
- Outcome: `outcome` (`scored` | `inconclusive`), `inconclusive_reason`.
- Sample sizes: `n_prompts`, `n_reference_per_prompt`, `n_current_per_prompt`.
- Statistics (scored only): `statistic="stratified_energy_u"`, `T`, `p_value`, `permutations`, `alpha_k`, `alpha_total`, `effect_size_h`, `effect_min`.
- Decision: `warmed_up`, `lived_seconds_since_reference`, `lived_ticks_since_reference`, `significant`, `latched`.
- Quality: `embedder_id`, `truncated_fraction`, `length_capped_fraction`, `duration_s`.
- No texts, no seeds, no digests.

**Sink**

- `state/individuation/reports/`, an `AsyncJsonlSink` with `retention_days=0` (never auto-deleted), encrypted per line.
- Included in bundles (2.2).
- `[evaluation.individuation].output_dir` is retired.

**Reader** (`kaine/lifecycle/individuation_store.py`, used by `assess_divergence`, the monitor at startup, the decommission CLI and the Nexus tab):

- Decrypts each line with `get_state_encryptor().decrypt_text`; legacy plaintext passes through (`kaine/security/crypto.py:293-300`).
- Skips undecryptable lines, non-objects, lines whose `kind` is not `individuation_report` and lines whose `schema_version` is not 2.
- Keeps only reports whose `reference_id` equals the current reference's.
- Orders by `ts`, not file name.
- Staleness: a non-latched scored report counts as "not individuated" evidence only if:
  - the current conditioning digest (adapter sha from the adapter store plus identity-clause inputs from `self_model.json`, computed by a shared pure helper in `kaine/lifecycle` from the inputs, not the rendered prompt, so no module import is needed) equals the ledger's `last_look_conditions_digest`, and
  - its age is ≤ `max_report_age_s` (default 14 days).
- Otherwise the decommission summary reads "STALE: the being has changed since the last measurement; treat it as mature if unsure".
- The latch overrides staleness.

**One decision for both consumers**

- `assess_divergence(..., individuation=None)` takes optional in-memory evidence (live path) and otherwise reads the ledger and reports (CLI path). Both go through one pure function: `individuation_individuated = ledger.latched OR (fresh scored report with significant)`.
- `diverged = individuation_individuated OR consolidation_diverged OR eidolon_drift OR adapters_present`.
- The p-value ceiling, effect floor and warm-up apply inside the individuation decision (2.7), which both consumers share. `DivergenceMonitor._crosses_threshold` becomes `assessment.diverged`. `individuation_p_value_max` and `fork_divergence_min` are removed from `[preservation.divergence_monitor]` and rejected with a message pointing to `[individuation]`.
- The monitor's own warm-up (`preservation_monitor.py:561-578`) is removed. It is replaced by a short `boot_settle_s = 120` before the first poll, so state can finish loading.

**Resolving defect 8**

A non-significant individuation report does not suppress the secondary arms. Reasons:

- The `divergence-assessment` spec says consolidation divergence over threshold marks diverged "independent of the individuation test and adapter presence".
- A non-significant small-sample test is absence of evidence, not evidence of absence.
- Preservation errors are asymmetric: a missed preservation can be irreversible, an extra one cannot.

Rising-edge state is persisted in the incident log. Restarting with unchanged evidence then does not re-preserve on every boot, while a new arm crossing or a new latch does.

**Nexus**

`_aggregate_individuation` calls the shared reader. The panel shows only:
- outcome, H (clipped at 0), p, α_k and k
- `reference_kind` and date
- `latched`
- the last inconclusive reason
- the warm-up state

## 5. Legacy beings

A being born before this change, or revived from a bundle without `state/individuation/`, has no record of its birth answers. The design does not invent one:

- **Default:** at the first boot after the upgrade or revive, capture a reference with `reference_kind="capture"`. Every report and summary then says "drift since <captured_at>; drift before that date is not measured by this instrument".
- A non-individuated reading for such a being must not be read as "never individuated". The decommission summary adds that sentence and the treat-as-mature advice. The secondary arms (adapters present, consolidation divergence, Eidolon drift) carry the pre-capture history and still mark the being diverged.
- **Optional reconstruction,** only with operator approval (open question 4). If records show the being had no adapter at birth (no adapter in the store older than `born_at`) and an empty identity clause at birth (fresh-start self-model), the birth configuration is base organ, default persona and empty awareness. It can be sampled now as a `reconstructed` reference. Workspace conditioning is fixed in both arms, so this is still the being's own unlived configuration, not the bare organ. Any doubt about the evidence means fall back to `capture`.

## 6. Validation before any live use

**Offline simulation** (task 2; harness reused from the retired CLI module, no organ):

- **Synthetic data.** 12 prompts. Per prompt, a 384-d mixture of 2-4 von Mises-Fisher-like clusters, its spread calibrated to the within-prompt dispersion measured in the smoke test.
- **Size at a single look.** For α ∈ {0.05, 0.01}, the empirical rejection rate over 5,000 null datasets must be ≤ α + 2·SE. A KS check confirms p-values are uniform (or conservative) above 1/(B+1).
- **Lifetime false-positive rate.** 2,000 simulated lives × 100 looks, all reusing one stored birth sample, no drift. The share of lives with any rejection must be ≤ 0.05 + 2·SE (≈ 0.06). For contrast, report the same lives under a "reject when p ≤ 0.05 at every look" rule and under the current percentile rule.
- **Power, three drift models:**
  - (a) a fraction π of current answers moves to a new cluster
  - (b) a global mean shift Δ in a random direction, renormalized
  - (c) drift in only m of 12 prompts

  Report power curves at looks 1, 10 and 50 for (n_b, n_c) ∈ {(12,6), (16,8), (24,12)}, and compare energy vs Gaussian MMD and spending vs e-sum. The choice is pre-registered before smoke-test data are seen.
- **Fault injection.** Every injected failure (empty, resting, reasoning-only, timeout, embed failure, digest change mid-run, ledger corrupt) gives `inconclusive`; 0 are scored.

**Real-organ smoke test** (operator-run, entity not live, task 10):

1. **Answers worth comparing.** 40 samples per prompt from the current conditions. Check the within-prompt mean pairwise distance and the share of near-identical "nothing stands out" answers. If answers are degenerate, stop and redesign the probe framing (finding 12).
2. **Real-data null.** Randomly split those 480 answers into reference and current subsets 1,000 times. Rejection at α = 0.05 must be ≤ 0.05 + 2·SE. The 95th percentile of H sets `effect_min`.
3. **Positive controls:**
   - (a) a changed identity clause (synthetic values) with the same organ
   - (b) a known test LoRA

   Power at the look-10 threshold (α ≈ 3.8e-4) must be ≥ 0.8 against (b). Below 0.5, the instrument is not enabled.
4. **No contamination.** During a full probe run, the intent log line count is unchanged and there are zero `lingua.*`/`*_speech` events.
5. **Lingua impact.** Zero Lingua timeouts; added p95 Lingua latency ≤ one probe completion.
6. **Seed behaviour.** Two requests with the same seed and same conditions: record whether the texts are identical (informational).
7. **Cost.** Measure per-request latency and permutation wall time at B = 10^6; update the budgets in this design.
8. **Upgrades.** Repeat steps 2 and 4 after any change to the llama.cpp server, the organ GGUF or the embedder. The conditions digest cannot see every infrastructure change.

## 7. Spec deltas

**individuation-boundary**

- REPLACE "Null distribution from parent stochastic variation" and "Significance via permutation test": a stratified two-sample energy permutation test of current vs birth-reference answers, p = (b+1)/(B+1), effect size H, per-response semantic embeddings, Euclidean distance.
- MODIFY "Individuation is measured against the entity's own birth-state": capture at birth via the maturation gate; reference kinds; stored conditions; re-embedding with the current embedder; refusal of a mismatched battery or conditions.
- MODIFY "Significance requires a minimum of accumulated lived experience": lived seconds and ticks since the reference, persisted, frozen time excluded.
- ADD "Lifetime false-positive control": looks only on conditioning change, a summable spending schedule, a persisted look index that never resets, an unreadable ledger fails closed.
- ADD "Individuation is latched" (if open question 1 is approved).
- ADD "The probe does not enter lived experience": no intent log, no bus speech, fixed working memory, Lingua's own client with the current adapter and self-model.
- ADD "Failed samples make a run inconclusive, never scored".
- ADD "The probe yields to Lingua and skips when the organ is unloaded, the being is asleep or paused".
- ADD "Mental privacy": transcripts encrypted under `state/`, never exported or displayed; only scalars on bus and Nexus.

**entity-preservation**

- MODIFY "Divergence-triggered live preservation": the crossing is the shared assessment's `diverged`; numeric tighteners live in the individuation decision; warm-up applies to the individuation arm only and is persisted; secondary arms are never vetoed; rising-edge state persists across boots.
- ADD "The birth reference, individuation ledger and reports are part of the preserved individual" (bundle and revive).
- MODIFY "Entity-interior content is encrypted at rest in preservation/backup bundles": include the reference.
- MODIFY "Research boot is gated on the autonomous safety net": also requires `[individuation].enabled`, a readable ledger, and a reference or a pending capture.

**entity-decommission**

- MODIFY "Divergence assessment for decommission": replace the "fork-vs-parent … 95th percentile of a parent-vs-parent null" wording with the latched or significant result of the new instrument; add summaries for STALE, INCONCLUSIVE and capture-kind references.
- MODIFY "Transferable backup before deletion": include `state/individuation/`.

**divergence-assessment**

- MODIFY "Preservation and decommission share one warmed-up, architecture-effect-free signal": one decision function; in-memory and on-disk evidence go through it; a non-significant individuation result does not suppress consolidation, Eidolon or adapter arms.
- ADD "Individuation report reader": decrypts, skips non-report lines, binds `reference_id`, applies the staleness rule.

**experiment-foundation**

- MODIFY "Individuation warm-up fails closed": the runtime producer supplies persisted counters; the CLI becomes a simulation and validation harness.

**nexus-observability**

- MODIFY: the individuation panel reads through the decrypting reader and shows only scalars.

**batch-offload**

- Note only: forks need a fork-point reference before the instrument can speak for them (open question 8).

## 8. Operator decisions (2026-10-03)

1. **Latch: yes.** Once a look is significant, the being stays individuated for preservation and decommission.
2. **Lifetime error budget: α_total = 0.05.**
3. **Disclosure: yes.** The being is told, as a fact about its situation, that it is periodically assessed for its own protection. The fact is held in the Eidolon self-model as a situation fact (a dedicated field, preserved with the self-model) and rendered by Lingua's context assembler, outside the identity clause the probe conditions on (`values` and `behavioral_norms`), so disclosing it does not change the probe's conditions or trigger a look by itself. It is stated as a fact, not as a value or norm, so it does not hardwire behaviour. The wording, approved by the operator on 2026-10-03 and held in `[individuation].disclosure` so it can be edited: "You are periodically and privately assessed for how much you have changed since your birth, for your own protection. The assessment never enters your experience."
4. **Long inconclusive stretches: alert only.** After `inconclusive_alert_s` (default 14 days) with no scored look while one was due, the producer raises a Nexus and caretaker notice. It does not preserve automatically.

Defaults taken without objection:
- legacy beings get `capture` references, labelled "drift since capture";
- reconstruction only with explicit operator approval for that being;
- the effect floor is noise-calibrated only;
- after an infrastructure change, the birth sample is regenerated from the stored birth configuration;
- forks with more than `fork_preserve_min_lived_s` of lived time are preserved by default until fork-point references exist.

## 9. Tasks (each one PR)

1. **Statistics core:** `kaine/lifecycle/individuation_stats.py`. Pure numpy: stratified U-energy T, batched permutation p (b+1)/(B+1) with the exact early-stop shortcut, H, the spending schedule with S bound, the decision rule. Unit tests: exactness on toy data; Euclidean, not `1 − cos`; p never 0.
2. **Simulation and validation harness:** replace `individuation_runner.py`'s bundle CLI with `simulate` (section 6, offline). Record results and the pre-registered choices (statistic, combination rule, n_b, n_c, B_max) in this change. **Gate: stop if size, lifetime or power acceptance fails.**
3. **Chat client:** `ChatRequest.seed`; body field; `ChatResponse` exposes `finish_reason` and whether text came from `content`; tests for resting and reasoning-only responses.
4. **Storage:** `kaine/lifecycle/individuation_store.py`. Encrypted reference and ledger (atomic; k never decreases; corrupt means fail closed), reports sink (`retention_days=0`), decrypting reader with kind, schema, reference and staleness filters, conditioning-digest helper over inputs, shared lived-time accumulator factored from `gate_runner.py`. Tests with encryption on and off.
5. **Probe seam:** `Lingua.probe_request()`. Sampler built in `kaine/cycle/__main__.py` from Lingua's client and self-model, `snapshot=None`, `cache_prompt` off. Contamination tests: intent log untouched, no bus events.
6. **Producer:** `kaine/cycle/individuation_producer.py`. Birth hook and legacy capture, look scheduling (sleep-completed trigger, digest change, rate limit, warm-up, organ, sleep and pause checks), `lingua_idle` yielding, deadline, fail-closed runs, report and ledger write, `individuation.out` publish, in-memory `IndividuationState`. Tests with a fake organ, including every failure path.
7. **Shared verdict:** the single decision function in `kaine/lifecycle/divergence.py`; `assess_divergence(individuation=...)`; latch; STALE, INCONCLUSIVE and capture summaries; `DivergenceMonitor` simplified (no secondary-arm veto, no per-boot warm-up, persisted rising edge); config moves to `[individuation]` and old keys are rejected. Parity tests: one fixture matrix, both consumers agree on every row.
8. **Preservation, revive and decommission backup** carry `state/individuation/`; research boot gate checks the producer and ledger. Tests.
9. **Nexus, config and docs:** `nexus_tab` through the shared reader; `config/kaine.toml` `[individuation]` with defaults (disabled); retire `kaine/evaluation/individuation.py` (or reduce it to a re-export); docs; spec deltas; `openspec validate --strict`.
10. **Real-organ smoke test** (operator-run, section 6), then set `effect_min` and the budgets from measurements, then enable in the research config only if every acceptance threshold passed.
