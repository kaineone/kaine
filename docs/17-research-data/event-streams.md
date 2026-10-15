# Research event streams

This page is for researchers reading a run, operators exporting one, and contributors adding a stream. It lists the module streams that feed the evaluation sidecar, the rules that keep that list from drifting, the payload fields of the predictive processors' reports and of the broadcast, and the event taxonomy that removes content before export.

## Canonical stream registry

`kaine/evaluation/stream_registry.py` is the single source of truth for the set of module streams. It defines the static `CANONICAL_MODULE_NAMES` tuple and builds stream names with `module_stream()` from `kaine/bus/schema.py`. It does not import `kaine/modules`, because the evaluation package must not depend on module code; the drift tests compare the static tuple against the real module packages from the test side.

Four consumers take their stream lists from the registry helpers:

| Consumer | Registry helper | Source file |
|---|---|---|
| Research-event observer | `curated_module_streams()` | `kaine/evaluation/observers/research_event_observer.py` |
| Raw bus archive | `raw_archive_module_streams()` | `kaine/evaluation/observers/raw_bus_archive_consumer.py` |
| dashboard diagnostics panel | `diagnostics_streams()` | `kaine/dashboard/__main__.py` |
| dashboard record consumer | `diagnostics_streams()` | `kaine/evaluation/observers/dashboard_record.py` |

All four call the registry helpers, so a stream added in one consumer and not in the registry fails the drift tests.

## What each list includes and excludes

The registry treats each canonical module as one `<module>.out` stream. The lists differ as follows.

- `curated_module_streams()` and `raw_archive_module_streams()` both add `action_selection_feedback.out` and `positive_control.out`.
- The curated list leaves out `vocal.out` (raw audio) and `language.out` (the language organ's text) so that the research log stays content-free. The raw archive keeps every produced stream.
- `diagnostics_streams()` leaves out the low-signal operational streams `action_selection.out`, `embodiment.out`, `perceptual_locus.out`, `welfare.out`, `preservation.out` and `individuation.out`, and appends `workspace.broadcast`. It includes `cycle.out`, which carries the cycle's `cycle.tick`, `cycle.rates` and `cycle.time_scale` events.

The language module (`kaine/modules/language/module.py`) publishes on `language.external` and `language.internal` and mirrors every utterance to `language.out`, which the raw archive and the dashboard diagnostics tail follow.

## Drift tests

`tests/test_stream_registry_drift.py` checks that the curated list, the raw-archive list and the diagnostics list each equal the set derived from the registry. The check is set equality, so a stream added to one consumer list without the registry fails, and a stream added to the registry reaches every consumer.

## Processor report fields

Every event carries its intensity in the event's `salience` field (the code's name for the intensity the producing module reports). The predictive processors also put the following fields in their report payloads.

| Field | Events | Meaning |
|---|---|---|
| `alert` | `vision.report`, `audition.perception` (acoustic), `audition.emotion` (tone), `interoception.report`, `sequence.report`; also the alert-level events of other modules, such as `affect.drive`, `affect.emotion`, `interoception.fatigue`, `interoception.regulation` and `sleep.sleep.completed` | On a processor report, true when the report met the processor's alert criterion and was published at the module's alert intensity; on another module's event, true when the event was published at that module's alert level. False when the intensity was graded from the error ratio. For the tone event it is true for any non-neutral tone under the default tone rule and never under the tone variant's rule; for the interoception module it is true when a host metric is past its hard threshold. The access rate's phasic input counts only events with `alert` true. |
| `context_gain` | `vision.report`, `audition.perception`, `interoception.report` | Cross-module broadcast information gain for this report: the forward model's error under the null context minus its error under the context it holds, divided by its running mean error. Positive values mean the other modules' share of the context helped the prediction. Null until the processor has adopted its first accessed broadcast. |
| `null_prediction_error` | `vision.report`, `audition.perception`, `interoception.report` | The error the scored prediction would have had under the null context, with the same weights. Null when `context_gain` is. |
| `mean_prediction_error` | `vision.report`, `audition.perception`, `interoception.report` | The running mean error that `context_gain` is divided by, so `context_gain` equals `null_prediction_error` minus `prediction_error`, over this value. Null when `context_gain` is. |
| `context_age_s` | `vision.report`, `audition.perception`, `interoception.report` | Entity seconds since the broadcast the processor holds as context was published (since its receipt when it carries no publication time), or null before the first adoption. All three measure it on the shared entity clock. |
| `prediction_broadcast_tick` | `vision.report`, `audition.perception`, `interoception.report` | The tick index of the latest broadcast the processor had received, accessed or inhibited, when it formed the prediction this report scores. That prediction was formed at the previous report. Null when the report scores no prediction (the first report, or the first after a skipped reading). The contrast at threshold assigns each report to the broadcast whose receipt preceded its prediction (paper Appendix A.8). |
| `prediction_context_age_s` | `vision.report`, `audition.perception`, `interoception.report` | The age of the context the scored prediction used, read when the prediction was formed, in entity seconds. Null when `prediction_broadcast_tick` is, or when the processor held no context then. It differs from `context_age_s`, which is the age of the context held at this report and used for the next prediction. The contrast at threshold bins reports by this age. |
| `entity_time_s` | `vision.report`, `audition.perception`, `interoception.report` | The shared entity clock's reading at the report, in entity seconds since the run started. The planned test counts a report only after the learning period T_learn, which is measured on this clock (paper Appendix A.8). |
| `awake` | `vision.report`, `audition.perception`, `interoception.report` | False while the sleep module holds the processor asleep. The planned test counts only reports made while the entity was awake. |

