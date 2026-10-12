## MODIFIED Requirements

### Requirement: Five-phase sleep pipeline runs in fixed order
The sleep module SHALL expose `async enter_sleep()` that runs five phases in
the documented order: light consolidation, deep consolidation,
associative replay, affective reset, voice alignment. Each
phase SHALL return a `PhaseResult` carrying `phase` name, `success`
bool, `elapsed_ms`, and `error` (None on success). A failure in any
one phase SHALL be logged and SHALL NOT prevent later phases from
running.

#### Scenario: All five phases ran in order
- **WHEN** `Sleep.enter_sleep()` is awaited against fake
  collaborators
- **THEN** the published `hypnos.sleep.completed` event's
  `phases` payload lists exactly the five phase names in the
  documented order

#### Scenario: One phase failing does not stop the others
- **WHEN** the light consolidation phase raises during
  `enter_sleep()`
- **THEN** all four subsequent phases still execute and the
  completion event records `success == False` for light
  consolidation but `success == True` for the others (assuming they
  succeeded)

### Requirement: Default Sleep config and disabled-by-default
The repository SHALL ship a `[hypnos]` block in `config/kaine.toml`
with default values for `interval_seconds`,
`max_deferral_seconds`, `per_defer_seconds`, `baseline_salience`,
`alert_salience` and `requested_rest_min_interval_s`, a nested
`[hypnos.consolidation]` table, and a nested
`[hypnos.voice_alignment]` table with `intent_log_path`,
`max_samples`, `lora_rank`, `learning_rate`, `dpo_beta`,
`capability_loss_threshold`, `adapter_output_dir`, `model_id`.
`[modules].hypnos = false` SHALL keep first boot from
auto-registering the sleep module.

#### Scenario: kaine.toml carries defaults
- **WHEN** an operator inspects `config/kaine.toml`
- **THEN** they find a `[hypnos]` section and a nested
  `[hypnos.voice_alignment]` section with the documented keys, and
  `[modules].hypnos == false`

#### Scenario: The shipped file sets no retired key
- **WHEN** an operator inspects the `[hypnos]` section of `config/kaine.toml`
- **THEN** it does not set `nous_step_burst`

## ADDED Requirements

### Requirement: Retired Sleep keys are ignored with a warning
The sleep module factory SHALL accept `[hypnos].nous_step_burst`, a retired key that
no longer drives anything, SHALL NOT pass it to the sleep module, and SHALL log a warning
that names the key and says it is ignored. Any other key outside the factory's
accepted set SHALL still stop boot.

#### Scenario: An old operator file still boots
- **WHEN** the operator configuration sets `[hypnos].nous_step_burst = 200`
- **THEN** the factory builds the sleep module and logs a warning naming
  `[hypnos].nous_step_burst`

#### Scenario: A misspelt key still stops boot
- **WHEN** the `[hypnos]` section sets a key the factory neither accepts nor
  lists as retired
- **THEN** building the sleep module raises an unknown-key error
