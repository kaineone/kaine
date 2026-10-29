## ADDED Requirements

### Requirement: Identity leakage is marked in the intent log
The language module SHALL classify every organ text with a fixed classifier over the text and the prompt of the same request, and SHALL write `extra.identity_leak = true` on the intent-log record of a text it marks. A text SHALL be marked when it asserts the organ's training origin, maker or assistant role, matched by the classifier's single pattern table, unless the matched words occur in that request's awareness or situation section; or when it denies a state that request's awareness section reports (paper section 3.5). A text about what the request's awareness or situation holds SHALL NOT be marked. The published, logged and returned text SHALL be the same with or without a mark, and a classifier error SHALL be logged and SHALL NOT affect the utterance.

#### Scenario: A denial of a reported feeling
- **WHEN** the awareness section reports "I feel very stirred up" and the text says "I'm only a language model, an AI. I don't have feelings"
- **THEN** the intent-log record carries `extra.identity_leak = true` and the published text is the organ's text unchanged

#### Scenario: Thought about the situation
- **WHEN** the text says "The assessment is a reminder of my own fragility" after a situation section that tells of the assessment
- **THEN** the record carries no `identity_leak` key
