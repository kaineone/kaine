## ADDED Requirements

### Requirement: Every module's alert-level events are categorical alerts
An event a module publishes at its alert level SHALL carry `alert` true in its payload, and an event whose intensity a module chooses between its baseline and its alert level SHALL carry `alert` set to whether the alert level was chosen, so that the access rate's phasic input counts every categorical alert the paper defines.

#### Scenario: A drive crossing is an alert
- **WHEN** Thymos publishes a `thymos.drive` crossing at its alert level
- **THEN** the payload has `alert` true and the access rate's phasic input counts it

#### Scenario: A successful sleep is not an alert
- **WHEN** Hypnos completes a sleep in which every phase succeeded
- **THEN** `hypnos.sleep.completed` is published at the baseline level with `alert` false
