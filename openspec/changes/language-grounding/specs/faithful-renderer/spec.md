## ADDED Requirements

### Requirement: Perceptual content is rendered by reference to prototypes

When prototypes are enabled, the felt rendering of a vision or audition report SHALL describe the matched prototype by its relations in the entity's history (same as the previous report, seen often, not seen before, returned after an absence, co-occurring with a current prototype of the other sense, its learned name) in place of the change and familiarity magnitude words. The prediction-error grading SHALL remain. Interoception and affect renderings SHALL be unchanged.

#### Scenario: A returning scene is rendered as returning

- **WHEN** a vision report matches a prototype last seen long before and seen many times
- **THEN** the rendering states that this is something seen many times that has come back, and contains no word from the change-magnitude table

#### Scenario: Rendering with prototypes off is unchanged

- **WHEN** prototypes are disabled
- **THEN** every rendering is identical to the current renderer's

### Requirement: Relational phrases are true of the entity's own state

Every relational phrase SHALL be emitted only when the prototype state it describes holds, and a learned name SHALL be rendered only when the word-referent learner reports it as a learned name.

#### Scenario: No name without a learned name

- **WHEN** a prototype has no learned name
- **THEN** the rendering states no word for it
