## ADDED Requirements

### Requirement: The content code ships off and is identical to absent when off
The `[workspace.feedback.content]` table SHALL have `enabled = false` in the shipped configuration. When it is false, no encoder SHALL be built, no head SHALL gain code columns, audition SHALL publish no `latent`, and no payload SHALL gain a key, so every published event and broadcast is identical to the current build with the same feedback arm. An unknown key or value in the table SHALL be a configuration error.

#### Scenario: Off is bit for bit the current build
- **WHEN** the same inputs and broadcasts drive the workspace and each processor once with the table absent and once with `enabled = false`, under the same feedback arm
- **THEN** every published payload, intensity and snapshot is identical

#### Scenario: Unknown source is refused
- **WHEN** `sources = ["vision", "affect"]`
- **THEN** loading the settings raises a configuration error naming `affect`

### Requirement: The content code needs both opt-in layers
The content code SHALL be built only when `enabled = true` and `KAINE_CONTENT_CODE_OPERATOR_APPROVED=1`. With the first and not the second it SHALL stay off, the boot SHALL print why, and the research gate SHALL record `content_code: not_approved`.

#### Scenario: Config on, operator variable missing
- **WHEN** `enabled = true` and the operator variable is unset
- **THEN** no content code is built and the research gate records `content_code: not_approved`

### Requirement: The content code refuses to start without its preconditions
With both opt-in layers set, the boot SHALL refuse with the reason when workspace feedback is off or its arm is `off`, when `kaine.privacy_filter.LATENT_RULE_VERSION` is missing or below 1, or when a stream the content code publishes on has a cap above `[privacy].latent_stream_maxlen`.

#### Scenario: The latent rule is missing
- **WHEN** the content code is opted in and the privacy filter has no `LATENT_RULE_VERSION`
- **THEN** the boot refuses and names the missing rule

#### Scenario: Every precondition holds
- **WHEN** `enabled = true`, the operator variable is set and every precondition holds
- **THEN** the content code is built

#### Scenario: Feedback off
- **WHEN** `enabled = true`, the operator variable is set and `[workspace.feedback].arm = "off"`
- **THEN** the boot refuses and names the feedback arm

### Requirement: Source slots are written only by accessed members
The workspace SHALL keep one slot per configured source holding the latent, graded intensity and entity time of that source's most recently accessed report. A slot SHALL be written only from an accessed member of an accessed broadcast, by the highest-scoring accessed report of that source. It SHALL be cleared when its age exceeds five times `slot_decay_s`, when that source's blind-sensor or sensor-silent advisory is raised, and at sleep onset.

#### Scenario: An inhibited broadcast writes nothing
- **WHEN** a broadcast holding a vision report is inhibited
- **THEN** the vision slot is unchanged

#### Scenario: An old slot is cleared
- **WHEN** the audition slot was written 11 entity seconds ago and `slot_decay_s = 2.0`
- **THEN** the next code is formed without audition

### Requirement: The code is formed on accessed broadcasts, intensity-weighted and age-decayed
On each accessed broadcast the workspace SHALL form `z_k = tanh(Σ α_s (W_s x_s + c_s))` over the present slots, with `α_s` the slot's intensity divided by the summed intensity of the present slots, times `exp(−age_s / slot_decay_s)`. With no slot present the code SHALL be the zero vector. The code SHALL be held until the next accessed broadcast.

#### Scenario: Weights follow intensity
- **WHEN** the vision and audition slots are both fresh with intensities 0.6 and 0.2
- **THEN** the vision term enters with weight 0.75 and the audition term with weight 0.25

#### Scenario: No source present
- **WHEN** an accessed broadcast is formed and no slot is present
- **THEN** the code is the zero vector

### Requirement: The code rides the accessed broadcast under the latent tag
The workspace SHALL attach the code to each accessed broadcast under `workspace_feedback.latent_derived.code` and SHALL attach none to an inhibited broadcast. Processors SHALL adopt a code only from an accessed broadcast and SHALL record its tick index as `code_tick`.

#### Scenario: The code is tagged
- **WHEN** an accessed broadcast is published with the content code on
- **THEN** its metadata holds the code inside a `latent_derived` mapping and nowhere else

### Requirement: Heads read the code and start continuous
With the content code on, each processor's top-down head SHALL use the regressor `(b, s, z, 1)` with `z` the adopted code (zeros before the first), SHALL start its code columns at zero, and SHALL learn all columns by its existing SGD step on its own error. The blend with the processor's own prediction SHALL be unchanged.

#### Scenario: Switch-on continuity
- **WHEN** the content code is enabled for a processor whose head has learned weights for `(b, s, 1)`
- **THEN** its first descending prediction equals the prediction the head makes without the code

