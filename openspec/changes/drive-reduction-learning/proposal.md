## Why

The paper says the three homeostatic deficits "build while unmet and fall with the events that meet them, the reduction being what drive-reduction accounts call reward (Hull 1943; Keramati and Gutkin 2014), though no learner in the first configuration uses it as a reward signal" (§3.5). Nothing in the reference implementation learns from that reduction, in the first configuration or in any held module.

Design only. Nothing is built until the start condition below holds.

### What already exists (audit, origin/main cb41895b)

- The drives and their relief. Each drive moves by the exact solution of its build and decay equation and is relieved by named channels (`kaine/modules/affect/drives.py`). The entity's own intents relieve restlessness (`kaine/modules/affect/module.py:1553`) and, when not about a drive, boredom by `rho_eng` (`module.py:1555-1566`). Learning progress and alert excess relieve boredom (`module.py:936-939`). Each heard voice relieves the social drive (`module.py:1515`).
- The credit rule. Every relief and every fall back below the band is labelled `own` or `other` (`drives.py:104-170`), with a no-response build input that decides whether a fall would have happened without the entity's response (`drives.py:104-128`; paper A.4). The coping score is the Laplace ratio of `own` ends (`drives.py:186-188`).
- One crude learner of consequences. Each active goal has an expected-relief likelihood `L` that only falls, by `eta_L * L`, when an intent brings no fall within `Delta_resp` (`kaine/modules/affect/goals.py:119-130`; `config/kaine.toml` `goal_response_window_s = 10.0`, `goal_likelihood_fall = 0.5`). `L` feeds the appraisal's obstruction term and never changes which intent is chosen.
- One held learner of action consequences. The planning module's Dirichlet transition learning (spec `planning-active-inference`, "Planning's actions have consequences it learns") learns how four meta-actions move a salience band, an affect quadrant and an event cluster. It has no drive factor, so it cannot learn relief.
- The reserved store. The episodic memory's `procedural` collection is reserved and written by no module (`kaine/memory_kinds.py:28-33`).

### What is missing

- No component estimates how much a given intent relieves a given drive, so the drive-reduction sentence of §3.5 names a reward signal that nothing uses, and Butlin et al.'s AE-1 indicator ("learning from feedback and selecting outputs so as to pursue goals") is absent with or without the held modules.
- The intents of later changes (an act on a stimulus-control effector, `stimulus-control-act`; act intents, `act-intent-derivation`) relieve drives through the world, not through an authored relief channel. Their relief has to be learned, or the choice among them has to be hand-written, which the emergent-behaviour rule forbids.

## What Changes

A design, settled first in the paper and then in code.

1. A held `valuation` module learns, for each coarse context and each intent kind the entity can produce, the expected relief of each deficit within a short window after the intent (an outcome model: "which intents relieve which drives").
2. The relief it learns from is the drive's distance below its no-response trajectory at the end of the window, using the no-response build input the credit rule already computes, so the learner and the credit rule share one definition of the entity's own effect.
3. An intent's value is state-dependent: the homeostatic reward of Keramati and Gutkin (2014), the fall of a convex drive function of the deficit vector, computed from the current deficits and the learned expected reliefs. A relief is worth more when the deficit is larger, so value tracks need (incentive learning, Dickinson and Balleine 1994).
4. The learning signal is a prediction error, `delta = relief - expected relief`, after the reward prediction error of midbrain dopamine neurons (Schultz, Dayan and Montague 1997). The module publishes a graded `valuation.surprise` event on a large error, a new kind of candidate for the competition, and a content-free `valuation.values` summary.
5. Windows that contain a sleep reset, a freeze of any holder, or a welfare response are discarded, so the learner never learns that resting or being paused relieves a drive. The sleep reset already counts as neither `own` nor `other` (A.4).
6. The learned tables are part of the entity: they persist with its state, survive preservation and revive, and a fork starts from a copy of its parent's.
7. Two stages. Stage A computes and records the values and publishes nothing that competes (shadow). Stage B lets `valuation.surprise` compete. No consumer acts on the values until `learned-action-selection`, `multi-step-planning` or `stimulus-control-act` is built and switched on.

## Capabilities

### New Capabilities
- `valuation`: the held valuation module, its outcome model, its relief signal, its state-dependent value, its prediction-error event, its exclusions and its persistence.

### Modified Capabilities
- `affect`: the state event carries each deficit's no-response value, the value the drive would have reached over the last update interval without the entity's own response. Drive dynamics and the credit rule are unchanged.

## Impact

- New: `kaine/modules/valuation/` (module, outcome table, value function), `kaine/boot/factories/valuation.py`, `[valuation]` in `config/kaine.toml` (module off, `stage = "shadow"`), a renderer phrase for `valuation.surprise`, `docs/09-modules/valuation.md`.
- Read only: `affect.state` (drive values, `drive_above`, `drive_ends`), `action_selection.out` intents, `sleep.out`, the control file's freeze holders.
- The affect module gains one content-free field on `affect.state`: each deficit's no-response trajectory value over the last update interval, so the valuation module does not duplicate the drive equations.
- Paper: §3.5 drive sentence keeps "no learner in the first configuration"; §4 gains a valuation row; A.4 gains the relief and value definitions; Table A1 gains the window, learning rate and bias bound.

## Dependencies and start condition

- Gate: the workspace-mediation ablation (§6.3) has run. Stage B, which adds a competing event, waits until the module-addition study's first round has finished, or joins it as its own branch by a CTO decision recorded in the study design.
- No code dependency for stage A. Its consumers are `learned-action-selection`, `multi-step-planning` and `stimulus-control-act`.
