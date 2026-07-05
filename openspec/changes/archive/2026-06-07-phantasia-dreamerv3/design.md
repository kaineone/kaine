# Design — Phantasia world model (danijar/dreamerv3 RSSM)

## Scope decision: world model only, not the agent

DreamerV3 is normally a model-based RL **agent**: an RSSM world model *plus* an
actor-critic trained on imagined rollouts to maximize reward. KAINE uses **only
the RSSM world model**. Rationale:

- Policy/action selection is **Nous (pymdp active inference)**'s job. Adding
  Dreamer's actor-critic would create two competing decision-makers and a reward
  signal KAINE does not define.
- The paper assigns Phantasia purely to *world-modeling and imagination* —
  predicting future states and extrapolating scenarios — which is exactly the
  RSSM's function.

So we vendor the RSSM (encoder, recurrent + stochastic latent transition,
decoder, and the imagination rollout) and exclude the actor/critic/return heads.

## Upstream: danijar/dreamerv3

The official **danijar/dreamerv3** repo (MIT-licensed, JAX-based, actively
maintained) is the upstream source. It is a run-as-script research codebase — its
transitive deps (jax, chex, einops, elements, embodied) are not packaged as a
clean pip library. We therefore **vendor** the relevant source under
`external/dreamerv3/` at a pinned upstream commit hash (recorded in
`external/dreamerv3/UPSTREAM`), with an SPDX `MIT` notice. The `[worldmodel]`
optional extra in `pyproject.toml` adds `jax[cpu]` and the other required deps.

We wrap the RSSM core behind a thin `WorldModel` protocol so the upstream choice
is swappable and tests use a `FakeWorldModel` that requires neither JAX nor the
vendored code.

## Observations = workspace trajectories

Phantasia does not see pixels. Its "observation" is a fixed-width vector encoded
from each `WorkspaceSnapshot`: the salience-weighted coalition (event source/type/
salience), affect summary, and inhibition flag. A bounded ring buffer of these
vectors collected during waking is the training corpus. This is a derived summary
of access-conscious content — no raw sense data (zero-persistence preserved).

## Two modes

- **Waking (inference):** each tick, predict the next latent from the current
  observation + recurrent state; publish `phantasia.world_error` = ||predicted −
  actual|| as a salience-only signal into the workspace. Cheap; can run CPU or a
  sliver of GPU. (`phantasia.world_error` is a salience signal; it does not carry
  imagined content and is not re-injected as a scenario.)

- **Offline (Hypnos):** (1) **train** the RSSM in-memory on the accumulated
  trajectory buffer (GPU, gated by `training_enabled`); (2) on a `mnemos.replay`
  cue, seed the RSSM with the replayed memory's encoded state and **roll out
  imagined trajectories**, publishing `phantasia.scenario`. `phantasia.scenario`
  events are re-injected into the workspace broadcast during maintenance so
  Nous, Thymos, and Eidolon process them via `on_workspace`, enabling associative
  consolidation (paper §3.3.5 phase 3). Without `mnemos-replay` providing replay
  cues, the offline scenario-generation path is silently dead.

## Zero-persistence: in-memory training only

Training operates entirely in-memory. The trajectory buffer is a Python ring
buffer — never serialized to disk. Any upstream DreamerV3 disk-serialization
hooks (checkpoint save, replay buffer flush) are bypassed. No `.pt`, `.pkl`,
`.npy`, `.arrow`, or `.jsonl` files are written to `/tmp` or the project directory
during a training pass.

## GPU + cold-start

Training is sleep-only and behind `training_enabled`; it shares the GPU split
with the language organ's alignment pass (both Hypnos-phase, not concurrent with
the live loop). `jax[cpu]` is the default; GPU requires manual config. Until
enough trajectories accumulate, the world model is under-trained and scenarios
are low quality — documented as a limitation (paper §9: "Phantasia begins from
scratch at first boot").

## Risks

- Upstream DreamerV3 code is research-grade → wrap behind `WorldModel` protocol;
  pin a commit; isolate in the extra; record hash in `external/dreamerv3/UPSTREAM`.
- Trajectory encoding drift if workspace schema changes → version the encoder.
- Training instability → gate behind flag; NaN-loss guard aborts the training
  pass without corrupting in-memory state.

## Out of scope

Dreamer's actor-critic / reward modeling; V-JEPA 2 (paper §10 future work);
pixel-based world modeling.
