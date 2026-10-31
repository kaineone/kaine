## ADDED Requirements

### Requirement: The workspace delegates scoring, access and context to its seams
The workspace SHALL score each candidate with its `workspace.salience` implementation, decide access with its `workspace.access` implementation, and the processors SHALL encode their context with the `workspace.context` implementation. With no plugin, each SHALL be the in-tree default, and every snapshot, score table, context vector and null context SHALL equal those of the build before this change for the same inputs.

#### Scenario: The default account is bit for bit
- **WHEN** recorded candidate batches and broadcast ticks drive the workspace and a processor once on the build before this change and once with the default account
- **THEN** the snapshots, score tables, context vectors and null contexts are identical

### Requirement: The access rule returns a checked decision
`AccessRule.decide` SHALL return the ordered coalition, the accessed members and the inhibited flag for one broadcast tick, from the candidates' final scores after the regulation bias and the coherence factor. The workspace SHALL check that accessed members are coalition members, coalition members are candidates, ids are unique, `inhibited` holds exactly when nothing is accessed, the coalition fits the declared capacity, and the decision's metadata holds no vector.

#### Scenario: The regulation bias reaches a plugin rule
- **WHEN** the tier-1 regulation bias halves one source's scores and a plugin access rule is in use
- **THEN** the rule receives the halved scores

#### Scenario: A well-formed decision is used as given
- **WHEN** a plugin rule returns a coalition of one accessed member
- **THEN** the snapshot's coalition is that member, it is not inhibited, and the access threshold metadata is the rule's

### Requirement: A failed access decision inhibits the broadcast and is counted
When `decide` raises or returns a decision that fails the check, the workspace SHALL publish that tick's broadcast as inhibited with an empty coalition, log the failure, and count it under `access_rule_failures` in the broadcast metadata and the research log. It SHALL NOT fall back to another access rule.

#### Scenario: A raising rule does not fall back
- **WHEN** a plugin access rule raises on a broadcast tick
- **THEN** the broadcast is inhibited with no members, `access_rule_failures` increases by one, and no default rule runs

#### Scenario: A decision naming a non-candidate is refused
- **WHEN** a plugin rule returns an accessed id that is not among the tick's candidates
- **THEN** the broadcast is inhibited and the failure is counted

### Requirement: The control arms are defined over the access decision
With a plugin access rule, the matched arm SHALL keep the rule's decision of each broadcast tick for its accessed count and inhibited flag and SHALL replace the accessed members by candidates drawn uniformly without regard to score from the run-seeded generator. The pooled arm SHALL broadcast every candidate with no gate, as it does for the default rule.

#### Scenario: Matched keeps the plugin rule's count
- **WHEN** a plugin rule accesses one of six candidates on a matched broadcast tick
- **THEN** the matched broadcast accesses one member drawn uniformly from the six and is not inhibited

#### Scenario: Matched keeps the plugin rule's inhibition
- **WHEN** a plugin rule inhibits a broadcast tick in the matched arm
- **THEN** the matched broadcast is inhibited

### Requirement: Processors size their context from the encoder
Each processor SHALL size its context weights from the encoder's declared width, which SHALL be at most 1024, and SHALL record the encoder's id and width with its checkpoint. A checkpoint without an encoder id SHALL be read as trained under the default encoder.

#### Scenario: A wider encoder sizes the forward model
- **WHEN** a plugin context encoder declares width 48
- **THEN** the vision, audition and interoception forward models are built with 48 context inputs

#### Scenario: An over-wide encoder is refused
- **WHEN** a plugin context encoder declares width 4096
- **THEN** boot raises `PluginError` naming the plugin and the width

### Requirement: Context weights from another encoder are not loaded silently
When a processor checkpoint names an encoder id or width different from the encoder in use, boot SHALL stop with an error naming the processor and both encoders, unless `[workspace.seams].reinit_context_weights` is true. With the flag, the processor SHALL load its other weights, start its context weights at zero, log the reinitialisation at WARNING and record it in the run manifest.

#### Scenario: A mismatched checkpoint stops the boot
- **WHEN** a vision checkpoint trained under the default encoder is loaded with a plugin encoder and the flag is false
- **THEN** boot stops with an error naming vision, `"default"` and the plugin encoder's id

#### Scenario: The flag starts the context weights at zero
- **WHEN** the same load runs with `reinit_context_weights = true`
- **THEN** vision's non-context weights equal the checkpoint's, its context weights are zero, and the manifest records the reinitialisation

### Requirement: Latent-derived context is never logged or stored
A context vector from any encoder SHALL live only in the processors' working state. It SHALL NOT be written to the research log, the bus diagnostics surface, the episodic memory module's traces or any persisted file other than the processors' learned weights.

#### Scenario: The diagnostics surface carries no context vector
- **WHEN** a processor publishes a report while holding a 48-component plugin context
- **THEN** the diagnostics copy of the report carries no context vector
