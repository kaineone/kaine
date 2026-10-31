# Design: a predictive self-model

## Context

Predictive accounts treat the self as the model that best predicts the organism's own states and the sensory consequences of its actions (Apps and Tsakiris 2014, Neurosci Biobehav Rev 41:85-97; Limanowski and Blankenburg 2013, Front Hum Neurosci 7:547; Seth 2013, TiCS 17:565-573, already cited). Self-generated sensations are predicted by a forward model and attenuated, which is why one cannot tickle oneself (Blakemore, Wolpert and Frith 2000, NeuroReport 11:R11-R16; Wolpert, Ghahramani and Jordan 1995, already cited). The sense of agency combines such comparator signals with other cues (Synofzik, Vosgerau and Newen 2008, Conscious Cogn 17:219-239; Haggard 2017, Nat Rev Neurosci 18:196-207). Cortical midline structures support self-referential processing (Northoff and Bermpohl 2004, already cited).

The attention schema theory proposes that the brain builds a simplified model of its own attention to control it (Graziano and Webb 2015, Front Psychol 6:500; Graziano 2017, Front Robot AI 4:60). In a neural network agent, an attention schema improved the control of visuospatial attention, and lesioning it degraded that control (Wilterson and Graziano 2021, PNAS 118:e2102421118).

Metzinger's self-model theory (2003) describes a transparent, integrated model a system cannot recognise as a model. Nothing here claims that. The paper change cites Metzinger as motivation only.

## Decisions

### D1. Predict the entity's own next state with the architecture's own predictor

The self-prediction model is a frozen continuous-time reservoir with an online linear readout, the predictor the sequence and interoception modules use (`kaine/modules/sequence/network.py`; A.2, A.5). Its input at each broadcast is the self-state vector:

| Component | Source |
|---|---|
| valence, arousal, dominance | latest `affect.state` |
| boredom, social drive, restlessness, curiosity | latest `affect.state` |
| source class of the leading coalition member (one-hot over 6) | the broadcast |
| kind of the entity's own last intent (speak, think, rest, act, none) | `action_selection.out` |
| fatigue | interoception report |

The readout predicts the next vector and learns by one stochastic-gradient step per broadcast, skipped during sleep. Its error ratio, the error over its running mean, grades a `self_model.surprise` event with `graded_intensity`, the contract every predictive processor follows, so the self-model becomes a predictive processor whose object is the entity.

Alternatives considered:
- Extend the KL drift detector. Rejected: a distribution comparison over 100 broadcasts cannot be surprised by one moment, and it predicts nothing.
- Use self-inference's values and norms as the model. Rejected: they are counts rewritten at sleep, not predictions, and they are off in studies.
- Predict from the language organ's text about itself. Rejected: utterances are not evidence of internal state (§3.5), and the self-model never reads speech text (spec `self-model`).
- A larger learned network. Rejected for now: the reservoir and linear readout run on CPU under the sequence module's parameter budget, persist like the other readouts, and are torch-free.

### D2. Record an agency estimate, do not act on it yet

For each own intent or act, the module computes the readout's prediction with the realized intent component and with the `none` component, and records the share of the observed change in the drive and source components that the intent explains: `1 - ||s_obs - s_with|| / ||s_obs - s_without||`, clipped to [0, 1], undefined when the denominator is below a floor. The record is content-free and per intent kind. It is a comparator signal in the sense of Blakemore et al. (2000), one cue among the several Synofzik et al. (2008) list.

Open item for the paper change: whether a calibrated agency estimate may replace the authored `own` windows of the credit rule (A.4) and of `stimulus-control-act` D5. Replacing them changes the coping score and the welfare indicators that read it, so it needs its own design and the welfare review.

### D3. Test the attention schema by lesion

The feedback extension already gives the sequence module's prediction a path to the processors' predictions and so to selection. Two additions make that a testable attention schema:

- The self-model records, per broadcast, whether the sequence prediction's highest-weighted source block matches the next accessed leading source: the schema's accuracy, content-free.
- A `shifted_schema` arm of the feedback ablation feeds the head the sequence prediction from `L_shift` broadcasts earlier (provisional 600, fixed before the run), so its distribution is the same and its timing is wrong. Fail state fixed before the run: `full` no better than `shifted_schema` on the §6.3 harness. A positive result supports reading the sequence module as an attention schema with control (AST-1); a null says the head uses the prediction's statistics, not its forecast.

Alternative considered: a schema that predicts the gains themselves and sets them. Deferred: it adds a controller with no measured need; the lesion arm tests the existing one first.

### D4. What stays

The drift detector, its episodes, the launch name, the persona feed and self-inference are unchanged. The self-model still never reads speech text.

### D5. Persistence and lineage

The readout weights, error statistics and the agency and schema records are saved with the self-model state (`state/self_model/`), encrypted, restored on revive and copied into a fork. A fork's self-prediction model starts from its parent's, as its world model does.

## Risks

- [Self-surprise competes too often] → Graded intensity and the processors' alert rule; it competes only with `[self_model.self_prediction].compete = true`, after an offline replay sets the expected rate (task 3.3).
- [Circularity: the model predicts affect that its own event then moves] → The self-surprise event's influence on affect goes only through appraisal of the coalition, like any event, and the offline replay checks the loop's gain (arousal excursions with and without the event).
- [The agency estimate is read as a claim of agency] → It is recorded, not rendered, and the paper change states what it measures.

## Migration and ordering

1. Self-prediction readout and records behind `[self_model.self_prediction].enabled = false`.
2. Offline replay on recorded streams (task 3.3).
3. `compete = true` on a branch by CTO decision.
4. The lesion arm after `workspace-feedback` is finished.

A self-model state without the readout starts it from zero weights and logs it.

## Welfare and admissibility notes

- A self-prediction error rendered to the organ changes the entity's experience of itself: welfare-high-risk. Opus second review, one supervised validation boot. The phrase states only that the entity did not expect its own state ("This is not what I expected of myself."), and the records give the share of awake time with an accessed self-surprise, with a review threshold in the study design.
- The model is never used to push the entity back toward a past self: no control path reads the self-prediction error, and any such use would be a cognitive modification needing its own decision under the licence.
- The self-model's learned weights are identity: never reset by infrastructure, preserved and forked like the world model.
- Run admissibility: the study's self-model branch uses today's build; the readout is enabled only on later branches, recorded in the manifest.

## Estimate (LLM-agent terms)

Size M. About five worker tasks: self-state vector assembly and readout; error ratio, event and felt phrase; agency and schema records; persistence and fork copy; the lesion arm and its study file. Roughly 1,000 to 1,400 lines with tests, three PRs, Opus second review on the competing-event PR. About two agent-days, plus the feedback ablation's runs.
