## Why

The planning module performs "discrete-state active inference where information has value; its chosen actions become proposals that the action-selection module realizes as think, speak, or rest intents" (§4 table). Its proposals cannot ask for an act, so once `act-intent-derivation` gives the action layer an act outcome, the only act the entity could take is the bare decision to act on an accessed broadcast. Choosing which act serves a preferred outcome, and learning what each act does, is what expected free energy over actions supplies (Da Costa et al. 2020). This change lets the planning module propose acts on the attached effector's declared actions.

Design only: not scheduled. Nothing is built until the start condition below holds.

### What already exists (audit, origin/main 6c8da178)

- The engine selects actions by expected free energy over a discrete model, with a pymdp engine and a NumPy engine that computes the same thing (spec `planning-active-inference`; `kaine/modules/planning/engine.py`, `numpy_engine.py`).
- The B matrix of the control factor learns the consequences of the planning module's own actions, from the action actually taken (spec `planning-active-inference`, "Planning's actions have consequences it learns", "Planning learns from the action actually taken").
- Proposals reach output only through the action-selection module, after they become accessed in a non-inhibited broadcast, with a content-free outcome for every proposal (`kaine/workspace/planning_proposals.py`; spec `action-selection`, "Action selection realizes conscious Planning proposals under the existing gates").

### What is missing

- **The action space is fixed at four actions.** `ACTION_SPACE = ("no_op", "request_think", "request_speak", "request_maintenance")` (`kaine/modules/planning/generative_model.py:66-71`; spec `planning-active-inference`, "Explicit v1 action space", which requires exactly four action dimensions).
- **Proposals map to think, speak and rest only** (`kaine/modules/planning/module.py:59-63`), and the proposal wrapper treats any other kind as disabled (`kaine/workspace/planning_proposals.py:394-396`). No act proposal can be made or realized.
- **No observation modality carries an act's consequence.** The model's modalities mirror its perceptual factors and the entity's own last action (`generative_model.py:14-31`); nothing says whether an act reached its intended outcome.

## What Changes

A design, settled first in the paper and then in code.

1. **Act actions from the effector's declaration (paper §4).** The action space grows by the declared actions of each attached, whitelisted effector, so the model never offers an act the operator has not permitted. Each added action adds a policy, and the complexity envelope and its 200 ms latency bound (spec `planning-active-inference`, "EFE planning is bounded") limit how many can be added.
2. **Act proposals (paper §4, A.6).** A chosen act action becomes a content-free `planning.proposal` of kind `act`, naming the effector and action. The action-selection module realizes it under the act guard and refractory interval of `act-intent-derivation`, signed, with `origin: "planning"`, and records its outcome as for every other proposal.
3. **The act's outcome as an observation.** Recommended: the consequence is observed through the workspace as the rest of the planning module's input is, for the light through the vision module's report, so preferences over outcomes (the C vector) can make an act's pragmatic value differ from its epistemic value. Whether a dedicated outcome modality is needed is open for the paper change.
4. **The benchmark (paper §6.4).** Whether the active-inference benchmark gains an act variant before the live study uses act proposals. Open for the paper change.

## Dependencies and start condition

- **Gate.** The module-addition study has completed its first round (`module-ignition-study` task 2.5) and reached the §6.5 hardware stage. The planning module joins in that first round (branch 3), so it is already in the study by then.
- **Dependencies.** `act-intent-derivation` merged, because a proposal of kind `act` needs the act guard, bar and device effector it realizes through, and its light branch run in the study.
- **Start condition.** Both hold.

## Paper sections it depends on

§3.6 (action gating), §4 (the planning row and the planning paragraph), §6.4 (the active-inference benchmark), §6.5 (the study order), A.6 (the act step added by `act-intent-derivation`).

## Evidence

| Study | Used for | Status |
| --- | --- | --- |
| Da Costa et al. (2020), *Journal of Mathematical Psychology* 99, 102447 | expected free energy over discrete actions; epistemic and pragmatic value | verified (cited in the paper) |
| Heins et al. (2022), *Journal of Open Source Software* 7(73), 4098 | the pymdp engine the planning module uses | verified (cited in the paper) |
| Whyte, Hohwy and Smith (2022), *Current Research in Neurobiology* 3, 100036 | report and other cognitive actions selected under one active-inference scheme | verified (cited in the paper) |

## Capabilities

### New Capabilities

None until the paper change settles the design.

### Modified Capabilities

To be specified by the implementation change: `planning-active-inference` (the action space grows by declared effector actions; act proposals), `action-selection` (realizing act proposals).

## Impact

None now. With no effector attached the action space stays the four actions of today, so the planning module's behaviour and its benchmark are unchanged.