The null context keeps the reporting processor's own share of the context and replaces every other source's share with its mean over the contexts the processor has adopted so far in the run. The interoception module's null context also keeps the language module's share, because the language organ's load on the host would otherwise let its share predict the interoception module's input. The context and its null are built from one reading of the clock, so they carry the same age and flags. The sequence module publishes no `context_gain`, since the broadcast is its input. The context itself is computed in `kaine/modules/context.py`: a 24-component featurization of the accessed members of the latest accessed broadcast, weighted by the intensity each member reported, plus the context's age. An inhibited broadcast leaves the context unchanged.

These fields are on the bus and in the raw archive. The curated research log keeps only the keys in its allowlist (below). It records `alert` on every processor report, `context_gain`, `null_prediction_error`, `mean_prediction_error`, `context_age_s`, `prediction_broadcast_tick`, `prediction_context_age_s`, `entity_time_s` and `awake` on `vision.report`, `interoception.report` and `audition.perception` (logged with its numeric fields only, never the playlist item title), `alert` on `affect.drive`, `affect.emotion` and `sleep.sleep.completed`, and, on each broadcast record, `published_at` and, when the broadcast had candidates, `access_threshold`. Competitive and matched broadcasts, empty ones included, also carry `coalition_capacity`, the coalition size K, which the calibration tool uses to tell whether competition ever operated in a run.

## Positive control records

The positive control of the information-gain measure (paper §6.3, Appendix A.8) is enabled only by the workspace-mediation study configurations, in one of three modes set by `[positive_control].mode`.

**`estimate_pc`, the preliminary run.** The vision, audition and interoception modules each accumulate the mean and covariance of their awake, finite inputs. At shutdown each writes its inputs' first principal component v_j (the unit direction along which they vary most) and their mean mu_j to `data/evaluation/positive_control/<run_id>/principal_component_<processor>.json`, with the number of inputs and the projection's variance. No input is stored. The terminal `positive_control.result` record carries the file's sha256 in `pc_sha256`.

**`ladder`, the pilot runs of the on arm.** Each processor runs shadow copies of its forward model beside the live one, an informative and an uninformative one at each signal-to-noise ratio 4^-2, 4^-1, ..., 4^4 (fourteen shadows). Each shadow's context carries one extra component. The informative component is v_j^T (x - mu_j), the next input projected on the preliminary run's principal component, plus Gaussian noise whose variance is that of the earlier projections divided by the SNR. The uninformative component has the same running mean and variance and does not depend on the input. The noise is seeded from `[positive_control].seed` and the run's seed, so different runs draw independent noise. The shadows score in hindsight, forming at each report the prediction the previous report's state would have formed, so the extra component can carry the next input without the live model ever seeing it. After each awake report on which the live gain and every shadow's error difference are defined, the processor publishes a `positive_control.ladder` event with `processor`, `entity_time_s`, `gain` (the live `context_gain`), `gain_with` and `gain_noise` (each shadow's gain, one per rung, over the live model's running mean error), `snr` (the ladder) and `pc_sha256`. Every report is recorded; the calibration tool removes the reports before the learning period afterwards.

