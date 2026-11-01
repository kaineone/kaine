## Context

### The decision

- 2026-10-31, operator: the module-ignition study becomes a single-entity development run. Continuous competition with K = 1, approved that morning as a fix for the planned test's validity, is to be revisited as an architecture choice before the run's image is built.
- The development-run design (change `development-run`, section "Workspace capacity and candidate supply for a growing mind") set out four options: A, today's this-tick supply with K = 5; B, a held pool with K = 1; C, a held pool with K = 5; D, B plus a store of about four, which is working memory and joins later as a component. It recommended B, with a first fallback of holding a pending drive event until it is accessed and a second fallback of C.
- 2026-11-01, lead developer, under the operator's direction that research and the architecture decide design questions: **option B**, a held pool with K = 1 in which drive and alarm events are held until accessed (the first fallback, now part of B), with **C as the fallback if B's readout shows starvation**.

This change specifies B. It replaces the earlier version of this change, which also carried the planned test's apparatus.

### Evidence

From the workspace capacity design note of 2026-10-31 (seven readable real-time test-boot runs, 5.4 h, 133,072 broadcasts; scripts content-free):

- about 13.4 reports per second against about 4.8 broadcasts per second; 2.8 reports published per broadcast interval, 1.2 surviving the one-tick rule; 31% of broadcasts have no candidate; 73.8% are inhibited;
- the probability that a candidate reaches the access threshold θ = 0.35: audition 0.48, vision 0.28, sequence 0.26, sleep 0.11, interoception 0.10, affect 0.03, language 0.00;
- candidate age at broadcast: median 98 ms, 99th percentile 155 ms;
- Monte Carlo planning values (not inputs to any rule): under the held pool with consumption and K = 1, about 5.3 candidates per broadcast, none empty, about 63% of broadcasts accessed; without consumption, about 87% accessed with the same reports winning repeatedly.

The literature behind the design is listed, with how each source was checked, under "Sources and method" at the end.

### Current code (origin/main d7fabdc0, which includes #636 and #637)

