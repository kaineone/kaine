## ADDED Requirements

### Requirement: Operator speech is an auditory candidate like any heard sound
An operator's speech SHALL reach the workspace only as audition events (`audition.perception`, `audition.emotion`, `audition.prosody`, and with speech-to-text on `audition.transcription`), each scored on salience like every other candidate. No component SHALL weight a candidate by its audio channel or by whether its speaker is the operator.

#### Scenario: No operator weight
- **WHEN** an operator transcription and a media-channel transcription with equal intensity and novelty are candidates on the same tick
- **THEN** they receive equal salience scores

### Requirement: The entity has no reply obligation and no pressure to reply
No policy, drive, goal, check or learning path SHALL require or reward speech after heard speech, and no component SHALL take "the operator spoke and the entity did not" as an input to the entity's salience, affect, drives, goals, learning or any training corpus or preference pair. Relief of the social drive by heard operator speech SHALL NOT depend on whether the entity speaks.

#### Scenario: Silence after operator speech
- **WHEN** the entity hears an operator utterance and does not speak
- **THEN** its social drive is relieved as when it does speak, and no event, drive change or training record follows from its silence

#### Scenario: The readout stays outside the entity
- **WHEN** the ignition audit reports operator-speech counts
- **THEN** no module of the entity reads them

### Requirement: Speech-to-text off is bit-identical to absent
With `[audition].transcription_enabled = false`, every bus entry, broadcast, intent and sleep record SHALL be identical to those of a build without this change, on the same seeded feed.

#### Scenario: The first configuration
- **WHEN** the first configuration runs over a fixed seeded feed with and without this change
- **THEN** the bus entries, broadcasts, intents and sleep records are identical

### Requirement: No operator conversation before every module has joined
In the development run, the plan check SHALL refuse, before the last planned module join is recorded, a run-control record that turns on speech-to-text while an operator audio channel (the physical microphone capture, the live feed mode, or the remote bridge's microphone ingest) can deliver audio, naming the rule. After it, each conversation session SHALL be opened and closed by content-free run-control records that the run record and the welfare record keep.

#### Scenario: Too early
- **WHEN** the operator asks to turn on speech-to-text with the bridge microphone before the vocal module has joined
- **THEN** the plan check refuses and names the rule

#### Scenario: A session after the last join
- **WHEN** the operator opens and closes a conversation session after every planned module has joined
- **THEN** the run record holds a start and an end record with entity times and no content
