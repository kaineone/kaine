## Why

The workspace's candidates are the bus events published since the previous tick. Only an experiential tick broadcasts, about one tick in two or three, and the events of the other ticks are scored and thrown away. Every processor reports on its own clock (vision and audition every 0.503 s, interoception and affect every 1.006 s), so whether a report can compete depends on the phase of its period against the broadcast accumulator, not on its precision-weighted error. Measured over the seven readable real-time test-boot runs (5.4 h, 133,072 broadcasts):

- about 58% of processor reports never compete;
- a broadcast has about 1.2 candidates, and 31% have none;
- the capacity of five never truncated the accessed set, so the matched arm of the planned test equals the competitive arm on 99.94% of ticks, and the NOT EXERCISED guard passes a run on a single tick with more candidates than capacity;
- module broadcast shares are a rate-times-phase artefact (audition 36%, sequence 27%, vision 18%, affect 9%, interoception 9%).

Every other workspace implementation the design note reviewed (GNW network models, LIDA, the shared global workspace of Goyal et al. 2022, the global latent workspace) has all processors competing continuously and a capacity below the number of processors. KAINE has neither. The module-ignition study adds processors one at a time to see what they add to the competition; under the current rule a module's access chance depends on its period's alignment with the accumulator.

The operator approved the design in `workspace-capacity-design-2026-10-31.md` (continuous competition, K = 1, a count-yoked matched arm, the divergence rule for NOT EXERCISED) on 2026-10-31, design-first, with offline checks and one supervised validation boot before any pilot or study run. It changes the entity's dynamics, so it must land before the study and every study step must run on it.

## What Changes

- **Held candidate pool.** The cycle keeps each processor's latest report per (stream, event type). On every tick the candidates are every held report. A held report leaves the pool when its source publishes the next report of that type, when it is an accessed member of a published broadcast, or when it goes stale: a periodic report once its age exceeds 1.5 times its source's running mean report period; an event-driven report after three resting access intervals (about 0.9 s). An inhibited broadcast and a non-broadcast tick consume nothing.
- **Scoring.** Held reports are re-scored on every tick with the current arousal contrast, gains and goal factor; intensity is the report's own; novelty is evaluated once, when the report arrives.
- **Arrivals only.** The access rate's phasic input, the affect observer, the cycle's arousal estimate, the language organ's own-output forwarding and the feedback head's candidate observation read only the reports that arrived on the tick, so a held alert counts once.
- **K = 1.** `[workspace].top_k` ships 1: one accessed content per broadcast. K = 2 runs only as a pilot sensitivity setting and never sets a value.
- **Count-yoked matched arm.** On a broadcast tick the matched arm computes the competitive composition on the same tick (access flag and accessed count) and, when the competitive arm would access a members, accesses a held reports drawn uniformly regardless of score; when it would be inhibited, the matched broadcast is inhibited. The counterfactual is logged content-free. The drawn members are consumed.
- **NOT EXERCISED.** A run is NOT EXERCISED for the matched contrast when its expected membership divergence D is below D_min = 0.25 or fewer than n_min = 1,000 broadcasts had 0 < a < |E|, and for the pooled contrast when the share of broadcasts where pooled membership differs is below 0.25. The values are fixed before the pilots, and φ, D and the realised divergence are reported beside every verdict. The offline development run uses the same rule.
- **Records.** Broadcast records and the ignition log carry the pool size, the accessed count, and each member's age and whether it was held.
- **Preserved beings.** Preservation bundles and run manifests record the workspace supply. A revive of a bundle preserved under the old supply refuses unless the operator sets an explicit per-revive acknowledgement, because moving a being onto the new workspace changes its mind.
- **Study analysis.** The module-ignition analysis reports pool size and accessed share where it reported coalition size.

## Capabilities

### New Capabilities

### Modified Capabilities

- `cognitive-cycle`: the held candidate pool, its exits, the declared periodic types, arrivals-only consumers, and the phasic input on arrival.
- `workspace`: K = 1 by default, novelty once per report, re-scoring of held reports, the count-yoked matched arm.
- `workspace-mediation-ablation`: NOT EXERCISED by the divergence rule.
- `planned-test-calibration`: the divergence statistics and the K = 2 sensitivity pilots.
- `research-event-log`: broadcast records carry pool and access counts and member ages.
- `ignition-log`: members carry their age and whether they were held.
- `module-ignition-study`: per-viewing measures.
- `entity-preservation`: a revive across a workspace supply change needs the operator's decision.

## Impact

- New: `kaine/cycle/candidate_pool.py`.
- Changed: `kaine/cycle/engine.py` (`tick`), `kaine/workspace/core.py` (`_compose`, matched arm, metadata), `kaine/workspace/salience.py`, `kaine/workspace/novelty.py` (once-per-report cache), `kaine/workspace/feedback.py`, each predictive module's declared periodic report types, `kaine/experiment/calibrate.py` and `calibration_rules.py`, `kaine/evaluation/observers/research_event_observer.py`, `kaine/cycle/ignition_log.py`, `kaine/evaluation/benchmarks/workspace_mediation_ablation/`, `kaine/evaluation/redteam/harness.py`, `kaine/research/ignition_study/analysis.py`, the preservation bundle manifest and revive plan, `config/kaine.toml` (`top_k = 1`, `[workspace.pool]`), K = 2 pilot study files.
- Specs and docs: the workspace and cognitive-cycle chapters, `docs/17-research-data/README.md`.
- Paper (to REVISION-NOTES): §3.2 coalition sentence and figure caption, §3.4 "candidates on other ticks are discarded", §6.3 matched arm and NOT EXERCISED, A.1 (E_k is the pool, consumption), A.3 (phasic input on arrival), A.8 (matched arm, rule, φ and D), Table A1 (K = 1 with citations, stale tolerance, event-driven hold, D_min, n_min, φ^pool_min), §6.5 measures, §9 (one access per broadcast; held store deferred; the tested configuration differs from the 2026-10 test boots).
- High-risk class (entity dynamics): independent second review by the integrator.
