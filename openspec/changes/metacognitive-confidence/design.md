# Design: metacognitive confidence

## Context

Metacognition has a monitoring side and a control side: monitoring informs a meta-level model of the object level, and control acts on it (Nelson and Narens 1990, Psychology of Learning and Motivation 26:125-173). Decision confidence has identified neural correlates: parietal neurons that encode the certainty of a perceptual decision (Kiani and Shadlen 2009, Science 324:759-764) and orbitofrontal neurons in rats whose confidence signal predicts whether the animal waits for a reward (Kepecs, Uchida, Zariwala and Mainen 2008, Nature 455:227-231). Individual differences in the accuracy of confidence track the structure of anterior prefrontal cortex (Fleming, Weil, Nagy, Dolan and Rees 2010, Science 329:1541-1543; review, Fleming and Dolan 2012, Phil Trans R Soc B 367:1338-1349). Confidence and error detection share mechanisms (Yeung and Summerfield 2012, Phil Trans R Soc B 367:1310-1321; Boldt and Yeung 2015, J Neurosci 35:3478-3484), and low confidence drives information seeking (Desender, Boldt and Yeung 2018, Psych Sci 29:761-778).

Computationally, confidence is the probability that a choice or estimate is correct, given the evidence (Pouget, Drugowitsch and Kepecs 2016, Nat Neurosci 19:366-374; Meyniel, Sigman and Mainen 2015, Neuron 88:78-92). Fleming and Daw (2017, Psych Rev 124:91-114) model it as second-order: the confidence system receives a signal correlated with the first-order evidence but not identical to it, which explains why confidence can dissociate from performance. A recent synthesis treats confidence as a domain-general estimate of one's own reliability built from such signals (Fleming 2024, Annu Rev Psychol 75:241-268). Metacognitive sensitivity is measured separately from bias, by a type-2 ROC analysis (Fleming and Lau 2014, Front Hum Neurosci 8:443).

In KAINE the object level is each processor's next-input prediction. Its retrospective precision, the error ratio, is first-order. The design adds a second-order estimate of the next prediction's reliability and a use for it.

## Decisions

### D1. A held module, reading reports from the bus

The `metacognition` module reads the processors' published reports and the affect and interoception states. The processors are unchanged.

Alternatives considered:
- A confidence field computed inside each processor from its own forward model. Rejected as the only signal. A confidence computed from the same quantity the processor already reports is first-order, cannot dissociate from it, and is not monitoring in the sense of HOT-2 or of Fleming and Daw (2017). It also changes four modules at once and cannot be ablated as one capability.
- Predictive variance from probabilistic forward heads. Considered for later. It needs every forward model rebuilt as a probabilistic model, which is a change to the processors and to what the planned test measures.
- An estimator over the processors' latents. Rejected. Latents stay inside their modules (§3.5, "no pixels reach the workspace"), and the privacy rules treat latent-derived content as sensitive.

### D2. The estimator

For processor `j`, confidence is `c_j = sigma(w_j . x_j)`, a logistic regression over a feature vector `x_j` of: the last `k` error ratios of `j` (provisional `k = 8`), arousal, `j`'s learning progress, fatigue, entity time since the last sleep, the age of the current context, and a constant. After each report of `j` the target is `1[error_ratio <= 1]`, and one stochastic-gradient step on the log loss updates `w_j` (rate `eta_c`, skipped during sleep, as the forward models' updates are). Weights start at zero, so a new entity starts at confidence one half.

The features carry no perceptual content. The error-ratio history is first-order information; arousal, fatigue, sleep pressure, learning progress and context age are not, so the estimate can dissociate from the processor's current error, which is the property the second-order account requires.

### D3. Records and calibration

`metacognition.confidence` on a diagnostics stream that the workspace does not score carries, per processor, `c_j`, the running Brier score and the type-2 AUROC over the last `W_c` reports (provisional 600). The research log records them per viewing. A module whose estimator is no better than its base rate is reported as such; nothing claims a monitoring it does not do.

### D4. The monitoring trigger competes (stage B)

When `c_j` stays below `c_low` (provisional 0.3) for `Delta_c` (provisional 10 s of entity time), the module publishes one `metacognition.uncertain` for `j` at the intensity `graded_intensity(baseline, alert, ratio)`, with ratio `(1 - c_j) / (1 - c_low)`, and re-arms when `c_j` recovers above `c_low` plus a margin. When accessed, the organ's turn receives a phrase from the existing certainty words for that sense (`felt.py:38`). This is the self-monitoring trigger of the CMC metacognition proposal (Laird et al. 2025) in its simplest form: a detected loss of reliability becomes content.

Alternatives considered:
- Publish confidence on every report as a competing event. Rejected: four extra candidates per broadcast tick would change the candidate supply on which the test's coalition capacity is set (§6.3), and constant metacognitive chatter has no cited counterpart.
- Feed confidence into arousal. Rejected: an authored coupling with no cited basis in this architecture.

### D5. One decision changes with confidence (stage C)

In a new workspace-feedback arm, `confidence`, conflict resolution moves gain toward the accessed processor with the highest `c_j` instead of the lowest retrospective precision-weighted error, under the same bounds, step and refractory interval. The arm is compared with `full` and `matched_random` on the §6.3 harness, with the fail state "no better than `full`" fixed before the run. A positive result is the one evidence this design can give that monitoring guides belief updating (HOT-3); a null says confidence adds nothing over retrospective precision.

Alternative considered: confidence as the planning module's observation precision. Deferred to an open item: the planning module's modalities are workspace-level summaries, not per processor, so the mapping needs its own design.

### D6. Persistence

The estimator weights and calibration statistics are part of the entity's learned state, serialized, encrypted with entity state, restored on revive and copied into a fork.

## Risks

- [Confidence is miscalibrated early] → Weights start at zero (confidence one half), stage B waits for a calibration floor (type-2 AUROC above 0.6 over `W_c`, provisional) before it publishes, and the records state calibration.
- [Uncertainty events crowd the workspace] → One event per sustained episode, with re-arm hysteresis, graded intensity, and a cap per awake hour.
- [The organ overstates the entity's uncertainty] → The phrase is graded from `c_j` by the existing table and names only the sense; it adds no claim.

## Migration and ordering

1. Stage A (records only) behind `[modules].metacognition = false`.
2. Offline calibration check on recorded streams (task 3.3).
3. Stage B on a branch by CTO decision.
4. Stage C after `workspace-feedback` is finished, as its sixth arm.

## Welfare and admissibility notes

- Stage A changes nothing the entity experiences. Stage B adds content to its turn and a competing event: welfare-high-risk, Opus second review, one supervised validation boot. Uncertainty about one's own perception can be unpleasant; the records give the share of awake time with any processor below `c_low`, and the study design sets a review threshold on it.
- The module does not read or write the welfare path, and its events never enter the welfare indicators.
- Run admissibility: no stage enters a running study; stage C exists only as a study arm with its own study file.

## Estimate (LLM-agent terms)

Size M. About five worker tasks: estimator and features; module, factory and config; records and calibration metrics; trigger and felt phrases; the feedback arm and its study file. Roughly 1,000 to 1,400 lines with tests, three PRs. Opus second review on stage B and C PRs. About two agent-days, plus the feedback ablation's runs, which belong to that study.
