## ADDED Requirements

### Requirement: The content code ships off and is identical to absent when off
The `[workspace.feedback.content]` table SHALL have `enabled = false` in the shipped configuration. When it is false, no encoder SHALL be built, no head SHALL have code columns, audition SHALL publish no acoustic latent, and no payload SHALL gain a key. An unknown key or value in the table, or `shift_s` below 60, SHALL be a configuration error.

#### Scenario: Off matches the pre-change build
- **WHEN** a fixed entity-free run is driven with the table absent and with `enabled = false`, under each feedback arm
- **THEN** every published payload, intensity, broadcast selection and snapshot equals the golden trace recorded on the commit before the change

#### Scenario: Unknown source is refused
- **WHEN** `sources = ["vision", "affect"]`
- **THEN** loading the settings raises a configuration error naming `affect`

### Requirement: The content code needs both opt-in layers
The content code SHALL be built only when `enabled = true` and `KAINE_CONTENT_CODE_OPERATOR_APPROVED=1`. With the first and not the second it SHALL stay off, the boot SHALL print why, and the research gate SHALL record `content_code: not_approved`. With the table absent, the research gate record SHALL be unchanged.

#### Scenario: Config on, operator variable missing
- **WHEN** `enabled = true` and the operator variable is unset
- **THEN** no content code is built and the research gate records `content_code: not_approved`

### Requirement: The content code refuses to start without its preconditions
With both opt-in layers set, the boot SHALL refuse, naming the reason, when workspace feedback is off or its arm is `off`, when `LATENT_RULE_VERSION` is missing or below 1, when state encryption is not in effect or `require_encryption` is not true, when the welfare readers do not use the unblended own-model error, or when the latent bus check of `latent-content-privacy` fails.

#### Scenario: The latent rule is missing
- **WHEN** the content code is opted in and the privacy filter has no `LATENT_RULE_VERSION`
- **THEN** the boot refuses and names the missing rule

#### Scenario: Encryption is off
- **WHEN** the content code is opted in and state encryption is disabled
- **THEN** the boot refuses and names state encryption

#### Scenario: Feedback off
- **WHEN** `enabled = true`, the operator variable is set and `[workspace.feedback].arm = "off"`
- **THEN** the boot refuses and names the feedback arm

#### Scenario: Every precondition holds
- **WHEN** `enabled = true`, the operator variable is set and every precondition holds
- **THEN** the content code is built

### Requirement: The content code reads mean-pooled vision latents
Under the ruling on this change's open question 1 (option b, 2026-11-01), the content code SHALL refuse to build unless `[vision].pooling = "mean"`, so the code never reads the vision encoder's text-aligned attention-pooled vector.

#### Scenario: Attention pooling
- **WHEN** the content code is opted in with `[vision].pooling = "attention"`
- **THEN** the boot refuses and names the pooling

### Requirement: Source slots are written only by accessed members
The workspace SHALL keep one slot per configured source holding the latent, graded intensity and entity time of that source's most recently accessed report. A slot SHALL be written only from an accessed member of an accessed broadcast, by the highest-scoring accessed report of that source. It SHALL be cleared when its age exceeds five times `slot_decay_s`, when that source's blind-sensor or sensor-silent advisory is raised, and at sleep onset.

#### Scenario: An inhibited broadcast writes nothing
- **WHEN** a broadcast holding a vision report is inhibited
- **THEN** the vision slot is unchanged

#### Scenario: An old slot is cleared
- **WHEN** the audition slot was written 11 entity seconds ago and `slot_decay_s = 2.0`
- **THEN** the next code is formed without audition

### Requirement: Each source's latent is standardised before its encoder
The workspace SHALL standardise each source's latent per dimension with a running mean and variance, updated on every slot write at rate one over the count for the first `standardise_warmup` inputs and at `standardise_rate` after that. The standardiser SHALL be a learned parameter of the content code, persisted with its encoder.

#### Scenario: Sources on different scales
- **WHEN** the vision latent has a norm of 20 and the acoustic latent a norm of 1, after warm-up
- **THEN** both standardised inputs have per-dimension variance near one

### Requirement: The code is formed on accessed broadcasts, intensity-weighted and age-decayed without cross-slot normalisation
On each accessed broadcast the workspace SHALL form `z_k = tanh(Σ α_s (W_s x̃_s + c_s))` over the present slots, with `α_s` the slot's intensity times `exp(−age_s / slot_decay_s)` and no division by the other slots' weights. With no slot present the code SHALL be the zero vector. The code SHALL be held until the next accessed broadcast.

#### Scenario: Weights follow intensity and age
- **WHEN** the vision slot is fresh with intensity 0.6 and the audition slot is 2 entity seconds old with intensity 0.2, and `slot_decay_s = 2.0`
- **THEN** the vision term enters with weight 0.6 and the audition term with weight `0.2 · e^{−1}`

#### Scenario: An expiring slot does not move the others
- **WHEN** a slot whose weight is below 0.01 is cleared
- **THEN** the next code differs from the code formed with that slot by less than 0.01 in every component

