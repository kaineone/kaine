## ADDED Requirements

### Requirement: Sleep holds perception off without touching the source
With the perceptual-source registry on, the sleep module SHALL add its `sleep` off-holder when sleep starts and remove it on restore, and SHALL NOT write a locus or a source, so the pre-sleep source returns when sleep ends. A failed read SHALL resolve to the programme. No sensory content SHALL be persisted.

#### Scenario: Sleep in the simulated world
- **GIVEN** the simulated world is selected before sleep
- **WHEN** sleep completes
- **THEN** the simulated world is selected again, and the world resumes from its held state

#### Scenario: A failed read at restore
- **WHEN** the desired-state file cannot be read as sleep ends
- **THEN** the programme is selected, and no physical source opens
