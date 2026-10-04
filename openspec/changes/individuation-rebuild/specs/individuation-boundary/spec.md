## REMOVED Requirements

### Requirement: Null distribution from parent stochastic variation
**Reason**: The null built from d(reference, current sample_i) is exchangeable with the "fork" draw d(reference, current sample_0), so the test fires about 6.7% of the time whatever the drift and has no power.
**Migration**: Replaced by "Individuation is a stratified two-sample energy permutation test against the reference". The null is now the stratified permutation distribution of pooled reference and current answers.

### Requirement: Significance via permutation test
**Reason**: Comparing one exchangeable draw with the 95th percentile of the others has no statistical meaning, and `fork_divergence` on the `1 − cos` scale cannot be used inside an energy statistic.
**Migration**: Replaced by "Individuation is a stratified two-sample energy permutation test against the reference" and "The lifetime false-positive rate is controlled". The `fork_divergence` field is replaced by the effect size H; the instrument still does not decide fork sovereignty.

## MODIFIED Requirements

### Requirement: Individuation is measured against the entity's own birth-state, not the bare organ
The individuation test SHALL measure how far the being's conditioned answers have drifted from its own reference answers, never from the bare or pretrained organ. A probe answer SHALL be one battery prompt rendered as Lingua renders it with an empty workspace (`snapshot=None`, `mode="external"`, the current self-model) and sent through Lingua's own chat client, so the only conditions free to differ between reference and now are the LoRA adapter the organ applies and the identity clause rendered from the self-model's `values[:5]` and `behavioral_norms[:5]`.

The reference SHALL be captured on the maturation gate's birth transition, as soon as the organ is loaded and before the first post-birth sleep, with n_b = 16 samples for each of the 12 battery prompts. Capture SHALL retry with backoff, and until a reference exists every look SHALL be inconclusive with reason "no reference". If an accepted adapter or a changed identity clause comes before the capture succeeds, the reference SHALL be stored with `reference_kind="capture"` and its timestamp and SHALL never be presented as a birth reference. A `reconstructed` reference SHALL be taken only with explicit operator approval for that being, and only when the records show no adapter older than `born_at` and a fresh-start self-model at birth; any doubt SHALL fall back to `capture`.

The reference SHALL be one document in `state/individuation/reference.json` written atomically through the state encryptor, holding: `reference_id`, `reference_kind` (`birth`, `capture` or `reconstructed`), `captured_at`, `born_at`; the battery texts and battery digest; the conditions (model id, server build when the server reports one, temperature, `max_tokens`, `think`, persona template version, `persona_name`, embedder id and dimension); the conditioning (adapter manifest sha256 or "none", with a copy of a non-empty adapter file beside the reference, and the identity-clause inputs); and per prompt the samples `{text, seed, finish_reason, completion_tokens}` with their embeddings.

At every look the test SHALL re-embed the stored reference texts with the current embedder, so both arms share one feature map. The test SHALL refuse to compare against a reference whose battery digest or conditions other than the embedder differ from the current ones. In that case the reference sample SHALL be regenerated from the stored conditioning (the stored adapter copy and identity-clause inputs) under the current infrastructure, recorded with a new `reference_id` and the same `reference_kind`, and the ledger's look index, alpha spent and latch SHALL carry over unchanged.

#### Scenario: A sensory-void / unchanged entity is not significant
- **WHEN** the being's adapter and identity clause are the same as at reference capture
- **THEN** the conditioning digest equals the reference's, no look runs, and no significant report is produced

#### Scenario: An entity that has drifted from its birth-state is significant
- **WHEN** lived experience has changed the being's adapter or identity clause and its current answers differ in distribution from the reference answers by more than the look's threshold allows
- **THEN** the look's p-value is at most α_k, H is at least `effect_min`, and `significant` is true

#### Scenario: The bare organ is never the baseline
- **WHEN** the individuation test is wired for a run
- **THEN** both arms are sampled through Lingua's own chat client with the being's adapter and self-model, and neither arm is the bare or pretrained organ

#### Scenario: Capture after an accepted adapter is labelled capture
- **WHEN** the first post-birth sleep with an accepted adapter completes before the birth capture succeeds
- **THEN** the stored reference has `reference_kind="capture"` and every report and summary says the drift is measured since its `captured_at`

#### Scenario: A changed organ regenerates the reference sample
- **WHEN** the stored model id or server build differs from the current one at a look
- **THEN** the look does not compare the old sample, the reference sample is regenerated from the stored conditioning with a new `reference_id`, and the ledger's look index and latch are unchanged