#### Scenario: No source present
- **WHEN** an accessed broadcast is formed and no slot is present
- **THEN** the code is the zero vector

### Requirement: The code rides the accessed broadcast under the latent tag
The workspace SHALL attach the code to each accessed broadcast under `workspace_feedback.latent_derived.code`, on the broadcast's volatile companion entry (`latent-content-privacy` bus ruling, option B), and SHALL attach none to an inhibited broadcast. Processors SHALL adopt a code only from an accessed broadcast and SHALL keep its tick index with the prediction it forms.

#### Scenario: The code is tagged
- **WHEN** an accessed broadcast is published with the content code on
- **THEN** the code sits inside a `latent_derived` mapping and nowhere else

### Requirement: The novelty fingerprint excludes latent-derived values
The workspace's novelty fingerprint SHALL exclude the `latent_derived` key at any depth of the payload. Audition's content-on acoustic latent SHALL be published inside its `latent_derived` mapping. With the code on and every code column zero, the novelty and salience scores of identical inputs SHALL equal the code-off scores.

#### Scenario: Same inputs, code on with zero columns
- **WHEN** the same events are scored with the content code off and with it on before any code column has learned
- **THEN** every novelty and salience score is identical

### Requirement: Heads read the code and start continuous
With the content code on, each processor's top-down head SHALL use the regressor `(b, s, z, 1)` with `z` the adopted code (zeros before the first). A head restored without code columns SHALL be widened with zero code columns. Every column SHALL learn by the existing SGD step on the processor's own error. The blend with the processor's own prediction SHALL be unchanged.

#### Scenario: Switch-on continuity
- **WHEN** the content code is enabled for a processor whose head has learned weights for `(b, s, 1)`
- **THEN** the head is widened, and its first descending prediction equals the prediction it makes without the code

### Requirement: Code columns live with the encoders and survive switching off
With the content code off, no head SHALL hold code columns. At switch-off each head's code columns SHALL be kept in the content-code checkpoint, and at switch-on they SHALL be spliced back into the head.

#### Scenario: Off, on, off, on
- **WHEN** a trained content code is switched off, on, off and on again
- **THEN** the heads resume with the same code columns and the encoders are unchanged, and each off-state module snapshot equals the snapshot with the table absent

### Requirement: Heads persist in every arm
Each processor SHALL serialize its top-down head's base weights (context, sequence and constant columns) and running error windows with its forward model and restore them, in every feedback arm. A head whose recorded context width or input dimension differs from the running one SHALL be discarded with a warning naming the mismatch and SHALL start at zero. Gains SHALL NOT be persisted.

#### Scenario: A head survives a restart
- **WHEN** a processor with a trained head is serialized and restored into the same configuration
- **THEN** the restored head makes the same prediction for the same regressor

### Requirement: Ascending errors are defined at formation
A processor that scored a prediction formed with a code SHALL publish, under `latent_derived.ascending_error`, `g_j = (2 / (n_j m_j)) W_{j,z}ᵀ (ŷ_top − y)`, clipped to `ascending_clip`, with the code's `code_tick`. `m_j` SHALL be the running mean of the head's per-dimension mean squared error over `W_P`, `W_{j,z}` the code columns before that step's update, and the code the one stored when the prediction was formed. It SHALL publish on every scoring tick.

#### Scenario: The gradient is exact
- **WHEN** an ascending error is compared with a finite-difference gradient of the normalised head loss at the formation code and pre-update weights
- **THEN** they agree to within 1e-6 relative

### Requirement: Ascending errors train the encoders, guarded
The workspace SHALL keep the last `pending_codes` codes with their inputs, SHALL average the ascending errors for each held code per processor, and SHALL take one encoder step per code and processor scaled by each source's `α_s`. A non-finite step SHALL be skipped and counted, and each encoder row SHALL be rescaled to at most `encoder_max_norm`. An error for a code no longer held SHALL be dropped and counted.

#### Scenario: A held code is credited
- **WHEN** vision publishes two ascending errors for a code formed from vision and audition slots three broadcasts ago
- **THEN** both encoders take one step with vision's averaged error, scaled by their weights in that code

#### Scenario: A stale error is dropped
- **WHEN** an ascending error names a code older than the last `pending_codes`
- **THEN** no encoder changes and the dropped count rises by one

### Requirement: Nothing learns during sleep
While the processors are suspended, no head SHALL adapt, no processor SHALL publish an ascending error, and the workspace SHALL make no encoder step.

#### Scenario: Asleep
- **WHEN** the sleep module reports sleep and an ascending error arrives
- **THEN** no encoder weight changes

### Requirement: The content code adds no candidate and no surprise source
The content code SHALL publish no event that the workspace scores and SHALL add no term to any salience, intensity, arousal or drive. Its only effect on a processor SHALL be the head's prediction inside the blended error.

#### Scenario: Same event types
- **WHEN** an entity-free run is driven once with the content code off and once on
- **THEN** the module streams carry the same set of event types and the workspace scores candidates from the same streams

