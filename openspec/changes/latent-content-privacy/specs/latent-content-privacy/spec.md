## ADDED Requirements

### Requirement: Latent-derived values are defined by provenance
A value SHALL count as latent-derived when it is computed from a perceptual latent (an encoder output) or from another latent-derived value and keeps per-dimension information: a vector in an encoder's latent space or in a learned space computed from one, or a per-dimension statistic of such vectors over any window. Scalar reductions over all dimensions, counts, source names and tick indices SHALL NOT count as latent-derived.

#### Scenario: A short code is latent-derived
- **WHEN** a component computes an 8-number code from vision latents
- **THEN** the code is latent-derived

#### Scenario: A scalar error is not latent-derived
- **WHEN** a processor computes the L2 distance between its prediction and its input
- **THEN** the value is not latent-derived and is kept by every surface that keeps the report

#### Scenario: A residual against a decoded prediction is latent-derived
- **WHEN** interoception's prediction is blended with a prediction decoded from a content code
- **THEN** its residual vector is latent-derived, and its scalar `unexpected_error` is not

### Requirement: Latent-derived values are carried under one tag
A latent-derived value SHALL be published, stored in a payload or written in a record only inside a mapping under the key `latent_derived`, at any depth. `kaine/privacy_filter.py` SHALL define `LATENT_DERIVED_KEY = "latent_derived"`, include it in `VECTOR_FIELDS`, export that set as `LATENT_FIELDS`, define `strip_latent()` and define `LATENT_RULE_VERSION = 1`.

#### Scenario: A short code is tagged
- **WHEN** a component publishes an 8-number code computed from vision latents
- **THEN** the code sits under a `latent_derived` mapping in the payload

#### Scenario: The tag is a vector field
- **WHEN** `kaine.privacy_filter` is imported
- **THEN** `"latent_derived"` is in both `VECTOR_FIELDS` and `LATENT_FIELDS`

### Requirement: strip_latent removes every latent field at any depth
`strip_latent(value)` SHALL return a copy of `value` with every key in `LATENT_FIELDS` removed from every mapping at any depth, including mappings inside lists and tuples, and SHALL remove nothing else. It SHALL convert every numpy array it meets to a list of Python numbers before walking it, so that no array is later encoded by its `str()`.

#### Scenario: A nested mapping
- **WHEN** a record holds `{"workspace_feedback": {"gain": 1.1, "latent_derived": {"code": [0.2, 0.4]}}, "latent": [0.1, 0.3]}`
- **THEN** `strip_latent` returns `{"workspace_feedback": {"gain": 1.1}}`

#### Scenario: Long harmless lists stay
- **WHEN** a record holds `saliences` with 40 numbers
- **THEN** `strip_latent` keeps it

#### Scenario: An array under an unreviewed key
- **WHEN** a record holds a numpy array of 8 floats under the key `scores`
- **THEN** `strip_latent` returns it as a list of the same 8 floats, at full precision

### Requirement: Every JSONL record writer strips latent fields before encoding
`AsyncJsonlSink` SHALL apply `strip_latent()` inside its line encoder (`_encode_line`), so every record is stripped whether it arrives through `write`, `write_sync` or `enqueue`. `kaine/persistence/encrypted_jsonl.py` SHALL apply `strip_latent()` in `encode_record` and in `rewrite_encrypted`. No research, ignition, incident, dashboard, trajectory, raw-archive, observer, intent-log, sleep-corpus, voice-alignment or divergence record on disk SHALL hold a latent field.

#### Scenario: An observer copies a payload
- **WHEN** an observer writes a record holding a processor payload that carries `latent` and `latent_derived`
- **THEN** the line written to disk holds neither key and keeps the payload's other fields

#### Scenario: A direct enqueue
- **WHEN** an observer calls `enqueue` on a sink with a record that carries `latent_derived`
- **THEN** the line written to disk holds no `latent_derived` key

#### Scenario: The trajectory copies broadcast metadata
- **WHEN** a broadcast whose metadata carries `workspace_feedback.latent_derived.code` is recorded in the workspace trajectory
- **THEN** the trajectory record holds no `latent_derived` key

#### Scenario: The intent log
- **WHEN** the language module appends an intent-log record whose `numeric_rendering` source event carried `latent_derived`
- **THEN** the encrypted record, decrypted, holds no number from that mapping

### Requirement: The broadcast record carries no member's latent-derived mapping
When the cycle builds the workspace broadcast payload, it SHALL remove the `latent_derived` mapping from each selected member's payload. When no member carries the key, the broadcast payload SHALL be identical to the payload built without this rule.

#### Scenario: A member's ascending error stays off the broadcast
- **WHEN** an accessed vision report carries `latent_derived` and is selected into a broadcast
- **THEN** the broadcast's member payload for it has no `latent_derived` key and keeps its other fields

#### Scenario: No producer, no change
- **WHEN** no member payload carries `latent_derived`
- **THEN** the broadcast payload equals, field for field, the payload the current code builds

