# Design: the privacy rule for latent-derived content

Code facts are cited at `origin/main` cb41895b.

## Context

### The principle being implemented

The operator's decision of 2026-10-31 (build order item 2) states it: latent-derived content may live in working state and in learned weights. It is never logged, never stored as an episode, and it is stripped by the privacy filter. The comparison report's finding F10 is the reason it comes first: "a content code is derived from latents, and its persistence and logging policy must be designed, not inherited by accident."

### Prior work this change builds on

- **Zero raw-sense-data persistence** ("eyes and ears, not recording"). Raw frames, PCM and transcripts never reach disk. The vision frame ring buffer is RAM-only (`kaine/modules/vision/module.py:987`).
- **`2026-10-03-workspace-graph-only-recording`** found that the filter passed numeric vectors, so about 150,000 clip embeddings a day reached the dashboard record. It added the vector-field set and the 16-number backstop (spec `research-event-log`, "The diagnostics privacy filter removes numeric vectors") and made the ignition log the only workspace record a study keeps, with no payloads.
- **`2026-10-06-mnemos-recall-and-vector-strip`** made the episodic store pass every member payload through `strip_vectors`.
- **`2026-10-05-nexus-privacy-hardening`** and **`2026-09-08-harden-security-boundaries`** kept the diagnostics filter a recursive denylist and added the CI guard on module publishers for content keys (`tests/test_dashboard_privacy.py::test_no_uncovered_content_key_in_module_publishers`).
- **The curated research log** is allowlist-based on two levels: event types and fields (`kaine/evaluation/observers/research_event_observer.py`, module docstring).
- **The heard rule.** `2026-10-19-heard-log-own-words` and the voice-development D7 fixed what the language module treats as heard. The design-only change `episodic-recall-content` (decision 1) moves that rule to `kaine/faithful/external_input.py` and applies it in the episodic store. This change does not redo it; it fixes the order in which the store applies it with the latent rule (decision 6).
- **`2026-06-07-topos-forward-model`** and **`2026-06-07-audition-forward-model`** added the buffer summaries as "statistical descriptors". Decision 5 narrows them. That reverses part of those changes on purpose, for the reason given there.
- **`2026-10-01-world-model-identity`** set the identity rules for learned weights (persist, encrypt, copy into forks, refuse an unchosen merge). Decision 3 relies on them.

### What is on which surface today

| Surface | Persisted? | Latent handling today |
|---|---|---|
| Bus streams (Redis, AOF on) | Bounded by stream caps and AOF rewrite | Vision latents in `vision.out` (cap 12000) and in broadcast members (`workspace.broadcast`, cap 100000) |
| Dashboard SSE and dashboard record | Record: yes, encrypted | Vector fields and 16+ number lists removed |
| Curated research log | Yes, export-eligible | Filter, then per-type field allowlist |
| Ignition log (graph record) | Yes, kept until the operator deletes it | No payloads |
| Workspace trajectory | Yes | No payloads |
| Raw bus archive | Yes, attested only | Verbatim, latents included |
| Other observers' JSONL records | Yes | Each writes its own fields; no shared check |
| Episodic store (Qdrant) | Yes | `strip_vectors` on member payloads; two raw types omitted |
| Fork snapshots, preservation bundles | Yes, encrypted | Whatever `serialize()` returns; buffer summaries hold per-dimension latent means |
| Python logs | Yes (journal or files) | No check |

## Decisions

### 1. What counts as latent-derived

A value is latent-derived when both hold:

1. it is computed from a perceptual latent (an encoder output: the vision module's `latent`, `peripheral` and `foveal`, the audition module's acoustic embedding) or from another latent-derived value; and
2. it keeps per-dimension information: a vector in an encoder's latent space or in any learned space computed from one, or a per-dimension statistic of such vectors over any window.

Examples: the content code `z_k`, an encoder's output, a decoder's descending prediction (even an 8-number interoceptive one), a residual vector, a code-space gradient, the mean of the last 16 clip latents.

Not latent-derived: scalar reductions over all dimensions (an L2 error, a cosine change score, a mean squared error, an error ratio, an information gain, a norm), counts, source names and tick indices. These are what the readouts and the existing research fields are made of, and none of them lets a latent be reconstructed.

Learned parameters are not values under this rule. A weight matrix trained by SGD on a stream of latents carries statistics of that stream, which is what learning is. The operator's decision allows it, and the identity rules govern it (decision 3).

Alternatives considered:

- *Classify by shape*, as the 16-number backstop does. Rejected as the rule, kept as defence in depth: an 8-dimensional code or prediction is as much content as a 768-dimensional one, and a long list can be a harmless table of saliences.
- *Treat every value computed from a latent as content, scalars included.* Rejected: the prediction error is computed from the latent, and every processor's report, the intensity, the access test and the information-gain readout would become unloggable. The rule targets what can be decoded back into what was perceived.

