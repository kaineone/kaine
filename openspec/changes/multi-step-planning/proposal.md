## Why

The planning module is the only component that chooses among actions by their predicted consequences, and it looks one step ahead (`config/kaine.toml:629`, `planning_horizon = 1`; paper §4 table, "one-step discrete-state active inference over four meta-actions"). Its only preference is written in by hand: "Prefer the highest salience band (last index) — being engaged with the most salient content is the entity's default disposition" (`kaine/modules/planning/generative_model.py:310-322`). That is an authored disposition with no cited neuroscience, which the project's rule on emergent behaviour does not allow. The planning module does not read the world model (`grep world_model kaine/modules/planning` finds nothing), and the paper now states that the first configuration has no reasoning module and that "no multi-step reasoning" exists (§3.5, §9).

Design only. Nothing is built until the start condition below holds.

### What already exists (audit, origin/main cb41895b)

- Correct expected free energy at any horizon: each action's EFE is the best among the policies starting with it, and the published horizon is the configured one (spec `planning-active-inference`, "Per-action expected free energy is correct at any planning horizon"; `honest-planning-and-training`, archived 2026-09-27).
- A NumPy engine that matches pymdp at any horizon, checked at horizon 2 on the live model and horizon 4 (256 policies) on the benchmark (`numpy-nous-engine`, archived 2026-09-27).
- Learned transitions under every action from a broad prior, and learning from the action actually taken (`nous-learned-agency`, `nous-drives-action`, archived).
- A complexity envelope, `factors * max_states_per_factor * actions * planning_horizon <= 4096` (defaults give 64), a 200 ms median latency bound and a 250 ms timeout (spec `planning-active-inference`, "EFE planning is bounded"; `docs/09-modules/planning.md`).
- Designed and not built: act actions in the planning module's action space (`planning-act-proposals`) and an action-conditioned world model (`world-model-action-outcomes`).

### What is missing

- No horizon above one in any shipped or study configuration.
- No preference that is learned or derived; the one preference is authored.
- No drive in the planning module's model, so it cannot plan for the needs the paper's drives describe.
- No path from the world model to the planning module's transitions.

## What Changes

A design, settled first in the paper and then in code.

1. A deficit factor. The planning model gains a hidden-state factor and an observation modality for the dominant deficit and its band (none, boredom high, social drive high, restlessness high), read from `affect.state`.
2. Derived preferences. The authored preference for the highest salience band is removed: the salience, affect and event-cluster modalities carry flat preferences. The deficit modality's preferences are derived from the homeostatic set point, the log-preference of each deficit state falling with the drive function of `drive-reduction-learning`. In active inference, homeostatic set points enter as prior preferences over interoceptive outcomes (Pezzulo, Rigoli and Friston 2015); the set point is the only innate part, and which actions reach it is learned. The innateness is cited at the code site.
3. A horizon above one. The shipped held configuration plans over three steps by policy enumeration within the existing envelope, choosing each step's first action and replanning on the next broadcast. When the action space grows with `planning-act-proposals`, the engine switches to sophisticated inference with pruning (Friston et al. 2021), as people prune decision trees at large expected losses (Huys et al. 2012).
4. Imagined experience from the world model. During sleep's scenario window, the action-conditioned world model rolls out candidate actions from recent waking states; each imagined step is mapped into the planning model's states and added to its transition counts at a weight below one, so imagined experience counts for less than lived experience. This is Dyna-style planning by simulated experience (Sutton 1990), and it matches the reading of hippocampal replay as planning (Mattar and Daw 2018).
5. Sleep is outside the deficit model. A step that spans a sleep reset does not update the deficit factor's transitions, so the planning module never learns that resting clears its deficits; the credit rule treats the reset the same way (A.4).
6. The benchmark gains a two-step deficit-relief task and a horizon ablation (one against three) on it.

## Capabilities

### New Capabilities
- None.

### Modified Capabilities
- `planning-active-inference`: a deficit factor and modality; preferences derived from the homeostatic set point with no authored salience preference; planning over more than one step within the bound; imagined transitions from the world model at reduced weight; no deficit learning across a sleep reset; a deficit-relief benchmark task.

## Impact

- `kaine/modules/planning/generative_model.py` (factor, modality, preferences), `encode_snapshot` (deficit observation from the latest `affect.state`), `engine.py` and `numpy_engine.py` (pruned sophisticated inference, step two), `module.py` (sleep-span rule), `kaine/modules/world_model/` (a rollout export the planning module reads in sleep, after `world-model-action-outcomes`), `config/kaine.toml` `[planning]`, the active-inference benchmark, `docs/09-modules/planning.md`.
- A preserved entity's learned planning state gains a factor: the migration adds the deficit factor's prior counts and keeps every learned count of the existing factors.
- Paper: §4 planning row and paragraph, §9 limitation lines, §10, Table A1 (horizon, pruning thresholds, imagined-evidence weight).

## Dependencies and start condition

- Gate: the module-addition study's first round has finished. The planning module joins that round as branch 3 with today's planner, and changing it earlier would change what that branch tests.
- Steps 1 to 3 and 5 need no other change. Step 4 needs `world-model-action-outcomes`. Sophisticated inference is needed once `planning-act-proposals` adds actions.
