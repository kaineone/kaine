## ADDED Requirements

### Requirement: An offline replay reproduces organ requests under named prompt variants
The maintainer tool `tools/maintainer/organ_replay.py` SHALL rebuild each organ request from an intent-log record (its logged own-turn prompt, its mode and the system prompt named by its digest) and SHALL send it with the language module's request shape: own turn with the fixed user cue, thinking off, the configured temperature and DRY penalty, the stop sequence, the mode's length cap, and the sentence cut applied to the reply. It SHALL skip records whose logged prompt holds the heard-speech placeholder. Each variant SHALL be a pure transform of the prompt and system text, and the score step SHALL print the decision rule it applies.

#### Scenario: The as-logged variant reproduces the request
- **WHEN** a case is run under V0
- **THEN** the chat request's system, prompt, own-turn flag, stop sequence and length cap equal those the language module sent for that record

#### Scenario: A variant removes only its target
- **WHEN** V1 is applied to a prompt that opens with the situation section
- **THEN** the result is the prompt without that section and is otherwise unchanged