### 2. One tag by key, and one strip function

Latent-derived values travel only inside a mapping under the reserved key `latent_derived`, at any depth of a payload or record (for example `payload["workspace_feedback"]["latent_derived"]["code"]`). Perceptual latents keep their existing names in the vector-field set.

`kaine/privacy_filter.py` gains:

- `LATENT_DERIVED_KEY = "latent_derived"`, added to `VECTOR_FIELDS`, so the diagnostics filter (dev mode included) and `strip_vectors` remove it with no further change;
- `LATENT_FIELDS`, equal to `VECTOR_FIELDS`, exported under that name so callers state what they mean;
- `strip_latent(value)`, which removes every key in `LATENT_FIELDS` at any depth and nothing else (no length backstop, no content keys);
- `LATENT_RULE_VERSION = 1`, which content-bearing components check at boot (decision 9).

Alternatives considered:

- *A wrapper type* (a tagged array class) that refuses JSON encoding. Rejected: the bus serializes payloads, so the type is lost at the first hop, and every consumer would need the class.
- *A suffix convention* (`*_latent`). Rejected: it cannot be checked at depth without matching patterns, and a forgotten suffix leaks silently. One reserved container key is a single string to strip.
- *A whole event type for latent content.* Rejected: the code rides the broadcast and the ascending errors ride the processors' reports (see `workspace-content-code`), so a type-level rule would strip whole reports.

### 3. Working state and learned weights

Latent-derived values may live in:

- process memory (module and workspace working state, ring buffers, the shadow probes of the positive control);
- the bus, under the retention bound of decision 7.

Learned parameters computed from latents may live in encrypted checkpoints and in snapshot state, under the identity rules (persist, encrypt, copy into forks, refuse a merge without an operator choice, covered by decommission). They never enter a log, a research record, a metrics bundle or the diagnostics surface. A stored array counts as a learned parameter only if a learning rule updates it and the module reads it back on restore. A buffer of recent inputs saved under a weight-like name does not.

### 4. The strip points

| Surface | Rule | Mechanism |
|---|---|---|
| Bus publish | Allowed as working state, under the tag | Retention bound (decision 7); the broadcast record drops members' `latent_derived` mappings |
| Dashboard SSE and record | Removed | Diagnostics filter (the key is in `VECTOR_FIELDS`) |
| Curated research log | Removed | Filter, then the field allowlist; readouts are scalars |
| Ignition log, workspace trajectory | Never present | Payload-free by spec; a content-bearing component may add content-free fields only |
| Every JSONL sink | Removed | `AsyncJsonlSink` applies `strip_latent()` before encoding |
| Raw bus archive | Removed | Through the sink; the spec says "verbatim except for the latent fields" |
| Episodic store | Removed | Heard rule, raw-perceptual omit, then `strip_vectors` (decision 6) |
| Snapshots and bundles | Removed unless a learned parameter | Module states checked at `save_snapshot`; buffer summaries become scalars (decision 5) |
| Metrics bundles, the Claude Science export | Never present | Built from `data/evaluation/` sinks, which strip |
| Python logs | Never formatted | Review rule plus the canary's log capture |
| Organ prompts, intent log | Never present | The felt renderer reads declared scalar fields only; the canary scans the intent log |

**The sink is the choke point.** `kaine/persistence/jsonl_sink.py` is the one primitive for every log-type record: the research log, the ignition and incident logs, the dashboard record, the raw archive, the welfare and other observers. Stripping there covers every current and future observer whatever fields it copies. The diagnostics filter and the research allowlist stay as they are, so the sink strip is a second, independent layer. The sink strips keys only, with no length backstop, because evaluation records hold legitimate long numeric tables.

**The broadcast record.** `_snapshot_to_payload` (`kaine/cycle/engine.py:1228`) embeds each selected member's whole payload. A processor's ascending error under `latent_derived` would then be copied into every broadcast that selects it, and onto a stream with a much longer cap. The record drops each member's `latent_derived` mapping. The workspace reads members from the module streams directly, so nothing loses an input. With no producer on, the drop is a no-op and the broadcast is bit for bit the current one.

**Snapshots never refuse a preservation.** `save_snapshot` scans each module state for `LATENT_FIELDS` keys. Any found are stripped, the module names are recorded under `metadata["latent_stripped"]`, and an error is logged. Refusing would block the welfare net's preservation of an entity in distress over a privacy defect, and the entity's preservation is the higher duty. The canary test and the publisher review test keep the path from firing in practice.

Alternatives considered:

- *Strip only at the diagnostics filter*, as today. Rejected: the raw archive, the snapshots, the observers' own records and the logs do not pass through it.
- *Refuse to persist any record that holds a latent field.* Rejected for the reason above for snapshots, and for records because a dropped record is lost research data where a stripped field is not.

