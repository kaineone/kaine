## Why

Future work names "active vision that chooses where to look by expected free energy (a saccade's epistemic value)" (§10). Today the entity cannot look anywhere: its fovea is a crop of a fixed camera's frame, chosen by bottom-up salience (§3.5, A.2), and the perceptual-locus module only selects which world the senses bind to (§4 table: "selects physical sensors, virtual feeds, or none"). This change designs where-to-look by expected free energy and the overt turn of a movable camera, so the entity can turn toward what it sees or hears to look closer.

Design only: not scheduled. Nothing is built until the start condition below holds.

### What already exists (audit, origin/main 6c8da178)

- Covert attention. Each coarse tile is scored by the z-score of its frame change against its own history, and the fovea moves to the most salient tile past a hysteresis margin and narrows with arousal (`kaine/modules/vision/foveation.py:174-201`; paper §3.5, A.2 "Fovea").
- An attention schema. `FoveaPredictor` forward-models the fovea's own trajectory (`foveation.py:204-222`) and the vision module publishes its prediction (`kaine/modules/vision/module.py:284-291`, `549-551`).
- A top-down seam. `set_top_down_bias_provider` lets a provider bias the salience map (`vision/module.py:430-438`, `449-456`; `combine_saliency`, `foveation.py:145`).
- The perceptual locus. One authority binds perception to a physical or virtual world or none, with operator control and lock and a gated self-switch (spec `perceptual-locus`; `kaine/modules/perceptual_locus/module.py`).
- Gaze channels. The embodiment control surface already carries `gaze_yaw` and `gaze_pitch`, freed at the curriculum's second stage (`kaine/modules/embodiment/control_surface.py:79-83`).

### What is missing

- The trajectory steers nothing. The fovea's forward-modeled trajectory "is published but steers nothing" (§5.4), and no module outside the tests calls `set_top_down_bias_provider` (only `tests/test_vision_module.py:534`, `576`).
- No expected free energy for looking. Fovea selection is the argmax of bottom-up salience (`foveation.py:174-201`); nothing scores a candidate look by what it would reveal.
- No overt look. The camera cannot move, and the perceptual locus has no notion of gaze. Its only entity-initiated intent, `intent.perceptual_locus.switch`, has no producer (`perceptual_locus/module.py:13-20`; `config/kaine.toml:1548-1551`).

## What Changes

A design, settled first in the paper and then in code.

1. Where to look by expected free energy (paper §3.5, A.2, §10). In active inference a saccade is an experiment chosen for the information it is expected to gather (Friston et al. 2012), and visual search over a scene picks each fixation by its epistemic value, the uncertainty it would resolve (Mirza et al. 2016; Parr and Friston 2017). A candidate look is scored by the expected information gain about the vision module's predictions at that target, with any pragmatic value from preferences. The covert fovea and the overt camera turn share one score.
2. Where the score runs. Recommended: in the perceptual-locus module, below the workspace, as the fovea runs today, with accessed content setting its prior through the existing top-down seam, so each look stays fast and outside report. The alternative, discrete fixation states in the planning module (as in Mirza et al. 2016), would make every look a workspace proposal within the planning module's latency budget. Open for the paper change.
3. The overt turn. The camera turns through the gaze channels of the pan-tilt body from `embodiment-motor-contingency`, whose learned contingency predicts how a turn shifts the image; that prediction is what an expected-information-gain score needs. Oculomotor control itself can be cast as planning as inference (Parr and Friston 2018).
4. The attention schema steers. The fovea predictor's predicted next gaze is compared with the chosen look, so its error measures how well the schema predicts where the entity looks. Open for the paper change whether that error is reported.
5. The perceptual-locus row (paper §4). The row changes from selecting sensors to selecting sensors and where they look, with a brain function to cite if one is claimed.

## Dependencies and start condition

- Gate: The module-addition study has completed its first round (`module-ignition-study` task 2.5) and reached the §6.5 hardware stage.
- Dependencies: `embodiment-motor-contingency` merged and its pan-tilt camera body past the curriculum stage that frees both gaze channels on the entity. Without a learned contingency the score has no predicted outcome for a turn.
- Start condition: Both hold.

### Why this follows motor-contingency learning

The order handed to this change put active vision before motor-contingency learning. The code and the literature reverse it. The curriculum frees gaze only after demonstrated competence on the earlier stage (`control_surface.py:79-83`, `197-283`), so an aimed camera is itself a body the curriculum governs. The epistemic value of a look is computed from a model of what that look would show (Friston et al. 2012; Mirza et al. 2016), and for an overt turn that model is the learned sensorimotor contingency (O'Regan and Noë 2001). The paper's future work also names motor-contingency learning first (§10).

## Paper sections it depends on

§3.5 (the fovea), §4 (the perceptual-locus row and the hardware paragraph), §5.4 (the trajectory that steers nothing), §6.5 (the study order), §10 (active vision), A.2 (the fovea rule).

## Evidence

| Study | Used for | Status |
| --- | --- | --- |
| Friston, Adams, Perrinet and Breakspear (2012), *Frontiers in Psychology* 3, 151, doi:10.3389/fpsyg.2012.00151 | saccades as experiments that sample information efficiently | verified (abstract) |
| Mirza, Adams, Mathys and Friston (2016), *Frontiers in Computational Neuroscience* 10, 56, doi:10.3389/fncom.2016.00056 | each saccade chosen by expected free energy with epistemic value | verified (abstract) |
| Parr and Friston (2017), *Neuropsychologia* 104, 92-101, doi:10.1016/j.neuropsychologia.2017.08.003 | what we see depends on where we look; active sampling across senses | verified (abstract) |
| Parr and Friston (2018), *Neuropsychologia* 111, 334-343, doi:10.1016/j.neuropsychologia.2018.01.041 | oculomotor execution as planning as inference | verified (abstract) |
| Feldman and Friston (2010), *Frontiers in Human Neuroscience* 4, 215 | attention as gain on prediction error (today's fovea) | verified (cited in the paper) |
| O'Regan and Noë (2001), *Behavioral and Brain Sciences* 24, 939-973 | the sensorimotor contingency a turn obeys | verified (cited in the paper) |
| Graziano and Webb (2015) | the attention schema the fovea predictor is named after in the code | to verify (cited in code comments only; the paper does not cite it) |

## Capabilities

### New Capabilities

None until the paper change settles the design.

### Modified Capabilities

To be specified by the implementation change: `perceptual-locus` (where to look), `vision` (the expected-free-energy fovea and the steering attention schema).

## Impact

None now. With foveation's top-down provider unset and no camera body, the vision module stays bit for bit identical to the current build.