**`control`, the control itself.** Each processor runs one informative and one uninformative shadow at its own SNR_j, and reads SNR_j, `min_effect`, `min_reports`, the learning period T_learn and the principal components from the settings record named by `[positive_control].settings_record` (see [Settings of the planned test](../15-experiments/README.md#settings-of-the-planned-test)). The shadows learn on every report, but a report counts only when the entity was awake, its entity time is after T_learn, and the live gain and both shadow error differences are defined. After each counted report the processor publishes a cumulative `positive_control.result` event: `processor`, `mode`, `n_reports`, `ig_with` (the informative shadow's mean gain, with the component nulled to its running mean), `ig_without` (the live model's mean `context_gain` on the same reports), `ig_noise` (the uninformative shadow's mean gain), `effect` (`ig_with` minus `ig_without`), `noise_effect` (`ig_noise` minus `ig_without`), `min_effect`, `min_reports`, `snr`, `t_learn_s`, `settings_sha256`, `pc_sha256`, `detected`, `noise_detected`, `passed`, `failed` and `final`. All gains share one denominator, the live model's running mean error on that report, so a smaller shadow error cannot inflate the effect.

The control never delays a report. Each processor publishes its report first and then queues the control's step for that report; one worker per processor runs the steps in order, off the report path, with the live model's sleep flag as it was at the report. If more than 256 steps are waiting, the control has fallen behind, so it fails and publishes a failure record. At shutdown the processor waits for the queued steps, within `[positive_control].shutdown_drain_s` (5 seconds by default), before it publishes the terminal record. If they do not finish in time, it stops the control and publishes one failure record, so the run fails closed and shutdown continues. A control publishes exactly one terminal record: a failure after the control has already failed or finished publishes nothing. Both events go to `positive_control.out`, a stream the cycle never reads as candidates, and the curated research log keeps every field named above. A processor's last result must be its only terminal one. During shutdown the cycle has every processor publish its result with `final` true before it stops the research log, and the research-event observer drains its streams when it stops, so that record reaches the log. If the control raises, the processor logs the error, publishes a last result with `failed` and `final` true and `passed` false, and stops the control for the run.

The live test runs only after the measure passes for every processor. `python -m kaine.experiment.positive_control <run_id> [<run_id> ...]` checks complete control runs in the given order. It considers only results in mode `control`. Each run's records for a processor must hold no failed result and exactly one terminal record, with nothing after it, whose numbers are finite and whose effects equal the differences of the IG means. When one run has fewer than `min_reports` counted reports, the check pools the next runs, weighting each run's means by its report count, until the processor reaches `min_reports` (paper A.8: "the effect is taken over consecutive complete runs until it reaches that number"); later runs are not used for that processor, an incomplete run inside the pool fails it, and runs with different settings fail it. The verdict is re-derived from the numbers, never from a record's `passed`: the pooled `effect` must reach `min_effect` and the pooled `noise_effect` must stay below it. The check exits 0 only when all three processors pass and no record line failed to parse.

## Broadcast metadata

Each `workspace.broadcast` event carries `tick_index`, `inhibited`, `time_scale`, `salience_scores` (the score of every candidate, keyed by the candidate's id `<stream>:<entry_id>`, which is also each coalition member's `entry_id`), the coalition under `selected`, and a `metadata` object. The workspace writes the access threshold into `metadata` as `access_threshold`. A coalition member is accessed when its score reaches that threshold, and a broadcast is accessed when at least one member is; this is how a processor tells accessed members from members that rode along below the threshold. When the oscillatory coherence layer is on, `metadata` also carries `coherence`.

The curated research log's `workspace.broadcast` record keeps `tick_index`, `inhibited`, `salience_scores` and, for each coalition member, `entry_id`, `source`, `type`, `salience` and `causal_parent`. It never copies a member's payload or the `metadata` object. A member's `entry_id` is the same `<stream>:<entry_id>` id that keys its score. Records from earlier versions key `salience_scores` by the bare bus entry id. Those ids were unique only within a stream, so where two streams issued the same id in one millisecond the table holds one score for the two candidates, and the lost score cannot be recovered. A reader that looks up a member's score with the member's own id reads old and new records alike, since that id has the same form as the keys in the same record; `kaine.bus.schema.split_stream_entry_key` returns a stream of None for a bare id. The tone analysis is the exception: it joins records on the qualified id and refuses a bare one. No pilot or live run was recorded before the change.

## Tone events

The tone analysis of the planned test (paper Appendix A.8, "Speech sound and tone") asks whether emotional tone events are accessed content more often than neutral ones in the tone variant of the on arm. The research log's `audition.emotion` record keeps `category`, `confidence`, `scores`, `alert`, `tone_error_ratio` (the tone model's error ratio), `tone_rule`, `classified`, `entity_time_s` (the entity time at which the tone was classified) and the event's stream-qualified id `<stream>:<entry_id>` in `entry_id`, the same id the broadcast record gives the event as a member. A tone event is accessed content when it is a member of a broadcast that is not inhibited and its score in `salience_scores` reaches `access_threshold`. `kaine.experiment.tone_analysis` joins a tone event to a member on its source, type and id together. It refuses a tone event or member whose id has no stream, since a bare bus id is unique only within its stream, and a broadcast whose members share an id, which would mean a corrupt record. A record without a stream in its ids was written before candidate ids carried the stream; the analysis raises `ToneAnalysisError` naming it as such and never adds a stream to a bare id, because a bare id's table may already have lost a score. Such a run must be recorded again. It counts only events with `classified` true that come after the learning period T_learn, that is with `entity_time_s` above it, and computes two run-level statistics: the difference, the accessed fraction of the emotional tone events minus that of the neutral ones, and the adjusted difference, the plain mean of that difference within each tone bin over the bins that hold both classes. A tone record without `entity_time_s` was written before tone events carried the entity time; the analysis refuses it and the run must be recorded again. The calibration's tone bins are the quintiles of the error ratio over the same events, emotional and neutral, pooled over the tone-variant pilot runs on the counted seeds, and the tone section stays blocked while T_learn is not known. Each enters its own sign test at alpha 0.05 with no multiplicity adjustment; neither enters the verdict on the hypothesis. The range sweep bounds `tone_error_ratio` below by 0.

## Event taxonomy and allowlists

The research log is content-free. The allowlists in `kaine/evaluation/observers/research_event_observer.py` name the exact payload keys kept for each event type, and only those keys are copied. Each record is first passed through the privacy filter, which strips content fields such as `text`, `transcription` and `internal_speech`. The `intent.*` family is matched by exact key, so an unknown intent subtype is dropped. An event type that is not in the taxonomy produces no record, and a payload key that is not in its allowlist is dropped.

The taxonomy never includes latent vectors (`temporal_context`, `feature_vector`), transcripts or raw audio, and `audition.transcription` is deliberately absent. A regression test loops over the whole taxonomy and asserts that no latent field name appears in any allowlist.

New event types must be added to the observer's `_TAXONOMY`; unlisted types are dropped. See [Research participation](./participation.md) for how the curated log becomes a submission bundle, and [The evaluation sidecar](./README.md) for the overall flow.

## Sleep-time realization audit

The sleep module publishes `sleep.ignition_audit` (the code keeps the name "ignition" for a realized intent) on `sleep.out` at every sleep. The record is content-free and export-eligible. It is merged into the sleep's `PhaseResult` metadata and rides `sleep.sleep.completed` into the sleep-snapshots JSONL, carrying `sleep_index`. See the [sleep module](../09-modules/sleep.md) for how sleep is managed.

The audit classifies every realized speech, action or rest since the previous sleep into one of four buckets, checked in order:

1. `planning_initiated`: the realized intent carries `origin: "planning"`.
2. `input_triggered`: the coalition behind it contains `audition.transcription` or `embodiment.chat`.
3. `drive_triggered`: the coalition path contains `affect.drive`.
4. `self_initiated`: none of the above.

Realized events are those of type `external_speech`, `internal_speech`, `vocal.synthesized` or `effectors.action`, and a sleep whose `trigger` is `"requested"` counts as a realized rest. `realization_failed` events are counted separately and never as realized.

The research log keeps only these fields:

| Field | Meaning |
|---|---|
| `sleep_index` | The sleep window this audit covers. |
| `realized_total` | Realized speech, action and rest events in the window. |
| `input_triggered` | Realizations triggered by an external input. |
| `drive_triggered` | Realizations triggered by a drive. |
| `self_initiated` | Realizations that were neither input- nor drive-triggered. |
| `planning_initiated` | Realizations whose intent originated in the planning module. |
| `planning_proposals_realized` | Planning module proposals that were realized. |
| `planning_proposals_declined` | Planning module proposals that were not realized. |
| `planning_proposals_forwarded` | Planning module proposals forwarded to the sleep module as a rest request. |
| `unrealizable_planning_intents` | `intent.*` events on `planning.out`. No effector reads that stream, so this counter flags a wiring fault and should read zero. |
| `realization_failed_count` | `realization_failed` events in the window. |
| `audit_error` | A non-fatal error met while building the audit. |

`planning_proposals_forwarded` is reported on its own because the sleep module decides whether a forwarded rest becomes sleep; an accepted one appears as a requested sleep. The per-category `entry_id` lists, event types and intensities stay inside the sleep-snapshots payload, and no text, transcript or latent vector leaves the audit.
