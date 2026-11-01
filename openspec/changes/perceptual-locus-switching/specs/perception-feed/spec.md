## ADDED Requirements

### Requirement: Sleep restores the pre-sleep source
With the perceptual-source registry on, the sleep module's `off` write SHALL leave the selected source unchanged, and restore SHALL return to the pre-sleep source. A source that became unavailable during sleep SHALL fall back as the registry's loss rule states. No sensory content SHALL be persisted.

#### Scenario: Sleep in the simulated world
- **GIVEN** the simulated world is selected before sleep
- **WHEN** sleep completes
- **THEN** the simulated world is selected again, and the world resumes from its held state
