## ADDED Requirements

### Requirement: Heard audio carries its channel
Audio delivered through the live-microphone path SHALL carry the channel it came from: the perception-feed mode (`playlist`, `seeded`, `womb`, `screen`) when a feed plays, and `live_mic` for a real device. Only speech from an operator channel SHALL be treated as a user utterance addressed to the entity; speech from other channels SHALL still be perceived and compete for the workspace.

#### Scenario: A film character speaks
- **WHEN** a transcription from the playlist channel is broadcast
- **THEN** no speak intent answering it is formed

#### Scenario: The operator speaks
- **WHEN** a transcription from the live microphone is broadcast
- **THEN** a speak intent answering it may be formed as before
