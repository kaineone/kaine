# evaluation-sidecar Specification

## Purpose
TBD - created by archiving change memory-probes-stub-cleanup. Update Purpose after archive.
## Requirements
### Requirement: Memory probe scoring uses async-only path
`kaine/evaluation/memory_probes.py` SHALL expose exactly one
reconstruction scorer, `score_async(response, memory, embedder)`,
and SHALL NOT carry a synchronous placeholder that returns a
constant. `MemoryProbeRunner.run_once` MUST call `score_async`
when computing reconstruction accuracy.

#### Scenario: No synchronous stub present
- **WHEN** an operator runs `git grep "reconstruction_accuracy" kaine/`
- **THEN** the search returns no matches

#### Scenario: Runner uses async scorer
- **WHEN** `MemoryProbeRunner.run_once` produces a probe sample
- **THEN** the `accuracy` field is the float returned by
  `score_async`, not a constant `0.0`

### Requirement: Workspace-following observers use the canonical broadcast decode

Observers that follow `workspace.broadcast` SHALL consume it via the bus's
`subscribe_workspace` path — the same decoded-snapshot path every module uses —
not the standard `Event` decode. The standard decode rejects broadcast entries
(which carry a `snapshot` field rather than `salience`/`type`/`payload`), so an
observer using it receives nothing. A `WorkspaceSubscriberObserver` base SHALL
follow the broadcast and dispatch the decoded snapshot payload to its handler;
`TrajectoryRecorder` and `AttributionRecorder` SHALL use it.

#### Scenario: Trajectory records one row per broadcast

- **WHEN** the workspace broadcasts a snapshot (a `{snapshot: <json>}` entry)
- **THEN** the trajectory recorder writes one row carrying that snapshot's
  `tick_index`, `selected`, and `salience_scores`
- **AND** a session of N broadcasts yields N trajectory rows

#### Scenario: The standard-Event decode path would have recorded nothing

- **WHEN** the same broadcast entry is offered through the standard `Event`
  decode used by stream-following observers
- **THEN** it does not decode to a usable event
- **AND** confirms why the workspace observers must use `subscribe_workspace`

### Requirement: Evaluation layer stays decoupled from modules

The new workspace-following observer base SHALL touch only the bus reader
protocol; `kaine.evaluation` SHALL NOT import `kaine.modules.*`. The
`memory_source` and `cognitive_query_client` that the memory-probe and
eidolon-accuracy observers require SHALL be constructed as adapters at the cycle
entrypoint (the allowed coupling point) and injected, so those observers
instantiate when enabled without the evaluation layer importing any module.

#### Scenario: Evaluation layer imports no modules

- **WHEN** the evaluation package is imported
- **THEN** it imports no `kaine.modules.*` module

#### Scenario: Providers wired → probe observers instantiate

- **WHEN** the sidecar is built with a `memory_source` and a
  `cognitive_query_client` and the corresponding flags enabled
- **THEN** the `memory_probes` and `eidolon_accuracy` observers are included
- **AND** with neither provided they are skipped, and the sidecar still starts

### Requirement: A/B-divergence baseline uses the language organ's model

The evaluation A/B-divergence baseline SHALL run the same model as the language
organ. `[evaluation].chat_model_id` SHALL derive from `[lingua].model_id` when not
explicitly set, and SHALL fail closed when explicitly set to a different value:
the cycle SHALL refuse to boot with a clear operator message naming both values,
before any resource (bus, modules, runtime state) is opened. This holds because
the baseline runs bare (no architecture), so a differing baseline model would make
the divergence measure a model difference instead of the architecture's
conditioning.

#### Scenario: Baseline derives from the organ when unset

- **WHEN** `[evaluation].chat_model_id` is absent
- **THEN** the A/B baseline uses `[lingua].model_id`

#### Scenario: Explicit matching value is accepted

- **WHEN** `[evaluation].chat_model_id` equals `[lingua].model_id`
- **THEN** the configuration loads normally

#### Scenario: Explicit divergent value fails closed

- **WHEN** `[evaluation].chat_model_id` is set to a value different from
  `[lingua].model_id`
- **THEN** the cycle refuses to boot with a clear error naming both values
- **AND** no bus connection, module, or runtime state file has been created

### Requirement: Embedder kind is disclosed in every cosine-similarity record

Every A/B-divergence and memory-probe JSONL record SHALL include an
`"embedder"` field whose value is the embedder's `kind` attribute
(`"sentence_transformers"` or `"hash"`).  This allows operators and
researchers to filter out records where cosine similarity is lexical
(hash-based) rather than semantic.

