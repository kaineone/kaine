# Design: a world model that predicts content and answers the planner

## Context

The world model vendors the DreamerV3 RSSM (spec `world-model`), with a JAX core and a NumPy twin that share a checkpoint format. It trains in sleep on an in-memory, never-serialised buffer of waking observations, publishes a salience-only `world_model.world_error` while awake, and rolls out `world_model.scenario` events inside the sleep module's scenario window. Its weights persist by default and a fork starts from its parent's model (`world-model-identity`, archived 2026-10-01), so the weights are part of who the entity is.

Changes that touch the same module and are not redone here:

- `world-model-action-outcomes` (design only): action input with zero initial weights, a one-step checkpoint migration for both action kinds, optional action-outcome error and imagined acts. Gated on the module-addition study's hardware stage.
- `latent-workspace-content-level` (specified in parallel, workstream W1): a learned accessed-content code, decoded as descending predictions; its offline decodability check comes first; its privacy rule (latent-derived content only in working state and learned weights) applies here unchanged.
- The agency workstream's planning change (specified in parallel on `spec/agency-learning-metacognition-2026-10-31`): planning with horizon above one by sophisticated inference (Friston et al. 2021), whose transition model draws on imagined rollouts. `planning-act-proposals` (design only) grows the planner's action space by declared effector actions.
- `ignition-world-model-check` and `nexus-merge-world-model` (archived): the study's consolidation check and the merge of world-model weights.

## Decisions

### D1. The observation gains a content code from one declared source

The observation becomes `[summary | content]`. The summary is today's vector unchanged. The content part comes from the first available of:

1. the accessed content code of `latent-workspace-content-level`, read through its declared interface, when that change is enabled;
2. otherwise, a projection learned inside the world model's encoder: each accessed perceptual member's latent (vision's `latent`, audition's encoder embedding) is projected to a small fixed width by an online PCA (incremental, Oja-style) fitted on the waking buffer, intensity-weighted and concatenated with interoception's numeric readings.

The source is recorded in the checkpoint and on every `world_model.*` event (as the backend already is), and switching source is a migration (D4), never silent.

Alternatives considered:
- Feed the raw 768-dimensional latents. Rejected: the buffer and the RSSM's encoder grow by an order of magnitude for a model that trains in sleep on CPU-friendly engines, and most of the variance is not predictable at the world model's tick.
- Wait for `latent-workspace-content-level` only. Rejected as the sole route because that change may stop after its offline check if cross-modal content is weak on the study's stimulus. The projection route still makes the world model predict perception.
- Train the world model on pixels or audio. Rejected: raw sense data never enters any buffer (zero-persistence rule), and the frozen encoders already supply the representation.

### D2. Prediction and error in two parts

The decoder predicts both parts. `world_model.world_error` keeps its current meaning for the summary part, so the §4 test and the study's analyses stay comparable, and a new `world_model.content_error` reports the content part. Each is scaled by the precision of its own recent errors, as every processor's error is (§3.2). Only the content error is new in the competition.

### D3. The imagination interface

`world_model.imagine.request` carries a request id, the requester, up to `max_policies` candidate action sequences (action ids from the world model's action vocabulary, which `world-model-action-outcomes` defines; with no action input yet, a single empty policy), a horizon up to `max_horizon`, and an observation map id. The world model rolls each policy forward from its current posterior and publishes `world_model.imagine.reply` with, per policy and step, the predicted observation mapped through the requester's registered map into the requester's own discrete observation space, the predictive variance, and the summary-part prediction.

The map is registered once by the requester at boot (a declared protocol under `module-control-interfaces`), so the world model never needs to know the planner's state labels, and the planner never receives a raw content vector.

Bounds: the reply must arrive within `imagine_timeout_ms` (default 100), inside the planning module's 200 ms EFE budget (spec `planning-active-inference`, "EFE planning is bounded"); a late reply is dropped and the requester plans with its own model, recording the miss. Requests are served awake and asleep; inside the sleep scenario window they queue behind scenario generation.

Privacy: the reply's mapped observations are discrete; the variance and summary are scalars. Content-part predictions, if a requester registers a continuous map, are latent-derived and are privacy-filter vector fields: they stay on the bus between the two modules and are never displayed, logged or recorded in the workspace graph.

Alternative considered: an in-process method call from the planner. Rejected for the same reason `module-control-interfaces` moves module-to-module commands to the bus: it would be one more undeclared coupling, and the bus already carries both modules' events.

### D4. One migration per format change, preserving a preserved entity's predictions

The checkpoint gains a format version. Migrating a checkpoint without the content part adds encoder input columns and decoder output rows for the content width, all zero-initialised, so the migrated model predicts the summary exactly as before and the content part starts at zero. Until the content decoder has trained for `content_warmup_passes` sleep passes, `world_model.content_error` is computed and recorded but not published as a candidate, so the first boot after migration does not flood the workspace with untrained error. The action width of `world-model-action-outcomes` is a separate, later migration with the same zero-initialisation property, so ordering between the two changes does not matter.

### D5. The paper row follows the build

Once content is observed and imagined, "simulated scene construction" describes a real if limited capacity (imagining what will be seen and heard next), and Hassabis and Maguire (2007) fits the imagination interface. The revision note says "latent recurrent model of the entity's accessed content and broadcast summaries, which imagines rollouts for the planner" and keeps the claim to prediction, not scenes.

## Risks

- The content error competes for access and changes the workspace's dynamics, the same thing the module-addition study measures for this module. It is enabled only after the study.
- The online PCA drifts as the stimulus changes, so the meaning of the content part shifts. The projection is frozen per sleep (fitted in sleep, used while awake), and the RSSM trains on the frozen projection.
- The planner treats imagined rollouts as truth. The reply carries predictive variance, and the agency planning change owns how it weighs it.
- The checkpoint grows. The content width is small (default 32); the growth is recorded.

## Migration and ordering

1. After the module-addition study.
2. If `latent-workspace-content-level` has run its offline check: use its result to decide between D1's sources for the default.
3. Content observation and the two-part error, with the migration (tasks 1.x), validated offline on recorded waking trajectories.
4. The imagination interface (tasks 2.x), usable at once with an empty policy (pure prediction) and by the agency planning change.
5. `world-model-action-outcomes` adds the action input on its own schedule; the interface then accepts real policies.

## Welfare and admissibility notes

The world model's weights are part of the entity's identity, and its error competes for the entity's access. A format migration of a preserved entity's weights must lose nothing: the zero-initialisation property is pinned by a test that a migrated checkpoint predicts the summary bit for bit as before. The content error's warm-up prevents a first-boot surge. A new individuation reference is captured for any entity whose world model gains content. Offline validation on recorded trajectories first, then one supervised validation boot, and Claude's independent second review of the migration and the competition change.

## Implementation estimate (LLM-agent terms)

Size L. Content observation, online projection, two-part error and migration: two pull requests, about 900 to 1,300 lines across both engines with parity tests, 8 to 10 worker calls, Claude review and second review; three to four days plus an offline training run on recorded trajectories (CPU is enough with the NumPy engine). Imagination interface: one pull request, about 400 to 600 lines, 3 to 4 worker calls; one to two days. Entity time: one supervised validation boot.