### Requirement: Latent values never enter a persisted bus stream
No payload published on a stream of the main Redis bus SHALL hold a key in `LATENT_FIELDS`, at any depth. Every producer, and the cycle when it builds the broadcast payload, SHALL remove those keys before publishing.

#### Scenario: A vision report on the main bus
- **WHEN** the vision module publishes a report
- **THEN** the `vision.out` entry holds no `latent`, `peripheral` or `foveal` key

#### Scenario: A broadcast on the main bus
- **WHEN** the cycle publishes a broadcast whose metadata carries `latent_derived` and whose member carries `latent`
- **THEN** the `workspace.broadcast` entry holds neither key

### Requirement: Latent values a consumer needs travel on a volatile companion stream
A latent value that a declared consumer needs SHALL be published on the companion stream `<stream>.companion` of a second Redis instance that runs with no append-only file and no snapshots. A consumer SHALL treat a missing companion entry as an absent value. Decommission SHALL flush the volatile instance.

#### Scenario: A consumer joins the companion entry
- **WHEN** a declared consumer reads an accessed vision report whose envelope names a companion entry that exists
- **THEN** it reads the latent from that companion entry

#### Scenario: A missing companion entry
- **WHEN** the volatile instance restarted and the companion entry is gone
- **THEN** the consumer treats the latent as absent and raises no error

### Requirement: The companion entry is written first and named by the main entry
The producer SHALL write the companion entry before the main-bus entry, and the main-bus entry's envelope, outside the payload, SHALL record the companion's stream and entry id in the field `companion`. A consumer SHALL read the companion entry by that id. When the companion write fails, the producer SHALL log it and publish the main-bus entry without the `companion` field and without the diverted values.

#### Scenario: The companion exists before the main entry
- **WHEN** a consumer reads a main-bus entry whose envelope names a companion entry
- **THEN** that companion entry was written before the main-bus entry

#### Scenario: A failed companion write
- **WHEN** the volatile instance refuses a companion write
- **THEN** the main-bus entry is published without the latent values and without a `companion` field, and an error is logged

### Requirement: The companion mechanism takes a declared field set
The companion publisher and reader in `kaine/bus` SHALL take the set of fields a producer diverts to the volatile instance, so that another rule keeping a class of value off the persisted bus uses the same instance, companion streams, boot check and budget row. Each producer SHALL declare its companion streams and its field set.

#### Scenario: A second field set
- **WHEN** a producer declares a field set other than `LATENT_FIELDS`
- **THEN** its fields travel on companion streams of the same volatile instance, under the same cap and boot check

### Requirement: The boot refuses a companion producer without a bounded volatile bus
When any declared companion producer is enabled, whatever its field set, the boot and the preboot SHALL refuse unless the volatile instance is reachable, reports `appendonly` off and an empty `save`, and every companion stream the producer declares has a cap of at most `[privacy].companion_stream_maxlen` (default 12000). The refusal SHALL name the failed condition.

#### Scenario: The volatile instance persists
- **WHEN** a latent producer is enabled and the volatile instance reports `appendonly yes`
- **THEN** the boot refuses and names the volatile instance's persistence

#### Scenario: A companion cap is too high
- **WHEN** a latent producer declares a companion stream whose cap is 100000
- **THEN** the boot refuses and names the stream and 100000

### Requirement: Module states hold no latent value other than learned parameters
A module's serialized state SHALL hold no key in `LATENT_FIELDS` and no per-dimension statistic of latents, except the episodic identity-bound field of the next requirement. A learned parameter, updated by a learning rule and read back by the module on restore, MAY be held.

#### Scenario: Forward-model weights are kept
- **WHEN** the vision module serializes its forward model
- **THEN** the weights are in the snapshot and no `latent_stripped` entry is recorded

### Requirement: The episodic identity-bound field is the only exception to the module-state rule
In the episodic memory module's state, and in no other module's, exactly the fields `memory_state.short_term[i].payload.latent_derived.identity_bound` and `memory_state.persisted.<collection>[i].payload.latent_derived.identity_bound` MAY be kept by the module-state captures, rebuilt from their keys `code`, `code_id` and `generation` (episodic-memory spec). A malformed field, anything else inside it, and the same key at any other path SHALL be stripped and recorded.

#### Scenario: A well-formed trace field
- **WHEN** a preservation captures an episodic memory state whose short-term trace holds a well-formed identity-bound field
- **THEN** the bundle keeps it and records no `latent_stripped` entry

### Requirement: Every module-state capture strips latent fields and never refuses a preservation for it
One helper SHALL be applied to the module states of every capture: the fork snapshot (`ForkManager.snapshot`), the preservation capture, the rolling resume checkpoint, and the snapshots `ForkManager.fork` and `ForkManager.merge` write. It SHALL remove any `LATENT_FIELDS` key found in a module state, except the episodic identity-bound field of the previous requirement, record the module names under the capture's metadata key `latent_stripped`, log an error, and still save the capture.

#### Scenario: A module serializes a tagged value
- **WHEN** a module's `serialize()` returns a state holding `latent_derived`
- **THEN** the fork snapshot is saved without it, `latent_stripped` names the module, and an error is logged

