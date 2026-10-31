## ADDED Requirements

### Requirement: Planning observes the dominant deficit
With `[planning].model_version = 2`, the generative model SHALL include a `deficit` factor and modality with states `none`, `boredom_high`, `social_high` and `restlessness_high`, observed from the latest `affect.state` as the dominant deficit at or above its threshold, else `none`. Its transitions SHALL depend on the action and start from the broad prior of the other perceptual factors. Model version 1 SHALL remain selectable and unchanged.

#### Scenario: Boredom dominates above threshold
- **WHEN** the latest `affect.state` has boredom at or above its threshold and higher than the other deficits
- **THEN** the deficit observation is `boredom_high`

#### Scenario: Version 1
- **WHEN** `[planning].model_version = 1`
- **THEN** the generative model is the current four-factor model with its current preferences

### Requirement: Preferences derive from the homeostatic set point
With model version 2, the salience, affect-quadrant and event-cluster modalities SHALL carry zero preferences, and the deficit modality SHALL carry `C(none) = 0` and `C(d_high) = -kappa * F(theta_d e_d)`, with `F` the valuation drive function. No other preference SHALL be written into the model. The code that sets these preferences SHALL cite the neuroscience basis for the set point at the code site.

#### Scenario: No salience preference
- **WHEN** a version-2 model is built
- **THEN** every entry of the salience modality's preference vector is zero

#### Scenario: Deficit preferences
- **WHEN** a version-2 model is built with the shipped thresholds
- **THEN** `none` has the highest deficit preference and each deficit state's preference equals `-kappa` times the drive function at its threshold

### Requirement: Planning looks more than one step ahead within its bound
With model version 2 the shipped planning horizon SHALL be 3. The planning module SHALL propose the first action of the policy with the lowest expected free energy and SHALL replan at its next step. The complexity envelope, the latency benchmark and the timeout guard SHALL apply to the configured horizon.

#### Scenario: A two-step relief
- **WHEN** the learned transitions make a deficit fall only after one action followed by a different one
- **THEN** a horizon-3 planner proposes the first of those actions and a horizon-1 planner does not prefer it

### Requirement: Large action spaces use pruned sophisticated inference
When the number of actions times the horizon would make enumeration exceed the complexity envelope, the planning module SHALL evaluate policies by sophisticated inference, expanding no outcome whose predictive probability is below `p_min` and no action whose expected free energy exceeds its best sibling's by more than `Delta_G`, and SHALL report the number of pruned branches with its policy event.

#### Scenario: Pruning reported
- **WHEN** a planning step prunes branches
- **THEN** the `planning.policy` event carries the count of pruned branches

### Requirement: Imagined transitions train the planning model at reduced weight
When the world model's transition is action-conditioned and imagination is enabled, the planning module SHALL, during sleep's scenario window, add each imagined transition decoded into its factor states to its transition counts with weight `w_im` below one, under the existing concentration cap. Lived transitions SHALL keep weight one, and no imagined rollout SHALL cross a sleep.

#### Scenario: Imagined evidence counts less
- **WHEN** one imagined and one lived transition of the same states and action are added
- **THEN** the lived transition adds one to the counts and the imagined one adds `w_im`

#### Scenario: Contradicting lived experience wins
- **WHEN** lived transitions contradict an imagined pattern
- **THEN** the learned transition belief follows the lived pattern within the number of steps fixed in the test

### Requirement: The deficit factor does not learn across a sleep reset
When the interval between two planning steps contains a sleep onset or a sleep reset, the planning module SHALL update the transitions of every factor except `deficit`.

#### Scenario: A requested rest
- **WHEN** the planning module's rest proposal is realized and the following sleep resets the deficits
- **THEN** the deficit factor's transition counts are unchanged by that step

### Requirement: The benchmark tests a multi-step deficit task
The active-inference benchmark SHALL include a deficit-relief task that requires two different actions in sequence, with the tabular Q-learning baseline matched on observations and reward, and a horizon ablation comparing horizon 1 with horizon 3 against a minimum effect fixed before the run.

#### Scenario: The ablation runs offline
- **WHEN** the offline suite runs the benchmark
- **THEN** it reports a verdict for horizon 3 against horizon 1 on the deficit-relief task and boots no entity
