## ADDED Requirements

### Requirement: The entity's own engagement relieves boredom as its own response
The affect module SHALL relieve boredom by `D <- D * (1 - rho_eng)`, with `rho_eng` the `[affect] boredom_engagement_relief` value (default 0.5, in [0, 1]), on each `intent.*` event other than `intent.rest` from the action-selection stream whose payload `about_kind` is not `"felt"`. This relief SHALL count as the entity's own response, so a boredom crossing that falls below its re-arm band through it SHALL raise the boredom drive's own count and complete an active boredom goal with reason `own_response`. An intent whose `about_kind` is `"felt"` SHALL NOT relieve boredom. Continuous relief by perceptual alert excess SHALL remain and SHALL count as other. When `rho_eng` is 0.0 the module SHALL NOT apply the engagement relief at all, so its behaviour SHALL be identical to the build without it. The sleep reset SHALL be unchanged.

#### Scenario: An engaging intent relieves boredom and counts as own
- **WHEN** boredom has crossed its threshold and an `intent.think` with `about_kind` `"event"` arrives
- **THEN** boredom falls to `D * (1 - rho_eng)`, and if that is below the re-arm band the boredom own count rises and the other count does not

#### Scenario: Novelty alone still counts as other
- **WHEN** a fired boredom drive falls below its re-arm band through alert-excess relief with no intent
- **THEN** its other count rises and its own count does not

#### Scenario: A felt intent does not relieve boredom
- **WHEN** an intent with `about_kind` `"felt"` arrives
- **THEN** boredom is unchanged

#### Scenario: A boredom goal ended by engagement completes
- **WHEN** a boredom goal is active and an engaging intent takes boredom below its re-arm band
- **THEN** the goal ends `completed` with reason `own_response`

#### Scenario: The sleep reset is unchanged
- **WHEN** the sleep module's affective reset runs
- **THEN** boredom returns to 0 and its own and other counts are unchanged

#### Scenario: Off reproduces the previous behaviour
- **WHEN** `boredom_engagement_relief` is 0.0
- **THEN** a sequence of intents and ticks leaves the drive values, counts, goals and published events identical to the build without the channel