#### Scenario: The resume checkpoint
- **WHEN** the rolling resume checkpoint captures a module state holding `latent_derived`
- **THEN** the checkpoint file, decrypted, holds no `latent_derived` key and its metadata names the module

#### Scenario: A preservation is never refused
- **WHEN** a preservation captures a module state holding `latent_derived`
- **THEN** the bundle is written without it and the preservation completes

#### Scenario: A malformed identity-bound field in a preservation
- **WHEN** an episodic memory state's trace holds `latent_derived.identity_bound` with a latent field nested inside it, and another `latent_derived.identity_bound` outside `memory_state`
- **THEN** the bundle keeps only the trace's field rebuilt from `code`, `code_id` and `generation`, strips the other, and names `episodic_memory` under `latent_stripped`

### Requirement: A failing module capture is recorded by type and a bounded message
A module whose `serialize()` or preservation export raises SHALL be recorded, in the snapshot record, the preservation error and the log, by the exception type and a message of at most 200 characters. The bound limits size; it is not a privacy guarantee.

#### Scenario: A failing preservation export
- **WHEN** a module's preservation export raises with a 5000-character message
- **THEN** the preservation error names the exception type and holds at most 200 characters of the message, and does not chain the original exception

#### Scenario: A failing serialize
- **WHEN** a module's `serialize()` raises an exception whose message is 5000 characters long
- **THEN** the snapshot records the exception type and at most 200 characters of the message

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

### Requirement: Content-bearing components check the latent rule and encryption at boot
A component that produces latent-derived values SHALL refuse to start when `kaine.privacy_filter.LATENT_RULE_VERSION` is missing or lower than the version the component requires, when state encryption is not in effect with a resolvable key, or when `[preservation].require_encryption` is not true. It SHALL name the failed condition.

#### Scenario: The rule is missing
- **WHEN** a content-bearing component requiring version 1 starts against a filter with no `LATENT_RULE_VERSION`
- **THEN** it refuses to start and names the missing rule

#### Scenario: Encryption is off
- **WHEN** a content-bearing component starts with `[security.state_encryption] enabled = false`
- **THEN** it refuses to start and names state encryption

#### Scenario: Plaintext bundles are allowed
- **WHEN** a content-bearing component starts with `[preservation].require_encryption = false`
- **THEN** it refuses to start and names `require_encryption`

### Requirement: No latent value reaches a persisted file in an entity-free run
A test SHALL run the cycle entity-free on fake encoders, with a producer of `latent_derived` values, state encryption on under a test key, logging captured to a file and every persisting surface on. It SHALL record every float seen under a latent field in working state, decrypt every file under the state, data and fork roots, and find no recorded float and no `LATENT_FIELDS` key in any persisted record. Planted leaks SHALL be detected.

#### Scenario: The harness covers every surface
- **WHEN** the canary harness is built
- **THEN** it runs the vision, audition, interoception, sequence, affect, episodic memory and language modules, the language module runs on a fake organ client, the episodic store is file-backed, and the research log, the ignition log, the dashboard record, the workspace trajectory, the raw archive with both attestations, the incident log, the intent log, a fork snapshot, the resume checkpoint, a preservation bundle and any snapshot artifacts are on

#### Scenario: Text matches at every precision a writer uses
- **WHEN** the scan searches a text file for a recorded float
- **THEN** it matches the full `repr`, the float32-rounded `repr` and the 4-decimal `_fmt` form, skips 0.0, 1.0 and -1.0, and also reports any run of three consecutive numbers of a recorded vector in sequence

#### Scenario: Binary files are searched for packed floats
- **WHEN** the scan searches a sqlite file or a snapshot artifact
- **THEN** it searches for each recorded float packed as little-endian float32 and float64 bytes

#### Scenario: A clean run
- **WHEN** the harness runs for 2000 ticks with every surface on
- **THEN** the scan finds no recorded latent float and no latent key in any persisted file

#### Scenario: The scan can find a leak
- **WHEN** the planted controls write one latent through a sink with the strip disabled, one through the renderer with its strip disabled, and one into a binary artifact
- **THEN** the scan reports each of those files

### Requirement: The canary covers the bus
The canary SHALL wrap the bus client and assert that no publish to a main-bus stream carries a `LATENT_FIELDS` key and that companion streams go to the volatile client.

#### Scenario: A main-bus publish with a latent field
- **WHEN** a planted producer publishes `latent_derived` on a main-bus stream
- **THEN** the canary fails and names the stream

### Requirement: Every published numeric list is reviewed
A test SHALL walk every payload published in the entity-free harness and fail when a list, tuple or numpy array of two or more numbers sits under a key that is neither in `LATENT_FIELDS` nor in the reviewed set `NON_LATENT_NUMERIC_KEYS`.

#### Scenario: A new vector key
- **WHEN** a module starts publishing `decoded` holding 8 numbers
- **THEN** the test fails and names the module, the event type and the key

#### Scenario: An array is walked
- **WHEN** a module publishes a numpy array of 8 numbers under an unreviewed key
- **THEN** the test fails and names the key
