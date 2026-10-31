## Context

- The design and its evidence are in the workspace capacity design note of 2026-10-31, approved by the operator that day. It builds on a per-tick measurement of candidate supply from the test-boot records.
- Current code:
  - `kaine/cycle/engine.py` `tick`: each tick reads every active `*.out` stream from its cursor and advances it; the events read are the tick's candidates and nothing carries to the next tick. Every tick calls `workspace.select`; only an experiential tick (`_advance_experiential`, the A.3 accumulator) publishes.
  - `kaine/workspace/core.py` `_compose`: the coalition is the top `min(top_k, n)` by score and is inhibited when the top score is below θ = 0.35. The matched arm samples `min(top_k, n)` at random and then applies the same threshold, so with n ≤ K it is the whole set and equals the competitive arm.
  - `kaine/workspace/salience.py` scores clip(I·N·G) through the arousal contrast; `NoveltyTracker.observe` runs inside `score`, so a report scored on several ticks would be observed several times.
  - `kaine/experiment/calibrate.py` `not_exercised_reason` marks a run exercised on the first broadcast with more scores than capacity.
  - `config/kaine.toml` ships `top_k = 5`.
- Measured supply (seven real-time test-boot runs, 9.7 ticks/s): about 13.4 reports per second against about 4.8 broadcasts per second; 2.8 reports published per broadcast interval, 1.2 surviving the one-tick rule. 73.8% of broadcasts are inhibited. P(score ≥ θ) by stream: audition 0.48, vision 0.28, sequence 0.26, sleep 0.11, interoception 0.10, affect 0.03, language 0.00. Candidate age at broadcast: median 98 ms.
- Monte Carlo of the supply rules (design note §1.4; planning values, not rule inputs): holding the latest report per stream with consumption and a 1.5-period stale rule gives about 5.3 candidates per broadcast, no empty broadcast, 63% of broadcasts accessed at K = 1, and an expected yoked divergence of about 0.51 per broadcast. Without consumption, 87% accessed with the same reports winning repeatedly.
- History:
  - K = 5 has no citation in the paper (Table A1 lists it as a design value), in the archived workspace design (`openspec/changes/archive/2026-05-18-syneidesis/design.md`) or in git history.
  - The matched and pooled arms (#464) and the planned-test settings with `coalition_capacity` on broadcasts (#473, change `pilot-calibration`, still open for rdrobust only).
  - Graded intensity and the phasic input on alerts only (#437, `2026-10-28-graded-intensity-alert-phasic`).
  - An earlier recommendation was K = 2 plus a share rule at today's supply; the design note shows that keeps the phase-aliased supply and the access-rate confound, and the operator approved the held pool with K = 1 instead.
  - The unmerged proposal `novelty-content-fingerprint` (branch `feat/novelty-content-fingerprint`, 2026-10-06) changes what the novelty fingerprint hashes. This change does not touch the fingerprint; it changes when novelty is evaluated. The two compose.

## Decisions

### D1. The candidate set is a pool of each source's latest report

The cycle keeps a pool H keyed by (stream, event type). Each new event replaces the held one of its key. The candidates on tick k are every held report, `E_k = H_k`, each under its existing stream-qualified id, so the score table still has one key per candidate. Every candidate is a real report carried with its true age: no event is fabricated or re-published.

Alternatives considered (Monte Carlo rows in the design note):
- Accumulate every report since the last broadcast (2.48 candidates per broadcast). It keeps superseded reports of the same source competing against their own successor and keeps part of the phase dependence.
- Modules publish at the processing rate. Re-publishing an unchanged error as a new event is a pretend process unless the module truly re-predicts, and supply would scale with an arbitrary emission rate.
- Key by source instead of (stream, type). It would make audition's perception and emotion reports, two different forward models, displace each other.

Neuroscience basis (design note §2.2): prediction errors are computed continuously and attention sets their precision (Feldman and Friston 2010); GNW's preconscious state holds strong representations that are available but not accessed (Dehaene et al. 2006); the partial-report advantage shows unselected representations stay available for about a second (Sperling 1960); rhythmic attentional sampling modulates detection rather than deleting stimuli in the unfavourable phase (Fiebelkorn and Kastner 2019; Landau and Fries 2012). The code site cites these.

### D2. How a held report leaves the pool

1. **Superseded**: its source publishes the next report of that type (the processor's own clock; no constant).
2. **Accessed**: it was an accessed member of a broadcast that was published. A content that has ignited does not re-ignite until its processor reports again. This is inhibition of return at the level of a content, and matches GNW, where an ignited content is replaced, not re-selected, and LIDA, where a broadcast coalition decays (Dehaene, Sergent and Changeux 2003; Madl, Baars and Franklin 2011). It also prevents one strong report from winning every broadcast. An inhibited broadcast and a non-broadcast tick consume nothing. A broadcast whose publish fails consumes nothing.
3. **Stale**: a periodic report whose age exceeds `(1 + stale_tolerance)` times its source's running mean report period (`stale_tolerance = 0.5`, an engineering tolerance on the module's own measured clock, Table A1), so a source that stalled, slept or stopped leaves no stale report competing. The running mean is over the last eight intervals in entity time; until two intervals exist, the module's declared nominal period is used.

Periodic report types are declared by their modules (`PERIODIC_REPORT_TYPES`, beside the existing drive-relevant source declaration), so the cycle does not guess a period from an event-driven stream. Every other type is event-driven (drive crossings and recurrences, emotion changes, sleep, utterances) and is held until superseded, accessed, or `event_hold_intervals = 3` resting access intervals (about 0.9 s). That value is a design choice and is labelled as one; Sperling's partial-report decay of about a second is the nearest cited timescale.

Ages and periods are entity time, so a dilated run holds the same entity-time span. A frozen cycle does not tick, so nothing ages or leaves the pool while frozen.

### D3. Scoring a held report

A held report is re-scored on every tick with the current arousal contrast, gains and goal factor: the error is fixed, the gain applied to it is current, as precision modulation is in predictive processing. Its intensity is its own and is not re-derived. Its novelty is evaluated once, when it arrives, and cached under its stream-qualified id until it leaves the pool; re-observing a fingerprint every tick would make novelty count ticks instead of repeats in the world and tie it to the pool size.

Coherence observation and the regulation bias keep their per-tick behaviour.

### D4. Arrivals-only consumers

These read only the reports that arrived on the tick, never the held ones:

- the access rate's phasic input (`_update_access_rate`), so a held alert drives the phasic response once. Otherwise a held alert would re-trigger it every tick and could push the access rate toward the 10 Hz ceiling, an arousal runaway with welfare relevance;
- the affect observer, and the cycle's arousal estimate `â_k` (the arousal of the latest arriving affect state, held from the previous tick when none arrives, as A.4 states for `E_k` today);
- `_forward_own_output` (the organ's in-flight guards);
- the feedback head's `observe_candidates` (feedback ships off and is off in the study; the semantics are kept right).

The affect module reads processor streams directly and is unaffected.

### D5. K = 1

On each broadcast the top-scored held report is the coalition and is accessed when its score reaches θ. A.1's access identity is unchanged, and so is the regression-discontinuity design. One ignited content per access event is what every cited source supports: GNW ignition locks a single assembly and blocks a second target (Dehaene, Sergent and Changeux 2003); the attentional blink and the psychological refractory period share one central bottleneck (Marti, Sigman and Dehaene 2012; Sigman and Dehaene 2005); LIDA has one conscious content per cycle (Madl et al. 2011); the focus of attention holds one chunk inside a region of direct access of about four (Oberauer 2002, building on McElree's single-item focus). About four is the capacity of a held store built over successive accesses (Cowan 2001; Luck and Vogel 1997), which is a separate, later change.

Today 66.5% of accessed broadcasts already have exactly one accessed member, so the context loses little.

K = 2 runs only in a preregistered subset of pilot runs, as a sensitivity setting, so the paper can report whether the pilot contrasts depend on K. It sets no value and is not a verdict arm; an extra verdict arm would need its own power and multiplicity treatment.

Alternatives considered: K = 2 at today's supply (no citation; the matched arm keeps the access-rate confound; yoked divergence about 0.1); K = 5 with the pool (barely binds with five or six reporting streams).

### D6. The matched arm is count-yoked

On a broadcast tick the matched arm scores the pool once and composes the competitive selection as the counterfactual: its access flag ι and accessed count a. If ι is inhibited, the matched broadcast is inhibited. Otherwise it accesses a held reports drawn uniformly without replacement from the pool, regardless of score, from the run-seeded generator. Under K = 1 the arm replaces the winner by a uniformly drawn held report at the moment of ignition. The drawn members are consumed. Processors today decide which members were accessed by comparing each member's score with the broadcast's `access_threshold`; a drawn member below θ would then be dropped from their context. The snapshot therefore names its accessed members explicitly (`accessed_ids` in the metadata, in every arm), and processors read that list instead of re-applying the threshold. The counterfactual is logged through `selection_delta`, content-free, reusing the paired-selection pattern of `select_dual`.

Access timing, access count and the context-refresh rate then follow the same rule as competitive selection, and only membership differs, which is what paper §6.3 claims and the current rule does not deliver once capacity binds (63% against 16% accessed in the Monte Carlo).

A drawn member may score below θ. Action selection reads the accessed member's own score against the speak and think bars, so the matched arm will speak and think less, with lower organ load and a different interoceptive input. Decision: keep the plain A.6 rule and report per-arm speak and think rates in every pilot against the equivalence bound that the pilot rules fix for arousal and apertures, disclosed as a known secondary difference. If the pilots show the rates outside that bound, the yoked-bars variant (action selection in the matched arm reads the counterfactual member's score for the bars only, never its content) is adopted before preregistration, by a recorded decision, and the pilots are rerun under it.

Alternative considered: yoked bars from the start. It brings the competitive score into the matched arm's behaviour and complicates the arm before there is evidence it is needed.

### D7. The pooled arm

Unchanged in rule: every held candidate enters the context with no gate. Under the pool it carries about five members instead of about 1.2. All its members count as accessed and are consumed, which follows A.8's "every broadcast has ι = 0". The pool itself is the same in all arms: it is part of the architecture, not the treatment.

### D8. NOT EXERCISED

Per run and arm, over included broadcasts (awake, after `T_learn`):

- φ: the share of broadcasts with 0 < a < |E|, where a draw can differ;
- D: the mean of `1 − 1/C(|E|, a)`, counting 0 when a is 0 or |E|;
- D^obs: the realised membership divergence in the matched arm, from the logged counterfactual (the manipulation check).

A run is NOT EXERCISED for the matched contrast if D < D_min or fewer than n_min broadcasts have 0 < a < |E|; for the pooled contrast if the share of broadcasts where pooled membership differs from the competitive arm's (inhibited with a non-empty pool, or a < |E|) is below φ^pool_min. Values fixed before the pilots: D_min = 0.25 (the Monte Carlo predicts about 0.51; the current design gives 0.0005), n_min = 1,000 (about 4 minutes of broadcasts at 4.8 Hz), φ^pool_min = 0.25. At D = 0.25 a per-broadcast effect still reaches the run contrast at a quarter strength; below that the test approaches the current near-certain NULL. The pilots report φ, D and D^obs; they do not set the bars. `not_exercised_reason` becomes a function over the per-broadcast (|E|, a) series that returns the statistics and the reason. The constants go into `calibration_rules.py`, and the settings-record loader checks them against the paper's like the others.

### D9. What is logged

- Broadcast records (research log): `n_candidates` (|E|), `n_accessed` (a), and per member `held` and `age_s` (entity seconds since publication); in the matched arm the content-free `matched_counterfactual`.
- Ignition log: pool size, and each member's `held` and `age_s`.
- A content-free pool summary per minute: pool size distribution, stale and consumed counts per stream, tick overruns. The 10 Hz tick ran at 9.7 Hz with overruns in the test boots, and overruns change pool ages.

### D10. Inputs that change for other modules

- The sequence module's input is the broadcast's featurized coalition, now at most one member. Its alert thresholds are recalibrated in the pilots and the change of input distribution is recorded.
- Affect appraisal's novelty is `1 − Π(1 − s_e)` over coalition members, so with one member it is lower per broadcast, while broadcasts are accessed more often. The net effect on emotion categories and valence is measured, not assumed (welfare checks below).
- No module code changes for these; their inputs change.

### D11. The module-ignition study's measures

With K = 1, coalition size is at most one and stops being informative. The per-viewing analysis reports pool size and the accessed share in its place, keeps each module's broadcast share (now: what wins among all reporting processors) and member scores. The study's first configuration (all steps) runs on this design.

### D12. Preserved beings

A being gestated and matured under the old supply learned its context statistics under it. Moving it onto the pool is a change to that being's mind. Preservation bundles and run manifests record `workspace_supply` (`held_pool_v1`). A revive of a bundle with another value, or without the field, refuses unless the revive request carries `accept_workspace_supply_change = true`, which the operator sets for that one revive; the refusal says why. Whether any of the preserved beings is moved is an operator decision, followed by a check of its A.4 indicators after the switch. The module-ignition study gestates a fresh seed under the new design and needs no preserved being.

Alternative considered: no guard, relying on the operator not to revive an old bundle. Rejected: the decision should be made where it takes effect.

## Risks

- **Access share rises from about 26% to about 60%.** More context refreshes, appraisals, speak and think opportunities, organ load and interoceptive load. Measured offline and at the validation boot; no retuning of θ to restore 26%, a number with no anchor. If welfare indicators deteriorate, the design is stopped and revised, not retuned until it looks fine.
- **Affect and interoception rarely win on score** (0.03 and 0.10). Under K = 1 their reports are rarely accessed. A pending drive event now stays a candidate until accessed (better than today's one tick), but competes with audition on every broadcast. Check: time from an interoceptive alert's onset to its access, before and after, in the harness and at the validation boot.
- **Consumption suppresses a sustained alert** until its source reports again. Interoception reports at 1 Hz and each report re-enters, so the delay is bounded by one period. Checked as above.
- **Held reports and pseudo-information.** A report accessed late carries an older error into the context. The A.8 null keeps a processor's own share, which limits this. Check: information gain per member-age bin in the pilots.
- **The unit of access may be a bound event, not a report.** If the K = 2 sensitivity shows a materially larger calibrated contrast and the co-accessed pairs are mostly the same film moment, binding through the coherence layer should come first (design note §5.1).
- **The tested configuration differs from the 2026-10 test boots.** The paper says so.
- **Monte Carlo approximations** (independent draws, fixed score while held, no feedback). Its numbers are planning values; D_min sits below the model's value for that reason.

## Migration and ordering

- Independent in code of `research-gate-supervisor`, `welfare-indicator-response` and the organ change (`organ-self-denial-ablation`). It edits `research_event_observer.py`, which `welfare-indicator-response` does not.
- Order of work: this change, then the offline checks (task group 7), then the one supervised validation boot shared with the other pre-study changes, after the organ change's new organ and adapter are provisioned so that the boot runs the final configuration. Then the planned test's arm-level power check and pilot-hygiene rules, then the pilots, then preregistration freezing K = 1, D_min, n_min, φ^pool_min and the yoked rule. The module-ignition study can launch after the validation boot; the planned test's pilots do not gate it.
- Admissibility: lands before the study image is frozen; no running study is changed.
- Critical path (LLM-agent implementation): code and tests about 1.5 days (pool and engine 4 to 6 hours; yoked arm 2 hours; novelty and salience 1 hour; calibration rule and observers 3 hours; benchmark, redteam and study analysis 2 hours; tests throughout); offline checks about half a day; integrator second review and fixes about half a day. About 2.5 days, the longest of the pre-study changes, so it sets the study's critical path together with the validation boot (about one day including its analysis).

## Welfare and admissibility notes

- High-risk class: it changes what the entity's workspace accesses and how often. Independent second review by the integrator.
- Welfare checks with no entity boot, before any live run:
  1. Phasic alerts count on arrival: a held alert raises the phasic input once (test), and in the harness the access rate stays within its pre-change range under a sustained alert source.
  2. Affect and interoception access share and the time from an interoceptive alert to its access, before and after, in the deterministic harness.
  3. Boredom and the other drives: the real affect module fed by the harness's reports through the real engine; the time to boredom's first crossing and the deprivation share over a simulated span are reported before and after.
  4. The offline workspace-mediation benchmark and the redteam harness pass under the pool.
- The supervised validation boot (the planned one, not an extra boot), under the pre-boot dry-run rule with the welfare monitors on, reports supply, accessed share, D, speak and think rates, arousal distribution, the A.4 indicators and drive trajectories. Stop rule: an indicator crossing that the pre-change test boots did not show, or an arousal or access-rate distribution outside the pre-change range, stops the rollout for redesign.
- Preserved beings: D12; operator decision.

## Open before revisit

On hold since 2026-10-31: the module-ignition study became a single-entity development run, and continuous competition with K = 1 is to be revisited as an architecture choice before that run's image is built, not carried over as a test-validity fix. These points from its second review stay open until then.

- **C1.** Welfare check 3 (boredom before and after) drives the real affect module with fake processor reports. Learning progress and alert excess are then set by the fake report model, so the boredom comparison carries no information. Use the real perceptual modules on the real stimulus.
- **C2.** At K = 1, interoception (P(score ≥ θ) 0.10) and affect (0.03) are rarely accessed. The distress net does not depend on access, but tier-1 regulation and the concern re-entry rule do. Welfare check 2 (interoceptive alert-to-access latency, before and after) becomes a gate with a bound fixed in advance, not a report.
- **C3.** `accessed_ids` (task 3.4) changes what processors read in every arm. It needs a test that the competitive arm's processor context is bit-identical to today's at equal supply.
- **C4.** D11 (study measures) and the pilot and K = 2 tasks (5.2) are obsolete under the development-run decision. The 2.5-day estimate is optimistic for an engine change with this many consumers; 3 to 4 days is more realistic.