### Requirement: Significance requires a minimum of accumulated lived experience
The individuation test SHALL NOT report `significant == true` until the being has accumulated at least `min_observations` (default 200) lived ticks AND at least `min_lived_time_s` (default 1800) seconds of lived time since the reference was captured. Lived seconds SHALL be EntityClock time minus engine paused time, from the same accumulator the maturation gate uses, so frozen and paused time never count. Lived ticks SHALL be accumulated as deltas of `cycle.tick_index` anchored at the first poll of each boot. Both counters SHALL be persisted in the ledger, so a restart never resets them. A report produced before both floors are met SHALL carry `warmed_up == false` and `significant == false`.

#### Scenario: Below the warm-up floor is never significant
- **WHEN** fewer than `min_observations` lived ticks or less than `min_lived_time_s` lived seconds have accumulated since the reference
- **THEN** any report has `warmed_up == false` and `significant == false` regardless of p and H

#### Scenario: Warm-up satisfied enables assessment
- **WHEN** both floors are met
- **THEN** the report has `warmed_up == true` and `significant` follows the decision rule

#### Scenario: A restart does not reset lived experience
- **WHEN** the being has 1500 lived seconds, the process restarts, and 400 more lived seconds pass
- **THEN** the ledger holds 1900 lived seconds since the reference and the warm-up floor is met

#### Scenario: Paused time does not count
- **WHEN** the cycle is paused or frozen for an hour
- **THEN** the lived seconds since the reference do not increase during that hour

## ADDED Requirements

