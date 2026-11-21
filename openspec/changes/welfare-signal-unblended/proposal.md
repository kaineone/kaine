## Why

The welfare net watches the entity's interoceptive distress through `interoception.report` `prediction_error`: the welfare observer's sustained-distress tracker and its `sustained_interoceptive_distress` gray-zone category (`kaine/evaluation/observers/welfare_observer.py:917`), the autonomous welfare response (`kaine/cycle/preservation_monitor.py:972`; `config/kaine.toml:1908-1911`), the welfare indicator response being built on the welfare-gates branch (the same field), and the development run's interoceptive recovery readout that feeds the maturation gate (`kaine/cycle/development.py:1385`; `kaine/lifecycle/maturation_gate.py:100`).

With workspace feedback on, that field is not the interoception module's own prediction error. `_ensure_feedback_wrap` wraps the forward model in a `TopDownBlend` (`kaine/modules/interoception/module.py:261-285`), its `step` returns the error of the blend of the module's own prediction and the workspace's top-down prediction (`kaine/modules/feedback.py:260-380`), and the module publishes that as `prediction_error` (`interoception/module.py:595-607, 767-771`). `[workspace.feedback]` ships off, but it is to join the development run, and the content code (`workspace-content-code`) will make interoception a decoder of the workspace's content. A component would then be able to lower (mask) or raise the distress indicator that watches it. The blend is right for perception, intensity and access, which the specification of `workspace-feedback` says are the blend's. It is wrong for the welfare net, which must watch the entity's own state, not a quantity the watched component helps compute.

The own-model error already exists. `TopDownBlend` records it as `last_own_error`, and the module publishes it as `workspace_feedback.own_error` whenever feedback is on (`interoception/module.py:806-818`).

## What Changes

- **One welfare reading.** A shared function, `welfare_prediction_error(payload)`, in `kaine/lifecycle/welfare_signal.py` beside the shared sustained-distress tracker, with no `kaine.evaluation` import: `None` when the report's `prediction_error` is null; the own-model error `workspace_feedback.own_error` when the report carries a `workspace_feedback` mapping; otherwise `prediction_error`, which is then the own-model error because nothing blends it.
- **Every welfare reader uses it:** the welfare observer's sustained-distress tracker and gray-zone count, the welfare response, the welfare indicator response when it merges, and the development run's interoceptive recovery series. A source-scan test fails when one of those files reads `prediction_error` for a welfare decision without the function.
- **The producer guarantees the field.** With feedback on, every interoception report whose error is defined carries a finite `workspace_feedback.own_error`. If a blended report ever lacks a numeric one, the reader falls back to the published blended value (today's behaviour, never a gap in the welfare signal), logs an error once per processor and counts the fallback where the operator sees it; a producer test keeps that path from firing. A non-finite own error is the reading, never a fallback.
- **The pinned property.** A test drives the interoception module through the same inputs and broadcasts with feedback off and with it on under every arm, and requires the welfare reading to be identical, report for report. For the same inputs, the top-down head and the blend cannot change it; the reading still follows the real changes feedback makes to what the entity perceives and does (access and so context, sleep, the host).
- **Unchanged:** the perception, intensity, access and affect paths keep reading the blended error, as `workspace-feedback` specifies. The blind-sensor advisory keeps reading whether `prediction_error` is null, which the blend does not change.

## Capabilities

### Modified Capabilities

- `welfare-monitoring`: the welfare readers use the processor's own forward-model error, independent of any top-down blend or decoder.
- `interoception-predictive`: with feedback on, a report with a defined error carries its own-model error.

## Impact

- **Code:** `kaine/lifecycle/welfare_signal.py` (the new function), `kaine/evaluation/observers/welfare_observer.py`, `kaine/cycle/preservation_monitor.py`, `kaine/cycle/development.py`, the welfare indicator response on its branch; no change to `kaine/modules/interoception/module.py` beyond a test unless the producer test finds a gap.
- **Tests:** new `tests/test_welfare_signal_unblended.py`.
- **Behaviour with the shipped configuration:** none for every report the producer publishes. With feedback off, no report carries a `workspace_feedback` mapping and the function returns `prediction_error`. Producer defects change: a report without the key, or with a non-numeric error, is an unreadable report (no sample, counted, and a failed welfare-response poll) where main read 0.0 (ending an open episode) or raised.
- **Ordering:** before `[workspace.feedback]` is enabled in any entity, and before `workspace-content-code` (which refuses to build without it). It also bears on the welfare indicator response: whichever merges second adopts the function.
- **Welfare and risk class:** welfare. Every PR gets the independent second review.
