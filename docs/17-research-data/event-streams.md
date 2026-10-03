# Research event streams

Researchers, operators exporting a run, and contributors adding a stream all need the canonical list of module streams that feeds the evaluation sidecar, the rules that keep the list from drifting, and the event taxonomy that removes content before export.

## Canonical stream registry

`kaine/evaluation/stream_registry.py` is the single source of truth for the set of module streams. It defines the static `CANONICAL_MODULE_NAMES` tuple and imports `module_stream()` from `kaine/bus/schema.py` to build stream names. It does not import `kaine/modules`. That separation is deliberate: the evaluation package must not depend on module code.

Four consumers take their stream lists from the registry helpers:

| Consumer | Registry helper | Source file |
|---|---|---|
| Research-event observer | `curated_module_streams()` | `kaine/evaluation/observers/research_event_observer.py` |
| Raw bus archive | `raw_archive_module_streams()` | `kaine/evaluation/observers/raw_bus_archive_consumer.py` |
| Nexus diagnostics panel | `diagnostics_streams()` | `kaine/nexus/__main__.py` |
| Nexus record consumer | `diagnostics_streams()` | `kaine/evaluation/observers/nexus_record.py` |

Because all four call the registry helpers, adding a stream in one place without updating the registry breaks the drift tests.

## What each list includes and excludes

The registry treats each canonical module as one `<module>.out` stream. Two lists add an extra stream, and two apply extra exclusions.

- `curated_module_streams()` adds `volition_feedback.out`.
- `raw_archive_module_streams()` adds `volition_feedback.out`.
- The curated log excludes `vox.out` (raw audio) and `lingua.out` (transcripts) to stay content-free.
- `diagnostics_streams()` excludes the low-signal operational streams `volition.out`, `mundus.out`, `perception.out`, `welfare.out`, `preservation.out` and `individuation.out`, and appends `workspace.broadcast`. It includes `cycle.out`, which carries the cycle's `cycle.tick`, `cycle.rates` and `cycle.time_scale` events.

The Lingua module in `kaine/modules/lingua/module.py` publishes `lingua.external` and `lingua.internal`, not `lingua.out`. The registry lists `lingua.out`, and the consumer helpers do not expand it into the two real streams. The raw archive and Nexus diagnostics therefore subscribe to `lingua.out` and do not consume Lingua output.

## Drift tests

`tests/test_stream_registry_drift.py` checks that the curated list, raw-archive list, and diagnostics list are each exactly equal to the corresponding registry-derived set. Set equality, not subset equality. Adding a stream to one consumer list without adding it to the registry fails the test. Adding a stream to the registry updates all consumers automatically.

## Event taxonomy and allowlists

The research log is content-free. Allowlists in `kaine/evaluation/observers/research_event_observer.py` describe the exact fields that producers emit today, and only those fields are kept. Exact keys are matched for the `intent.*` family, not prefix-matched; unknown subtypes are dropped. Unknown event types produce no record at all, and unknown payload fields are dropped.

The taxonomy never includes latent vectors (`temporal_context`, `feature_vector`), transcripts, or raw audio. `audition.transcription` is intentionally absent. A regression test loops over the whole taxonomy and asserts that no latent field name appears in any allowlist.

See [Research participation and export](./participation.md) for how the curated log becomes a submission bundle, and the [Evaluation sidecar](./README.md) for the overall flow.

## Sleep-time ignition audit

`hypnos.ignition_audit` is a content-free, export-eligible record emitted on every sleep on `hypnos.out`. It is merged into the sleep `PhaseResult` metadata and rides `hypnos.sleep.completed` into the sleep-snapshots JSONL, carrying `sleep_index`. See the [Hypnos module](../09-modules/hypnos.md) for how sleep is managed.

The audit classifies every realized speech or action since the previous sleep into one of four buckets, checked in order:

1. `nous_initiated` — the realized intent carries `origin: "nous"`.
2. `input_triggered` — the winning coalition contains `audition.transcription` or `mundus.chat`.
3. `drive_triggered` — the coalition path contains `thymos.drive`.
4. `self_initiated` — none of the above.

Realized events are those with type `external_speech`, `internal_speech`, `vox.synthesized`, or `praxis.action`. `realization_failed` is excluded from the realized counts. A sleep whose `trigger` is `"requested"` counts as a realized rest.

The audit publishes only these numeric/categorical fields in the research log:

| Field | Meaning |
|---|---|
| `sleep_index` | The sleep window this audit covers. |
| `realized_total` | Total realized speech/action/rest events in the window. |
| `input_triggered` | Realizations triggered by an external input. |
| `drive_triggered` | Realizations triggered by a drive. |
| `self_initiated` | Realizations that were not input- or drive-triggered. |
| `nous_initiated` | Realizations whose intent originated in Nous. |
| `nous_proposals_realized` | Nous intents that were realized. |
| `nous_proposals_declined` | Nous intents that were not realized. |
| `nous_proposals_forwarded` | Nous intents forwarded to Hypnos as a rest request. |
| `unrealizable_nous_intents` | `intent.*` events on `nous.out`; no effector reads this stream, so these are wiring signals and this counter should read zero. |
| `realization_failed_count` | `realization_failed` events in the window. |
| `audit_error` | Non-fatal error encountered while building the audit. |

`nous_proposals_forwarded` is reported separately because Hypnos decides whether to turn a forwarded rest into sleep; if accepted, it appears as a requested sleep. The per-category `entry_id` lists, event types, and salience values stay inside the sleep-snapshots payload only. No text, transcripts, or latent vectors leave the audit.

New event types must be added to the observer's `_TAXONOMY`; unlisted types are dropped.
