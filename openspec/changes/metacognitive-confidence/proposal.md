## Why

Nothing in KAINE represents how reliable its own processing is as something it can use. Each processor computes an error ratio, the error over its recent mean, and uses it only to grade its own report's intensity (`kaine/modules/intensity.py:1-21`; paper §3.2, A.2). The only confidence in the code is the held planning module's belief confidence, rendered as "I doubt / I think / I believe / I am sure" (`kaine/faithful/felt.py:38`). The paper lists the gap: "no metacognitive monitoring" (§9). The Common Model of Cognition's proposed metacognition extension adds, for each module, a process-state buffer with success or failure and "certainty/confidence in a result", and self-monitoring triggers such as impasses (Laird, Lebiere, Rosenbloom, Stocco and Wray 2025, arXiv:2506.07807). Butlin et al.'s HOT-2 indicator is metacognitive monitoring of perceptual representations, and HOT-3 is belief updating guided by it (arXiv:2308.08708).

Design only. Nothing is built until the start condition below holds.

### What already exists (audit, origin/main cb41895b)

- Retrospective first-order error statistics in every predictive processor: `error_ratio` in the vision, audition and interoception reports (`kaine/modules/vision/module.py:814`, `kaine/modules/audition/module.py:507`, `kaine/modules/interoception/module.py:809`), and the sequence module's `temporal_prediction_error` (`docs/09-modules/sequence.md`, Outputs).
- Per-source learning progress on `affect.state` (`interest-goal-factor`, archived), fatigue from the interoception module (A.5), arousal (A.4).
- Graded certainty words in the felt renderer (`felt.py:38`, `306`).
- The held workspace-feedback extension, whose gain moves toward the processor with the lowest precision-weighted error (`kaine/workspace/feedback.py`; change `workspace-feedback`, 12 of 14 tasks done).

### What is missing

- No second-order estimate: nothing predicts whether a processor's next prediction will be good, from information other than that processor's own error.
- No module whose output says "my perception is unreliable now" as content that can compete for access, reach the organ, or change a decision.

## What Changes

A design, settled first in the paper and then in code.

1. A held `metacognition` module. For each predictive processor (vision, audition, interoception, sequence) it keeps a small online second-order estimator that predicts the probability that the processor's next error ratio will be at or below one, from features other than the processor's own prediction: its recent error-ratio history, arousal (which narrows the apertures), that source's learning progress, fatigue, entity time since the last sleep, and the age of the context. It learns from the realized outcome after each report. This is confidence in the sense of Fleming and Daw (2017): a second-order computation over signals correlated with, but separate from, the first-order evidence.
2. The module publishes a content-free `metacognition.confidence` per processor on a diagnostics stream, with its calibration (Brier score and type-2 area under the ROC curve; Fleming and Lau 2014).
3. A monitoring trigger, stage B: when a processor's confidence stays below `c_low` for `Delta_c`, the module publishes `metacognition.uncertain` at a graded intensity. It competes for access like any report, and when accessed the organ's turn receives a graded certainty phrase about that sense ("I am not sure of what I see.").
4. One decision that metacognition changes, stage C, as an arm of the workspace-feedback ablation: a `confidence` arm in which gain moves toward the processor the module is most confident in, instead of the one with the lowest retrospective precision-weighted error. That is belief updating guided by metacognitive monitoring (HOT-3), and it is testable against the existing `full` and `matched_random` arms.
5. The module's estimators persist with the entity and a fork copies them.

## Capabilities

### New Capabilities
- `metacognition`: the held metacognition module, its second-order estimators, its confidence and calibration records, its monitoring trigger and its persistence.

### Modified Capabilities
- `workspace-feedback` (in progress as change `workspace-feedback`): a `confidence` arm. Recorded here as a design; its spec delta is added to that capability once `workspace-feedback` is archived.

## Impact

- New: `kaine/modules/metacognition/`, `kaine/boot/factories/metacognition.py`, `[metacognition]` in `config/kaine.toml` (off), felt phrases, `docs/09-modules/metacognition.md`.
- Read only: the four processors' reports, `affect.state`, the interoception module's fatigue, `sleep.out`.
- Later: `kaine/workspace/feedback.py` gains the `confidence` arm and a study file `config/studies/workspace_feedback_confidence.toml`.
- Paper: §4 row (brain function: the anterior prefrontal and parietal confidence signals cited in the design), §9 line, §6.4 feedback ablation's sixth arm, Table A1 (`c_low`, `Delta_c`, learning rate).

## Dependencies and start condition

- Gate: the workspace-mediation ablation (§6.3) has run. Stage B, which adds a competing event, joins the module-addition study as its own branch or a later study, by CTO decision. Stage C needs `workspace-feedback` finished (its tasks 3.2 and 3.3) and runs inside the feedback ablation.