### Requirement: Heads persist in every arm
Each processor SHALL serialize its top-down head's weights and running error windows with its forward model and restore them, in every feedback arm. A head whose recorded code width, context width or input dimension differs from the running one SHALL be discarded with a warning naming the mismatch and SHALL start at zero. Gains SHALL NOT be persisted.

#### Scenario: A head survives a restart
- **WHEN** a processor with a trained head is serialized and restored into the same configuration
- **THEN** the restored head makes the same prediction for the same regressor

### Requirement: Ascending errors train the encoders
A processor that used a code SHALL publish on its report, under `latent_derived.ascending_error`, the gradient of its head's squared error, divided by its running mean, with respect to the code, clipped to `ascending_clip`, with the scalar `code_tick`. The workspace SHALL keep the last `pending_codes` codes with their inputs and SHALL take one encoder step per ascending error whose code it holds, scaled by each source's `α_s`. An error for a code no longer held SHALL be dropped and counted.

#### Scenario: A held code is credited
- **WHEN** vision publishes an ascending error for a code formed from vision and audition slots three broadcasts ago
- **THEN** both encoders take one step scaled by their weights in that code

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
A processor report formed with a code SHALL carry `content_gain` (the reported blended error against the blend with the null code, over the running mean error), `content_shift_gain` (the same with the code from `shift_broadcasts` accessed broadcasts earlier), `code_sources` and `code_age_s`. The null code SHALL be the running mean of the last `null_code_window` accessed codes. All four fields SHALL be outside the latent tag.

#### Scenario: A code that predicts
- **WHEN** a synthetic audition input follows the preceding vision input and the head has learned it
- **THEN** audition's `content_gain` is positive and above its `content_shift_gain`

### Requirement: The translation arm is a measurement-only shadow
With `comparison = "translation_shadow"` the workspace SHALL train a second code from the same slots with translation, demi-cycle and full-cycle losses. It SHALL keep one probe per processor and code predicting the next published latent, and SHALL publish the probes' gains as scalars under `workspace_feedback.content_readout`. The shadow and probes SHALL never reach a processor, the bus or a snapshot.

#### Scenario: The shadow leaves the entity unchanged
- **WHEN** the same entity-free run is driven with `comparison = "none"` and with `"translation_shadow"`
- **THEN** every processor's reported errors, intensities and the broadcasts' selections are identical

### Requirement: The content-code checkpoint persists encrypted and is bound to its encoders
The encoders SHALL be saved encrypted with an atomic replace at sleep onset, shutdown, every snapshot and every `checkpoint_interval_s` awake, with each source's encoder id and input dimension. At boot a source whose encoder differs SHALL be refused unless `reset_sources` names it for that boot. A different `code_dim` SHALL be refused. Slots, pending codes and the shadow SHALL never be saved.

#### Scenario: The audition encoder changed
- **WHEN** the checkpoint records `spectral-logband-32-v2` for audition and the running encoder is Dasheng
- **THEN** the boot refuses, naming audition and both ids

#### Scenario: A one-boot reset
- **WHEN** the same mismatch occurs with `reset_sources = ["audition"]`
- **THEN** audition's encoder starts fresh with a warning and vision's weights are kept

### Requirement: The content code suspends during welfare responses
While a welfare rest or freeze is in place, the heads SHALL read the null code, nothing in the content code SHALL learn, and accessed broadcasts SHALL record the suspension under `workspace_feedback.content_readout`. The code SHALL resume when the rest or freeze ends.

#### Scenario: A requested rest
- **WHEN** the welfare indicator response places a rest
- **THEN** every head reads the null code until the rest ends, and no encoder or head weight changes

### Requirement: A harm breaker latches when the code makes prediction worse
When any processor's median `content_gain` over the last `breaker_window_s` of awake reports falls below `breaker_gain_floor`, the content code SHALL suspend as during a welfare response and latch. The latch SHALL be saved in the checkpoint, survive restarts, clear only for a boot with `resume_after_breaker = true`, and raise a caretaker notice naming the processor and the median.

#### Scenario: A harmful code is stopped
- **WHEN** vision's median `content_gain` over the window is -0.08 with the floor at -0.05
- **THEN** the code suspends, the latch is saved, and the caretaker notice names vision and -0.08

#### Scenario: The latch survives a restart
- **WHEN** the cycle restarts with the latch saved and `resume_after_breaker = false`
- **THEN** the code stays suspended

### Requirement: An entity-free welfare check passes before any entity uses the code
Before the content code is enabled in any entity, an entity-free run of the real vision, audition, interoception, sequence and affect modules over the programme films, with the code off and then on under one seed, SHALL meet the bounds fixed in the design (alert rates, arousal, negative valence, drive crossings, switch-on transient, saturation, finiteness). Its result SHALL be recorded under `docs/records/validation/`.

#### Scenario: A bound fails
- **WHEN** the on run's vision alert rate is 14% above the off run's
- **THEN** the check fails, the record says so, and the code is not enabled in any entity
