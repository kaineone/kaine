## ADDED Requirements

### Requirement: Selection applies no per-source precision weight
Syneidesis's v1 salience strategy SHALL compute a candidate's priority as the clipped product of its intensity, novelty and goal relevance, with no weight that depends on the statistics of other events from its source. Precision enters through each processor's own scoring of its prediction error; arousal is the only global gain on the competition.

#### Scenario: A steady heartbeat does not suppress perceptual alerts
- **WHEN** one source publishes a constant intensity of 0.1 every second for ten minutes while another publishes alerts at 0.8 one time in ten, at baseline arousal
- **THEN** each alert's score equals the level factor at baseline arousal times 0.8, the same as when the steady source is absent
