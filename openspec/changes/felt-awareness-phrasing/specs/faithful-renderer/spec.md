## ADDED Requirements

### Requirement: Felt rendering with graded words
The faithful package SHALL provide a felt template set covering every key of the numeric template set plus `embodiment.chat`, and a felt fallback for unregistered keys. A felt line SHALL name its source in plain words and SHALL express each numeric quantity only as a word from that quantity's documented bin table, where a value equal to an edge falls in the higher bin and a missing, boolean or non-finite value contributes no word. A felt line SHALL contain no digit, except inside the quoted text of heard speech (`audition.transcription`, `embodiment.chat`); a felt line that would contain one SHALL be replaced by the number-free fallback line for its source.

#### Scenario: Vision report in words
- **WHEN** a `vision.report` with `change_score` 0.0004, `habituation_score` 0.6116 and `normalised_error` 1.2 is rendered felt
- **THEN** the line is "What I see is barely changing, feels somewhat familiar and is a little unexpected." and contains no digit

#### Scenario: Bin edge goes up
- **WHEN** arousal is exactly 0.4
- **THEN** the arousal word is "alert", and for 0.39 it is "calm"

#### Scenario: Heard speech keeps its digits
- **WHEN** an `audition.transcription` with text "call me at 5" is rendered felt
- **THEN** the line is `Speech heard: "call me at 5".`

#### Scenario: Numeric rendering unchanged
- **WHEN** a renderer is built without felt templates
- **THEN** it renders every event exactly as before this change
