## ADDED Requirements

### Requirement: No policy answers heard speech by rule
No action-selection policy SHALL form an intent because a coalition member is heard speech, and no policy SHALL test a member's source, type or audio channel to decide whether to speak. A heard member MAY lead to speech only as any accessed member can, through the policy's own rule over the coalition's scores. `DefaultActionSelectionPolicy` SHALL keep its guards and SHALL produce no intent of its own.

#### Scenario: An accessed operator utterance under the default policy
- **WHEN** the default policy runs on a non-inhibited coalition holding an operator transcription with non-empty words
- **THEN** it produces no intent

#### Scenario: The drive policy gives heard speech no precedence
- **WHEN** a non-inhibited coalition holds an operator transcription and a `social_drive` crossing, and no speak intent is in flight
- **THEN** the drive-biased policy's speak intent is the one for the drive crossing

### Requirement: No intent carries heard words
No intent's `about` SHALL hold another speaker's words, and no shipped policy SHALL emit an intent with `about_kind` `"heard"`. An intent caused by a heard member SHALL name it with the same felt or numeric summary used for any event, with `about_kind` `"event"`.

#### Scenario: Planning summarizes a heard event
- **WHEN** the planning wrapper realizes a proposal whose top non-planning member is a transcription
- **THEN** the intent's `about` holds no word of the transcription and its `about_kind` is `"event"`

### Requirement: The cycle selects a named action-selection policy
The cycle SHALL select the self-initiated report policy when `[action_selection].policy` is absent or `"self_initiated_report"`, and the drive-biased policy only when it is `"drive_biased"`. It SHALL refuse to boot on any other value and when `[action_selection].drive_initiative` is set, naming the accepted values. `config/kaine.toml` SHALL set `policy = "self_initiated_report"`.

#### Scenario: A typo
- **WHEN** the configuration sets `policy = "self_initiated_reprot"`
- **THEN** the boot refuses and names `"self_initiated_report"` and `"drive_biased"`

#### Scenario: The retired key
- **WHEN** the configuration sets `drive_initiative = true`
- **THEN** the boot refuses and names `policy`

## REMOVED Requirements

### Requirement: Drive crossings in the conscious coalition can produce intents
**Reason**: It gives a heard user utterance precedence over a drive-initiated speak, a rule that answers heard speech (`operator-speech-as-perception` design decision 2).
**Migration**: Replaced by "Drive crossings in the accessed coalition can produce intents, with no heard-speech precedence", which keeps the drive mapping without the precedence.

### Requirement: Action selection realizes conscious Planning proposals under the existing gates
**Reason**: One scenario names "a user response" as the configured policy's intent; no policy answers a user any more.
**Migration**: Replaced by "Action selection realizes accessed planning proposals under the existing gates", identical except that scenario.

## ADDED Requirements

### Requirement: Drive crossings in the accessed coalition can produce intents, with no heard-speech precedence

When selected, the drive-biased policy SHALL form intents from `affect.drive` crossings in a non-inhibited accessed coalition: `social_drive` MAY produce a `speak` intent, and `curiosity`, `boredom` or `restlessness` a `think` intent. These intents SHALL stay subject to the inhibition gate and the in-flight and no-self-response guards, with at most one `speak` per tick. A heard member SHALL NOT take precedence over a drive-initiated intent.

#### Scenario: Social drive crossing initiates speech

- **WHEN** a non-inhibited coalition contains a `affect.drive` event for
  `social_drive` and no speak intent is in flight
- **THEN** a `speak` intent is produced

#### Scenario: Curiosity crossing initiates internal deliberation

- **WHEN** a non-inhibited coalition contains a `affect.drive` event for
  `curiosity` (or `boredom`/`restlessness`) and no think intent is in flight
- **THEN** a `think` intent is produced (internal speech, not external)

#### Scenario: Inhibition still gates drive-initiated intents

- **WHEN** the snapshot is inhibited
- **THEN** no intent is produced even if drive crossings are present

#### Scenario: Heard speech does not outrank a drive-initiated speak

- **WHEN** a non-inhibited coalition contains both an operator transcription
  and a `social_drive` crossing
- **THEN** the single `speak` intent produced is the drive-initiated one

### Requirement: Action selection realizes accessed planning proposals under the existing gates

With `[planning].drive_actions` true, the action selection module SHALL turn the most salient `think`, `speak` or `rest` proposal of a non-inhibited accessed coalition into that kind of intent with `origin: "planning"`, under every other intent's gate, guards and refractory periods. It SHALL produce at most one per snapshot, never displacing the configured policy's intent, and the configured policy SHALL decide with every proposal removed.

#### Scenario: An inhibited coalition never realizes a proposal
- **WHEN** a `planning.proposal` is in the coalition of an inhibited snapshot
- **THEN** no intent is produced, nothing is published to `action_selection.out`, and its outcome on `action_selection_feedback.out` is `realized: false`, `reason: "inhibited"`

#### Scenario: A proposal that never became conscious is never realized
- **WHEN** a `planning.proposal` is published but is not in any conscious coalition
- **THEN** the action selection module produces no intent for it

#### Scenario: A conscious think proposal becomes internal speech
- **WHEN** a non-inhibited coalition contains a `think` proposal and no think intent is in flight
- **THEN** a `think` intent with `origin: "planning"` is published on `action_selection.out`, and the language module realizes it as `internal_speech`

#### Scenario: The configured policy's speak outranks a Planning speak proposal
- **WHEN** the configured policy produces a `speak` intent for a snapshot that also contains a `speak` proposal
- **THEN** only the configured policy's intent is published, and the proposal's outcome is `reason: "superseded"`

#### Scenario: The configured policy never acts on a proposal itself
- **WHEN** a coalition contains a `planning.proposal` and other members
- **THEN** the configured policy decides on the coalition without the proposal, so none of its intents is about the proposal, and it produces the same intents whether `[planning].drive_actions` is true or false

#### Scenario: A lost realization never mutes a kind
- **WHEN** a planning module `think` or `speak` intent is realized under any configured policy, and the matching speech never becomes conscious
- **THEN** that kind's in-flight guard clears after the guard timeout, and a later proposal or policy intent of that kind can be realized again

#### Scenario: Observational ablation
- **WHEN** `[planning].drive_actions` is false
- **THEN** no proposal-derived intent is produced, and every proposal's outcome is `reason: "disabled"`

### Requirement: Every planning proposal seen gets a content-free outcome
For every proposal it sees, the action selection module SHALL publish a content-free `action_selection.proposal_outcome` (`proposal_id`, `realized`, `reason`) on the `action_selection_feedback.out` stream, never on `action_selection.out`.

#### Scenario: A declined proposal
- **WHEN** a `speak` proposal is in an accessed coalition while a speak intent is in flight
- **THEN** an outcome with `realized: false` is published on `action_selection_feedback.out` and nothing about it on `action_selection.out`
