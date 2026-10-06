## REMOVED Requirements

### Requirement: Voice alignment builds DPO pairs from faithful renderings
**Reason**: The faithful rendering is templated telemetry ("Soma reports wellness 0.83, no alerts"), not an utterance. As the chosen side it trains the language organ to recite workspace readings, the opposite of a voice of the entity's own (voice research 2026-10-05; operator decision V1). The rule that chosen text is never LLM output was one sufficient defence against model collapse, not the only one.
**Migration**: Replaced by "Voice alignment trains only on a validated preference source, with collapse defences". Until a validated source exists, the phase trains nothing.

## ADDED Requirements

### Requirement: Voice alignment trains only on a validated preference source, with collapse defences
The voice-alignment phase SHALL build training examples only from a preference source that has passed its recorded offline validation. Self-generated text SHALL become preferred training data only when the corpus accumulates across sleeps without replacement, a fixed share of each training batch comes from a fixed real-data set, selection is by a signal the generator does not control, training starts from the entity's previous accepted adapter as its reference, and diversity and distinctiveness monitors stay inside the birth band in both directions. When no validated source is configured, the phase SHALL train nothing and SHALL report that in the sleep summary.

#### Scenario: No validated source
- **WHEN** a sleep's voice-alignment phase runs with no validated preference source configured
- **THEN** no adapter is trained and the sleep summary states that no preference source is available

#### Scenario: The faithful rendering is never a training target
- **WHEN** the phase builds training examples from any configured source
- **THEN** no example's preferred text is a faithful rendering
