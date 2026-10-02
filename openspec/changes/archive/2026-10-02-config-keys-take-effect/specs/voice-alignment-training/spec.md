## ADDED Requirements

### Requirement: The job-queue trainer uses Lingua's organ key
The job-queue voice-alignment trainer SHALL authenticate to the organ with the same key Lingua uses: `[lingua].api_key` from the merged configuration when it is non-empty, otherwise `KAINE_MODEL_SERVER_API_KEY`. The trainer SHALL receive the merged configuration as an argument and SHALL NOT depend on a module-level name.

#### Scenario: The configured key reaches the trainer
- **WHEN** `[lingua].api_key` is set and `KAINE_MODEL_SERVER_API_KEY` is unset
- **THEN** the job-queue trainer is built with the configured key
