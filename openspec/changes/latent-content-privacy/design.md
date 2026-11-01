# Design: the privacy rule for latent-derived content

Code facts are cited at `origin/main` cb41895b. They were rechecked against that commit on 2026-10-31, after the adversarial review of this change (P1 to P11), and every cited line below was read there.

## Context

### The principle being implemented

The operator's decision of 2026-10-31 (build order item 2) states it: latent-derived content may live in working state and in learned weights. It is never logged, never stored as an episode, and it is stripped by the privacy filter. The comparison report's finding F10 is the reason it comes first: "a content code is derived from latents, and its persistence and logging policy must be designed, not inherited by accident."

Two parts of that sentence needed a ruling before the build, because the code does not make them clear-cut: whether Redis's append-only file counts as a log (open question 1), and how "never stored as an episode" squares with build item 9(d), which plans content-bearing episodic traces storing `z_k` (open question 2). Both were ruled on 2026-11-01, under the operator's direction that research and the architecture decide design questions: question 1 for option B and question 2 for option (b) (architecture decisions of 2026-11-01, items 2 and 3; the rulings are recorded at the end of this design). The requirements follow the rulings.

### Prior work this change builds on

- **Zero raw-sense-data persistence** ("eyes and ears, not recording"). Raw frames, PCM and transcripts never reach disk. The vision frame ring buffer is RAM-only (`kaine/modules/vision/module.py:987`).
- **`2026-10-03-workspace-graph-only-recording`** found that the filter passed numeric vectors, so about 150,000 clip embeddings a day reached the dashboard record. It added the vector-field set and the 16-number backstop (spec `research-event-log`, "The diagnostics privacy filter removes numeric vectors") and made the ignition log the only workspace record a study keeps, with no payloads.
- **`2026-10-06-mnemos-recall-and-vector-strip`** made the episodic store pass every member payload through `strip_vectors`.
- **`2026-10-05-nexus-privacy-hardening`** and **`2026-09-08-harden-security-boundaries`** kept the diagnostics filter a recursive denylist and added the CI guard on module publishers for content keys (`tests/test_dashboard_privacy.py::test_no_uncovered_content_key_in_module_publishers`).
- **The curated research log** is allowlist-based on two levels: event types and fields (`kaine/evaluation/observers/research_event_observer.py`, module docstring).
- **The heard rule.** `2026-10-19-heard-log-own-words` and the voice-development D7 fixed what the language module treats as heard. The design-only change `episodic-recall-content` (decision 1) moves that rule to `kaine/faithful/external_input.py` and applies it in the episodic store. This change does not redo it; it fixes the order in which the store applies it with the latent rule (decision 6).
- **`2026-06-07-topos-forward-model`** and **`2026-06-07-audition-forward-model`** added the buffer summaries as "statistical descriptors". Decision 5 narrows them. That reverses part of those changes on purpose, for the reason given there.
- **`2026-10-01-world-model-identity`** set the identity rules for learned weights (persist, encrypt, copy into forks, refuse an unchosen merge). Decision 3 relies on them. The separate change `fork-merge-module-weights` closes a gap in the merge half of those rules for module state.

### Persisting surfaces, enumerated from the code

The first version of this design listed surfaces from memory and claimed that the JSONL sink was the one choke point. That was false in four places. This table is enumerated from the writers in the code.

