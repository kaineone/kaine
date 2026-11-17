## REMOVED Requirements

### Requirement: Voice alignment builds DPO pairs from faithful renderings
**Reason**: The faithful rendering is templated telemetry ("Interoception reports wellness 0.83, no alerts"), not an utterance. As the chosen side it trains the language organ to recite workspace readings, the opposite of a voice of the entity's own (voice research 2026-10-05; operator decision V1). The rule that chosen text is never LLM output was one sufficient defence against model collapse, not the only one.
**Migration**: Replaced by "Voice alignment trains only on a validated preference source, with collapse defences". Until a validated source exists, the phase trains nothing.

## ADDED Requirements

### Requirement: Validated preference source only
The voice-alignment phase SHALL build training examples only from a preference source that has passed its recorded offline validation.

#### Scenario: The faithful rendering is never a training target
- **WHEN** the phase builds training examples from any configured source
- **THEN** no example's preferred text is a faithful rendering

#### Scenario: Unvalidated source is not used
- **WHEN** a preference source has not passed its recorded offline validation
- **THEN** the voice-alignment phase does not build training examples from it

### Requirement: Self-generated preferred data accumulates
Self-generated preferred text SHALL be drawn only from a corpus that accumulates across sleeps without replacement.

#### Scenario: Corpus accumulates across sleeps
- **WHEN** self-generated preferred text is selected
- **THEN** it is drawn from a corpus that accumulates across sleeps without replacement

### Requirement: Fixed real-data share
Each training batch SHALL contain a fixed share from a fixed real-data set.

#### Scenario: Fixed share from fixed real-data set
- **WHEN** a training batch is built
- **THEN** it contains a fixed share from a fixed real-data set

### Requirement: Selection by an uncontrolled signal
Preference selection SHALL be by a signal the generator does not control.

#### Scenario: Selection signal uncontrolled by generator
- **WHEN** preference selection runs
- **THEN** selection is performed by a signal the generator does not control

### Requirement: Previous accepted adapter as reference
Training SHALL start from the entity's previous accepted adapter as the reference.

#### Scenario: Training starts from previous accepted adapter
- **WHEN** training starts
- **THEN** it starts from the entity's previous accepted adapter as the reference

### Requirement: Monitors in band
Diversity and distinctiveness monitors SHALL remain inside the maturation band in both directions.

#### Scenario: Monitors remain in band
- **WHEN** training proceeds
- **THEN** diversity and distinctiveness monitors remain inside the maturation band in both directions

### Requirement: No validated source means no training
When no validated preference source is configured, the phase SHALL train nothing and report that in the sleep summary.

#### Scenario: No validated source
- **WHEN** a sleep's voice-alignment phase runs with no validated preference source configured
- **THEN** no adapter is trained and the sleep summary states that no preference source is available