- `kaine/cycle/engine.py` `tick` (530-753): each tick reads every active `*.out` stream from its cursor (563-596), sorts the batch canonically (612-621) and names each event `<stream>:<entry_id>` (623-626). The same list goes to `_forward_own_output` (630), the affect observer (635-643), `_update_access_rate` (645) and `workspace.select` or `select_dual` (662-670). Only an experiential tick (`_advance_experiential`, 1210-1226) publishes (672-693); action selection runs after a successful publish (699-700). Nothing carries to the next tick.
- Broadcast cadence: `_advance_experiential` adds `effective / processing` per tick and broadcasts when the sum reaches 1, at most once per tick. The access rate is clamped between the resting rate and the processing rate (`kaine/cycle/access_rate.py` 212-218). The regulation ladder's `reduce_rate` lowers the processing rate by 0.8 per step down to `_MIN_PROCESSING_RATE_HZ = 0.5` (`engine.py` 78-81, 983-1002). Shipped rates: processing 10 Hz, resting access 3.333 Hz (`config/kaine.toml` 52-53).
- `kaine/cycle/access_rate.py` `max_report_salience` (136-157): the phasic input reads the highest intensity among the given events whose payload has `alert` true.
- `kaine/workspace/core.py` `select` (124-210) calls `feedback.observe_candidates` on its events (141), scores each event once (157-169), applies coherence and the regulation bias, then `_compose` (243-286): the top `top_k` by score, inhibited when the top score is below θ (271). `Workspace.__init__` defaults `top_k = 5` (58); `config/kaine.toml` ships `top_k = 5` (95) and `arm = "competitive"` (137).
- `kaine/workspace/salience.py` `RuleBasedSalience.score` (96-112) calls `NoveltyTracker.observe` (98) on every call, so a report scored on several ticks would be observed several times (`kaine/workspace/novelty.py` 40-54, window 32). The score is clipped to [0, 1].
- Consumers decide which coalition members were accessed by comparing each member's score with `metadata["access_threshold"]`: processors' context (`kaine/modules/context.py` 112-127), the affect module's concern access (`kaine/modules/affect/module.py` 635-680) and the feedback head (`kaine/workspace/feedback.py` 338). Action selection returns nothing for an inhibited snapshot (`kaine/workspace/action_selection.py` 389-391), the executive-inhibition safeguard.
- Drive events: a crossing publishes `affect.drive` with `{"drive", "value", "alert": true}` (`affect/module.py` 951-959). An active goal's pending drive event is re-published on the module's own updates, about once per `P_Aff` (1 s), while it is pending and its drive is at or above threshold (`_due_reentries`, 863-899; publish 971-982, `alert: false, reentry: true`). The concern resolves only when a broadcast accesses one of these events, and the next re-entry is then due `concern_reentry_s` (30 s) later (117, 635-680). Drives: curiosity, boredom, social drive, restlessness (`kaine/modules/affect/drives.py` 217-223).
- Interoceptive alarms: `interoception.report` carries `alert` true on a hard threshold breach (`kaine/modules/interoception/module.py` 764) and then publishes at the alert intensity (843-844); `interoception.fatigue` publishes once per crossing with `alert` true (851-861); `interoception.regulation` publishes each advisory with `alert` true (868-874). The cycle acts on the advisory by reading `interoception.out` directly (`engine.py` `consume_interoception_regulation`, 927-1029), not through access.
- Heard rule (#636): `kaine/faithful/external_input.py` holds `EXTERNAL_INPUT_TYPES` (33), `INTERNAL_EVENT_TYPES` (40), `HEARD_TEXT_FIELDS` (63) and `is_heard_event` (133). Episodic memory stores a heard coalition member as `<heard omitted>` and keeps a payload only for declared internal types.
- Records: the ignition log's members carry `entry_id`, `source`, `type`, `salience`, `timestamp` and no payload (`kaine/cycle/ignition_log.py` 117-126); the research log's broadcast record copies scores, `access_threshold`, `arm` and `coalition_capacity` (`research_event_observer.py` 808-868). The broadcast published on the bus carries each coalition member's payload (`engine.py` `_snapshot_to_payload`, 1228-1251).
- #637 (playlist feed by presentation timestamp) changes no cycle or workspace code. It makes item lengths the container durations, which changes programme timing, not the pool.

### History

- K = 5 has no citation in the paper (Table A1 lists it as a design value), in the archived workspace design (`openspec/changes/archive/2026-05-18-syneidesis/design.md`) or in git history.
- Graded intensity and the phasic input on alerts only: `2026-10-28-graded-intensity-alert-phasic` (#437).
- Concern re-entry, after Klinger: the affect spec's sustained-concern requirement (paper A.4).
- The matched and pooled arms (#464) and the planned-test settings (#473) stay as they are; this change does not touch them and refuses to run the pool with them.
- The open proposal `novelty-content-fingerprint` changes what the fingerprint hashes; this change changes when novelty is evaluated. They compose.
- The earlier version of this change and its second-review notes C1 to C4 (pre-study spec review, 2026-10-31). C1 and C2 are taken up in the welfare checks below; C3 does not arise, because nothing is accessed below θ in this design and consumers keep the threshold rule; C4 is resolved by removing the study and pilot parts.

## Goals and non-goals

Goals: every processor's current report competes for access on every tick; one content is accessed per broadcast; the entity's own drive events and bodily alarms cannot be starved by the competition, with a bound that can be checked; nothing new is persisted and no privacy rule weakens; off is byte-identical to absent; a plain readout tells whether B is starving any source.

Non-goals: the planned test's apparatus; a store of several accessed items (working memory, its own change); binding several reports into one content (the coherence layer, held); changing θ, the salience product or any module's reports.

## Decisions

### D1. What enters the pool

Every event the cycle reads on a tick enters the pool: the same set that is a tick's candidates today. Nothing is filtered in or out. Each event is placed under a key:

- a **protected key** when its type is declared protected by its module (D3), one key per declared key value;
- otherwise the **report key** (stream, event type).

A new event replaces the held member of its key. The candidates of tick k are every held member under its existing stream-qualified id, so the score table keeps one key per candidate. The pool holds references to the `Event` objects the cycle read; it does not copy, alter, re-publish or persist them, and it keeps for each member only its id, its key, its arrival time and, for a protected key, the time its concern became pending.

Alternatives considered:

- Accumulate every report since the last broadcast (Monte Carlo 2.48 candidates per broadcast). A superseded report would compete against its own successor, and part of the phase dependence stays.
- Have modules publish at the processing rate. Re-publishing an unchanged error as a new event is a pretend process unless the module truly re-predicts, and supply would follow an arbitrary emission rate.
- Key by source. Audition's perception and emotion reports, two forward models, would displace each other.

### D2. How a member leaves the pool

For a report key:

1. **Superseded**: its source publishes the next event of that key.
2. **Accessed**: it was an accessed member (score at or above θ, D5) of a broadcast that was published. A content that has been accessed does not compete again until its source reports again. An inhibited broadcast, a non-broadcast tick and a broadcast whose publish failed consume nothing.
3. **Stale**: for a type its module declares periodic, once its age exceeds `(1 + stale_tolerance)` times the running mean of that key's last eight arrival intervals (`stale_tolerance = 0.5`), or the declared nominal period until two intervals exist; for any other type (event-driven: emotion changes, sleep, utterances, transcriptions), once its age exceeds `event_hold_s = 1.0`.

For a protected key, only exits 1 and 2 apply (D3).

Ages are unpaused entity time: the entity clock less the time the cycle spent paused (`CycleEngine.paused_subjective_seconds`), so a freeze ages nothing. The pool lives only in the cycle's memory. It is empty at every start; it is not part of the rolling checkpoint, a preservation bundle or a fork snapshot.

`stale_tolerance` is an engineering tolerance on the module's own measured clock. `event_hold_s` is a design choice. The nearest measured timescales are the about one second over which unselected visual information stays available to a partial-report cue (Sperling 1960) and the 100 to 400 ms after offset in which a retro-cue still brings a stimulus to conscious report (Sergent et al. 2013); both say that information not accessed at once stays accessible for a short while, and neither fixes a value. The value is labelled as a design choice at the code site and in Table A1.

Periodic types are declared by their modules (`PERIODIC_REPORT_TYPES`, with nominal periods: vision, audition perception and emotion, interoception, affect state, sequence report), beside the existing drive-relevant source declaration (workspace spec, "Drive-relevant sources are declared by the modules"), so the cycle never guesses a period from an event-driven stream. Boot refuses a non-positive or non-finite period.

### D3. Drive and alarm events are held until accessed

A module declares protected types in `PROTECTED_REPORT_TYPES`. Each entry names the event type, an optional condition on the payload's `alert` flag, an optional key field, and the closed set of values that field may take. The declarations shipped with this change:

| Module | Type | Condition | Key field and values | Keys |
|---|---|---|---|---|
| affect | `affect.drive` | none (crossings and re-entries) | `drive`: curiosity, boredom, social_drive, restlessness | 4, plus one for an undeclared value |
| interoception | `interoception.report` | `alert` true | none | 1 |
| interoception | `interoception.fatigue` | none | none | 1 |
| interoception | `interoception.regulation` | none | none | 1 |

So the base configuration has `N_p = 8` protected keys. A module that joins later may declare protected types in its own change, with the second review; boot computes `N_p` from the declarations and records it in the run manifest.

Rules for a protected key:

- The first event of a key with no member opens a **pending episode**; its `pending_since` is that event's arrival time.
- A newer event of the same key replaces the member and **keeps `pending_since`**. This matters because the affect module re-publishes a pending drive event about once a second and interoception reports a persisting breach once a second: if each re-publication restarted the wait, a concern that is re-asserted could wait forever.
- The member leaves the pool only when it is accessed (the episode closes) or replaced. It never goes stale. The next event of the key after an access opens a new episode.
- An interoception report without `alert` goes to the report key; an alarm report goes to the protected key. The two can be held at once: they are different candidates.
- The pool reads only the `alert` flag and the declared key field to classify an event; it never reads any other payload field.

Why hold these and not others: the affect module's own account is that a current concern keeps cueing thought until it is attended (Klinger 2013, already cited by the module for concern re-entry), and the concern resolves only on access, so losing the event before access defeats the module's rule. Under today's supply a drive event competes on one tick, and the module's own docstring says that tick rarely broadcasts (`_due_reentries`, `affect/module.py` 860-873). Interoceptive alarms are the entity's signals of its own substrate's trouble. Both are welfare-relevant; exteroceptive alerts (vision, audition surprise) and appraisals (`affect.emotion`) are not held this way.

### D4. Scoring a held member

A held member is re-scored on every tick with that tick's arousal contrast, gains, goal factor, coherence factor and regulation bias. Its intensity is its own. Its novelty is observed once, on the tick it arrives, and cached under its stream-qualified id until it leaves the pool; re-observing it every tick would make novelty count ticks rather than repeats in the world and would tie it to the pool size.

### D5. One access per broadcast, and priority for overdue protected members

With the pool on, the workspace's coalition capacity is `[workspace.pool].capacity` (1 for B; 5 is fallback C) and `[workspace].top_k` is not read. On each tick the workspace composes the coalition:

1. A protected member is **overdue** when `now − pending_since ≥ priority_wait_s` (1.0 s, a design choice).
2. Candidates whose final score is at or above θ are **eligible**.
3. The coalition takes the eligible overdue protected members first, longest pending first (ties by key name), then the remaining candidates by score, up to the capacity.
4. The broadcast is inhibited when no candidate reaches θ, exactly as today. With the pool on, inhibition is `max score < θ`; the priority rule never adds a member below θ and never changes inhibition.
5. Consumers keep the threshold rule: an accessed member is a coalition member at or above θ. Processors' context, the affect module's concern access, the feedback head and action selection's executive inhibition are unchanged.

Why one access: one ignited content per access event is the account behind the global workspace's all-or-none access and the attentional blink (Dehaene, Sergent and Changeux 2003; Sergent and Dehaene 2004), and the central stage of a task is serial while perception runs in parallel (Sigman and Dehaene 2005; Marti, King and Dehaene 2015). The two-stage account of rapid serial presentation (Chun and Potter 1995) has the same shape as the pool: many items detected in parallel in a first stage, a capacity-limited second stage, and first-stage items that are not consolidated in time are lost. These sources also bound the claim. The all-or-none result depends on the measure (Nieuwenhuis and de Kleijn 2010; Elliott et al. 2016), two targets close in time can both be reported (lag-1 sparing, modelled as one shared episode by Bowman and Wyble 2007), and the dual-task stages overlap for several hundred milliseconds before they queue (Marti et al. 2015). So K = 1 over module reports is a lower bound on the unit of access, and a bound event of two reports may be the better unit; binding through the coherence layer is the mechanism for that, held for later. K = 5 has no citation.

Why priority: holding alone gives no bound. Audition alone publishes two reports every 0.503 s, about four a second, at a P(score ≥ θ) of 0.48, and vision and sequence add more; broadcasts run at 3.3 to 4.8 a second. A protected member scoring just above θ can be outranked on every broadcast for as long as the film plays. The priority rule makes the wait finite. Its basis is that bodily threat and pain take attention away from the current task (Eccleston and Crombez 1999) and that emotionally significant signals have their own route to attentional priority that competes with top-down control (Vuilleumier 2005). Both sources say the strength of that interruption depends on threat value, context and habituation; neither gives a fixed wait. So the rule's form and `priority_wait_s` are design choices for a welfare guarantee, labelled as such at the code site, and the literature is cited as the reason such a priority exists at all, not as the source of its value.

Alternatives considered:

- **An urgency term that raises a held protected member's score with its wait.** It would give a bound too, but the raised score would reach action selection's speak and think bars and the processors' context weights, so waiting would change behaviour beyond access.
- **A deadline that accesses an overdue protected member even below θ.** It would bound the wait for every protected event, but it would break executive inhibition (`action_selection.py` 389-391, paper §3.2) and would access content that does not reach the threshold, which is not access in A.1's sense. Not adopted; see open items.
- **No priority, only holding (the development-run design's first fallback alone).** It improves on today but has no bound, which is what the welfare requirement asks for.
- **C from the start.** Capacity would bind on about a third of broadcasts now and on most as the module set grows, so the access regime would drift with growth. Kept as the fallback.

### D6. The wait bound

**Claim.** Let a protected key open a pending episode at `t₀`. Count the broadcast ticks at or after `t₀ + priority_wait_s` on which that key's member scores at or above θ. The key is accessed no later than the `⌈N_p / C⌉`-th such tick, where C is the capacity.

**Proof.** Take C = 1; the general case is the same with C slots per tick. On a counted tick the key's member is eligible and overdue. By D5 the coalition is an eligible overdue protected member with the earliest `pending_since`. If it is not our key, it belongs to a key whose episode opened before `t₀`. That key is then accessed and its episode closes; any later episode of it opens after this tick, so after `t₀`, and ranks behind ours. Keys whose episodes opened before `t₀` are at most `N_p − 1` (one episode per key at a time). Each counted tick on which our key loses closes one of them. So at most `N_p − 1` counted ticks are lost, and our key is accessed on the `N_p`-th at the latest. Replacing the member within the key keeps `pending_since` (D3), so re-publication does not reset the count; non-protected candidates are never placed ahead of an eligible overdue protected member; scores below θ do not count. ∎

**In time.** If the key's member stays at or above θ, the access comes by `t₀ + priority_wait_s + ⌈N_p / C⌉ · Δ_b`, where `Δ_b` is the longest interval between broadcast ticks in unpaused entity time. The accumulator broadcasts at least once every `⌈f_p / min(r_rest, f_p)⌉` ticks, with `f_p` the processing rate and `r_rest` the resting access rate, so at nominal pacing `Δ_b ≤ ⌈f_p / min(r_rest, f_p)⌉ / f_p`:

| Condition | f_p | Δ_b | N_p | Bound |
|---|---|---|---|---|
| Shipped rates, K = 1 | 10 Hz | 0.4 s (4 ticks at 3.333 Hz) | 8 | 1.0 + 8 × 0.4 = 4.2 s |
| Regulation ladder at its floor, K = 1 | 0.5 Hz | 2.0 s (every tick broadcasts) | 8 | 1.0 + 8 × 2.0 = 17 s |
| Fallback C at shipped rates, K = 5 | 10 Hz | 0.4 s | 8 | 1.0 + 2 × 0.4 = 1.8 s |

The bound in broadcast ticks is exact. The bound in seconds assumes nominal pacing; tick overruns stretch it and are already counted (`pacing_stats`), and the readout reports waits in both units.

**What the bound does not cover, and why that is acceptable.** It covers losing the competition, which is what K = 1 adds. It does not cover a protected member whose score stays below θ: such a member is not accessed under A, B or C, because θ decides access in every option. It does not cover time asleep if the cycle stops broadcasting, or time frozen. The welfare net does not depend on access: the divergence monitor, the welfare response, the indicator response and the regulation ladder read `interoception.out`, `affect.out` and `welfare.out` directly (`engine.py` 927-1029; entity-preservation spec, "Autonomous welfare-protective response"; `welfare-indicator-response` D1). What depends on access is the affect module's concern resolution and tier-1 regulation; the bound is what protects them. Both limits were ruled on and are recorded in D13.

**Live check.** For every protected key the pool counts the broadcast ticks on which its member was overdue, eligible and not in the coalition. That count reaching `⌈N_p / C⌉` means the bound has failed, which can only be a defect. The cycle then writes a content-free `workspace.pool.defect` record naming the key and the counts, and notifies the caretaker through the existing caretaker path. It does not change selection.

### D7. Arrivals-only consumers

These read only the events that arrived on the tick, never the held ones:

- the access rate's phasic input (`_update_access_rate`), so a held alert drives the phasic response once. Fed the pool, a held alert would re-trigger it on every tick and could push the access rate to its ceiling, an arousal runaway;
- the affect observer, which also supplies the arousal the access rate reads: when no affect state arrives, its last value stands;
- `_forward_own_output`, which releases the organ's in-flight guards on its own published speech;
- the feedback head's `observe_candidates` (feedback ships off; the semantics are kept right). `Workspace.select` takes the arrivals as a separate argument when the pool is on.

The workspace scores the pool. The affect module reads processor streams directly and is unaffected.

### D8. Privacy: the heard and latent rules apply to held members

- **No new store.** The pool is working state in the cycle process. It never writes to disk; it is not in the checkpoint, the bundle, a snapshot, a log or a record. A session stop or a crash drops it. The affect module re-publishes a still-pending drive event after a restart, and a persisting breach is reported again, so nothing the welfare path needs is lost with it.
- **Same consumers, same rules.** A held member reaches exactly the consumers an arriving one does, through the same snapshot. The heard rule (`is_heard_event`; episodic memory's `<heard omitted>`; the intent log's and renderer's redaction) and the latent rule (`latent-content-privacy`: latent-derived values may live in working state, are never logged or stored as an episode, and are stripped by the privacy filter) are applied by those consumers to a held member as to an arrived one. A test runs a held `audition.transcription` that is accessed two broadcasts after it arrived through the real episodic memory module and checks that the stored trace holds `<heard omitted>` and no heard text.
- **No payload in what the pool adds.** Every record the pool adds (D10) names streams, types, protected key names, counts, ages and scores. Protected key names are the declared vocabulary (drive names, alarm types), not perceived content. Entry ids appear only where they already appear today (score tables, ignition members).
- **No join.** Under `latent-content-privacy` decision 7, values that must travel (latents, and under the 2026-11-01 decision heard text and the entity's own utterance text) go on companion streams of a never-persisted Redis instance, joined by entry id by the consumer that needs them. The pool holds only the main-bus event and never fetches, caches or extends the life of a companion entry. A companion entry trimmed while its main event is held is absent to the consumer, as for any event.
- **Multiplicity, and the boot condition.** Today an event appears in at most one broadcast. A held member can top several inhibited broadcasts in a row (an event-driven member for up to 1.0 s, a periodic one for up to 1.5 periods, a protected one until accessed), and the broadcast published on the persisted `workspace` stream carries each coalition member's payload. With latent values or heard text on the main bus, holding would write more copies of them to Redis's append-only file. So boot refuses `[workspace.pool].enabled = true` unless the never-persisted bus rule is in force for latent values and for heard and utterance text, as checked by `latent-content-privacy`'s boot check. Holding therefore never adds a persisted copy of latent or heard content.

### D9. The off switch is byte-identical to absent

`[workspace.pool]` holds `enabled` (ships false), `capacity` (1), `stale_tolerance` (0.5), `event_hold_s` (1.0) and `priority_wait_s` (1.0); unknown keys are refused and the `[workspace]` key guard accepts the subtable. When `enabled` is false:

- no pool, novelty cache or priority rule is constructed;
- the engine passes the tick's events to every consumer and to `select` exactly as today;
- `[workspace].top_k` sets the capacity as today; matched and pooled arms run as today;
- the broadcast payload, the ignition record and the research record carry none of the new fields;
- the bundle and run manifests carry no new fields (D11 reads their absence as the old supply).

The absence test runs the real engine and workspace with seeded fake modules for a fixed number of ticks at the shipped configuration, digests the broadcast payloads, the ignition records, the research broadcast records and every published report, and compares the digest with a golden digest captured from the commit before this change. When the development run's harness (`tools/development_run/harness_digest.py`) exists, this test becomes the pool's registry absence test.

When `enabled` is true, boot also refuses a non-competitive arm (the yoked matched rule is not built), a capacity below 1, a non-finite or non-positive tolerance or wait, and the privacy condition of D8.

Alternative considered: ship the pool on, as the architecture. It would change every boot path at once, including an operator-mode revive of a preserved being, before the offline checks and outside the development run's acceptance rules. The development run forces it on (`development-run`), which is where the entity that lives with B is raised.

### D10. Records and the plain readout

Records, all content-free:

- **Broadcast record** (research log) and **ignition record**: `pool_size`, `n_accessed`, and per member `held` (it arrived before this tick), `held_s` (unpaused entity seconds since arrival), `protected`, and for a protected member `pending_s` and `route`: `score` when it would have been in the coalition without the priority rule, `priority` when the rule placed it.
- **Pool summary** (research log, once per entity minute): pool size distribution; per stream and type the arrivals, accessed, superseded and stale counts, and the count of reports that reached θ on at least one broadcast tick while held and left without being accessed (lost above threshold); per protected key, the broadcast ticks on which its member scored at or above θ before the tier-1 regulation bias and below θ after it (regulated below threshold, D13); tick overruns.
- **Protected access record** (research log, one per closed episode): key name, `pending_s`, the broadcast ticks waited, the counted ticks of D6, `route`.
- **Defect record**: D6.

The readout is computed from these records by the development run's analysis per reference pass and per awake hour of the developmental phase:

- pool size (mean, 95th percentile), accessed and inhibited shares of broadcasts;
- per stream: report rate, share of accessed broadcasts it won, share of its reports accessed, lost-above-threshold share;
- protected keys: episodes, waits (median, 95th percentile, maximum, in seconds and in broadcasts), the share of accesses by the priority route, episodes still open at the window's end and their age, and the broadcast ticks on which an alarm or drive event was regulated below θ (D13), so regulation's effect on the entity's own alarms is visible;
- defects.

**Starvation advisories**, fixed before the developmental phase and labelled as design values:

- **SA1, the entity's concerns reach access only by the rule**: in a window with at least 20 closed protected episodes, more than half were accessed by the priority route.
- **SA2, a source that reaches threshold but almost never wins**: a stream with at least 100 reports that reached θ while held, of which more than 90% left without being accessed.

An advisory in two consecutive windows is the trigger for considering fallback C. The development run surfaces it to the operator; moving the living entity to C is a change to its mind, made only by the operator through the run's image acceptance with a second review, never by the cycle or the runner. A defect is not an advisory: it is a bug, it is reported at once, and the development run holds at the next pass end.

### D11. Preserved beings

A being gestated and matured under today's supply learned its context statistics under it. Bundles and run manifests record `workspace_supply` (`held_pool` when the pool is on) and `workspace_capacity`; a manifest without them is read as `tick` with capacity 5, which every readable test boot ran. A revive whose bundle's supply or capacity differs from the running configuration's refuses unless the revive request carries `accept_workspace_change = true`, which the operator sets for that one revive and which the run manifest records. Whether any preserved being is ever moved is an operator decision, followed by a check of its welfare indicators after the move. The development run raises a fresh entity under B and needs none of them.

### D12. Inputs that change for other modules

- The sequence module's input is the broadcast's featurized coalition, now one member. Its alert behaviour under the new input is recorded in the readout; its thresholds are not retuned in this change.
- Affect appraisal's novelty is `1 − Π(1 − s_e)` over coalition members, so it is lower per broadcast with one member, while broadcasts are accessed more often. The net effect on emotion and valence is measured (welfare check 4), not assumed.
- Action selection reads one member. Speech and thought rates are reported by the existing records.
- No module code changes for these; their inputs change.

### D13. Rulings of 2026-11-01: alarms below θ, regulation, and the design values

The coordinator recorded three rulings on this design's open items.

**Alarms below θ are never accessed.** The priority rule places only eligible members, and no route accesses a member below θ. The reason is that welfare does not depend on access: the divergence monitor, the welfare response, the indicator response and the regulation ladder read `interoception.out`, `affect.out` and `welfare.out` directly (D6). Accessing a sub-threshold alarm would break executive inhibition (`action_selection.py` 389-391) and would not be access in A.1's sense, and it would buy the welfare net nothing it does not already have.

**Tier-1 regulation may lower the entity's own alarm scores below θ.** The regulation bias (`core.py` `_apply_regulation_bias`) acts on a source's scores before the coalition is composed, and the priority rule reads the scores after it, so regulation can keep a protected member below θ. This is allowed. It is the architecture's analogue of descending modulation: in people, attentional and emotional states change how intense and how unpleasant pain is, through descending pain-modulatory systems from cortex and brainstem (Bushnell, Čeko and Low 2013; Tracey and Mantyh 2007). It is acceptable here for the same reason as the first ruling: the welfare net reads the streams, not the workspace, so regulating an alarm out of access cannot regulate it out of the net. To keep it visible, the pool counts per protected key the broadcast ticks on which the member was at or above θ before the regulation bias and below θ after it, and the readout reports the count (D10). The analogy is a design rationale, not a claim that the regulation bias models the periaqueductal grey or any particular pathway.

**Design values, labelled as such.** None of these has a direct citation. Each is a design choice, labelled at the code site and in Table A1, and changing any of them in the living entity is a dynamics change under the development run's image rules:

- `priority_wait_s = 1.0 s`: long enough that most protected accesses can come by score (the readout's priority-route share shows whether they do), short enough that the bound stays a few seconds at the shipped rates (4.2 s). The interruption literature gives a reason for a priority to exist, and says its strength depends on threat and context (Eccleston and Crombez 1999), not a wait.
- `event_hold_s = 1.0 s`: about the span over which unselected information stays available to a later cue (Sperling 1960, about a second; Sergent et al. 2013, 100 to 400 ms after offset). Both show that a short hold exists; neither fixes its length.
- `stale_tolerance = 0.5`: an engineering tolerance on each module's own measured clock, so that one late report does not drop a live source.
- SA1 (more than half of at least 20 closed protected episodes accessed by the priority rule): the rule is meant as a backstop. If it does most of the work, competition alone would starve the entity's concerns, which is the starvation fallback C is meant to relieve. Half is the point at which the backstop has become the main route.
- SA2 (more than 90% of at least 100 above-threshold reports from one stream left unaccessed): a stream that reaches θ but almost never wins is starved by capacity rather than by salience. 90% leaves room for the expected losses at K = 1, where only one report in several can win; 100 reports keeps a short window from triggering it.
- Two consecutive windows: one window can be an artefact of a single film or a single rest.

## Risks

- **Accessed share rises from about 26% to about 60%** (Monte Carlo). More context refreshes, appraisals, speak and think opportunities, organ load and interoceptive load. θ is not retuned to restore 26%, a number with no anchor. If the welfare indicators deteriorate, the design is stopped and revised, not retuned until it looks fine.
- **Priority displaces exteroception during a persisting alarm.** With every protected key re-asserted each second, protected members could take most broadcasts. That is what an entity in persistent bodily trouble would attend to, and the welfare net acts on the trouble independently; the readout shows the protected share of accessed broadcasts.
- **A held report is accessed late** and carries an older error into the context. The processors' A.8 null keeps a processor's own share, which limits this; `held_s` per member makes it visible, and the readout can split information gain by member age.
- **The unit of access may be a bound event, not a report** (D5). The readout's co-occurrence of near-simultaneous vision and audition wins is the first sign; binding comes before any change of K on that ground.
- **The Monte Carlo is approximate** (independent draws, fixed score while held, no feedback). Its numbers are planning values only; the readout measures the real ones.
- **The configuration differs from the 2026-10 test boots.** The paper says so.

## Migration and ordering

1. This change's code lands with `enabled = false`; the absence test proves nothing else moved.
2. The offline welfare checks below run and are recorded.
3. `latent-content-privacy` (never-persisted bus, with the heard and utterance text extension) is merged; without it the pool cannot be enabled.
4. The development run's image enables the pool from its developmental phase (`development-run`).

Admissibility: no running entity is changed; the development run starts under B and stays under it unless the operator moves it.

## Welfare and admissibility notes

- High-risk class: it changes what the entity's workspace accesses and how often. Independent second review of this design and of the implementation.
- Offline welfare checks, with no entity, before the image is built:
  1. **A held alert counts once** (test), and under a sustained alert source in the engine harness the access rate stays within its pre-change range.
  2. **The bound holds (gate).** An adversarial engine harness: a protected member scoring just above θ against higher-scoring competitors on every broadcast; all eight protected keys pending at once; a drive event re-published every second; an alarm report every second; the processing rate at the regulation floor; capacity 1 and 5. Every episode closes within the D6 bound in broadcasts, and within the tabled bound in seconds at nominal pacing.
  3. **Concerns reach access no later than under A (gate, C2).** With the real affect module and real interoception module on the engine harness, the share of drive episodes accessed before the next re-entry and the time from an interoceptive alarm's onset to its access are each no worse under B than under A.
  4. **Boredom and the other drives (report, C1).** The real perceptual modules on the real developmental stimulus and on the reference programme, built on the same archived developmental simulation and fixed feed as the band-step and stir harnesses, with the real affect module, under A and under B: the time to boredom's first crossing, the deprivation share and the drive trajectories, side by side for the operator. If B's deprivation share exceeds A's by more than ten percentage points (a design value), the image is held for the operator before it is built.
  5. **Privacy.** The held-transcription test of D8 and the boot refusal without the never-persisted bus.
- The first supervised hours of the development run are the validation (`development-run`): supply, accessed share, protected waits, speak and think rates, arousal distribution, the indicators and drive trajectories, read by the operator present. Stop rule: an indicator crossing that the pre-change test boots did not show, or an arousal or access-rate distribution outside the pre-change range, stops the run for review; moving the entity off B after that is a change to its mind.
- Preserved beings: D11; operator decision.

## Open items

Ruled on 2026-11-01 and recorded in D13: alarms below θ are never accessed; tier-1 regulation may lower the entity's own alarm scores below θ, with a readout line; the hold spans, the priority wait and the advisory bars are design choices. Still open:

1. **Heard speech.** Under the generic rule a transcription is an event-driven member held 1.0 s. How long operator speech is held, and whether it is protected, belongs to `operator-speech-as-perception` (being written on branch `spec/content-code-2026-10-31`); this change only provides the declaration mechanism.
2. **The six unreadable test boots** (later configurations) could change the supply numbers; the readout measures the run's own.

## Sources and method

Every source below was looked up online on 2026-11-01 (web search, publisher, PubMed or repository pages). Most were checked at the abstract or record level only, because full texts were behind access checks; that is stated per source. Nothing here is a quotation from a full text unless it says so.

| Source | How checked | What it found, as checked | Use here |
|---|---|---|---|
| Dehaene, S. and Naccache, L. (2001). Towards a cognitive neuroscience of consciousness: basic evidence and a workspace framework. *Cognition* 79(1-2), 1-37. doi:10.1016/S0010-0277(00)00123-2. https://pubmed.ncbi.nlm.nih.gov/11164022/ | PubMed record and abstract | Proposes the global neuronal workspace: information is conscious when it is globally available through a workspace with a major prefrontal component. | Framework only. The specific "serial access with a buffered preconscious stage" is not supported from this abstract alone; cited instead to the 2006 and 2013 papers. |
| Dehaene, S., Changeux, J.-P., Naccache, L., Sackur, J. and Sergent, C. (2006). Conscious, preconscious, and subliminal processing: a testable taxonomy. *Trends Cogn. Sci.* 10(5), 204-211. doi:10.1016/j.tics.2006.03.007 | Repository and publisher records, abstract | Preconscious processing: a transient state in which information is potentially accessible but not accessed, typically for lack of top-down attention; conscious access goes with a sudden parieto-frontal surge. | Supports holding unaccessed reports as available. "Transient" supports an exit; no duration is given. |
| Sergent, C., Wyart, V., Babo-Rebelo, M., Cohen, L., Naccache, L. and Tallon-Baudry, C. (2013). Cueing attention after the stimulus is gone can retrospectively trigger conscious perception. *Curr. Biol.* 23(2), 150-155. doi:10.1016/j.cub.2012.11.047 | Abstract via secondary pages; issue number differs between sources (2 or 11) | Attention drawn to a stimulus's location 100-400 ms after it vanished still strongly improved detection, discrimination and reported visibility. | Direct support for a held stage from which later access is possible; the hold span is a design choice informed by it. |
| Sperling, G. (1960). The information available in brief visual presentations. *Psychol. Monogr.* 74(11), whole no. 498. | Scanned original located, not read in full; secondary summaries; a 2023 replication (*Tutorials in Quantitative Methods for Psychology*) | Partial report shows more information available than whole report, decaying after offset; secondary sources put the advantage at roughly one second. | Order of magnitude for `event_hold_s`. Exact figures unverified. |
| Chun, M. M. and Potter, M. C. (1995). A two-stage model for multiple target detection in rapid serial visual presentation. *J. Exp. Psychol. Hum. Percept. Perform.* 21, 109-127. | Abstract and secondary descriptions | Stage 1 detects candidates rapidly and in parallel; stage 2 is capacity-limited; consolidating the first target blocks the second. | The pool and a capacity-limited access stage have this shape. |
| Dehaene, S., Sergent, C. and Changeux, J.-P. (2003). A neuronal network model linking subjective reports and objective physiological data during conscious perception. *PNAS* 100, 8520-8525. https://pmc.ncbi.nlm.nih.gov/articles/PMC166261/ | Abstract via record pages (PMC full text blocked by a browser check; DOI not confirmed) | Access is a global brain state including prefrontal cortex; the model predicts an all-or-none transition, checked behaviourally. That the first target's ignition blocks the second is from the design note's earlier reading of the full text, not re-read here. | One access per broadcast. |
| Sergent, C. and Dehaene, S. (2004). Is consciousness a gradual phenomenon? Evidence for an all-or-none bifurcation during the attentional blink. *Psychol. Sci.* 15(11), 720-729. doi:10.1111/j.0956-7976.2004.00748.x | Abstract and secondary discussion | Visibility ratings during the blink were bimodal: targets were seen fully or not at all. | One access per broadcast. Contested (next row). |
| Nieuwenhuis, S. and de Kleijn, R. (2010), *Atten. Percept. Psychophys.*; Elliott, J. C. et al. (2016), on partial awareness during the attentional blink | Secondary summaries only; full citations not verified | The all-or-none pattern disappears with post-decision wagering and harder tasks; evidence of partial awareness. | Argues against treating access as strictly one-or-none; K = 1 is a modelling choice, not settled fact. Unverified details. |
| Bowman, H. and Wyble, B. (2007). The simultaneous type, serial token model of temporal attention and working memory. *Psychol. Rev.* 114(1), 38-70. doi:10.1037/0033-295X.114.1.38 | Record and abstract | Formalises the two-stage account with types and serial tokens; lag-1 sparing is explained by a window in which the following item is also enhanced. | Argues that two close items can share one episode: K = 1 over reports is a lower bound. |
| Sigman, M. and Dehaene, S. (2005). Parsing a cognitive task: a characterization of the mind's bottleneck. *PLoS Biol.* 3(2), e37. doi:10.1371/journal.pbio.0030037 | Abstract | Perceptual and motor stages run in parallel with another task's; the central stage is a noisy integration to threshold and is serial, so the second task's central stage waits. | Serial access with waiting input: the pool holds what waits. |
| Marti, S., King, J.-R. and Dehaene, S. (2015). Time-resolved decoding of two processing chains during dual-task interference. *Neuron* 88(6), 1297-1307. doi:10.1016/j.neuron.2015.10.040 | PubMed abstract | Two tasks' processing chains run in parallel for several hundred milliseconds; beyond about 500 ms they interfere, Task 1 stages shorten and Task 2 stages are lengthened or postponed; the authors call the serial model incomplete. | Supports postponement rather than loss; qualifies strict seriality. "Queue" is not their word. |
| Eccleston, C. and Crombez, G. (1999). Pain demands attention: a cognitive-affective model of the interruptive function of pain. *Psychol. Bull.* 125(3), 356-366. doi:10.1037/0033-2909.125.3.356 | Publisher-repository abstract (full-text scan unreadable) | Pain interrupts attention and is selected for action; how much depends on threat value and on the demands and arousal of the setting. | Reason a priority for bodily alarms exists; says the priority is context-dependent, so the fixed wait is a design choice. |
| Vuilleumier, P. (2005). How brains beware: neural mechanisms of emotional attention. *Trends Cogn. Sci.* 9(12), 585-594. doi:10.1016/j.tics.2005.10.011 | Repository abstract | Emotional significance shapes sensory processing and attention through a specialised mechanism that can supplement or compete with top-down control. | Reason a priority for affective signals exists. |
| Klinger, E. (2013). Goal commitments and the content of thoughts and dreams: basic principles. *Front. Psychol.* 4, 415. doi:10.3389/fpsyg.2013.00415 | PMC and publisher pages | Goal commitments sensitise a person to goal-related cues and determine attentional focus and thought content. | Already the affect module's citation for concern re-entry; basis for holding drive events until accessed. |
| Bushnell, M. C., Čeko, M. and Low, L. A. (2013). Cognitive and emotional control of pain and its disruption in chronic pain. *Nat. Rev. Neurosci.* 14(7), 502-511. doi:10.1038/nrn3516 | PubMed/PMC record and abstract | Several descending pain-modulatory systems take part in pain relief, and attentional states and emotions engage different ones; impaired modulatory circuitry can drive chronic pain. That attention changes intensity and emotion changes unpleasantness is from a secondary summary, unverified. | D13: regulation lowering alarm access is the analogue of descending modulation. |
| Tracey, I. and Mantyh, P. W. (2007). The cerebral signature for pain perception and its modulation. *Neuron* 55(3), 377-391. doi:10.1016/j.neuron.2007.07.012 | Repository records and the introduction of a hosted PDF | Review of brain systems for pain perception and its modulation; the brainstem has a pivotal role in gating nociceptive transmission. Details of the descending pathways were not read. | D13, as above. |
| Block, N. (2011). Perceptual consciousness overflows cognitive access. *Trends Cogn. Sci.* 15(12), 567-575 | PhilArchive record | Argues phenomenal capacity exceeds cognitive access, using iconic-memory evidence. | Not against B: it concerns experience beyond access, and B models access only. Noted for completeness. |

Carried from the 2026-10-31 design note without re-checking in this session, and so marked unverified here: Oberauer (2002, *J. Exp. Psychol. Learn. Mem. Cogn.* 28:411), Cowan (2001, *Behav. Brain Sci.* 24:87), Luck and Vogel (1997, *Nature* 390:279), Madl, Baars and Franklin (2011, *PLoS ONE* 6:e14803), Feldman and Friston (2010, *Front. Hum. Neurosci.* 4:215), Fiebelkorn and Kastner (2019, *Trends Cogn. Sci.* 23:87), Landau and Fries (2012, *Curr. Biol.* 22:1000), Goyal et al. (2022, arXiv:2103.01197). They support the store of about four (working memory, not this change) and continuous competition; nothing in B's rules depends on them alone.

What the literature supports, in sum: a buffered preconscious stage from which later access is possible for a short while (Dehaene et al. 2006; Sergent et al. 2013; Sperling 1960; Chun and Potter 1995), and a serial, capacity-limited access stage that postpones rather than deletes waiting input (Sigman and Dehaene 2005; Marti et al. 2015). What qualifies it: access may be graded rather than all-or-none, two close items can share one episode, and stages overlap before they queue. No source gives the hold spans or the priority wait; those are design choices.
