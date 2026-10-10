# Research event streams

This page is for researchers reading a run, operators exporting one, and contributors adding a stream. It lists the module streams that feed the evaluation sidecar, the rules that keep that list from drifting, the payload fields of the predictive processors' reports and of the broadcast, and the event taxonomy that removes content before export.

## Canonical stream registry

`kaine/evaluation/stream_registry.py` is the single source of truth for the set of module streams. It defines the static `CANONICAL_MODULE_NAMES` tuple and builds stream names with `module_stream()` from `kaine/bus/schema.py`. It does not import `kaine/modules`, because the evaluation package must not depend on module code; the drift tests compare the static tuple against the real module packages from the test side.

Four consumers take their stream lists from the registry helpers:

| Consumer | Registry helper | Source file |
|---|---|---|
| Research-event observer | `curated_module_streams()` | `kaine/evaluation/observers/research_event_observer.py` |
| Raw bus archive | `raw_archive_module_streams()` | `kaine/evaluation/observers/raw_bus_archive_consumer.py` |
| Nexus diagnostics panel | `diagnostics_streams()` | `kaine/nexus/__main__.py` |
| Nexus record consumer | `diagnostics_streams()` | `kaine/evaluation/observers/nexus_record.py` |

All four call the registry helpers, so a stream added in one consumer and not in the registry fails the drift tests.

## What each list includes and excludes

The registry treats each canonical module as one `<module>.out` stream. The lists differ as follows.

- `curated_module_streams()` and `raw_archive_module_streams()` both add `volition_feedback.out`.
- The curated list leaves out `vox.out` (raw audio) and `lingua.out` (the language organ's text) so that the research log stays content-free. The raw archive keeps every produced stream.
- `diagnostics_streams()` leaves out the low-signal operational streams `volition.out`, `mundus.out`, `perception.out`, `welfare.out`, `preservation.out` and `individuation.out`, and appends `workspace.broadcast`. It includes `cycle.out`, which carries the cycle's `cycle.tick`, `cycle.rates` and `cycle.time_scale` events.

Lingua (`kaine/modules/lingua/module.py`) publishes on `lingua.external` and `lingua.internal` and mirrors every utterance to `lingua.out`, which the raw archive and the Nexus diagnostics tail follow.

## Drift tests

`tests/test_stream_registry_drift.py` checks that the curated list, the raw-archive list and the diagnostics list each equal the set derived from the registry. The check is set equality, so a stream added to one consumer list without the registry fails, and a stream added to the registry reaches every consumer.

## Processor report fields

Every event carries its intensity in the event's `salience` field (the code's name for the intensity the producing module reports). The predictive processors also put the following fields in their report payloads.

| Field | Events | Meaning |
|---|---|---|
| `alert` | `topos.report`, `audition.perception` (acoustic), `audition.emotion` (tone), `soma.report`, `chronos.report`; also the alert-level events of other modules, such as `thymos.drive`, `thymos.emotion`, `soma.fatigue`, `soma.regulation` and `hypnos.sleep.completed` | On a processor report, true when the report met the processor's alert criterion and was published at the module's alert intensity; on another module's event, true when the event was published at that module's alert level. False when the intensity was graded from the error ratio. For the tone event it is true for any non-neutral tone; for Soma it is true when a host metric is past its hard threshold. The access rate's phasic input counts only events with `alert` true. |
| `context_gain` | `topos.report`, `audition.perception`, `soma.report` | Cross-module broadcast information gain for this report: the forward model's error under the null context minus its error under the context it holds, divided by its running mean error. Positive values mean the other modules' share of the context helped the prediction. Null until the processor has adopted its first accessed broadcast. |
| `context_age_s` | `topos.report`, `audition.perception`, `soma.report` | Entity seconds since the broadcast the processor holds as context was published (since its receipt when it carries no publication time), or null before the first adoption. All three measure it on the shared entity clock. |

The null context keeps the reporting processor's own share of the context and replaces every other source's share with its mean over the contexts the processor has adopted so far in the run. Soma's null context also keeps Lingua's share, because the language organ's load on the host would otherwise let its share predict Soma's input. Chronos publishes no `context_gain`, since the broadcast is its input. The context itself is computed in `kaine/modules/context.py`: a 24-component featurization of the accessed members of the latest accessed broadcast, weighted by the intensity each member reported, plus the context's age. An inhibited broadcast leaves the context unchanged.

