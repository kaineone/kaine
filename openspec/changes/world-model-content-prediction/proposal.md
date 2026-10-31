## Why

The paper's §4 table now calls the world model a "latent recurrent model of the entity's waking sequence of broadcast summaries", under the brain function "simulated scene construction" (Hassabis and Maguire 2007; Ha and Schmidhuber 2018; Hafner et al. 2025). The realization is accurate. It is not a model of the world, and three gaps keep it from being one:

- It predicts the coalition ledger. Its observation is "a small fixed-width vector of DERIVED NUMERIC SUMMARIES": one salience-weighted bucket per source, an affect summary and the inhibition flag (`kaine/modules/world_model/encoder.py:1-20`; spec `world-model`, "Observations are workspace summaries, not raw senses"). It learns which modules will speak and how loudly, not what will be seen or heard.
- It takes no action. "Its recurrent transition takes no action, so it cannot predict what the entity's own act or movement will do" (`openspec/changes/world-model-action-outcomes/proposal.md`; `rssm_numpy.py:177-193`, `257-285`).
- Nothing reads it to decide. The planning module's generative model is built by hand from four meta-actions and never reads the world model (`grep world_model kaine/modules/planning` finds nothing; `kaine/modules/planning/generative_model.py:14-71`). The world model's rollouts are published as `world_model.scenario` events in sleep and compete for access; no module uses them to choose.

Scene construction is the imagination of spatially coherent content. A rollout of per-source intensity buckets is not that, so the citation describes what the module should become. The audit flagged this as E7; the triage put the action-conditioned transition and a planner that uses it in W3.

This change covers the first and third gaps: content as the world model's observation and prediction, and a declared imagination interface the planner reads. The second gap is `world-model-action-outcomes`, which already designs the action-conditioned transition and is referenced here, not repeated. The planner's use of imagined rollouts (horizon above one, sophisticated inference) is the agency workstream's planning change, specified in parallel on branch `spec/agency-learning-metacognition-2026-10-31`; this change defines only what the world model offers it.

## What Changes

1. A content observation. The world model observes, beside today's summary, a content code of the accessed broadcast: the accessed content code of `latent-workspace-content-level` when that change is enabled, otherwise a learned low-dimensional projection of the accessed perceptual members' latents (vision, audition) and interoception's readings. It predicts both parts. The encoder is versioned; the checkpoint migrates once with zero-initialised new weights so a preserved model predicts the summary exactly as before.
2. The waking error splits into a summary part and a content part, each precision-scaled, so the existing test of §4 (whether its error changes the sequence of accessed coalitions) stays measurable and a content error can compete beside it.
3. An imagination interface. A typed request on the bus asks the world model to roll out candidate action sequences from the current state for a horizon; the reply gives, per step, predicted observations mapped into the requester's discrete observation space, and the predictive uncertainty. It is bounded in latency and policies, carries latent-derived values only between the two modules, and is never logged.
4. Coordination by reference: `world-model-action-outcomes` supplies the action input the interface needs; the agency planning change consumes the interface. Neither is redesigned here.
5. Paper: the §4 row's realization and citation follow what is built; a revision note is a task.

## Capabilities

### New Capabilities

- `world-model-imagination`: the request and reply contract for imagined rollouts, its bounds and its privacy rule.

### Modified Capabilities

- `world-model`: the observation includes a content code; the waking error has summary and content parts; the checkpoint migration.

## Impact

- Code: `kaine/modules/world_model/` (encoder, both engines, module, checkpoint), the privacy filter, the boot factory.
- Bus: two new event types (`world_model.imagine.request`, `world_model.imagine.reply`) on existing streams.
- Workspace: a new candidate type for the content error.
- Persistence: a checkpoint format version; the weights stay the entity's identity (persisted by default, copied to forks).
- Studies: none until after the module-addition study, in which the world model is the second module added.
- Docs: `docs/09-modules/world-model.md`; a paper revision note for §4 and §10.
