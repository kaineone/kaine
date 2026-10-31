## ADDED Requirements

### Requirement: A plain pair is encoded with thinking off
The trainer SHALL encode a plain pair (no `own_turn`) as the system turn when given, the prompt as the user turn, and the chat template's generation prompt rendered with `enable_thinking=False`, with the completion appended and closed with EOS. The prompt tokens SHALL equal those of the served prompt for the same request with `think=False`.

#### Scenario: The organ's template closes the think block
- **WHEN** a plain pair is encoded with the organ's real chat template
- **THEN** the prompt ends with `<|im_start|>assistant\n<think>\n\n</think>\n\n` and its tokens equal the served prompt's

### Requirement: Every pair shape matches a served request
The trainer SHALL accept exactly three pair shapes, plain, own-turn with the fixed cue and own-turn with a user turn, and SHALL encode each as the language client sends it with thinking off. A test SHALL render each shape through the organ's real chat template, read from the local base model and skipped only when it is absent, and assert token identity with the served prompt.

#### Scenario: An own-turn pair with a heard turn
- **WHEN** an own-turn pair with a user turn is encoded with the real template
- **THEN** its prompt tokens equal those of the served request built by `chat_messages` with the same system prompt, user turn and notes

### Requirement: The veto's probes are rendered as served
The trainer SHALL generate every capability and abliteration probe, for the base and the candidate, in two served layouts with thinking off: the bare layout (no system turn, the probe as the user turn) and the persona own-turn layout the job writer renders from the language module's fixed probe conditions. No probe SHALL be tokenized as raw text.

#### Scenario: A probe reaches the model in the served shape
- **WHEN** the veto scores a capability probe
- **THEN** the token ids passed to generation equal the served prompt for that probe in each layout, with thinking off

### Requirement: The relative veto applies in each layout
The trainer SHALL reject an adapter that, in either layout, deflects on a probe its base passes or deflects more often overall than its base, and SHALL take the lower of the two layouts' capability scores. The result SHALL record both layouts' counts.

#### Scenario: Worse only under the persona
- **WHEN** an adapter matches its base on the bare layout but deflects on one own-turn probe its base passes
- **THEN** the adapter is rejected and the result names the own-turn layout
