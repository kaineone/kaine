## ADDED Requirements

### Requirement: Latent-derived values are defined by provenance
A value SHALL count as latent-derived when it is computed from a perceptual latent (an encoder output) or from another latent-derived value and keeps per-dimension information: a vector in an encoder's latent space or in a learned space computed from one, or a per-dimension statistic of such vectors over any window. Scalar reductions over all dimensions, counts, source names and tick indices SHALL NOT count as latent-derived.

#### Scenario: A short code is latent-derived
- **WHEN** a component computes an 8-number code from vision latents
- **THEN** the code is latent-derived

#### Scenario: A scalar error is not latent-derived
- **WHEN** a processor computes the L2 distance between its prediction and its input
- **THEN** the value is not latent-derived and is kept by every surface that keeps the report

### Requirement: Latent-derived values are carried under one tag
A latent-derived value SHALL be published, stored in a payload or written in a record only inside a mapping under the key `latent_derived`, at any depth. `kaine/privacy_filter.py` SHALL define `LATENT_DERIVED_KEY = "latent_derived"`, include it in `VECTOR_FIELDS`, export that set as `LATENT_FIELDS`, define `strip_latent()` and define `LATENT_RULE_VERSION = 1`.

#### Scenario: A short code is tagged
- **WHEN** a component publishes an 8-number code computed from vision latents
- **THEN** the code sits under a `latent_derived` mapping in the payload

#### Scenario: The tag is a vector field
- **WHEN** `kaine.privacy_filter` is imported
- **THEN** `"latent_derived"` is in both `VECTOR_FIELDS` and `LATENT_FIELDS`

### Requirement: strip_latent removes every latent field at any depth
`strip_latent(value)` SHALL return a copy of `value` with every key in `LATENT_FIELDS` removed from every mapping at any depth, including mappings inside lists, and SHALL remove nothing else.

#### Scenario: A nested mapping
- **WHEN** a record holds `{"workspace_feedback": {"gain": 1.1, "latent_derived": {"code": [0.2, 0.4]}}, "latent": [0.1, 0.3]}`
- **THEN** `strip_latent` returns `{"workspace_feedback": {"gain": 1.1}}`

#### Scenario: Long harmless lists stay
- **WHEN** a record holds `saliences` with 40 numbers
- **THEN** `strip_latent` keeps it

### Requirement: Every JSONL sink strips latent fields before writing
`AsyncJsonlSink` SHALL apply `strip_latent()` to every record before encoding it, for every sink instance, so no research, ignition, incident, dashboard, raw-archive or observer record on disk holds a latent field.

#### Scenario: An observer copies a payload
- **WHEN** an observer writes a record holding a processor payload that carries `latent` and `latent_derived`
- **THEN** the line written to disk holds neither key and keeps the payload's other fields

### Requirement: The broadcast record carries no member's latent-derived mapping
When the cycle builds the workspace broadcast payload, it SHALL remove the `latent_derived` mapping from each selected member's payload. A `latent_derived` mapping that the workspace itself attaches to the broadcast metadata SHALL be kept. When no member carries the key, the broadcast payload SHALL be identical to the payload built without this rule.

#### Scenario: A member's ascending error stays off the broadcast
- **WHEN** an accessed vision report carries `latent_derived` and is selected into a broadcast
- **THEN** the broadcast's member payload for it has no `latent_derived` key and keeps its other fields

#### Scenario: No producer, no change
- **WHEN** no member payload carries `latent_derived`
- **THEN** the broadcast payload equals, field for field, the payload the current code builds

### Requirement: Streams that carry latent-derived values have a bounded cap
`config/kaine.toml` SHALL have `[privacy].latent_stream_maxlen`, default 12000. When any producer of latent-derived values is enabled, the boot and the preboot bus-budget row SHALL refuse a configuration in which a stream that producer publishes on has a cap above `latent_stream_maxlen`, naming the stream and its cap.

#### Scenario: The broadcast cap is too high
- **WHEN** a producer that publishes on `workspace.broadcast` is enabled and that stream's cap is 100000
- **THEN** the boot refuses and names `workspace.broadcast` and 100000

