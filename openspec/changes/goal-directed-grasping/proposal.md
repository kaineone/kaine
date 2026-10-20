## Why

The end of the action path is an entity that sees an object, turns to look at it, reaches and grasps it with a gripper because grasping serves an outcome it prefers. Vision for action runs in the dorsal stream (Goodale and Milner 1992), and a reach-to-grasp couples the arm's transport with the hand's grip (Jeannerod 1984). The paper connects the workspace to a body through the embodiment layer (§10) and has no grasp. This change designs goal-directed grasping as the composition of the five earlier action-path changes, and adds only what none of them supplies.

Design only: not scheduled. Nothing is built until the start condition below holds.

### What already exists (audit, origin/main 6c8da178)

- An `interact` channel, freed at the control surface's last stage, described as "one interaction primitive with a provided target-resolver" (`kaine/modules/embodiment/control_surface.py:24-29`, `79-83`).
- Symbolic action families with per-family exposure on the body adapter (`kaine/modules/embodiment/adapter.py:16-25`, `56-60`), which have no producer in the entity's policy (`kaine/modules/embodiment/module.py:28-31`).

### What is missing

- No gripper body. The only adapter is the stub (`kaine/modules/embodiment/adapters/stub.py`), and no stage of `MOTOR_STAGES` names an arm joint or a grip.
- No grasp. No module represents a target to reach, a grip to form or a grasp's outcome.
- The provided target-resolver of the `interact` primitive resolves what the entity acts on outside its own learning (`control_surface.py:24-29`), which the paper must either justify as a scaffold or replace with the gaze of `active-vision`.

## What Changes

A design, settled first in the paper and then in code.

1. Grasping as a composition (paper §4, §10). The target reaches the workspace through vision; the decision to act is the act outcome of `act-intent-derivation`; which act serves the preferred outcome is a proposal of `planning-act-proposals`; the target is fixated by `active-vision`; reach and grip are degrees of freedom of the arm body learned under `embodiment-motor-contingency`; the grasp's outcome is predicted by `world-model-action-outcomes`.
2. The arm body's stages. Recommended: the arm declares freeze-then-free stages in which reaching precedes grip, after the infant course from prereaching to reaching (von Hofsten 1984; Thelen et al. 1993) and Bernstein's freezing of degrees of freedom. Open for the paper change.
3. The target. Recommended: the reach target is the current overt gaze of `active-vision`, which retires the provided target-resolver. Open for the paper change.
4. The device bound. The gripper declares a force and travel limit as part of the device bound of `act-intent-derivation`.
5. The study step (paper §6.5). A grasping branch after the embodiment and perceptual-locus branches.

## Dependencies and start condition

- Gate: The module-addition study has completed its first round (`module-ignition-study` task 2.5) and reached the §6.5 hardware stage.
- Dependencies: All five earlier action-path changes merged and their study branches run: `act-intent-derivation`, `planning-act-proposals`, `embodiment-motor-contingency`, `active-vision`, `world-model-action-outcomes`.
- Start condition: All hold, and an arm with a gripper is attached with the operator's approval under the embodiment module's two-layer gate.

## Paper sections it depends on

§3.6 (action gating and the device bound), §4 (the embodiment and world-model rows), §6.5 (the study order), §10 (embodiment in future work), and every section the five earlier changes amend.

## Evidence

| Study | Used for | Status |
| --- | --- | --- |
| Goodale and Milner (1992), *Trends in Neurosciences* 15, 20-25 | separate visual pathways for perception and for action | verified (cited in the paper) |
| Jeannerod (1984), *Journal of Motor Behavior* 16, 235-254, doi:10.1080/00222895.1984.10735319 | transport and grip components of a natural prehension movement | to verify (bibliographic record checked) |
| von Hofsten (1984), *Developmental Psychology* 20, 378-388, doi:10.1037/0012-1649.20.3.378 | prereaching movements precede reaching | to verify (bibliographic record checked) |
| Thelen et al. (1993), *Child Development* 64, 1058-1098, doi:10.2307/1131327 | reaching emerges from the infant's exploration of its own arm dynamics | to verify (bibliographic record checked) |
| Bernstein (1967), *The co-ordination and regulation of movements* | freeze-then-free degrees of freedom | verified (cited in the paper) |

## Capabilities

### New Capabilities

None until the paper change settles the design.

### Modified Capabilities

To be specified by the implementation change: `embodiment-exposure` (the arm's declared degrees of freedom and stages), `effectors` (the gripper's bound), and whichever capabilities the five earlier changes create.

## Impact

None now.