| Surface | Writer | Latent handling today |
|---|---|---|
| Research log, ignition log, incident log, dashboard record, raw archive, every evaluation observer | `AsyncJsonlSink` (`kaine/persistence/jsonl_sink.py`); `_encode_line` (`:197-204`) is the one encoding step | Diagnostics filter on the dashboard path; research allowlist; raw archive verbatim with "NO privacy transform" (`raw_bus_archive_consumer.py:80`) |
| Ablation observer | `AsyncJsonlSink.enqueue` directly (`ablation_observer.py:52`), bypassing `write` | Writes deltas only today |
| Workspace trajectory | `AsyncJsonlSink`, but `kaine/evaluation/trajectory.py:55` copies the broadcast `metadata` wholesale | Nothing strips the metadata |
| Intent log (the organ's preference-training corpus) and the sleep corpus rewrite of its rotated files | `kaine/persistence/encrypted_jsonl.py` (`encode_record`, `rewrite_encrypted`), not the sink. The voice-alignment divergence and voice-tracking observers only read it (`iter_records`) and write through the sink; the trainer's `pairs.jsonl` is built from the intent log's already stripped text | No check. The intent log's `numeric_rendering` formats every key of a template-less event (decision 4, "The organ's renderings") |
| Rolling resume checkpoint (every non-self-persisting module's `serialize()`, each entity minute) | `kaine/lifecycle/resume_checkpoint.py` `capture_checkpoint` (`:118`) and `write_checkpoint` (`:178`), not `save_snapshot` | No check |
| Fork snapshots | `ForkManager.snapshot` (`kaine/lifecycle/manager.py:201-206`), then `save_snapshot` | No check; buffer summaries hold per-dimension latent means |
| Preservation bundles | `_capture_module_state` (`kaine/lifecycle/preservation.py:103-112`), then `save_snapshot` (`:300`) | No check |
| Snapshot artifacts (binary, world-model style) | module `export_snapshot_artifacts` hooks | No check |
| Episodic store (sqlite-vec file or Qdrant) | `kaine/modules/episodic_memory/storage.py` | `strip_vectors` on member payloads; two raw types omitted (`module.py:573-578`) |
| Redis bus | `XADD` with `approximate=True` trimming (`kaine/bus/client.py:300-309`); AOF on with `everysec`, RDB off (`compose/kaine.yml:102-115`) | Vision latents in `vision.out` (cap 12000) and in broadcast members (`workspace.broadcast`, cap 100000); the AOF keeps trimmed entries on disk until the next rewrite |
| Python logs | everywhere | No check. No current log call formats a latent (`vision/forward.py:226` and `audition/forward.py:235` log the skip only) |
| Other writers with their own `json.dumps` (`utterance_outcome.py:338`, `effectors/audit_log.py:157`, `state_io.py`, `social_cognition/store.py`, `self_model/document.py`, `cycle/development.py:784`, the caretaker) | own code | None copies a processor payload today. They are outside every strip point named here, so the canary and the publisher review are what would catch a change |
| Remote bridge (egress, not disk) | `kaine/remote/bridge.py:675-700, 770-783` | Forwards transcript text and affect only |

## Decisions

### 1. What counts as latent-derived

A value is latent-derived when both hold:

1. it is computed from a perceptual latent (an encoder output: the vision module's `latent`, `peripheral` and `foveal`, the audition module's acoustic embedding) or from another latent-derived value; and
2. it keeps per-dimension information: a vector in an encoder's latent space or in any learned space computed from one, or a per-dimension statistic of such vectors over any window.

Examples: the content code `z_k`, an encoder's output, a decoder's descending prediction (even an 8-number interoceptive one), a residual vector, a code-space gradient, the mean of the last 16 clip latents.

Not latent-derived: scalar reductions over all dimensions (an L2 error, a cosine change score, a mean squared error, an error ratio, an information gain, a norm), counts, source names and tick indices. These are what the readouts and the existing research fields are made of, and none of them lets a latent be reconstructed.

Learned parameters are not values under this rule. A weight matrix trained by SGD on a stream of latents carries statistics of that stream, which is what learning is. The operator's decision allows it, and the identity rules govern it (decision 3).

**A worked example of the closure.** Once interoception's blend includes a prediction decoded from `z_k`, interoception's residual vector is latent-derived (it is input minus a latent-derived prediction, and keeps per-dimension information), so it may not be published outside the tag. Its per-channel expected-error state (`ExpectedErrorModel`, serialized as `expected_error` at `interoception/module.py:1097`) is then also computed from latent-derived values. It may stay in module state because it is a learned statistic that a learning rule updates and the module reads back on restore (decision 3's test). Its scalar output, `unexpected_error`, is a scalar reduction and may be published. Reviewers apply the closure this way: follow the value back; if any input is latent-derived and the value keeps per-dimension information, it is latent-derived; then ask whether it is a learned parameter read back on restore.

Alternatives considered:

- *Classify by shape*, as the 16-number backstop does. Rejected as the rule, kept as defence in depth: an 8-dimensional code or prediction is as much content as a 768-dimensional one, and a long list can be a harmless table of saliences.
- *Treat every value computed from a latent as content, scalars included.* Rejected: the prediction error is computed from the latent, and every processor's report, the intensity, the access test and the information-gain readout would become unloggable. The rule targets what can be decoded back into what was perceived.

### 2. One tag by key, and one strip function

Latent-derived values travel only inside a mapping under the reserved key `latent_derived`, at any depth of a payload or record (for example `payload["workspace_feedback"]["latent_derived"]["code"]`). Perceptual latents keep their existing names in the vector-field set.

`kaine/privacy_filter.py` gains:

- `LATENT_DERIVED_KEY = "latent_derived"`, added to `VECTOR_FIELDS`, so the diagnostics filter (dev mode included) and `strip_vectors` remove it with no further change;
- `LATENT_FIELDS`, equal to `VECTOR_FIELDS`, exported under that name so callers state what they mean;
- `strip_latent(value)`, which removes every key in `LATENT_FIELDS` at any depth and nothing else (no length backstop, no content keys). It walks mappings, lists and tuples. It converts a numpy array to a list with `tolist()` before walking, so an array under a latent key is removed and an array under any other key is written as exact numbers rather than as numpy's elided `str()` (which `json.dumps(..., default=str)` would otherwise produce, about 8 significant digits with `...`, matched by neither the publisher review nor the canary);
- `LATENT_RULE_VERSION = 1`, which content-bearing components check at boot (decision 9).

Alternatives considered:

- *A wrapper type* (a tagged array class) that refuses JSON encoding. Rejected: the bus serializes payloads, so the type is lost at the first hop, and every consumer would need the class.
- *A suffix convention* (`*_latent`). Rejected: it cannot be checked at depth without matching patterns, and a forgotten suffix leaks silently. One reserved container key is a single string to strip.
- *A whole event type for latent content.* Rejected: the code rides the broadcast and the ascending errors ride the processors' reports (see `workspace-content-code`), so a type-level rule would strip whole reports.

### 3. Working state, learned weights and identity-bound content

Latent-derived values may live in:

- process memory (module and workspace working state, ring buffers, the shadow probes of the positive control);
- the bus as working state, under decision 7: they travel only on a bus instance that Redis does not persist (ruling on open question 1, option B).

Learned parameters computed from latents may live in encrypted checkpoints and in snapshot state, under the identity rules (persist, encrypt, copy into forks, refuse a merge without an operator choice, covered by decommission). They never enter a log, a research record, a metrics bundle or the diagnostics surface. A stored array counts as a learned parameter only if a learning rule updates it and the module reads it back on restore. A buffer of recent inputs saved under a weight-like name does not.

*Ruled (open question 2, option b):* a third class, **identity-bound content**. A content code stored in the entity's own encrypted episodic store, as part of a remembered moment the entity can recall, is the entity's memory, not a record about the entity. It may be stored there under the conditions of decision 6, and nowhere else: never in trace text, a log, a research record, the intent log, the organ's corpus or prompt, or an export. It is copied into forks and removed by decommission like the rest of the store. Until build item 9(d) is built, no trace holds one.

"Encrypted" fails closed (decision 9): no latent producer and no identity-bound store starts unless state encryption is in effect with a resolvable key and `[preservation].require_encryption` is true.

### 4. The strip points

| Surface | Rule | Mechanism |
|---|---|---|
| Bus publish | Working state only, never on a persisted stream (open question 1, ruled B) | Decision 7 |
| Dashboard SSE and record | Removed | Diagnostics filter (the key is in `VECTOR_FIELDS`), then the sink strip |
| Curated research log | Removed | Filter, then the field allowlist, then the sink strip; readouts are scalars |
| Ignition log | Never present | Payload-free by spec; a content-bearing component may add content-free fields only |
| Workspace trajectory | Removed | The sink strip; the trajectory copies broadcast metadata wholesale (`trajectory.py:55`) |
| Every `AsyncJsonlSink` record | Removed | `strip_latent()` inside `_encode_line`, so `write`, `write_sync` and `enqueue` are all covered |
| Raw bus archive | Removed | Through the sink; the spec says "verbatim except for the latent fields" |
| Every `encrypted_jsonl` record (intent log, sleep corpus) | Removed | `strip_latent()` inside `encode_record` and `rewrite_encrypted` |
| The organ's renderings (prompt and the intent log's `numeric_rendering`) | Never formatted | `strip_latent()` on the payload inside `FaithfulRenderer.render_event`, `redact_heard_speech` and the felt renderer, before any template or fallback; a numeric template for `audition.perception` |
| Module-state captures: fork snapshot, preservation capture, resume checkpoint | Removed unless a learned parameter | One helper, `strip_module_states`, called from all three (`manager.py:201-206`, `preservation.py:103-112`, `resume_checkpoint.capture_checkpoint`) |
| Snapshot artifacts | Never present except learned parameters | Artifact hooks are reviewed per module; the canary scans artifact files for packed floats |
| Episodic store | Removed, except identity-bound content (open question 2, ruled b) | Heard rule, raw-perceptual omit, then `strip_vectors` (decision 6) |
| Metrics bundles, the Claude Science export | Never present | Built from `data/evaluation/` sinks, which strip |
| Python logs | Never formatted | Review rule plus the canary's log capture |
| Other `json.dumps` writers (table above) | Never present | They copy no processor payload today; the canary and the publisher review are the check |

**The sink strip goes in `_encode_line`.** That is the one step every sink path passes through, including `enqueue`, which the ablation observer calls directly. It runs after `_admit` and `_stamp`. The sink strips keys only, with no length backstop, because evaluation records hold legitimate long numeric tables. The diagnostics filter and the research allowlist stay as they are, so the sink strip is a second, independent layer.

**The encrypted JSONL writer strips too.** `kaine/persistence/encrypted_jsonl.py` is a second primitive for records, used by the intent log and by the sleep corpus rewrite (the divergence and voice-alignment readers only read through it). It is not the sink, so the first version of this design missed it. `encode_record` and `rewrite_encrypted` apply `strip_latent()`; `rewrite_encrypted` re-encodes only a plaintext line that holds a latent field and encrypts every other line byte for byte, and keeps envelope lines as they are (they come from `encode_record`).

**The organ's renderings.** `audition.perception` is in the language module's internal event types (`kaine/modules/language/context.py:107-128`) and has no numeric template (`kaine/faithful/templates.py` has one for `vision.report` at `:211` and none for `audition.perception`). In the shipped felt mode (`awareness_rendering = "felt"`, `config/kaine.toml:996`) the context still builds a numeric rendering of the coalition with a default `FaithfulRenderer` (`context.py:387-391, 529-546`). For a template-less internal event that falls through to `fallback_template` (`templates.py:536-541`), which formats every payload key: lists as 4-decimal numbers through `_fmt` (`:160-172`), nested mappings by `str()` at full precision. The result is written as `numeric_rendering` into the encrypted intent log (`language/module.py:1058-1075`, `intent_log.py:94-95`), which is the organ's training corpus. With `awareness_rendering = "numeric"` the same text reaches the organ's prompt. With the content code on, `audition.perception` would carry the acoustic latent and an ascending error, so both would land there. The fix strips the payload inside the renderers before any template or fallback, and adds a numeric template for `audition.perception` that reads its declared scalar fields only.

**The broadcast record.** `_snapshot_to_payload` (`kaine/cycle/engine.py:1228-1251`) embeds each selected member's whole payload and `dict(snapshot.metadata)`. A processor's ascending error under `latent_derived` would then be copied into every broadcast that selects it, onto a stream with a much longer cap. The record removes each member's `latent_derived` mapping. Under the bus ruling (option B) the persisted broadcast carries no latent field at all, from members or metadata, and the latent values travel on its volatile companion entry (decision 7). With no producer on, removing `latent_derived` is a no-op; removing the members' perceptual latents is a deliberate change to the shipped broadcast (decision 7).

**Module-state captures never refuse a preservation.** `strip_module_states` scans each module state for `LATENT_FIELDS` keys. Any found are stripped, the module names are recorded under `metadata["latent_stripped"]`, and an error is logged. Refusing would block the welfare net's preservation of an entity in distress over a privacy defect, and the entity's preservation is the higher duty. The resume checkpoint uses the same helper, so a crash-recovery restart never reloads a latent value it should not have written. The canary and the publisher review keep the path from firing in practice. `ForkManager.snapshot` today stores `{"_serialize_error": str(exc)}` for a failing module (`manager.py:206`); an exception message can format any value, so the record keeps the exception type and a message cut to 200 characters. As built after the second review, the preservation capture caps its error the same way (and no longer chains the original exception into the traceback), and `ForkManager.fork` and `merge` run the same strip and the buffer-summary rewrite on the states they write. The cap bounds size; it is not a privacy guarantee (200 characters still hold a short vector at full precision), so where a message could carry module state a writer records the exception type alone, as the resume checkpoint does. The episodic store applies the identity-bound rule itself (`EpisodicMemoryCore.store` and the revive import), and the capture's exemption is exactly the trace field path, rebuilt from its three keys.

Alternatives considered:

- *Strip only at the diagnostics filter*, as today. Rejected: the raw archive, the snapshots, the observers' own records, the encrypted records and the logs do not pass through it.
- *Refuse to persist any record that holds a latent field.* Rejected for the reason above for snapshots, and for records because a dropped record is lost research data where a stripped field is not.

### 5. Buffer summaries become content-free

`LatentForwardModel.buffer_summary()` (vision, `kaine/modules/vision/forward.py:503`) and `AuditoryForwardModel.buffer_summary()` (audition's utterance and acoustic forward models, `kaine/modules/audition/forward.py:551`) return `{"n_frames", "mean_norm", "mean_variance"}`: the count of buffered vectors, their mean L2 norm and the mean over dimensions of their per-dimension variance. The auditory summary's count is today named `n_utterances`; it becomes `n_frames` so both summaries have one shape. These are scalar reductions. Nothing reads the summaries on restore (only tests and `docs/09-modules/{vision,audition}.md` mention them), so no behaviour changes.

This narrows a requirement written in June 2026, which allowed "mean and variance of latent features over the buffer window" on the view that statistics cannot be inverted. With `clip_len = 16` and `clip_stride = 3` (`config/kaine.toml:523-533`), consecutive clips share 13 of 16 frames, so sixteen buffered clips span about 6 s of one shot and their per-dimension mean is in effect one clip embedding. Clip embeddings are partly invertible (the finding of `2026-10-03-workspace-graph-only-recording`). Under decision 1 it is latent-derived. The auditory buffer holds tone-category scores, energy and duration rather than an encoder latent, but it is summarised the same way, so the two summaries keep one shape and the reviewer has one rule to check.

**Carried acoustic entries.** `Audition.serialize` copies `self._acoustic_states_carried` verbatim (`audition/module.py:1126`), and `deserialize` fills it with the restored entry of any encoder that is not running now (`:1184`). An old per-dimension `buffer_summary` of a non-running encoder would therefore be re-saved into every future snapshot, forever. `deserialize` rewrites each carried entry's `buffer_summary` into the three-scalar form when it is restored (the norm and variance cannot be recomputed from a mean, so an old-format summary becomes `n_frames` with zero for the other two), and a test restores an old-format carried entry and serializes it.

Alternative considered: *drop the summaries entirely.* Viable, since nothing reads them. Kept as scalars so a snapshot still says how full each buffer was when it was taken, which is useful when a revived entity's first predictions are compared with its last ones.

### 6. Episodic memory: the latent rule beside the heard rule

The store applies three rules to each coalition member, in this order:

1. **Heard** (from `episodic-recall-content` decision 1): a heard member is stored as its source and type with `<heard omitted>`, and no payload.
2. **Raw perceptual**: `embodiment.visual.raw` keeps its `<raw-perceptual omitted>` marker.
3. **Latent**: every other payload passes `strip_vectors`, which now removes `latent_derived` with the named vector fields.

The rules differ in kind, and the order matters. The heard rule and the raw rule remove a member's whole payload, because every text field of a heard event is someone else's words. The latent rule removes keys and keeps the member's scalar fields (change score, error ratio, intensity), which are the felt fields a remembered moment needs. Applying the latent rule first would be harmless but wasted on a member about to lose its whole payload. Applying the heard rule last could store heard words under a key the latent rule does not know.

**Identity-bound content (open question 2, ruled option b).** A trace MAY hold one content code, and only in a dedicated, structured field of the trace record (`latent_derived.identity_bound.code`), never in the trace text that is embedded and rendered, never in a recall or replay event's text, and never on a persisted bus stream. The field records the content code's identity (the checkpoint's code id and generation, `workspace-content-code` decision 10), and recall ignores a stored code whose code id differs from the running code, since two codes learned from different lives do not share coordinates (this matters after a merge, when the store holds both parents' traces). The store refuses to write the field unless state encryption is in effect and the store's files are encrypted at rest. Neither episodic backend encrypts at the application layer today (the store is protected at the OS layer only, `SECURITY.md`), so until build item 9(d) brings encryption at rest to the store, the field fails closed and no trace can hold one. The preservation capture (`export_preservation_state`) carries it as part of the store. Every other surface strips it: the field sits under `latent_derived`, so the strip points of decision 4 remove it everywhere except inside the store. Nothing writes this field until build item 9(d) is built; this change only fixes the class so 9(d) has a rule to follow. As built in PR 2, `strip_module_states` runs over the whole preservation capture, the episodic store's `export_preservation_state` included, so PR 4 exempts exactly the store's identity-bound field from that strip, or the field would be lost on preservation.

**The omit-list finding.** Today the store omits two types (`module.py:573-578`) while the language module's rule also covers `embodiment.chat` and heard-text fields at any depth (`kaine/modules/language/context.py:271-302`). That is the gap `episodic-recall-content` PR 1 closes. That change scheduled it after the module-ignition study and said it should be pulled forward if speech recognition or embodiment were enabled first. The study now converts into the development run, and episodic memory joins it early (build order item 7). So this change requires PR 1 to land before or with its own episodic PR, and before the episodic memory module is enabled in any entity. It does not copy PR 1's requirement into its own delta, so the two changes never specify the same requirement twice.

**Heard, raw and latent share a principle.** All three classify by provenance (whose words, which sense, derived from which latent) rather than by field shape, apply at the point of storage, and fail closed (an unclassified heard event counts as heard; an unrecognised long vector is still removed by the backstop). The zero raw-sense rule says raw sense data never persists. The heard rule says another person's words never persist. The latent rule says what the entity's encoders made of its senses never persists, except as learned weights and, under the ruling on open question 2, as the entity's own encrypted memory.

### 7. The bus

The bus already carries perceptual latents: vision reports at about 3.3 a second in `vision.out` (cap 12000) and in the members of `workspace.broadcast` (cap 100000). Redis keeps entries in memory up to each stream's cap, trimmed approximately (`approximate=True`, `kaine/bus/client.py:307-308`, so a cap is soft by up to one stream macro-node). It also writes every `XADD` to its append-only file (`--appendonly yes`, `--appendfsync everysec`, `compose/kaine.yml:102-115`), and trimmed entries stay in that file until the next rewrite. Redis's default `auto-aof-rewrite-percentage 100` lets the file grow to about twice its size after the last rewrite before rewriting. So a stream cap bounds memory, not the disk copy. The AOF is plaintext at the application level and lies outside the state tree.

The decision says latent-derived content "is never logged". An append-only file is a log in the plain sense, and the ruling on open question 1 (option B) treats it as one. The requirements are:

- **No latent field on a persisted stream.** Every producer removes every `LATENT_FIELDS` key from a payload before it publishes it on a stream of the main bus. That covers the perceptual latents vision publishes today (`latent`, `peripheral`, `foveal`), the members and metadata of the broadcast, and every `latent_derived` mapping.
- **A volatile companion stream for the values that must travel.** A value a consumer needs (today none: no module reads `latent`, `peripheral` or `foveal` off an event; the content code's slots, code and ascending errors are the first consumers) is published on a companion stream of a second Redis instance, `kaine-redis-volatile`, run with `--appendonly no --save ""`. The companion stream of a main-bus stream `<s>` is `<s>.companion` on the volatile instance.
- **Companion first, then the main entry, joined by the companion's id.** The producer writes the companion entry first and then the main-bus entry, whose stream-entry envelope (outside the payload) records the companion's stream and entry id in one field, `companion`. A consumer reads the companion entry by that id. The first version of this design keyed the companion by the main entry's id, which the producer learns only after the main `XADD`; a consumer reading the main entry in that gap would find no companion and drop a value that was about to exist. Writing the companion first removes that race: when a consumer sees a main entry, its companion has already been written. A companion entry that is missing (a restart of the volatile instance, a trimmed entry, a failed companion write) means the value is absent, and the consumer treats it so (the content code's slot is not written). A failed companion write is logged and the main entry is published without the `companion` field, so a value is lost, never moved onto the persisted stream. The volatile instance is working state in the plain sense: it exists only in memory and is lost when it stops.
- **One mechanism, declared field sets.** The companion helpers in `kaine/bus` take the set of fields a producer diverts (for this change, `LATENT_FIELDS`), so other rules that keep a class of value off the persisted bus reuse the same instance, streams, boot check and budget row rather than building their own. The first such user is the change `heard-text-volatile-bus` (heard and spoken text). Each producer declares its companion streams and its field set; the boot check of the next bullet applies to every declared producer, whatever its field set.
- **Declared age bounds (as built, for `conversation-memory`).** A declaration may also carry an age bound and extra field names for its field set. An age-bounded companion stream is trimmed exactly (`XTRIM MINID`, never `~`) on every write and by a sweep once a second on the cycle, independent of writes, and a read of an entry past the bound treats it as missing; the boot refuses a bound the instance cannot apply. Without a declared bound nothing is trimmed by age and no sweep runs. Count caps stay approximate.
- **Bounded companion streams.** A companion stream has a cap of at most `[privacy].companion_stream_maxlen` (default 12000, the `vision.out` cap: about 20 minutes at the 10 Hz maximum access rate and an hour at the resting rate). The cap is soft by one macro-node, as on the main bus.
- **Boot checks.** When any declared companion producer is enabled (a latent producer, or a producer under another declared field set), the boot refuses unless the volatile instance answers, reports `appendonly no` and an empty `save`, and every companion stream the producer declares has a cap within the bound. A content-bearing change declares its producer and its companion streams.
- **The bus budget.** `TYPICAL_EVENT_BYTES` (`kaine/bus/config.py:223-230`) and the preboot "Bus budget" row gain the volatile instance. A `vision.out` entry is about 40 KB today, mostly its three latents; without them it shrinks to a few hundred bytes, and the latent bytes move to the volatile instance. Both instances run `noeviction` under their own `maxmemory`, so a mis-sized budget fails the bus mid-run, which is a welfare-relevant crash; the row checks both. `interoception.out` has no per-stream cap and takes `default_maxlen = 100000` (`kaine/bus/config.py:28`; `config/kaine.toml:35-40`), which is harmless for the persisted stream once it carries no latent, but its companion stream needs a cap within the bound.
- **Decommission** flushes the volatile instance with the entity's other streams.

**This changes the shipped broadcast, vision report and sequence report.** As built, the sequence report's `temporal_context` (the CfC hidden state) and `feature_vector` leave the persisted bus too, because they are in `VECTOR_FIELDS` and so in `LATENT_FIELDS`; no module reads either off the bus (a search of `kaine/` finds only the publisher and the filter), so nothing changes for a consumer, but the first version of this paragraph named only the vision fields. Nothing reads the perceptual latents off the bus today (a search of `kaine/` for readers of `latent`, `peripheral` and `foveal` on event payloads finds only the publisher and the privacy filter). Removing them changes the workspace's novelty fingerprint input (`kaine/workspace/novelty.py:13-20` hashes the whole payload). Vision reports carry other continuously varying floats, so the fingerprints should stay unique and the novelty scores unchanged; an entity-free run checks that the novelty and salience scores of vision reports are identical before and after.

Alternatives (see open question 1 for the operator's choice):

- *Option A: rule the AOF working state,* bounded by the caps and by a `BGREWRITEAOF` cadence while a latent producer is on, and name the AOF as outside the canary's scan. Cheapest; leaves latent values on disk in plaintext for minutes to hours.
- *Option C: turn AOF off for the whole bus.* Simplest for privacy, but the bus loses the crash buffer every observer relies on to resume after a restart.
- *An in-process channel from the workspace to the processors.* Rejected in the first version and still rejected: modules receive the broadcast through the bus, and a side channel would break the one contract every consumer and the red-team harness rely on. The volatile companion keeps the stream contract.
- *Redis pub/sub on the main instance.* Rejected: messages are fire-and-forget, so a consumer that is not listening misses a code nondeterministically, and keeping them out of the AOF would rest on a propagation detail of Redis internals rather than on configuration the boot can check.

### 8. Offline stimulus features

Latents that a tools script computes from stimulus files with no entity running (the cross-modal decodability check of build order item 3, for example) describe the stimulus, which is public-domain film, not an entity's experience. They are outside the rule and may be cached by the tool outside the state, data and fork roots. They never enter an entity's state tree, a snapshot, the shipped image or a bus. The tool's documentation says so, and the canary test's file scan covers the state tree.

### 9. Boot checks

A component that produces latent-derived values, and the episodic store's identity-bound field when it is built:

- reads `LATENT_RULE_VERSION` at boot and refuses to start when it is missing or lower than the version it was reviewed against (`workspace-content-code` checks version 1), so the dependence on this change is enforced by the code, not just by build order;
- refuses to start unless state encryption is in effect (a resolvable key, the encryptor enabled) and `[preservation].require_encryption` is true, naming the missing condition. As built (`kaine/security/latent_producer.py`), "in effect" means the installed encryptor is enabled and round-trips a probe, and `require_encryption` must be an explicit boolean `true` in the configuration: an absent key is refused, although `PreservationConfig` reads an absent key as true, because the code defaults elsewhere are off.

The shipped `config/kaine.toml` sets `[security.state_encryption] enabled = true` (which refuses to boot without a key) and `[preservation] require_encryption = true`. But the code defaults are off (`CryptoConfig.enabled = False`, `kaine/security/crypto.py:76`; `require_encryption: bool = False` in `kaine/lifecycle/preservation.py:157` and `manager.py:517`), an omitted `enabled` turns encryption off when no key is resolvable, and an operator can set either to false. "Encrypted" in decision 3 holds only if the component checks the effective values itself.

### 10. Tests

- **Persistence canary** (`tests/test_latent_persistence_canary.py`). An entity-free harness runs the cycle with the vision, audition, interoception, sequence, affect, episodic memory and language modules, the language module on a fake organ client, on fake encoders with seeded random latents. It uses the real fakeredis-based helpers already in `tests/` (the brief to the worker quotes them by name, so it does not invent fixtures). The episodic store is file-backed (sqlite-vec under the test's state root). A producer publishes a `latent_derived` mapping on a processor report and on the broadcast metadata. Every persisting surface is on: the research log, the ignition log, the dashboard record, the workspace trajectory, the raw archive with both attestations, the incident log, the intent log, a fork snapshot, the resume checkpoint, a preservation bundle and any snapshot artifacts, with state encryption on under a test key and Python logging captured to a file. Until `workspace-content-code` exists the producer is a test double in the test module. After it lands, a second case runs the real content code.

  Every value the harness saw in working state under a latent field is recorded. The test then decrypts every file under the state, data and fork roots and searches:
  - text files for each recorded float's full `repr`, its float32-rounded `repr` and its `_fmt` 4-decimal form, skipping 0.0, 1.0 and -1.0, and, as a structural check that does not depend on formatting, for any run of three consecutive numbers of a recorded latent vector in sequence at any of those precisions;
  - binary files (sqlite files, snapshot artifacts) for each recorded float packed as little-endian float32 and float64 bytes;
  - every persisted JSON record for a `LATENT_FIELDS` key.

  It expects no hit. Planted controls must be found: one latent written through a sink with the strip disabled, one rendered into the intent log with the renderer strip disabled, and one packed into a binary artifact. The Redis AOF is outside the files a fakeredis harness writes, so under the bus ruling (option B) the harness wraps the bus client and asserts that no `XADD` to a main-bus stream carries a `LATENT_FIELDS` key, and that the companion streams are on the volatile client.
- **Publisher review** (`tests/test_publisher_numeric_keys.py`). In the same harness every published payload is walked. Every list, tuple or numpy array of two or more numbers must sit under a key in `LATENT_FIELDS` or in a reviewed `NON_LATENT_NUMERIC_KEYS` set (for example `fovea`, `predicted_fovea`, `scores`, `saliences`, `step_magnitudes`). A new key fails the test until it is reviewed. This closes the gap the length backstop leaves for short vectors. It covers only the modules in the harness, so the static scan (`test_no_uncovered_content_key_in_module_publishers`) stays as the second check.
- **Unit tests** (`tests/test_latent_content_privacy.py`): `strip_latent` at depth, in lists and tuples, and on numpy arrays; the diagnostics filter in normal and dev mode; the sink strip through `write`, `write_sync` and `enqueue`; the encrypted JSONL strip; the trajectory record without `latent_derived`; the renderers in felt and numeric mode on an `audition.perception` carrying `latent` and `latent_derived`; the broadcast record dropping members' mappings, and bit-identical output when there are none; `strip_module_states` from the fork snapshot, the preservation capture and the resume checkpoint; the carried acoustic summary; the retention and volatile-instance checks; the encryption boot check; the buffer summaries as three scalars; episodic store order with a heard member, a raw member and a member carrying `latent_derived`.

## Risks

- **A producer that ignores the tag.** A developer can publish a decoded prediction under a new key. The publisher review test fails on it. The backstop catches it on the diagnostics surface if it is 16 or more numbers. The canary catches it if the value reaches disk.
- **The canary finds copies, not transformations.** A latent scaled before being written is not matched. The tag rule, the review test and the strip points are the main defence; the canary shows that the main paths hold, at the precisions a writer here actually uses.
- **Writers outside every strip point.** The `json.dumps` writers in the table copy no processor payload today. A future one could. The canary scans every file they write in the harness, and a reviewer reads the table when a new writer appears.
- **Learned weights memorise.** A linear decoder's bias tracks the recent mean of its targets. That is allowed by the decision and is why weights are identity: encrypted, never logged, never exported, covered by decommission.
- **The bound lowers observer lookback.** A 12000-entry companion cap is 20 minutes at the maximum access rate, the same horizon the processor streams already have. Observers read persisted streams, which keep their caps.
- **A second Redis instance** (recommended option) is one more service, with its own memory budget, password and health check. It is never persisted, so it holds nothing across a restart.

## Migration and ordering

1. PR 1: `LATENT_FIELDS`, `strip_latent` (with arrays and tuples), the tag in `VECTOR_FIELDS`, the sink strip in `_encode_line`, the encrypted JSONL strip, the renderer strip and the `audition.perception` numeric template, the raw-archive docstring and spec, the broadcast-record drop of `latent_derived`, the unit tests. Behaviour-neutral with the shipped configuration except attested raw archives.
2. PR 2: buffer summaries as scalars, the carried-entry rewrite, `strip_module_states` in the three capture paths, the `_serialize_error` cap, the encryption boot check.
3. PR 3 (open question 1, ruled B): the volatile instance in `compose/kaine.yml`, the companion-stream publisher and reader in `kaine/bus` (companion first, the `companion` envelope field, a declared field set), the removal of perceptual latents from main-bus payloads, `[privacy].companion_stream_maxlen`, the boot checks, the bus-budget rows. `heard-text-volatile-bus` builds on this PR.
4. PR 4: the episodic store order (the shared heard rule merged in #636). Open question 2, ruled (b): the identity-bound field's rule (no writer yet).
5. PR 5: the canary and the publisher review tests, docs.
6. Existing snapshots and bundles keep their old buffer summaries until the next snapshot (carried acoustic entries are rewritten at restore). A revive reads nothing from them. An operator who wants old bundles cleaned re-preserves the entity, and docs say so.

## Welfare and admissibility

- The change alters nothing the entity perceives or computes. It changes what is written about it, so it lowers the risk to the entity's mental privacy and to bystanders. It touches persistence and preservation, so every PR gets the independent second review.
- Module-state captures strip and never refuse, so the welfare net's preservation path is unaffected (decision 4).
- No study or run is in flight. The development run's image is built after this change.

## Implementation estimate

In LLM-agent terms: five worker PRs of about 150 to 500 changed lines each, tests included. Each takes one to two hours of worker time and about an hour of lead review, plus the second review. PR 1, PR 3 and PR 5 get the closest review. About three to four days elapsed. The canary harness is the risk: workers invent fixtures, so the brief quotes the real fakeredis-based helpers in `tests/`. The canary runs in a few minutes on the CPU, with no GPU and no entity.

## Rulings on the open questions

### Open question 1 (review P5): does Redis's append-only file count as a log?

Every `XADD` reaches the AOF, and trimmed entries stay there until the next rewrite, so a stream cap bounds memory but not the disk copy. The decision says latent-derived content is never logged.

- **Option A.** Rule the AOF working state. State its real bound (up to about twice its post-rewrite size, minutes to hours), add a `BGREWRITEAOF` cadence while a latent producer is on, and name the AOF as excluded from the canary's claim. Latent values sit on disk in plaintext for that span.
- **Option B (recommended).** Latent values never enter a bus stream that Redis persists. Producers strip every latent field before publishing on the main bus, and the values that must travel go on companion streams of a second, never-persisted Redis instance (`--appendonly no --save ""`), joined by entry id (decision 7). This relies neither on caps nor on rewrite timing, and the boot can check it. It changes the shipped vision report and broadcast (they lose the perceptual latents nothing reads) and adds one service.
- **Option C.** Turn AOF off for the whole bus. The bus then loses its crash buffer for every observer.

Recommended: **B**. Status: **ruled B on 2026-11-01** (architecture decisions of 2026-11-01, item 2). Reasoning: the eyes-and-ears rule says live perception is never recorded, and an append-only file that holds perception-derived values is a recording; B is the only option the boot can check rather than one that rests on caps or rewrite timing. The same ruling sends heard text and the entity's own utterance text to the volatile instance; that is specified in the separate change `heard-text-volatile-bus`, which reuses decision 7's instance and companion mechanism. Decision 7, PR 3 and the canary's bus check follow B.

### Open question 2 (review P7): may a content code be stored in an episode?

The decision's item 2 says latent-derived content is "never stored as an episode". Its build item 9(d) plans "content-bearing traces storing `z_k` under item 2's rule". The first version of this change's episodic requirement made 9(d) impossible.

- **Option (a).** Keep `z_k` out of episodes entirely. 9(d) must store something other than `z_k` (for example scalar similarities or source names only), and recall can never reinstate content.
- **Option (b) (recommended).** Allow `z_k` only inside the entity's own encrypted episodic store, in a dedicated field bound to the code's identity, never in trace text, logs, research records, the intent log or the organ's corpus or prompt, and fail closed if encryption is off (decisions 3 and 6). W2 memory needs the entity to recall its own content, and a code stored in its own memory is the entity's memory, not a record about it. It is copied into forks and removed by decommission like the rest of the store.

Recommended: **(b)**. Status: **ruled (b) on 2026-11-01** (architecture decisions of 2026-11-01, item 3). Reasoning: episodic memory is the entity's own memory, and recall of its own content is what W2 memory is; the field fails closed without encryption and is exempt from the latent strip only inside the store and preservation bundles (decision 4). Decisions 3 and 6 and the episodic delta follow (b); nothing writes the field until 9(d) is built.