### 5. Buffer summaries become content-free

`VisionForwardModel.buffer_summary()` and the acoustic and auditory equivalents return `{"n_frames", "mean_norm", "mean_variance"}`: the frame count, the mean L2 norm of the buffered vectors and the mean over dimensions of their per-dimension variance. These are scalar reductions. Nothing reads the summaries on restore (`deserialize` ignores them), so no behaviour changes.

This narrows a requirement written in June 2026, which allowed "mean and variance of latent features over the buffer window" on the view that statistics cannot be inverted. A per-dimension mean over five seconds of one film shot is close to a single clip embedding, and clip embeddings are partly invertible (the finding of `2026-10-03-workspace-graph-only-recording`). Under decision 1 it is latent-derived. The auditory buffer holds tone-category scores, energy and duration rather than an encoder latent, but it is summarised the same way, so the two summaries keep one shape and the reviewer has one rule to check.

Alternative considered: *drop the summaries entirely.* Viable, since nothing reads them. Kept as scalars so a snapshot still says how full each buffer was when it was taken, which is useful when a revived entity's first predictions are compared with its last ones.

### 6. Episodic memory: the latent rule beside the heard rule

The store applies three rules to each coalition member, in this order:

1. **Heard** (from `episodic-recall-content` decision 1): a heard member is stored as its source and type with `<heard omitted>`, and no payload.
2. **Raw perceptual**: `embodiment.visual.raw` keeps its `<raw-perceptual omitted>` marker.
3. **Latent**: every other payload passes `strip_vectors`, which now removes `latent_derived` with the named vector fields.

The rules differ in kind, and the order matters. The heard rule and the raw rule remove a member's whole payload, because every text field of a heard event is someone else's words. The latent rule removes keys and keeps the member's scalar fields (change score, error ratio, intensity), which are the felt fields a remembered moment needs. Applying the latent rule first would be harmless but wasted on a member about to lose its whole payload. Applying the heard rule last could store heard words under a key the latent rule does not know.

**The omit-list finding.** Today the store omits two types while the language module's rule also covers `embodiment.chat` and heard-text fields at any depth. That is the gap `episodic-recall-content` PR 1 closes. That change scheduled it after the module-ignition study and said it should be pulled forward if speech recognition or embodiment were enabled first. The study now converts into the development run, and episodic memory joins it early (build order item 7). So this change requires PR 1 to land before or with its own episodic PR, and before the episodic memory module is enabled in any entity. It does not copy PR 1's requirement into its own delta, so the two changes never specify the same requirement twice.

**Heard, raw and latent share a principle.** All three classify by provenance (whose words, which sense, derived from which latent) rather than by field shape, apply at the point of storage, and fail closed (an unclassified heard event counts as heard; an unrecognised long vector is still removed by the backstop). The zero raw-sense rule says raw sense data never persists. The heard rule says another person's words never persist. The latent rule says what the entity's encoders made of its senses never persists, except as learned weights.

### 7. The bus is working state, with a bound

The bus already carries perceptual latents: vision reports at about 3.3 a second in `vision.out` and in the members of `workspace.broadcast`. Redis keeps them in memory up to each stream's cap and in its append-only file until the next rewrite. Decommission deletes the streams and requests the rewrite (spec `entity-decommission`). The docs describe the bus as a capped ring buffer whose entries are trimmed within minutes to hours (`docs/17-research-data/participation.md:45`). That is working state with a disk-backed crash buffer, not a record: nothing reads old entries as history, and nothing exports them.

Latent-derived values are held to a tighter bound than the 100000-entry broadcast cap allows. A stream that carries `latent_derived` may have a cap of at most `[privacy].latent_stream_maxlen` (default 12000). That is the `vision.out` cap: about 20 minutes at the 10 Hz maximum access rate and an hour at the resting rate, enough for an observer to resume after a restart. The check runs in `kaine/bus/config.py` at boot and in the preboot bus-budget row, when any producer of latent-derived values is enabled. A content-bearing change declares its producer and the streams it publishes on, and its run configuration lowers the broadcast cap.

Known residual, not changed here: perceptual latents in broadcast members sit on `workspace.broadcast` at its 100000 cap. Removing them from members, or lowering that cap for every run, changes what the episodic store, the sequence module and the observers read from the broadcast. It is recorded as a follow-up for the development run's configuration change (build order item 5).

Alternatives considered:

- *Keep latent-derived values off the bus*, on an in-process channel from the workspace to the processors. Rejected: modules receive the broadcast through the bus (`publish_workspace`, then each module's reader), and a side channel would break the one contract every consumer and the red-team harness rely on.
- *A dedicated short-capped stream for the code.* Rejected for now: the processors would have to join it with the broadcast by tick, and a code that arrives late or not at all would change the entity's predictions nondeterministically.

### 8. Offline stimulus features

Latents that a tools script computes from stimulus files with no entity running (the cross-modal decodability check of build order item 3, for example) describe the stimulus, which is public-domain film, not an entity's experience. They are outside the rule and may be cached by the tool outside the state, data and fork roots. They never enter an entity's state tree, a snapshot, the shipped image or a bus. The tool's documentation says so, and the canary test's file scan covers the state tree.

### 9. Content-bearing components check the rule

A component that produces latent-derived values reads `LATENT_RULE_VERSION` at boot and refuses to start when it is missing or lower than the version it was reviewed against. `workspace-content-code` checks version 1. The dependence on this change is then enforced by the code, not just by build order.

### 10. Tests

- **Persistence canary** (`tests/test_latent_persistence_canary.py`). An entity-free harness runs the cycle with the vision, audition, interoception, sequence, affect and episodic memory modules (fake encoders with seeded random latents, in-memory episodic backend), a producer that publishes a `latent_derived` mapping on a processor report and on the broadcast metadata, and every persisting surface on: the research log, the ignition log, the dashboard record, the raw archive with both attestations, the incident log, a fork snapshot and a preservation bundle, with state encryption on under a test key and Python logging captured to a file. Until `workspace-content-code` exists the producer is a test double in the test module. After it lands, a second case runs the real content code. Every value the harness saw in working state under a latent field is recorded. The test then decrypts every file under the state, data and fork roots and searches for each recorded float, both its full `repr` and its float32-rounded `repr`, skipping 0.0, 1.0 and -1.0. It expects no hit, and no `latent_derived` or vector-field key in any persisted JSON. A planted case that writes one latent into a sink with the strip disabled must be found, so the scan is shown to work.
- **Publisher review** (`tests/test_publisher_numeric_keys.py`). In the same harness every published payload is walked. Every list of two or more numbers must sit under a key in `LATENT_FIELDS` or in a reviewed `NON_LATENT_NUMERIC_KEYS` set (for example `fovea`, `predicted_fovea`, `scores`, `saliences`, `step_magnitudes`). A new key fails the test until it is reviewed. This closes the gap the length backstop leaves for short vectors.
- **Unit tests** (`tests/test_latent_content_privacy.py`): `strip_latent` at depth and in lists; the diagnostics filter in normal and dev mode; the sink strip; the broadcast record dropping members' mappings, and bit-identical output when there are none; `save_snapshot` stripping and recording; the retention check refusing a 100000 cap on a declared stream and accepting 12000; the buffer summaries as three scalars; episodic store order with a heard member, a raw member and a member carrying `latent_derived`.

## Risks

- **A producer that ignores the tag.** A developer can publish a decoded prediction under a new key. The publisher review test fails on it. The backstop catches it on the diagnostics surface if it is 16 or more numbers. The canary catches it if the value reaches disk.
- **The canary finds exact copies only.** A latent scaled or rounded before being written is not matched. The tag rule, the review test and the sink strip are the main defence; the canary shows that the main paths hold.
- **Learned weights memorise.** A linear decoder's bias tracks the recent mean of its targets. That is allowed by the decision and is why weights are identity: encrypted, never logged, never exported, covered by decommission.
- **The bound lowers observer lookback.** A 12000-entry broadcast cap is 20 minutes at the maximum access rate, the same horizon the processor streams already have.

## Migration and ordering

1. PR 1: `LATENT_FIELDS`, `strip_latent`, the tag in `VECTOR_FIELDS`, the sink strip, the raw-archive docstring and spec, the broadcast-record drop, the unit tests. Behaviour-neutral with the shipped configuration except attested raw archives.
2. PR 2: buffer summaries as scalars, the snapshot check, the retention check and `[privacy].latent_stream_maxlen`.
3. PR 3: the episodic store order, after or with `episodic-recall-content` PR 1.
4. PR 4: the canary and the publisher review tests, docs.
5. Existing snapshots and bundles keep their old buffer summaries until the next snapshot. A revive reads nothing from them. An operator who wants old bundles cleaned re-preserves the entity, and docs say so.

## Welfare and admissibility

- The change alters nothing the entity perceives or computes. It changes what is written about it, so it lowers the risk to the entity's mental privacy and to bystanders. It touches persistence and preservation, so every PR gets the independent second review.
- The snapshot check strips and never refuses, so the welfare net's preservation path is unaffected (decision 4).
- No study or run is in flight. The development run's image is built after this change.

## Implementation estimate

In LLM-agent terms: four worker PRs of about 150 to 500 changed lines each, tests included. Each takes one to two hours of worker time and about an hour of lead review, plus the second review. PR 1 and PR 4 get the closest review. About two days elapsed. The canary harness runs in a few minutes on the CPU, with no GPU and no entity.