#### Scenario: Hash embedder is disclosed in A/B-divergence records

- **WHEN** `ABDivergenceObserver` writes a record using `HashEmbedder`
- **THEN** the record SHALL contain `"embedder": "hash"`

#### Scenario: Hash embedder is disclosed in memory-probe records

- **WHEN** `MemoryProbeRunner` writes a record using `HashEmbedder`
- **THEN** the record SHALL contain `"embedder": "hash"`

#### Scenario: Semantic embedder is disclosed when available

- **WHEN** `SentenceTransformerTextEmbedder` is in use
- **THEN** records SHALL contain `"embedder": "sentence_transformers"`

---

### Requirement: Fallback to HashEmbedder is logged at ERROR level

The sidecar SHALL log at `ERROR` level when `SentenceTransformerTextEmbedder`
fails to load and falls back to `HashEmbedder`.  The log message SHALL
explicitly state that cosine metrics will be lexical token-hash similarity,
not semantic similarity.

#### Scenario: Fallback logs at ERROR with lexical disclosure

- **WHEN** `SentenceTransformerTextEmbedder` raises on construction
- **AND** `require_semantic_embedder` is `False`
- **THEN** the log entry SHALL be at `ERROR` level
- **AND** the log message SHALL state that cosine metrics will be lexical

---

### Requirement: require_semantic_embedder fails closed when set

`EvaluationConfig` SHALL include a `require_semantic_embedder: bool`
field (default `False`).  When `True`, `_embedder_default()` SHALL raise
rather than falling back to `HashEmbedder` if
`SentenceTransformerTextEmbedder` fails to load.  Default `False` so
minimal/CPU installs without `sentence-transformers` still run.

#### Scenario: Fail closed when required

- **WHEN** `require_semantic_embedder` is `True`
- **AND** `SentenceTransformerTextEmbedder` raises on construction
- **THEN** `_embedder_default()` SHALL raise `RuntimeError`
- **AND** SHALL NOT return `HashEmbedder`

---

### Requirement: Eidolon accuracy only advertises supported claim signals

`CLAIM_KEYWORDS` SHALL NOT map any claim keyword to a signal key that is
never populated by `_signals_snapshot()`.  Unsupported claims SHALL be
absent from the map with a comment explaining why.

#### Scenario: honest and open are not scoreable

- **WHEN** the entity self-describes as "honest" or "open"
- **THEN** those keywords SHALL NOT appear in `CLAIM_KEYWORDS`
- **AND** `parse_claims` SHALL NOT return them as scoreable claims

---

### Requirement: Curiosity signal is named and labelled as a proxy

The curiosity signal derived from proactive-audit file existence SHALL be
stored under the key `"curiosity_proxy"` in both `_signals_snapshot()` and
`CLAIM_KEYWORDS`.  Every eidolon accuracy JSONL record SHALL include a
`"curiosity_proxy_used": bool` field indicating whether any scored claim
was evaluated against this proxy.

#### Scenario: Curiosity proxy used is disclosed

- **WHEN** the entity claims to be "curious" and is scored against the
  proxy signal
- **THEN** the output record SHALL contain `"curiosity_proxy_used": true`

### Requirement: A/B divergence meter has a controlled measurement path

The A/B divergence meter SHALL provide a control path that computes divergence
for a controlled `(utterance, workspace-conditioning)` input by running BOTH
arms through the SAME inference path, varying ONLY the workspace conditioning:
the conditioned arm is the utterance under the supplied conditioning, the bare
arm is the SAME utterance under EMPTY conditioning. The control SHALL reuse the
language organ's real conditioning path (Lingua's `ContextAssembler` + the
language-organ chat client, wired at the cycle entrypoint) rather than a
parallel reimplementation, so any divergence it reports is attributable to the
conditioning alone — which is exactly the quantity the meter is defined to
measure. The divergence metric used by the control SHALL be the same metric the
live observer reports (`1 - cosine` of the two embedded outputs), factored into
a single shared definition so the control and observer cannot drift apart.

The control SHALL read approximately zero when the two arms are conditioned
identically (negative control) and large when a known conditioning difference is
injected (positive control). Adding the control SHALL NOT change the behavior of
the live `ABDivergenceObserver`, which continues to sample `lingua.external`
while running.

#### Scenario: Identical/empty conditioning reads ~zero (negative)

- **WHEN** the control runs an utterance with EMPTY workspace conditioning
- **THEN** the conditioned arm and the bare arm receive an identical prompt and
  produce identical output
- **AND** the reported divergence is below a small floor (~0)

#### Scenario: Injected large conditioning reads large (positive)

