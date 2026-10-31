## ADDED Requirements

### Requirement: The graph record names the sources written into the code
With the content code on, each ignition-log row of an accessed broadcast SHALL carry `code_sources`, the names of the sources whose slots were present in the code formed on that broadcast. The row SHALL carry no code value, slot value or weight.

#### Scenario: A broadcast with both senses in the code
- **WHEN** a code is formed from the vision and audition slots
- **THEN** the row's `code_sources` is `["audition", "vision"]` and the row holds no number from the code

#### Scenario: Code off
- **WHEN** the content code is off
- **THEN** the row has no `code_sources` field