These fields are on the bus and in the raw archive. The curated research log keeps only the keys in its allowlist (below). It records `alert` on every processor report, `context_gain` and `context_age_s` on `topos.report`, `soma.report` and `audition.perception` (logged with its numeric fields only, never the playlist item title), `alert` on `thymos.drive`, `thymos.emotion` and `hypnos.sleep.completed`, and, on each broadcast record, `published_at` and, when the broadcast had candidates, `access_threshold`.

## Broadcast metadata

Each `workspace.broadcast` event carries `tick_index`, `inhibited`, `time_scale`, `salience_scores` (the score of every candidate), the coalition under `selected`, and a `metadata` object. Syneidesis writes the access threshold into `metadata` as `access_threshold`. A coalition member is accessed when its score reaches that threshold, and a broadcast is accessed when at least one member is; this is how a processor tells accessed members from members that rode along below the threshold. When the oscillatory coherence layer is on, `metadata` also carries `coherence`.

The curated research log's `workspace.broadcast` record keeps `tick_index`, `inhibited`, `salience_scores` and, for each coalition member, `source`, `type`, `salience` and `causal_parent`. It never copies a member's payload or the `metadata` object.

## Event taxonomy and allowlists

The research log is content-free. The allowlists in `kaine/evaluation/observers/research_event_observer.py` name the exact payload keys kept for each event type, and only those keys are copied. Each record is first passed through the privacy filter, which strips content fields such as `text`, `transcription` and `internal_speech`. The `intent.*` family is matched by exact key, so an unknown intent subtype is dropped. An event type that is not in the taxonomy produces no record, and a payload key that is not in its allowlist is dropped.

The taxonomy never includes latent vectors (`temporal_context`, `feature_vector`), transcripts or raw audio, and `audition.transcription` is deliberately absent. A regression test loops over the whole taxonomy and asserts that no latent field name appears in any allowlist.

New event types must be added to the observer's `_TAXONOMY`; unlisted types are dropped. See [Research participation](./participation.md) for how the curated log becomes a submission bundle, and [The evaluation sidecar](./README.md) for the overall flow.

## Sleep-time realization audit

Hypnos publishes `hypnos.ignition_audit` (the code keeps the name "ignition" for a realized intent) on `hypnos.out` at every sleep. The record is content-free and export-eligible. It is merged into the sleep's `PhaseResult` metadata and rides `hypnos.sleep.completed` into the sleep-snapshots JSONL, carrying `sleep_index`. See [Hypnos](../09-modules/hypnos.md) for how sleep is managed.

The audit classifies every realized speech, action or rest since the previous sleep into one of four buckets, checked in order:

1. `nous_initiated`: the realized intent carries `origin: "nous"`.
2. `input_triggered`: the coalition behind it contains `audition.transcription` or `mundus.chat`.
3. `drive_triggered`: the coalition path contains `thymos.drive`.
4. `self_initiated`: none of the above.

Realized events are those of type `external_speech`, `internal_speech`, `vox.synthesized` or `praxis.action`, and a sleep whose `trigger` is `"requested"` counts as a realized rest. `realization_failed` events are counted separately and never as realized.

The research log keeps only these fields:

| Field | Meaning |
|---|---|
| `sleep_index` | The sleep window this audit covers. |
| `realized_total` | Realized speech, action and rest events in the window. |
| `input_triggered` | Realizations triggered by an external input. |
| `drive_triggered` | Realizations triggered by a drive. |
| `self_initiated` | Realizations that were neither input- nor drive-triggered. |
| `nous_initiated` | Realizations whose intent originated in Nous. |
| `nous_proposals_realized` | Nous proposals that were realized. |
| `nous_proposals_declined` | Nous proposals that were not realized. |
| `nous_proposals_forwarded` | Nous proposals forwarded to Hypnos as a rest request. |
| `unrealizable_nous_intents` | `intent.*` events on `nous.out`. No effector reads that stream, so this counter flags a wiring fault and should read zero. |
| `realization_failed_count` | `realization_failed` events in the window. |
| `audit_error` | A non-fatal error met while building the audit. |

`nous_proposals_forwarded` is reported on its own because Hypnos decides whether a forwarded rest becomes sleep; an accepted one appears as a requested sleep. The per-category `entry_id` lists, event types and intensities stay inside the sleep-snapshots payload, and no text, transcript or latent vector leaves the audit.