#### Scenario: A bounded cap is accepted
- **WHEN** the same producer is enabled and the cap is 12000
- **THEN** the boot proceeds

### Requirement: Snapshots hold no latent value other than learned parameters, and never refuse a preservation for it
A module's serialized state SHALL hold no key in `LATENT_FIELDS` and no per-dimension statistic of latents. A learned parameter, updated by a learning rule and read back by the module on restore, MAY be held. `save_snapshot` SHALL remove any `LATENT_FIELDS` key found in a module state, record the module names under the snapshot metadata key `latent_stripped`, log an error, and still save the snapshot.

#### Scenario: A module serializes a tagged value
- **WHEN** a module's `serialize()` returns a state holding `latent_derived`
- **THEN** the snapshot is saved without it, `latent_stripped` names the module, and an error is logged

#### Scenario: Forward-model weights are kept
- **WHEN** the vision module serializes its forward model
- **THEN** the weights are in the snapshot and no `latent_stripped` entry is recorded

### Requirement: Log calls never format a latent value
No log call SHALL format a value held under a `LATENT_FIELDS` key, at any level.

#### Scenario: A malformed latent is logged by its shape
- **WHEN** a processor skips a non-finite latent and logs the skip
- **THEN** the message names the length and the reason and contains none of the latent's numbers

### Requirement: Offline stimulus features stay outside an entity's state
Latents computed with no entity running, from stimulus files, by a tools script SHALL NOT be written into the state, data or fork roots, a snapshot, a bus stream or the shipped image.

#### Scenario: The decodability check caches clip latents
- **WHEN** the offline cross-modal check caches its film latents
- **THEN** the cache lies outside the state, data and fork roots and is never loaded by the cycle

### Requirement: Content-bearing components check the latent rule at boot
A component that produces latent-derived values SHALL refuse to start when `kaine.privacy_filter.LATENT_RULE_VERSION` is missing or lower than the version the component requires, and SHALL name the missing rule.

#### Scenario: The rule is missing
- **WHEN** a content-bearing component requiring version 1 starts against a filter with no `LATENT_RULE_VERSION`
- **THEN** it refuses to start and names the missing rule

### Requirement: No latent value reaches a persisted file in an entity-free run
A test SHALL run the cycle entity-free, on fake encoders, with a producer of `latent_derived` values, state encryption on under a test key, Python logging captured to a file, and every persisting surface on. It SHALL record every float seen under a latent field in working state, decrypt every file under the state, data and fork roots, and find none of those floats and no `LATENT_FIELDS` key in any persisted record. A planted leak SHALL be detected.

#### Scenario: The harness covers every surface
- **WHEN** the canary harness is built
- **THEN** it runs the vision, audition, interoception, sequence, affect and episodic memory modules, publishes `latent_derived` on a processor report and on the broadcast metadata, and has the research log, the ignition log, the dashboard record, the raw archive with both attestations, the incident log, the episodic store, a fork snapshot and a preservation bundle on

#### Scenario: Floats are matched in both precisions
- **WHEN** the scan searches for a recorded float
- **THEN** it matches the full `repr` and the float32-rounded `repr`, and skips 0.0, 1.0 and -1.0

#### Scenario: A clean run
- **WHEN** the harness runs for 2000 ticks with every surface on
- **THEN** the scan finds no recorded latent float and no latent key in any persisted file

#### Scenario: The scan can find a leak
- **WHEN** the planted control writes one latent through a sink with the strip disabled
- **THEN** the scan reports that latent's file

### Requirement: Every published numeric list is reviewed
A test SHALL walk every payload published in the entity-free harness and fail when a list of two or more numbers sits under a key that is neither in `LATENT_FIELDS` nor in the reviewed set `NON_LATENT_NUMERIC_KEYS`.

#### Scenario: A new vector key
- **WHEN** a module starts publishing `decoded` holding 8 numbers
- **THEN** the test fails and names the module, the event type and the key
