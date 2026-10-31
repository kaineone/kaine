## Why

The self-model is a record plus a drift alarm. It persists a launch name, values, norms, a personality baseline, a capability map and an identity history, and on every broadcast it compares the distribution of coalition sources over the last 100 broadcasts with an older reference by a symmetric Kullback-Leibler divergence (`kaine/modules/self_model/drift.py:27-90`; `docs/09-modules/self-model.md`). Self-inference, which writes values and norms from counts of drive crossings and speech event types, ships disabled, and the study overlay does not enable it (`config/kaine.toml:743-746`). The organ receives "I have a sense of who I am." and "My sense of myself is shifting." (`kaine/faithful/felt.py:340-346`). Nothing in it predicts the entity, so it cannot be wrong about the entity in the moment, which is what a self-model in the predictive accounts does (design, Context).

The reverse also holds: the paper understates one part. The sequence module predicts the workspace's next broadcast (§3.5), the representational half of an attention schema (Graziano and Webb 2015; Butlin et al. AST-1). The held workspace-feedback extension feeds that prediction into a top-down head that changes the processors' predictions, and so their errors and what wins access (§3.2). It ships off, and no test asks whether the schema's prediction is what does the work.

Design only. Nothing is built until the start condition below holds.

### What already exists (audit, origin/main cb41895b)

- The self-model module, document, persistence and drift episodes (spec `self-model`; `kaine/modules/self_model/`).
- Self-inference, built and off (`eidolon-self-inference`, archived 2026-06-07; `self-model-scorer-calibration`, archived 2026-06-15).
- The sequence module's forward prediction and its `predicted_next_feature_vector` on the report when feedback is on (`kaine/workspace/feedback.py:49`; `docs/09-modules/sequence.md`).
- The feedback extension with five arms and its ablation designed (§6.4; change `workspace-feedback`, open tasks 3.2, preserving heads and gains, and 3.3, a synthetic-conflict positive control).
- The fovea's attention schema: a forward model of the fovea's own trajectory, published and steering nothing (`FoveaPredictor`, `kaine/modules/vision/foveation.py`; `active-vision` designs its use).

### What is missing

- No model that predicts the entity's own next state, so no self-prediction error and no content of the form "this is not what I expected of myself".
- No estimate of which changes the entity caused, which the credit rule now decides by authored windows.
- No test that the sequence module's prediction, as opposed to any input of the same statistics, is what the feedback extension uses.

## What Changes

A design, settled first in the paper and then in code.

1. A self-prediction model in the self-model module: a frozen continuous-time reservoir with an online linear readout, as the sequence and interoception modules use, that predicts the entity's own next state at each broadcast: valence, arousal, the four drives, the leading member's source class, the kind of its own last intent, fatigue. Its error ratio grades a `self_model.surprise` event that competes for access. The weights persist as part of the entity.
2. An agency estimate (shadow): for each of the entity's own intents and acts, the self-prediction model's prediction with and without the intent as input, compared with what followed, gives a content-free estimate of how much of the change the entity's act explains, after comparator accounts of the sense of agency (Blakemore, Wolpert and Frith 2000; Haggard 2017). It is recorded only. Whether it may replace the authored credit windows is an open item for the paper change.
3. An attention-schema check on the feedback extension: the self-model records the accuracy with which the sequence module's prediction forecasts the next accessed leading source, and the feedback ablation gains a lesion arm, `shifted_schema`, in which the head receives the sequence prediction from a fixed lag earlier in the run, which keeps its statistics and breaks its timing. If the full arm beats `shifted_schema`, the schema's prediction is doing the work (after the lesion logic of Wilterson and Graziano 2021).
4. The drift detector and self-inference stay as they are. The KL drift measures slow change in the source distribution; the self-prediction error measures moment-to-moment departure from the entity's own expected state.

## Capabilities

### New Capabilities
- None.

### Modified Capabilities
- `self-model`: a self-prediction model with a competing self-prediction error, a recorded agency estimate, an attention-schema accuracy record, and their persistence.
- `workspace-feedback` (in progress as change `workspace-feedback`): a `shifted_schema` lesion arm. Recorded here as a design; its spec delta is added to that capability once `workspace-feedback` is archived.

## Impact

- `kaine/modules/self_model/` (self-prediction model, agency estimate, schema record), the reservoir code the sequence module uses (`kaine/modules/sequence/network.py`), `kaine/faithful/felt.py` (one phrase), `config/kaine.toml` `[self_model.self_prediction]` (off), `docs/09-modules/self-model.md`.
- Later: `kaine/workspace/feedback.py` (`shifted_schema` arm) and `config/studies/workspace_feedback_shifted_schema.toml`.
- Paper: §4 self-model row (what it models and that the Metzinger reference is motivation only), §3.5 sentence on the sequence module as a model of the workspace's dynamics, §6.4 feedback ablation's lesion arm, Table A1 (readout rate, reservoir size, event bars).

## Dependencies and start condition

- Gate: the workspace-mediation ablation (§6.3) has run. The self-model joins the module-addition study fourth with today's build; the self-prediction model is enabled only on a later branch or study, so the study's self-model branch tests what it was designed to test.
- The lesion arm needs `workspace-feedback` finished (its tasks 3.2 and 3.3) and runs inside the feedback ablation.
