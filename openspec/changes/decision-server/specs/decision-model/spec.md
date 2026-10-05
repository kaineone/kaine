## ADDED Requirements

### Requirement: The decision model is served on its own on-demand server
The decision model SHALL be served by a separate llama-server on the organ's pinned build, bound to loopback, requiring an API key on every endpoint except `/health`, sleeping when idle, and running only while an entity runs with `[decision].enabled = true`. The shipped configuration SHALL keep it disabled.

#### Scenario: Disabled by default
- **WHEN** KAINE boots with the shipped configuration
- **THEN** no decision server is started and no client call is made

### Requirement: The decision client never turns a failure into a negative
The client SHALL return no answer on any transport error, non-success status, malformed body, missing answer or schema mismatch, and SHALL NOT log or persist utterances, contexts or answers. Callers SHALL treat "no answer" as "no signal", never as a negative.

#### Scenario: Server unreachable
- **WHEN** the decision server cannot be reached
- **THEN** `ask` returns no answer and a content-free error is logged at most once per minute per kind

### Requirement: The decision server is independent of the organ's sleep window and known to residency
The Hypnos organ window SHALL NOT stop the decision server, so the decision model stays available while the organ is unloaded for training. The decision server SHALL be a `decision` organ in the residency rung and footprint catalogues, counted by the fit report when enabled, with its rung (or `off`) named per tier and recorded in the run manifest.

#### Scenario: The organ window leaves the decision server running
- **WHEN** the organ window stops the language-organ server for voice-alignment training
- **THEN** the decision server keeps running and the client keeps answering

#### Scenario: A small host sees the decision server's cost
- **WHEN** `[decision].enabled = true` on a host whose budget is tight
- **THEN** the fit report counts the decision rung's footprint and names it in the plan