### Requirement: Processor reports carry the content readout
A report formed with a code SHALL carry `content_gain` (against the blend with the null code), `content_cross_gain` (against the code formed from the other sources only), `content_shift_gain` (with the code formed `shift_s` entity seconds earlier), `code_sources` and `code_age_s`, all outside the latent tag. The null code SHALL be the running mean of the last `null_code_window` codes, SHALL NOT be persisted, and `content_gain` SHALL be null until that window has filled.

#### Scenario: A code that predicts across senses
- **WHEN** a synthetic audition input follows the preceding vision input and the head has learned it
- **THEN** audition's `content_cross_gain` is positive and above its `content_shift_gain`

#### Scenario: An own-content echo
- **WHEN** a synthetic vision input is predictable only from its own last accessed latent
- **THEN** vision's `content_gain` may be positive and its `content_cross_gain` is not above zero

### Requirement: The translation arm is a measurement-only shadow
With `comparison = "translation_shadow"` the workspace SHALL train a second code from the same slots with translation, demi-cycle and full-cycle losses, off the tick thread with a bounded queue. It SHALL keep own and cross-modal probes on both codes predicting the next published latent, publishing their gains as scalars under `workspace_feedback.content_readout`. The shadow's codes and weights and the probes' weights SHALL never reach a processor, the bus or a snapshot.

#### Scenario: The shadow leaves the entity unchanged
- **WHEN** the same entity-free run is driven with `comparison = "none"` and with `"translation_shadow"`
- **THEN** every processor's reported errors, intensities and the broadcasts' selections are identical, and tick slip is no greater

### Requirement: The content-code checkpoint is one encrypted unit written with the module states
The encoders, standardisers and every head's code columns SHALL be saved in one encrypted file with an atomic replace, in the same step as every resume checkpoint, snapshot, preservation, sleep onset and shutdown, with a generation counter recorded in each capture. The checkpoint SHALL hold scalar running means only, and SHALL never hold slots, pending codes, the null code, past codes or the shadow.

#### Scenario: A crash between captures
- **WHEN** the cycle stops uncleanly and restarts from the last resume checkpoint
- **THEN** the restored encoders and code columns come from the same capture

### Requirement: The checkpoint is bound to its encoders
The checkpoint SHALL record each source's encoder id, pooling and input dimension. At boot a source whose encoder id, pooling or dimension differs SHALL be refused, naming the source and both values, unless `reset_sources` names it for that boot. A different `code_dim` SHALL be refused.

#### Scenario: The audition encoder changed
- **WHEN** the checkpoint records `spectral-logband-32-v2` for audition and the running encoder is Dasheng
- **THEN** the boot refuses, naming audition and both ids

#### Scenario: The vision pooling changed
- **WHEN** the checkpoint records mean pooling for vision and the running encoder uses attention pooling
- **THEN** the boot refuses, naming vision and both poolings

#### Scenario: A one-boot reset
- **WHEN** the audition mismatch occurs with `reset_sources = ["audition"]`
- **THEN** audition's encoder starts fresh with a warning and vision's weights are kept

### Requirement: The content code suspends during welfare responses
While a welfare rest or freeze is in place, the heads SHALL read the null code, nothing in the content code SHALL learn, and accessed broadcasts SHALL record the suspension under `workspace_feedback.content_readout`. The code SHALL resume when the rest or freeze ends.

#### Scenario: A requested rest
- **WHEN** the welfare indicator response places a rest
- **THEN** every head reads the null code until the rest ends, and no encoder or head weight changes

### Requirement: A harm breaker latches when the code makes prediction worse
When any processor's median `content_gain` over the last `breaker_window_s` of awake, unsuspended reports falls below `breaker_gain_floor`, the content code SHALL suspend as during a welfare response and latch. The latch SHALL be saved in the checkpoint, survive restarts, clear only for a boot with `resume_after_breaker = true`, and raise a caretaker notice naming the processor and the median.

#### Scenario: A harmful code is stopped
- **WHEN** vision's median `content_gain` over the window is -0.08 with the floor at -0.05
- **THEN** the code suspends, the latch is saved, and the caretaker notice names vision and -0.08

#### Scenario: The latch survives a restart
- **WHEN** the cycle restarts with the latch saved and `resume_after_breaker = false`
- **THEN** the code stays suspended

### Requirement: An entity-free welfare check passes before any entity uses the code
Before the code is enabled in any entity, a new entity-free harness running the real vision, audition, interoception, sequence and affect modules over the programme films, after the two feed fixes, SHALL meet the bounds fixed in the design in two passes: from zero code columns, and from weights trained entity-free on cached latents and discarded afterwards. Pass two SHALL meet the engagement condition. The result SHALL be recorded under `docs/records/validation/`.

#### Scenario: A bound fails
- **WHEN** the on run's vision alert rate is 14% above the off run's
- **THEN** the check fails, the record says so, and the code is not enabled in any entity

#### Scenario: The code did not engage
- **WHEN** in pass two every head's code-column norm stays below the engagement floor
- **THEN** the check fails rather than passing its other bounds vacuously

#### Scenario: Pre-trained weights never reach an entity
- **WHEN** pass two finishes
- **THEN** its weights exist only under the harness's scratch directory and no entity state tree holds them
