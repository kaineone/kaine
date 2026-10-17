## ADDED Requirements

### Requirement: Workspace feedback ships off and is identical to the current build when off
The `[workspace.feedback]` table SHALL have `enabled = false` in the shipped configuration. When `enabled` is false or `arm` is `"off"`, no feedback object SHALL be built, the workspace SHALL attach no feedback metadata, the processors SHALL wrap no forward model and add no payload key, and the sequence module SHALL publish no prediction, so every published event and broadcast is identical to the current build. `arm` SHALL be one of `off`, `head_only`, `head_gain`, `full`, `matched_random`; any other value or unknown key SHALL be a configuration error. Feedback SHALL refuse to start with the coherence layer on, with a workspace arm other than `competitive`, or with the positive control of A.8 enabled.

#### Scenario: Shipped configuration builds no feedback
- **WHEN** the shipped configuration is loaded
- **THEN** `[workspace.feedback].enabled` is false and the boot builds no feedback controller

#### Scenario: Off is bit for bit the current build
- **WHEN** the same inputs and broadcasts drive a processor and the workspace once with feedback absent and once with `enabled = true` and `arm = "off"`
- **THEN** the published payloads, intensities and snapshots are identical

#### Scenario: Unknown arm is refused
- **WHEN** `arm = "fullest"`
- **THEN** loading the feedback settings raises a configuration error

### Requirement: Top-down head and precision-weighted blend
In every arm other than `off`, vision, audition's acoustic path and interoception SHALL each hold a linear top-down head mapping the context `b`, the adopted sequence prediction (zeros when none) and a constant to a prediction of the next input. The head SHALL start at zero and take one stochastic-gradient step on the mean squared error per input at `head_learning_rate`, skipped while the forward model is suspended. The processor's prediction SHALL be the blend of its own and the top-down prediction, each weighted by the inverse square of its running mean error over the last `W_P` scored errors; before the head has a scored error, or when the own mean error is zero, the blend SHALL be the own prediction. The reported error, error ratio, intensity, and for interoception the residuals, SHALL be the blend's. The null-context error SHALL be that of the blend formed with the null context in both predictions and the same weights. A skipped non-finite input SHALL clear the blend, so nothing is scored or learned across it.

#### Scenario: Blend weights follow inverse squared mean errors
- **WHEN** the own mean error is 1.0 and the head's mean error is 2.0
- **THEN** the blend is 0.8 times the own prediction plus 0.2 times the top-down prediction

#### Scenario: A head without history leaves the own prediction
- **WHEN** the head has no scored error yet
- **THEN** the blend equals the own prediction and the reported error equals the own error

#### Scenario: The head learns online
- **WHEN** a constant input repeats with a constant context while the processor is awake
- **THEN** the head's error falls, and while suspended its weights do not change

### Requirement: Gain on the standardized error with mean one
In arms `head_gain`, `full` and `matched_random`, each processor's graded intensity SHALL use `pi_j` times its error ratio, with `pi_j` the gain carried by the latest accessed broadcast (one before any). The workspace SHALL keep `pi_j` in `[pi_min, pi_max]` with the mean over vision, audition and interoception at one, SHALL move gain only in equal and opposite steps clipped so both processors stay in bounds, and SHALL relax every gain toward one with time constant `gain_relax_s` in entity time. Categorical alert criteria and the published error ratio SHALL be unchanged by the gain.

#### Scenario: Gains stay bounded with mean one
- **WHEN** many episodes move gain toward one processor
- **THEN** its gain never exceeds `pi_max`, no gain falls below `pi_min`, and the mean stays one

#### Scenario: Gains relax to neutral
- **WHEN** no episode occurs for many relaxation time constants
- **THEN** every gain returns to one

### Requirement: Conflict detection and resolution
In arm `full`, a processor SHALL be in conflict when its highest-scoring accessed report carries a disagreement of at least `disagreement_threshold` and an error ratio of at least `conflict_error_ratio` and it is not refractory. Resolution SHALL move `gain_step` toward the other accessed processor with the lowest precision-weighted error `pi_l` times its ratio and away from the conflicting one; with no other accessed processor no gain SHALL move. Each episode SHALL make the conflicting processor refractory for `refractory_s`. In arm `matched_random` the same episodes SHALL move the same step between two distinct processors drawn by a generator seeded from the run seed. In arm `head_gain`, each accessed broadcast with at least two accessed processors SHALL move `gain_step` toward the lowest and away from the highest precision-weighted error, the loser then refractory. No gain SHALL move and no feedback metadata SHALL be attached on an inhibited broadcast, and the processors SHALL adopt nothing from one.

#### Scenario: A conflict shifts gain toward the better-supported processor
- **WHEN** an accessed vision report has disagreement 3.0 and error ratio 2.5, and an accessed audition report has error ratio 0.5
- **THEN** audition's gain rises by `gain_step` and vision's falls by `gain_step`

#### Scenario: Refractory interval blocks a second episode
- **WHEN** vision conflicts again before `refractory_s` has passed
- **THEN** no gain moves

#### Scenario: Inhibited broadcasts carry no feedback
- **WHEN** a broadcast is inhibited
- **THEN** its metadata has no feedback entry and the gains move only by relaxation

#### Scenario: Matched random is reproducible
- **WHEN** two controllers with the same seed see the same broadcasts
- **THEN** they make the same random choices

### Requirement: Ablation arms are selectable by study
Five study files `config/studies/workspace_feedback_off.toml`, `workspace_feedback_head_only.toml`, `workspace_feedback_head_gain.toml`, `workspace_feedback_full.toml` and `workspace_feedback_matched_random.toml` SHALL set `[workspace.feedback]` and nothing outside the tables a study may set, and the workspace-mediation study files SHALL be unchanged.

#### Scenario: A study selects its arm
- **WHEN** the configuration is loaded with `study = "workspace_feedback_full"`
- **THEN** `[workspace.feedback]` has `enabled = true` and `arm = "full"`
