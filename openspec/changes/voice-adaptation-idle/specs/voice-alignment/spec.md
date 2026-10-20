## ADDED Requirements

### Requirement: Voice adaptation idles without a validated preference source
The voice-alignment phase SHALL build preference pairs only when it is enabled, operator approval is granted and its configured preference source is a validated training source. Otherwise it SHALL build no pairs and SHALL compute, publish and persist no organ-level divergence: no `sleep.consolidation_divergence` event, no `state/sleep/consolidation_divergence.json` and no `consolidation_divergence` key in the phase metadata (paper section 3.5). The sleep index SHALL advance once per sleep, at its start, and `sleep.sleep.started` SHALL carry it as `sleep_index`, so listeners learn it whether or not the sleep-time intent audit succeeds.

#### Scenario: The first configuration
- **WHEN** a sleep runs with voice alignment disabled and an intent log of 100 records
- **THEN** no pairs are built, no consolidation divergence record or event exists, and the sleep index rises by one and appears on `sleep.sleep.started`
