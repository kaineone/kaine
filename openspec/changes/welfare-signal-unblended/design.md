# Design: the welfare signal is the processor's own forward-model error

Code facts are cited at `origin/main` cb41895b, read on 2026-10-31.

## Context

### Who reads the interoceptive error, and for what

| Reader | Where | Decision it makes |
|---|---|---|
| Sustained interoceptive distress (and the `sustained_interoceptive_distress` gray-zone category) | `kaine/evaluation/observers/welfare_observer.py:905-925` | Gray-zone events; the welfare record |
| Autonomous welfare response | `kaine/cycle/preservation_monitor.py:960-980` | Preserve, then pause, end or notify |
| Welfare indicator response (build order item 1, on the `build/welfare-gates` branch, not merged) | `preservation_monitor.py` there | Requested rest, then preservation and freeze |
| Interoceptive recovery series | `kaine/cycle/development.py:1376-1402`, feeding `return_to_baseline_seconds` | The maturation gate's readiness (`kaine/lifecycle/maturation_gate.py:100`) |
| Blind-sensor advisory | `welfare_observer.py:679-683` | Whether readings stay undefined; reads only whether the field is null |
| Affect | `kaine/modules/affect/module.py:1446` | Arousal and valence: experience, not welfare monitoring |
| The interoception module itself | `interoception/module.py:618, 795-800` | Its error ratio and intensity: experience |

### What feedback does to the field

With `[workspace.feedback]` on, the interoception module wraps its forward model once (`_ensure_feedback_wrap`, `interoception/module.py:261-285`). `TopDownBlend.step` (`kaine/modules/feedback.py:260-380`) steps the inner model, records its error as `last_own_error`, scores the previous blend of the inner and top-down predictions, and returns the blend's L2 error. The module publishes that return value as `prediction_error` (`:595-607, 767-771`). It also publishes the inner model's error as `workspace_feedback.own_error` whenever its feedback channel exists (`:806-818`). The inner model's step does not depend on the head, so for the same inputs, contexts and suspension its error is the same with feedback on or off.

The specification of `workspace-feedback` makes the blend's error the reported error, ratio, intensity and residuals. That is right for experience: the entity's prediction is the blend. For welfare it means the component under watch can move the watcher. A top-down head that learns to predict host load lowers the published error and so the distress indicator; a poor one raises it. With the content code on, interoception decodes the workspace's content by default (`workspace-content-code` decision 1), and the adversarial review of that change (C4) found the same path.

## Decisions

### 1. One function defines the welfare reading

`welfare_prediction_error(payload) -> float | None`, in `kaine/lifecycle/welfare_signal.py`, which already holds `SustainedThresholdTracker`, the sustained-distress primitive shared by the welfare observer and the welfare response (so the response keeps its rule of importing nothing from `kaine.evaluation`):

