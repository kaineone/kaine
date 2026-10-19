## ADDED Requirements

### Requirement: The intent log's residual redaction spares the entity's own words
After assembling the context, the language module SHALL replace in the logged prompt, logged faithful rendering, logged heard turn and logged numeric rendering every occurrence (of at least three characters) of the texts of external-input events in the coalition and of the heard-field values of coalition events whose source is not the language module, with the heard-speech placeholder. It SHALL NOT replace a value only because it appears in a heard field of the language module's own earlier event, since those fields are redacted when that event is published. The warning that a placeholder was applied to residual text SHALL fire only when this replacement changed the logged prompt or faithful rendering.

#### Scenario: The entity's own felt phrase recurs
- **WHEN** the coalition holds the language module's own earlier external speech whose `user_input` is the felt phrase that now drives a new utterance
- **THEN** the intent log's prompt holds that phrase verbatim, holds no placeholder, and no residual-text warning is logged

#### Scenario: Another module's heard field still reaches no log
- **WHEN** another module's coalition event carries a heard-field value that the new prompt repeats
- **THEN** the intent log holds the placeholder in its place and not the value
