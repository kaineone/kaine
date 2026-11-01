## ADDED Requirements

### Requirement: The language module reads words from companion entries
The language module SHALL declare `reads_spoken_text`, so the snapshots it caches carry the words of heard members and of its own earlier utterances, joined from their companion entries. Its heard turn and its residual log redaction SHALL use the joined words. A heard member whose companion entry is missing SHALL be rendered as speech heard but indistinct.

#### Scenario: A heard member is quoted
- **WHEN** a speak intent is realized from a coalition holding an operator transcription whose companion entry exists
- **THEN** the organ's heard turn quotes the transcription's words, and the intent log holds the heard-speech placeholder instead

#### Scenario: The words are gone
- **WHEN** the transcription's companion entry is missing
- **THEN** the heard member renders as "Speech heard but indistinct." and no error is raised
