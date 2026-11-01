## ADDED Requirements

### Requirement: Spoken text is defined by provenance
`split_spoken_text(event)` in `kaine/faithful/external_input.py` SHALL return the main-bus payload and the diverted values. On an `EXTERNAL_INPUT_TYPES` event it SHALL divert every string leaf except under `SPOKEN_TEXT_METADATA_KEYS` (`source_label`, `model`, `backend`). On any other event, the language module's own included, it SHALL divert every value under a `HEARD_TEXT_FIELDS` key at any depth. The module SHALL define `SPOKEN_TEXT_RULE_VERSION = 1`.

#### Scenario: A transcription
- **WHEN** an `audition.transcription` with `text`, `source_label`, `model`, `latency_ms` and `prediction_error` is split
- **THEN** `text` is diverted and the other fields stay in the main payload

#### Scenario: An unknown string on a chat event
- **WHEN** an `embodiment.chat` event carries a string under a key that is not reviewed metadata
- **THEN** that string is diverted

#### Scenario: The entity's own utterance
- **WHEN** an `external_speech` event with `text`, `user_input` and `faithful_rendering` is split
- **THEN** all three are diverted

#### Scenario: A remembered trace
- **WHEN** an `episodic_memory.replay` event is split
- **THEN** its `text` is diverted

### Requirement: Content-free counts replace diverted text
When the split diverts a top-level `text`, the main payload SHALL carry `text_chars` (its length in characters) and `text_words` (its count of whitespace-separated words). An event with nothing to divert SHALL be published unchanged, with no counts and no `companion` field.

#### Scenario: Counts are kept
- **WHEN** a transcription whose text is "come and see this" is published
- **THEN** its main-bus payload holds `text_chars = 17` and `text_words = 4` and no `text`

#### Scenario: An event without words
- **WHEN** an `affect.state` event is published
- **THEN** the main-bus entry is identical to the entry published without this rule

### Requirement: No main-bus stream holds spoken text
Every publish to a stream of the main Redis bus, including `workspace.broadcast` and `action_selection.out`, SHALL hold no diverted value. The bus client SHALL apply `split_spoken_text` on every main-bus publish through the companion mechanism of `latent-content-privacy`, with this field set declared, and the diverted values SHALL travel only on the never-persisted instance.

#### Scenario: A heard utterance on the main bus
- **WHEN** audition publishes a transcription
- **THEN** the `audition.out` entry holds no words and its envelope names a companion entry that holds them

#### Scenario: The three language streams
- **WHEN** the language module publishes an utterance on `language.external` and on `language.out`
- **THEN** neither main-bus entry holds the utterance's words

### Requirement: Broadcast members reference their own companion entries
When the cycle builds the broadcast payload it SHALL split each selected member's payload and SHALL record in the member record the member's own companion reference. It SHALL NOT write a second copy of a member's words.

#### Scenario: An accessed heard utterance
- **WHEN** an operator transcription is selected into an accessed broadcast
- **THEN** the broadcast member holds no words and names the transcription's own companion entry

### Requirement: Only declared consumers receive spoken text
The shared snapshot decoder SHALL join members' companion entries only for a module that declares `reads_spoken_text`. The language module, the episodic memory module, the vocal module, the embodiment module, the remote bridge's transcript feed and the `external_utterance_log`, `ab_divergence` and `affect_correlation` observers SHALL read spoken text from companion entries. Social cognition, sequence, the utterance-outcome recorder and the self-model SHALL read the main-bus copy only.

#### Scenario: A module that does not declare it
- **WHEN** the planning module decodes a broadcast holding an accessed transcription
- **THEN** its snapshot holds no words

#### Scenario: Sequence counts an interaction without words
- **WHEN** a non-empty operator transcription is published
- **THEN** sequence counts the interaction from `text_chars` on the main bus

### Requirement: A missing companion entry means absent words
A consumer that finds no companion entry for an event SHALL treat its words as absent and raise no error: the language module SHALL render a heard member as speech heard but indistinct; the episodic store SHALL store the entity's own speech as `<words unavailable>`; the vocal module SHALL synthesize nothing and SHALL publish a failed `vocal.synthesized` with `error: "words unavailable"`; the bridge SHALL skip the line; the observers SHALL skip and count the record.

#### Scenario: The volatile instance restarted
- **WHEN** the vocal module reads an `external_speech` whose companion entry is gone
- **THEN** nothing is played and a failed `vocal.synthesized` is published

### Requirement: Spoken-text producers require the volatile instance
The language module, and the audition module when `transcription_enabled` is true, SHALL be declared companion producers under this field set, so the shared boot check of `latent-content-privacy` refuses to start without a reachable, unpersisted and capped volatile instance.

#### Scenario: No volatile instance
- **WHEN** the cycle boots with the language module on and no volatile instance reachable
- **THEN** the boot refuses and names the volatile instance

### Requirement: No spoken text reaches the main bus in an entity-free run
A test SHALL run the cycle entity-free with a fake speech-to-text backend and a fake organ that emit planted strings, the episodic store file-backed, the vocal module on a fake backend, the bridge's transcript loop and the observers named above. It SHALL find no planted string in any main-bus entry, SHALL find every planted string on the volatile instance, SHALL confirm that each declared consumer received the strings it needs, and SHALL detect planted controls.

#### Scenario: A clean run
- **WHEN** the harness runs with planted heard sentences on an operator and a media channel and planted own sentences
- **THEN** no main-bus entry holds any of them, the organ's heard turn holds the heard sentence, and the episodic store holds the own sentence and no heard one

#### Scenario: The canary finds an intent leak
- **WHEN** a planted control places a heard sentence in an intent's `about`
- **THEN** the canary fails and names `action_selection.out`

### Requirement: Salience scores are unchanged by the split
An entity-free check SHALL show that every candidate's salience score is identical with and without the split.

#### Scenario: Scores before and after
- **WHEN** the same feed runs with the split on and with it off
- **THEN** every candidate's novelty and salience scores are identical
