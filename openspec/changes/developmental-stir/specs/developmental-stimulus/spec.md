## MODIFIED Requirements

### Requirement: The maternal channel is external and entity-independent
The stimulus source SHALL present a **maternal channel** consisting of a fast rhythm (the
heartbeat) and a slow state (an emotional-weather signal that colours the visual
field). Both SHALL be synthesised, deterministic, bounded signals that are
**independent of the entity's own state**: nothing the entity does or feels SHALL
change the heartbeat or the maternal state. The stimulus source SHALL NOT read the entity's
affect to drive any developmental stimulus. The only element of the stimulus that depends
on the entity SHALL be the maternal voice's answer to a stir, which depends on the entity's
act and never on its affect directly; scheduled maternal speech SHALL be unchanged by stirring.

#### Scenario: Maternal state does not depend on the entity
- **WHEN** the entity's internal affect changes, or the entity stirs, during the developmental phase
- **THEN** the maternal-state signal and the maternal heartbeat are unchanged (they
  are functions of the seed and index only)

#### Scenario: No self-referential visual loop exists
- **WHEN** the stimulus source is auditing its inputs
- **THEN** no visual stimulus and no heartbeat value is derived from the entity's own affect or output, and the only entity-dependent sound is a stir's answer

#### Scenario: The maternal-state signal stays bounded
- **WHEN** the maternal-state generator runs for any length of a run
- **THEN** its value remains within its declared valid range at all times

## ADDED Requirements

### Requirement: A stir is answered by maternal speech
On the stir with index `i`, the local stimulus source SHALL answer when a keyed draw on `(seed, i)` is below `answer_probability` (default 0.5), after a keyed delay uniform on `[answer_delay_min_s, answer_delay_max_s]` (default 2 to 10 s), with one keyed utterance from the unlocked items other than the repeated passage, through the hearing band. An answer due during scheduled speech SHALL wait for that utterance to end.

#### Scenario: The same seed and stir times give the same answers
- **WHEN** two developmental runs with the same seed stir at the same entity times
- **THEN** they answer the same stirs with the same utterances at the same times

#### Scenario: Slot plans are untouched
- **WHEN** an entity stirs during a stretch of slots
- **THEN** every slot's scheduled plan is the one it would have had without the stir

### Requirement: An answer is announced without content
For each answer the local stimulus source SHALL publish `development.stir_answer` with the stir index and the answer's start and end in entity time, and no content.

#### Scenario: An answered stir is announced
- **WHEN** the voice answers stir 4
- **THEN** one `development.stir_answer` with index 4, a start and an end is published, and it carries no utterance id or text