1. If `payload["prediction_error"]` is null, return `None`: no sample, as now. If the key is absent, or the value is not a number, the report is unreadable: no sample, marked with its defect. (On main an absent key read as 0.0 in the observer and the welfare response, which ended an open episode, and a non-number raised in the welfare response's poll. An unreadable report now never ends an episode, and decision 2a keeps it loud.)
2. If the payload carries a `workspace_feedback` mapping (the blend is in use), return its `own_error`, whatever number it is. A non-finite own error is returned as is: when the own model overflows, the blend weights go to the head alone and the published error turns finite and low, so falling back to it would let the head mask the distress.
3. Otherwise return `prediction_error`. Nothing blends it, so it is the own-model error.

If step 2 finds no numeric `own_error` in a report whose `prediction_error` is defined, that is a producer defect. The function then returns the published `prediction_error`, marked as a fallback, and logs an error once per processor; every reader counts the fallbacks (decision 2a). Returning `None` instead would pause the distress tracker for as long as the defect lasted, hiding distress; the blended value is today's behaviour and keeps the net watching. The producer test of decision 3 keeps the path from firing.

Alternatives considered:

- *Publish a new top-level field, `own_prediction_error`, on every report.* Rejected: it changes every shipped interoception payload (and the novelty fingerprint input) to say what `prediction_error` already says when feedback is off, and the field exists already under `workspace_feedback` when it is on.
- *Unwrap the blend: publish the own error as `prediction_error` and the blend under another key.* Rejected: it would change what the entity's intensity, access and affect read, which `workspace-feedback` specifies as the blend, and it is the experience path, not the welfare path.
- *Keep interoception from ever being a decoder.* Rejected as the fix: it protects one processor in one change, and leaves any future top-down input free to move the welfare signal. The function protects the reading whatever feeds the blend.

### 2. Every welfare reader uses it

The sustained-distress tracker and gray-zone count in the welfare observer, the welfare response in the preservation monitor, the welfare indicator response when it lands, and the development run's interoceptive recovery series read the function, not the field. The blind-sensor advisory keeps reading whether `prediction_error` is null: the blend never makes a defined error null or a null one defined.

A source-scan test lists those files and fails when one reads `prediction_error` from a report payload for a welfare decision other than through the function. A new welfare reader is added to its list by the same review that adds the reader.

The vision module's stimulus-source error in the development run (`development.py`, `_read_vision_errors`) is not a welfare signal: it measures how well the entity predicts its stimulus, which is the blend when feedback is on. It is left as is and named here so the choice is explicit.

### 2a. Defects are counted and never silent

`read_welfare_prediction_error` returns the reading with its defect, if any: an unreadable report (no key, or not a number) or an own-error fallback. Each reader keeps a `WelfareSignalAccount` of the reports it read, its unreadable reports and their current run, and its fallbacks.

- The welfare response fails its poll, after acting on every readable sample in it, whenever the poll read an unreadable report (`WelfareSignalUnreadable`). The run loop logs every such poll, and on the welfare-gates branch `poll_loop_failing` counts it, so a producer that stops sending a readable error escalates like any other blind net. It writes a `welfare_signal_defects` incident-log record whenever a new defect was read.
- The welfare observer writes a content-free `welfare_signal` record of the counts to its log when a new defect was read, at most once per distress duration and at stop.
- The development run skips an unreadable report as a sample and puts `interoception_unreadable_reports` and `interoception_own_error_fallbacks` in its readout once either is non-zero.

A fallback does not fail the poll: the reading is defined, and failing would pause or preserve a healthy entity over a code bug, against the rule that a sensor fault is not distress. It is counted where the operator sees it.

### 2b. What still follows the blend, on purpose

The distress reading is the instrument that watches the substrate, so the component under watch must not compute it. Fatigue, regulation and affect are different: they are the entity's own state, computed from the prediction it actually makes, and filtering them would report a counterfactual entity. So the unmaintained-fatigue gray zone (through the blend's residuals in the unexpected error, and under an absolute threshold breach the blended error itself in the fatigue input, `interoception/module.py` `action_error`), the sustained-extreme-VAD gray zone (affect reads the blended vision and audition errors), and with them the repeat arm of the welfare response, follow the blend and are reported unfiltered. The hard-threshold alert reads the raw thresholds and is unaffected.

### 3. The producer guarantees the field

With feedback on, every `interoception.report` whose `prediction_error` is defined carries a finite `workspace_feedback.own_error` equal to the inner forward model's error for that reading. A test drives the wrapped module through skipped readings, the first defined reading after a skip (the reading right after a skip publishes no error, paper A.5), readings before the head has a scored error, and suspension, and checks the field on every report with a defined error.

### 4. The pinned property

The test that matters: the interoception module is driven twice with the same feature vectors, timestamps, contexts, sequence predictions and suspension, once with feedback off and once with it on, under each arm (`head_only`, `head_gain`, `full`, `matched_random`). The sequence of `welfare_prediction_error` values over the reports is identical between the runs, value for value. When `workspace-content-code` lands, its tests add the content code on to the same comparison.

## Risks

- **A welfare reader added later reads the field directly.** The source-scan test lists the welfare files; a reviewer adds a new one to it. The function's docstring states the rule.
- **The welfare indicator response is on an unmerged branch.** Whichever of the two merges second adopts the function; the task list says so.
- **Thresholds were calibrated on the own-model error.** With feedback off they are the same value, so nothing to recalibrate. That is another reason to read the own error: the thresholds keep their meaning when feedback is turned on.

## Migration and ordering

1. PR 1: the function, the readers, the producer test, the pinned property test, the source-scan test.
2. Before `[workspace.feedback]` is enabled in any entity and before `workspace-content-code`, which checks for this change at boot.

## Welfare and admissibility

- Welfare code: the PR gets the independent second review.
- With the shipped configuration the welfare readings are unchanged, bit for bit, for every report the producer publishes. Only producer defects read differently: a report without the key, or with a non-numeric error, is now an unreadable report (no sample, counted, and a failed welfare-response poll) where main read 0.0 or raised.
- No run is in flight.

## Implementation estimate

One worker PR of about 150 to 300 changed lines, tests included. Half a day elapsed with the second review.
