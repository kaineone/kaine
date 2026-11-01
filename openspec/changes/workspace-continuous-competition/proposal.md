## Why

The workspace's candidates are the bus events published since the previous tick. Only an experiential tick broadcasts, about one tick in two or three, and the events read on the other ticks are scored and thrown away. Every processor reports on its own clock (vision and audition every 0.503 s, interoception and affect every 1.006 s), so whether a report can compete depends on the phase of its period against the broadcast accumulator, not on its precision-weighted error. Measured over the seven readable real-time test-boot runs (5.4 h, 133,072 broadcasts):

- about 58% of processor reports never compete;
- a broadcast has about 1.2 candidates, and 31% have none;
- the capacity of five never truncated the accessed set;
- module broadcast shares follow report rate times phase (audition 36%, sequence 27%, vision 18%, affect 9%, interoception 9%);
- an affect drive event competes on one tick only, and that tick rarely broadcasts.

The operator ruled on 2026-10-31 that the module-ignition study becomes a single-entity development run and that this change be revisited as an architecture choice, not carried over as a fix for a planned test. On 2026-11-01 the lead developer decided the choice: option B of the development-run design, a held candidate pool with one access per broadcast (K = 1), with drive and alarm events held until they are accessed. Option C (the same pool with K = 5) is the fallback if B's readout shows starvation. This change specifies B and nothing of the planned test.

## What Changes

- **Held candidate pool (`[workspace.pool]`).** The cycle keeps each source's latest report per (stream, event type). Every tick's candidates are the held reports. A report leaves the pool when its source publishes the next report of that key, when it is accessed by a published broadcast, or when it goes stale: a periodic report once it is older than 1.5 times its source's running report period, an event-driven report after 1.0 s. Ages are unpaused entity time. The pool holds the event objects the cycle read and nothing else; it never creates, copies, re-publishes or persists an event.
- **Drive and alarm events are held until accessed.** Modules declare protected types: the affect module's drive events (one key per drive) and interoception's alarms (an alarm report, the fatigue crossing and the regulation advisory). A protected member leaves only when it is accessed or replaced by a newer member of the same key, which keeps the time the concern has been pending.
- **One access per broadcast, with a proven wait bound for protected members.** The coalition capacity is `[workspace.pool].capacity`, 1 for option B. A protected member that has waited at least `priority_wait_s` (1.0 s) takes the coalition before any other candidate that also reaches the access threshold, the longest-pending first. The threshold, the inhibition rule and executive inhibition are unchanged: nothing is accessed below θ. A protected member that reaches θ is accessed within `priority_wait_s` plus one broadcast per protected key (4.2 s at the shipped rates, 17 s at the regulation ladder's slowest processing rate). The cycle checks the bound live and reports a breach as a defect.
- **Scoring.** Held reports are re-scored on every tick with the current gains; intensity is the report's own; novelty is evaluated once, on arrival.
- **Arrivals only.** The access rate's phasic input, the affect observer, the organ's own-output forwarding and the feedback head's candidate observation read only the reports that arrived on the tick, so a held alert counts once.
- **Privacy.** Held members fall under the heard rule and the latent rule exactly as arrived ones do, and the pool reads no payload field except the alert flag and a protected type's declared key. Because a held member can top several inhibited broadcasts, the pool is enabled only together with the bus privacy rule that keeps latent values, heard text and utterance text off every persisted stream (`latent-content-privacy`, extended by the 2026-11-01 decision).
- **Off equals absent.** `[workspace.pool].enabled` ships false. Off, the cycle, the workspace, the records and `[workspace].top_k` behave byte for byte as before this change, checked against a golden digest. The development run turns the pool on from its developmental phase.
- **Readout and starvation advisories.** Content-free records give the pool size, waits, each source's wins and losses, protected waits and the share of protected accesses that needed the priority rule. Two advisories, fixed before the developmental phase, are the trigger for considering fallback C; switching is an operator decision, never automatic.
- **Preserved beings.** Bundles and run manifests record the workspace supply and capacity. A revive across a change of either needs the operator's acknowledgement for that revive.
- **Not in this change.** The count-yoked matched arm, the divergence rule for NOT EXERCISED, the calibration statistics and the K = 2 pilots. They served the planned test, which the development run does not run, and they wait for an experiment designed later. The pool refuses the matched and pooled arms.

## Capabilities

### New Capabilities

### Modified Capabilities

- `cognitive-cycle`: the held candidate pool, its exits, the declared periodic and protected types, the arrivals-only consumers, the phasic input on arrival, the live bound check, and the pool's boot conditions.
- `workspace`: capacity from the pool, priority for overdue protected members, novelty once per report, re-scoring of held reports.
- `research-event-log`: broadcast records carry the pool and its members' holding; a per-minute pool summary; protected access records; defect records.
- `ignition-log`: members carry whether they were held and for how long.
- `entity-preservation`: a revive across a workspace supply or capacity change needs the operator's decision.

## Impact

- New: `kaine/cycle/candidate_pool.py`.
- Changed: `kaine/cycle/engine.py` (`tick`), `kaine/workspace/core.py` (`select`, `_compose`), `kaine/workspace/salience.py` (novelty cache), `kaine/workspace/feedback.py` call site, the affect and interoception modules' type declarations, every predictive module's periodic type declaration, `kaine/evaluation/observers/research_event_observer.py`, `kaine/cycle/ignition_log.py`, the bundle and run manifests and the revive plan, the cycle's boot checks, `config/kaine.toml` (`[workspace.pool]`, shipped off).
- Unchanged: `[workspace].top_k = 5` and the matched and pooled arms with the pool off; the offline mediation benchmark and the red-team harness, which build a `Workspace` directly.
- Depends on: `latent-content-privacy` with the never-persisted bus for latent values and for heard and utterance text, before the pool can be enabled. Read by: `development-run` (forces the pool on, reads its readout), `operator-speech-as-perception` (how long heard speech is held).
- Docs: the workspace and cognitive-cycle chapters, `docs/17-research-data/README.md`.
- Paper (to REVISION-NOTES): §3.2 coalition sentence and figure caption, §3.4 "candidates on other ticks are discarded", A.1 (the candidate set is the pool; consumption; protected priority), A.3 (phasic input on arrival), Table A1 (K = 1 with citations; stale tolerance; event hold; `priority_wait_s`), §9 (one access per broadcast; the store of about four deferred to working memory; the configuration differs from the 2026-10 test boots).
- High-risk class: it changes what the entity's workspace accesses and how often. Independent second review.
- Size L (about 3 to 4 days of implementation with tests and the offline checks). Before the development run's image is built.
