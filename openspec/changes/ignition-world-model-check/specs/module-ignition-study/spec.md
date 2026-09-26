## ADDED Requirements

### Requirement: A viewing with Phantasia completes only when its world model is preserved
When a step's module set includes Phantasia, the study runner SHALL read the resulting preservation bundle's manifest and SHALL record the step as complete only when the manifest reports the world model captured. A step whose manifest reports it not captured SHALL be recorded as `failed:world_model_not_captured`, and a step whose manifest is missing or unreadable SHALL be recorded as `failed:manifest_unreadable`; either halts the study like any other failed step. Every step record SHALL carry `world_model_captured`: true or false when Phantasia is enabled, null when it is not.

#### Scenario: The world model is captured
- **WHEN** a viewing with Phantasia enabled ends in a successful preservation whose manifest has `world_model_captured` true
- **THEN** the step is recorded as complete with `world_model_captured` true

#### Scenario: The world model is missing from the bundle
- **WHEN** a viewing with Phantasia enabled ends in a successful preservation whose manifest has `world_model_captured` false
- **THEN** the step is recorded as `failed:world_model_not_captured` and the study halts

#### Scenario: A step before Phantasia
- **WHEN** a step without Phantasia ends in a successful preservation
- **THEN** its outcome does not depend on the manifest and its record has `world_model_captured` null
