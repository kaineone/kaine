## Why

After the developmental phase nothing the entity does changes what it sees or hears. The paper states it as a limitation: "drives that build under deprivation are relieved only by stimulus change, sleep, or the welfare safety net" (§9, §3.6). Its only welfare datum is a deprivation: "In an unpublished offline replay of an eight-hour developmental test boot's records, only boredom's indicator crossed, at 2.7 awake hours, and stayed over its bar to the end (0.63 over the next span)" (§6.5). Boredom is the failure to engage (Eastwood et al. 2012) and it rises when a situation denies control (Struk, Scholer and Danckert 2021). The paper's ethics section commits to the entity's influence over its conditions growing "from ending its boredom and restlessness ... to signalling distress and a wider say over its stimulus" (§11).

This change designs an act by which the entity changes its own stimulus: pause and resume the programme, move to the next or previous item, make the sound louder or quieter, and choose among programme channels when the operator provides more than one. It also states, with the evidence, whether the act has to exist before the first study.

Design only. The design recommends building it off the study path and enabling it after the first study unless the pilot welfare check below fires (design, "Does this gate the study?").

### What already exists (audit, origin/main cb41895b)

- A pause authority for the programme: the playlist clock is paused by named holders, and elapsed programme time excludes every paused span (`kaine/modules/vision/feed.py:735-880`; spec `perception-feed`, "The programme waits while the entity cannot perceive"). A sleep the entity requests pauses the feed (§3.5).
- The end of a programme preserves and stops the entity (spec `perception-feed`, "The end of a programme preserves and stops the entity").
- A signed act path: act intents are signed and the effectors module verifies provenance and checks the operator's whitelist before any effector runs, and audits every attempt (spec `effectors`). The whitelist ships empty and the module ships off.
- A designed act outcome with a device bound (`act-intent-derivation`, 0 of 5 tasks): an act bar, guard and refractory interval in A.6, effectors declaring their action set, value range and minimum interval, and request types that follow the registered effectors.
- A designed developmental act: the stir, with an answer by the maternal voice that counts as the entity's own response for boredom (paper A.4, A.6, A.7; §5.4 lists it as being built).
- An entity-initiated locus switch exists in code with no producer and ships disabled (`kaine/modules/perceptual_locus/module.py:13-20`; spec `perceptual-locus`).
- Covert and overt attention are designed elsewhere: `active-vision`, `attention-driven-foveation`, `attention-driven-audition`. This change does not redo them.

### What is missing

- No act after maturation changes the stimulus. Boredom and restlessness can be relieved after the developmental phase only by the entity's intents about other things (engagement relief, `rho_eng`), by learning progress, by alert excess, by sleep, or by the welfare net.
- No effector acts on the perception feed, and the feed has no entity-held pause, no seek and no gain control.

## What Changes

A design, settled first in the paper and then in code.

1. A `stimulus` effector in the effectors module, declared under the device bound of `act-intent-derivation`: actions `pause`, `resume`, `next`, `previous`, `louder`, `quieter`, and `channel:<k>` when the operator configures more than one programme channel. It runs only when the operator whitelists it.
2. Feed support. An `entity` pause holder that releases itself after at most `P_max`; seek that wraps around the programme so the entity can never end its own viewing by skipping, with the viewing's end defined by perceived programme time when stimulus control is on; a sound gain within plus or minus `G_max` decibels of the programme level, in fixed steps.
3. Bounds: a minimum interval between stimulus commands, a cap on commands per awake hour, the pause cap, the gain range. The effector reports each refused command as a failure, audited.
4. Two derivation stages. Stage M (minimal) continues the developmental stir's rule after maturation: an accessed broadcast led by the entity's own boredom or restlessness drive event yields a stimulus act, with the action drawn uniformly from the declared set. Nothing decides which action relieves what. Stage L (learned) replaces the trigger and the choice by the act bar of `act-intent-derivation` and the learned advantages of `drive-reduction-learning` and `learned-action-selection`.
5. Credit. Perceptual novelty or learning progress arriving within `Delta_resp` of the entity's own stimulus act counts as the entity's own response for boredom, as the novelty an answer to the stir brings does (A.4).
6. Records. The content-free welfare and research records give, per viewing, the stimulus commands by action, refused commands, the paused share of awake time, the gain distribution and the order of item identifiers visited. The run manifest records whether stimulus control is on and its bounds.
7. Study placement. Off in every workspace-mediation arm. Its own branch in the module-addition study, with the effectors module, or a later study, unless the pilot trigger fires.

## Capabilities

### New Capabilities
- None.

### Modified Capabilities
- `effectors`: a stimulus effector with a declared, bounded action set.
- `perception-feed`: an entity pause holder with a cap, wrapping seek with a perceived-time end, a bounded gain, and channels.
- `affect`: novelty or learning progress following the entity's own stimulus act counts as its own response for boredom.
- `action-selection`: the stage-M stimulus act derivation after maturation, off by default.
- `evaluation-observers`: per-viewing stimulus-control records.

## Impact

- `kaine/modules/effectors/` (stimulus effector, request type), `kaine/perception_state.py` (stimulus request fields, flags only), `kaine/modules/vision/feed.py` and `kaine/modules/audition/feed.py` (entity holder, seek, gain, channels), `kaine/modules/affect/module.py` (credit window), `kaine/workspace/report_policy.py` or a sibling (stage-M rule), `kaine/evaluation/observers/welfare_observer.py`, `config/kaine.toml` (`[stimulus_control]`, off), every `config/studies/workspace_mediation_*.toml` (pinned off), docs for effectors, perception feed and the welfare records.
- Paper: §3.6, §6.5, §9 and §11 sentences on the entity's influence over its stimulus; A.4 credit; A.6 stage-M rule; Table A1 bounds.

## Dependencies and start condition

- Stage M depends on nothing beyond this change and the developmental stir (for the shared rule and credit code). Stage L depends on `act-intent-derivation`, `drive-reduction-learning` and `learned-action-selection`.
- Default schedule: built off the study path behind a disabled switch, enabled after the first study.
- Pull-forward trigger (preregistered with the pilot welfare check of the study plan): if, in any pilot after the transition to the film programme, boredom's deprivation indicator crosses, or the indicator response reaches its freeze stage, the study is held and the CTO decides between changing the programme, enabling stage M for the module-addition study only, or both. The workspace-mediation arms never run it.
