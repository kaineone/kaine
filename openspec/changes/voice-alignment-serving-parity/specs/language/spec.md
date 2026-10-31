## ADDED Requirements

### Requirement: The intent log records the thinking flag sent and redaction
The chat client SHALL report on each response the thinking flag it actually sent (`false`, `true`, or null after the retry without the flag). The language module SHALL record it in the intent-log record's `extra.think_sent`, and SHALL set `extra.served_text_redacted` to true when the logged prompt or the logged heard turn differs from the text sent to the organ. Neither field SHALL carry content.

#### Scenario: A server that rejects the flag
- **WHEN** the server rejects `chat_template_kwargs` and the client retries without it
- **THEN** the record's `extra.think_sent` is null

#### Scenario: Heard speech in the working memory
- **WHEN** the residual redaction replaces heard speech in the logged prompt
- **THEN** the record's `extra.served_text_redacted` is true