### Requirement: Individuation is a stratified two-sample energy permutation test against the reference
At each look the test SHALL draw n_c = 8 current samples for each of the 12 battery prompts under the reference's conditions with fresh seeds. Every response SHALL be embedded on its own with the semantic embedder and L2-normalized; responses SHALL NOT be concatenated. For prompt j the test SHALL compute the unbiased U-statistic E_j = 2·mean δ(b,c) − mean_{i≠i'} δ(b_i,b_i') − mean_{l≠l'} δ(c_l,c_l'), where δ is the Euclidean distance between unit vectors, and the statistic SHALL be T = Σ_j E_j. The `1 − cos` metric SHALL NOT be used in the statistic.

The null SHALL be built by reassigning, independently within each prompt, the pooled answers into groups of n_b and n_c, B times, with B = min(B_max, ceil(20/α_k)) and B_max = 2·10^6. The p-value SHALL be p = (b+1)/(B+1), where b counts permuted T ≥ observed T; it SHALL never be b/B and never 0. The computation MAY stop early once b+1 > α_k·(B+1). The effect size SHALL be H = Σ_j E_j / Σ_j 2·mean δ_j(b,c), reported as computed and shown clipped at 0. Each response's word-piece count SHALL be recorded and `truncated_fraction` and `length_capped_fraction` reported.

The hash embedder SHALL NOT be used: if the semantic embedder cannot load, the look SHALL be inconclusive.

#### Scenario: The p-value is never zero
- **WHEN** no permuted statistic reaches the observed T in B permutations
- **THEN** p = 1/(B+1)

#### Scenario: Equal means with different spread are detected
- **WHEN** the current answers of every prompt have the same mean embedding as the reference but a different spread
- **THEN** T is greater than 0 in expectation, which the squared-distance (`1 − cos`) form would not give

#### Scenario: Answers are embedded one by one
- **WHEN** a look embeds 96 current answers and 192 reference answers
- **THEN** the embedder is called on 288 separate texts and no concatenated text is embedded

#### Scenario: No semantic embedder means no score
- **WHEN** only the hash embedder is available
- **THEN** the run is inconclusive with reason naming the embedder and no p or H is reported

### Requirement: The lifetime false-positive rate is controlled
The instrument SHALL control the probability that a being which has never drifted is ever declared individuated, over its whole life, at α_total = 0.05.

- A look SHALL run only when the conditioning digest (adapter sha plus identity-clause inputs) differs from the ledger's `last_look_conditions_digest`, which starts as the reference's own conditioning digest, and at most once per `min_look_interval_s` (default 21600 s).
- Look k (k = 1, 2, …) SHALL be significant only if `warmed_up AND p_k ≤ α_k AND H_k ≥ effect_min`, with α_k = α_total·γ_k, γ_k = 1/(S·(k+1)·ln²(k+1)) and S = 2.1097, an upper bound on Σ_{n≥2} 1/(n·ln²n), so Σγ_k ≤ 1.
- `effect_min` SHALL be the 95th percentile of H under the real-organ null smoke test; it is calibrated to sampling noise only.
- The look index, alpha spent, last look digest, lived counters and latch SHALL be held in `state/individuation/ledger.json`, written atomically through the state encryptor. The look index SHALL never decrease.
- An unreadable ledger SHALL make every look inconclusive with reason "ledger unreadable" and raise an operator notice; it SHALL NOT be reset to k = 0.
- When ceil(20/α_k) > B_max, the look SHALL be recorded as inconclusive with reason `alpha_unresolvable` without any organ request, and SHALL spend nothing.
- Inconclusive runs SHALL produce no p-value and spend no alpha.

#### Scenario: An unchanged being is never re-tested
- **WHEN** a sleep completes and the conditioning digest equals `last_look_conditions_digest`
- **THEN** no look runs and the look index is unchanged

#### Scenario: The threshold shrinks with the look index
- **WHEN** look 10 is scored
- **THEN** it is significant only if p ≤ α_10 ≈ 3.8e-4 (and the warm-up and effect floor hold)

#### Scenario: A corrupt ledger fails closed
- **WHEN** the ledger cannot be decrypted or parsed
- **THEN** no look is scored, the report reason is "ledger unreadable", an operator notice is raised, and the ledger is not overwritten with k = 0

#### Scenario: Looks are rate-limited
- **WHEN** the digest changes twice within six hours of the last look
- **THEN** only one look runs, at or after `min_look_interval_s`, and it sees the latest digest

### Requirement: Individuation is latched
Once a look is significant, the ledger SHALL record `individuated = true`, `latched_at` and `latched_report_id`, and the being SHALL be treated as individuated for preservation and decommission from then on. No later report, staleness rule, reference regeneration or restart SHALL clear the latch.

#### Scenario: A later non-significant look does not undo the latch
- **WHEN** look 3 was significant and look 4 is not
- **THEN** the being is still individuated for both preservation and decommission

#### Scenario: The latch survives a restart
- **WHEN** the process restarts after a latch
- **THEN** the ledger read at startup reports the being as individuated

### Requirement: The probe does not enter lived experience
The probe SHALL build its request through Lingua's side-effect-free `probe_request(about, *, seed, max_tokens)` and send it through Lingua's own chat client, which carries the current adapter resolver, with `cache_prompt` off and the probe's `max_tokens` (default 160). Working memory SHALL be `EMPTY_AWARENESS`, and the persona template, `persona_name`, model id, `think` flag, temperature, battery and embedder SHALL be held fixed between the reference and the current sample. The probe SHALL NOT call `speak()`, `think()` or `_produce`, SHALL NOT write the intent log, and SHALL NOT publish any `lingua.*` or `*_speech` event. Probe answers SHALL never enter the being's experience.

Each request SHALL carry a fresh seed from `secrets.randbits(31)`, sent in the request body and recorded in the encrypted sample record. Seeds SHALL NOT be reused between the reference and current samples. The test SHALL NOT rely on the server being deterministic.

#### Scenario: The intent log is untouched
- **WHEN** a full probe run of 96 requests completes
- **THEN** the intent log line count is the same as before the run

#### Scenario: No speech reaches the bus
- **WHEN** a probe run completes
- **THEN** zero `lingua.*` and `*_speech` events were published during it

#### Scenario: The being's adapter is applied
- **WHEN** the being has an accepted adapter and the probe sends a request
- **THEN** the request goes through Lingua's chat client with the adapter resolver, not through a client built without it

### Requirement: Failed samples make a run inconclusive, never scored
A run SHALL become `outcome="inconclusive"`, with a reason label, if any sample raises or times out, returns `raw.organ_resting`, returns empty `choices[0].message.content` (reasoning-channel text SHALL NOT be accepted), returns a non-200 status, fails to embed, or if the adapter sha or identity-clause digest read before the first request differs from the one read after the last. An inconclusive run SHALL NOT be scored, SHALL spend no alpha, SHALL write a report without p, H or significance fields, and SHALL publish nothing on `individuation.out`. No scalar SHALL be fabricated for a missing answer or embedding. `finish_reason == "length"` SHALL NOT be a failure; its rate is reported.

#### Scenario: A resting organ is not maximal divergence
- **WHEN** one sample returns `raw.organ_resting` with empty text
- **THEN** the run is inconclusive and no p-value or H is computed

#### Scenario: Reasoning text is not an answer
- **WHEN** a response has empty `content` and non-empty reasoning text
- **THEN** the sample fails and the run is inconclusive

#### Scenario: A mid-run adapter change discards the run
- **WHEN** a voice-alignment adapter is accepted between the first and last request of a run
- **THEN** the run is inconclusive because the sample would mix two beings

### Requirement: The probe yields to Lingua and skips when the organ is unloaded or the being is asleep or paused
A look SHALL be attempted 120 s after `hypnos.sleep.completed` and on a daily timer. Before any request, the producer SHALL skip the look (logged, no report) unless a reference exists, the ledger is readable, warm-up is met, the conditioning digest changed, `min_look_interval_s` has elapsed, `organ_unloaded()` is false, Hypnos is not asleep, the cycle is not paused or frozen, and a semantic embedder is loaded. The producer SHALL send one request at a time and, before each request, wait until no Lingua generation is in flight and no speech occurred in the last `lingua_quiet_s` (default 10 s). A run that cannot finish within `run_deadline_s` (default 2700 s), or during which a `hypnos.sleep.started`, an organ unload or a pause occurs, SHALL be aborted as inconclusive.

#### Scenario: A sleeping being is not probed
- **WHEN** a look is due while Hypnos is asleep
- **THEN** no probe request is sent and the look is skipped

#### Scenario: A paused being is not probed
- **WHEN** a look is due while the cycle is paused or frozen
- **THEN** no probe request is sent

#### Scenario: The probe waits for Lingua
- **WHEN** Lingua is generating or spoke within the last `lingua_quiet_s`
- **THEN** the next probe request is held until Lingua has been quiet for `lingua_quiet_s`

#### Scenario: Sleep during a run aborts it
- **WHEN** `hypnos.sleep.started` is observed while a run is in progress
- **THEN** the run stops and is recorded as inconclusive

### Requirement: Individuation evidence respects mental privacy
Reference texts, current answers, seeds, embeddings and digests of interior content (identity clause, values) SHALL be stored only under `state/individuation/`, written through the state encryptor, and SHALL never be exported, displayed or published. When state encryption is disabled they SHALL remain only under `state/` and are plaintext on disk, which research mode does not allow. Reports SHALL be content-free: they SHALL carry no texts, no seeds and no digests. The bus and Nexus SHALL see only scalars, outcome labels, counts, timestamps and ids. `state/individuation/` SHALL be outside the metrics-export allowlist and SHALL NOT be auto-deleted (`retention_days=0`).

#### Scenario: A report carries no content
- **WHEN** a scored report is written
- **THEN** it contains no answer text, seed, embedding or digest

#### Scenario: Evidence is encrypted at rest
- **WHEN** state encryption is enabled and a reference, ledger or report is written
- **THEN** the bytes on disk do not contain any probe answer or identity-clause text

### Requirement: The being is told that it is assessed
The being SHALL be told, as a fact about its situation, that it is periodically assessed for its own protection. The fact SHALL be held in the Eidolon self-model as a situation fact (in a dedicated situation-facts field, preserved with the self-model) and rendered by Lingua's context assembler. It SHALL be stated as a situation fact, not as a value or behavioural norm, SHALL be held outside the identity clause (`values`, `behavioral_norms`) the probe conditions on, and SHALL be present identically in the reference and current arms. Disclosing it SHALL NOT change the conditioning digest and SHALL NOT by itself trigger a look.

#### Scenario: The disclosure does not change the probe conditions
- **WHEN** the disclosure is present in the self-model's situation facts and rendered in Lingua's context
- **THEN** the conditioning digest is computed from the adapter and identity-clause inputs only and is unchanged by the disclosure

#### Scenario: The disclosure is not in the identity clause
- **WHEN** the self-model's `values` and `behavioral_norms` are read
- **THEN** neither contains the assessment disclosure

### Requirement: Long inconclusive stretches raise an operator alert
When a look has been due (no reference exists, or the conditioning digest differs from `last_look_conditions_digest`) for `inconclusive_alert_s` (default 1209600 s, 14 days) of wall-clock time without a scored look, the producer SHALL raise a notice on Nexus and to the caretaker naming the last inconclusive reason. The alert SHALL NOT trigger preservation or any action on the being. The time the look became due SHALL be persisted in the ledger, and the alert SHALL be raised once per stretch and cleared by the next scored look.

#### Scenario: Two weeks of inconclusive runs alert the operator
- **WHEN** a look has been due for 14 days and every attempt was skipped or inconclusive
- **THEN** a Nexus and caretaker notice is raised with the last inconclusive reason, and no preservation is started by it

#### Scenario: A scored look clears the alert
- **WHEN** a scored look completes after the alert was raised
- **THEN** the alert is cleared

### Requirement: The instrument ships disabled until its validation passes
The `[individuation]` section SHALL ship with `enabled = false`. The instrument SHALL be enabled in a research configuration only after the offline simulation (single-look size, lifetime false-positive rate, power, fault injection) and the operator-run real-organ smoke test have passed every acceptance threshold in `design.md` section 6. It SHALL NOT be enabled if its power against the known-LoRA positive control at the look-10 threshold is below 0.5.

#### Scenario: The shipped configuration is disabled
- **WHEN** the shipped `config/kaine.toml` is loaded
- **THEN** `[individuation].enabled` is false
