## Why

The embodiment module is a "body-agnostic control surface with pluggable body adapters", drawing on internal forward models of the body (Wolpert, Ghahramani, and Jordan 1995) (§4 table). The paper's embodiment experiment "asks whether motor-contingency learning (a freeze-then-free curriculum, Bernstein 1967; perception as sensorimotor mastery, O'Regan and Noë 2001) changes the workspace's dynamics" (§4), and future work connects the workspace to a body "with motor-contingency learning through the control surface" (§10). The code has the scaffold of that learning and none of the learner. This change designs the learner, the loop that drives it, and the first body, a camera on a pan-tilt mount.

Design only: not scheduled. Nothing is built until the start condition below holds.

### What already exists (audit, origin/main 6c8da178)

- **The control surface** emits a clamped continuous command per call over five channels, `drive`, `yaw_rate`, `gaze_yaw`, `gaze_pitch` and `interact` (`kaine/modules/embodiment/control_surface.py:1-50`, `387-406`), and is built only when `[embodiment.control_surface].enabled = true` (`kaine/boot/factories/embodiment.py:63-84`; `config/kaine.toml:1585`).
- **The freeze-then-free curriculum.** `MOTOR_STAGES` frees channels in three stages (`control_surface.py:79-83`), and `MotorCurriculum` frees the next stage only when the rolling forward-model error over a window falls below a competence threshold (`control_surface.py:197-283`).
- **The efference loop.** The emitted command's efference copy and the proprioceptive feedback feed a forward model whose error is the competence signal (`control_surface.py:285-325`, `411-419`). It reuses the interoception module's reservoir forward model class (`control_surface.py:306-312`).
- **The body boundary.** The embodiment module requires both `[embodiment].enabled` and `KAINE_EMBODIMENT_OPERATOR_APPROVED=1` (`kaine/modules/embodiment/module.py:20-22`), routes continuous setpoints per exposed channel (`module.py:318-372`), and exposure keys are routed by the body's declared names (spec `embodiment-exposure`).

### What is missing

- **No learner.** The only motor policy is `QuiescentMotorPolicy`, which emits nothing (`control_surface.py:184-195`), so no command is ever explored and the forward model has nothing to learn. The docstring names the gap: "a real learner is injected at the seam" (`control_surface.py:33-38`).
- **No driving loop.** Nothing outside `control_surface.py` calls `emit` or `observe_feedback`; the boot factory notes that "its per-tick driving loop is the cycle's motor seam" (`kaine/boot/factories/embodiment.py:66-67`), and that seam is unbuilt.
- **Stages fixed to one body.** `MOTOR_STAGES` assumes a locomoting avatar (crawl and turn, then gaze, then interact). A pan-tilt camera has gaze channels only, and an arm with a gripper has joints the stages do not name.
- **No physical body.** The only adapter is the stub (`kaine/modules/embodiment/adapters/stub.py`).
- **The competence error reaches no workspace candidate.** The efference loop's error gates the curriculum and is not published as a prediction error that could compete for access, so the paper's question, whether this learning changes the workspace's dynamics, has no signal to measure.
- **Where continuous control sits is unstated.** The control surface's `intent.avatar.control` comes from the embodiment layer itself (`kaine/modules/embodiment/module.py:28-38`), while §3.3 makes the action-selection module "the only path from the workspace to output". The paper does not say whether per-tick motor control is such an output.

## What Changes

A design, settled first in the paper and then in code.

1. **Where continuous control sits (paper §3.3, §3.6, §4).** Recommended: per-tick motor control runs below the workspace, as the vision module's fovea already moves without an intent (§3.5), and the workspace reaches it through act intents that set what the body attempts. The control surface's inhibition input (`control_surface.py:387-399`) keeps an inhibited entity still. Open for the paper change, which states the choice in §3.3 and §3.6.
2. **The learner (paper §4).** Exploratory movement first, then movement shaped by its consequences, as in self-organizing early motor development (Kuniyoshi and Sangawa 2006) and in the infant's prereaching movements before reaching (von Hofsten 1984; Thelen et al. 1993). Recommended: exploration directed by the learning progress of the motor forward model, the signal curiosity already uses (Oudeyer, Kaplan, and Hafner 2007), so the entity explores where its predictions of its own movement are improving.
3. **Body-declared stages.** The body adapter declares its degrees of freedom and their freeze-then-free order (Bernstein 1967), and the curriculum frees them by demonstrated competence as today. For the pan-tilt camera the stages are pan, then pan and tilt.
4. **The motor error as a candidate.** Recommended: the efference loop's prediction error is published as a precision-scaled report like the other predictive processors' (§3.2), so motor-contingency learning can change the workspace's dynamics and the study can measure it.
5. **The first body.** A camera on a pan-tilt mount: the smallest body with lawful sensorimotor contingencies (O'Regan and Noë 2001), because turning it shifts the image predictably, and the body that `active-vision` then aims.
6. **The study step (paper §6.5).** The embodiment module joins after the effector module.

## Dependencies and start condition

- **Gate.** The module-addition study has completed its first round (`module-ignition-study` task 2.5) and reached the §6.5 hardware stage.
- **Dependencies.** `act-intent-derivation` merged, because recommendation 1 routes what the body attempts through act intents, and the first device bound and its audit are settled on a light before a moving device.
- **Start condition.** Both hold, and a pan-tilt camera is attached with the operator's approval under the embodiment module's two-layer gate.

## Paper sections it depends on

§3.2 (precision-scaled reports), §3.3 (the only path to output), §3.5 (the fovea), §3.6 (action gating), §4 (the embodiment row and paragraph), §6.5 (the study order), §7 (developmental robotics, Kuniyoshi and Sangawa 2006), §10 (embodiment in future work).

## Evidence

| Study | Used for | Status |
| --- | --- | --- |
| Wolpert, Ghahramani and Jordan (1995), *Science* 269, 1880-1882 | forward models of the body and the efference copy | verified (cited in the paper) |
| Bernstein (1967), *The co-ordination and regulation of movements* | freeze-then-free degrees of freedom | verified (cited in the paper) |
| O'Regan and Noë (2001), *Behavioral and Brain Sciences* 24, 939-973 | perception as mastery of sensorimotor contingencies | verified (cited in the paper) |
| Kuniyoshi and Sangawa (2006), *Biological Cybernetics* 95, 589-605 | self-organizing movement from a simulated fetal stage | verified (cited in the paper) |
| Oudeyer, Kaplan and Hafner (2007), *IEEE Transactions on Evolutionary Computation* 11, 265-286 | exploration directed by learning progress | verified (cited in the paper for curiosity); its use for motor exploration to verify |
| von Hofsten (1984), *Developmental Psychology* 20, 378-388, doi:10.1037/0012-1649.20.3.378 | prereaching movements precede reaching | to verify (bibliographic record checked) |
| Thelen et al. (1993), *Child Development* 64, 1058-1098, doi:10.2307/1131327 | reaching emerges as infants explore and modulate their own arm dynamics | to verify (bibliographic record checked) |

## Capabilities

### New Capabilities

None until the paper change settles the design.

### Modified Capabilities

To be specified by the implementation change: `embodiment-exposure` (body-declared degrees of freedom and stages), and the embodiment control surface and its learner, which today have no capability spec of their own.

## Impact

None now. The control surface stays off by default; with it off, every later implementation stays bit for bit identical to the current build.