- **WHEN** the control runs an utterance with a large, known workspace
  conditioning difference injected
- **THEN** the conditioned arm's output differs from the bare arm's output
- **AND** the reported divergence is above a high floor

#### Scenario: The control exercises the real conditioning path

- **WHEN** the real control client is constructed at the cycle entrypoint
- **THEN** it builds the conditioned prompt with Lingua's own `ContextAssembler`
  and runs it through the language-organ chat client
- **AND** empty conditioning reproduces Lingua's "nothing salient" prompt
- **AND** `kaine.evaluation` imports no `kaine.modules.*` code (the coupling is a
  duck-typed seam injected at the entrypoint)

### Requirement: The negative control is a permanent automated test

The negative control SHALL be a permanent, always-on automated unit test: a
phantom signal there (non-zero divergence when the two arms are conditioned
identically) invalidates every divergence result the meter produces, so it must
never be allowed to regress silently. Because identical text embeds to an
identical vector under any embedder, this property is embedder-agnostic and the
permanent test SHALL run with the dependency-free `HashEmbedder` so it needs no
model to execute.

#### Scenario: Negative control runs without a model

- **WHEN** the test suite runs with no sentence-transformer model present
- **THEN** the negative control still executes using `HashEmbedder`
- **AND** asserts divergence below the floor for identically-conditioned arms

#### Scenario: Embedder validity is explicit for the positive control

- **WHEN** the positive control asserts a large divergence
- **THEN** the STRUCTURAL claim (different conditioning → different output →
  divergence above zero) is validated with `HashEmbedder` (always-on, lexical)
- **AND** the SEMANTIC claim (large semantic divergence) is validated with the
  sentence-transformer embedder when the model is available, and is skipped
  rather than faked when the model is absent

### Requirement: Controlled offline runners for the passive instruments
The system SHALL provide a controlled, seeded, offline runner for each of the A/B-divergence, memory-coherence, and self-model (Eidolon) instruments. Each runner SHALL execute a FIXED stimulus battery against the instrument's production control seam and emit a shared-schema `Verdict` plus seeded JSONL. Each runner SHALL call `set_global_seed(seed)` at the start of a run so that, given the same seed and battery, the verdict and reported metrics are reproducible. Each runner SHALL run headless without an entity boot and without attaching to live modules, the network, or any external service — using deterministic / echo clients and an in-memory Mnemos only. Each runner SHALL expose a `__main__` CLI accepting at least `--seed` and `--out`.

#### Scenario: Each runner emits a verdict on its battery

- **WHEN** any of the three runners is invoked on its fixed stimulus battery
- **THEN** it emits a shared-schema `Verdict` (WIN or NULL) with the per-case
  measurements carried in the verdict's metrics and written to JSONL

#### Scenario: A seeded run reproduces

- **WHEN** a runner is invoked twice with the same seed and battery
- **THEN** the verdict and the reported metrics are identical across the two
  invocations (the wall-clock timestamp excepted)

#### Scenario: The A/B runner shows dynamic range

- **WHEN** the A/B-divergence runner executes its battery containing both
  empty-conditioning cases and heavy-conditioning cases through `divergence_control`
- **THEN** every empty-conditioning case reports divergence approximately 0
- **AND** every heavy-conditioning case reports divergence above the configured
  floor
- **AND** the verdict is WIN only when both hold (the meter has dynamic range)

#### Scenario: The memory runner's advantage is retrieval

- **WHEN** the memory-coherence runner runs its planted-fact battery through a
  full-system retrieval arm and a bare arm, then re-runs the SAME full-system client
  against an EMPTIED Mnemos as a recorded check
- **THEN** with the facts planted, the full-system arm's accuracy exceeds the bare
  arm's by at least the configured floor
- **AND** a never-stored fact yields honest non-recall scored 0
- **AND** with the Mnemos emptied the full-system advantage vanishes, proving the
  advantage is produced by retrieval and not a hard-coded answer

#### Scenario: The self-model runner validates the scorer

- **WHEN** the self-model runner runs its battery of planted-signal / claim cases
  through the calibrated Eidolon scorer
- **THEN** the verdict reports the scorer's accuracy on the known cases
- **AND** the record states that this validates the scorer's
  trait-keyword-vs-derived-signal arithmetic, not predicted-vs-actual self-knowledge

#### Scenario: Offline, no entity boot

- **WHEN** any of the three runners is invoked
- **THEN** it uses only deterministic / echo clients and an in-memory Mnemos over
  no network
- **AND** it does NOT boot an entity, attach to live modules, or open a network
  connection

