# Design: workspace-graph-only recording

## 0. Sources
- **Operator, 2026-10-03:**
  - "the original plan was to only save the global workspace graphs, so that some future module or phantasia could use them to help train the world model before deleting them. We shouldn't be saving this much data."
  - "I don't think we need to log every thing multiple times per second, just a regular sampling of the things that matter most to the research goals in our paper, looking for ignition in the workspace graph."
- **Operator, 2026-09-26:** describing the study, "documenting the changes in perception via its workspace graph."
- **The paper:** Phantasia is a world model "trained on accumulated workspace trajectories". `docs/02-architecture/README.md:220` says the same.
- **Prior changes this builds on:**
  - `evaluation-sidecar` (2026-05-20): the trajectory recorder, which originally kept "selected events (full payload)".
  - `nexus-privacy-hardening`: routes the trajectory payload through the privacy filter and keeps the trajectory opt-in.
  - `run-recording` (2026-09-28): added the Nexus record and turned it, the trajectory and the ignition log on in studies.
  - `ignition-log`: the payload-free per-broadcast record the analysis reads.

## 1. The workspace graph is the ignition log
The ignition log already records the graph, one row per successful broadcast:
- run id and sequence number;
- tick index, bus entry id, and wall and monotonic time;
- programme position and audio position;
- salience scores and inhibition;
- time scale;
- each coalition member's entry id, source, type, salience and original timestamp.

It holds no payloads. `kaine/research/ignition_study/analysis.py` reads it for coalition size, member sources, inhibition share and drift.

**It is kept at full rate.** An ignition is a discrete event: a coalition crossing threshold and being broadcast. Sampling the log at a fixed interval would drop ignitions and bias every rate the analysis computes. One row per broadcast at up to 10 Hz is about 11 MB an hour, or 0.27 GB a day, so the cost is small. The operator's "regular sampling" asked for less volume. Dropping everything except the graph delivers that without thinning the graph itself.

**Not added:** candidate sources for losing entries. Only the selected events carry a source in the broadcast payload; `salience_scores` is keyed by entry id. Recording who competed and lost would mean changing the broadcast contract that every module consumes. That is out of scope here and can be proposed separately if the analysis needs it.

## 2. Studies record the graph only
`build_overlay` sets:
- `research_event_log.nexus_record.enabled = False`
- `evaluation.workspace_trajectory = False`

It does this the same way it already sets `research_event_log.raw_archive.enabled = False`, so the overlay overrides any operator setting. It keeps:
- `ignition_log.enabled = True`;
- `research_event_log.enabled` and `external_utterances`, which are low volume and were requested by the operator in `run-recording`;
- the evaluation instruments, which are small: the whole `data/evaluation` tree was 1.4 GB over 29 h;
- the preservation and welfare monitors;
- gestation readouts and viability.

The runner, the safety net and the admissibility checks need these. None of them stores module payloads at high rate.

## 3. The workspace trajectory records the graph
`TrajectoryRecorder._filter_selected_entry` keeps:
- `entry_id`, the bus entry id of the member, where today the member loses its own id;
- `source`, `type`, `salience`, `causal_parent`;
- the member's original `timestamp`.

It drops `payload`. The row drops `thymos_state`: affect is module state, and `affect_correlation` already records it for the instruments that need it. The trajectory stays opt-in and is off in studies. Outside studies it remains a graph record for runs that do not enable the ignition log.

## 4. The privacy filter removes numeric vectors
**Where the filter runs.** `PrivacyFilter.filter_for_diagnostics` (`kaine/privacy_filter.py`) has four callers:
- the Nexus bridge;
- the Nexus record;
- the research event observer, which runs the filter before its per-type allowlist;
- the trajectory recorder, on `selected[].payload`.

**Vectors on the diagnostics streams** (audit of 2026-10-03):

| Stream, type | Field | Length | What it is |
|---|---|---|---|
| `topos.out` `topos.report` | `latent`, and with foveation `peripheral` and `foveal` | 768 (InternVideo-Next), 384 (DINOv2 fallback) | Perceptual clip or frame embeddings |
| `chronos.out` `chronos.report` | `temporal_context` | 32 (`cfc_units`); 24 when it falls back to the feature vector | CfC hidden state |
| `chronos.out` `chronos.report` | `feature_vector` | 24 | Workspace summary features; the research taxonomy already treats it as latent |

Every one of them can also appear nested in `workspace.broadcast` → `selected[].payload`.

**Numeric lists that are not embeddings:**
- `thymos.emotion.scores` (5 elements, kept by the research allowlist);
- `mundus.proprio.position` (3);
- `phantasia.scenario.step_magnitudes` (8 by default, bounded only by `rollout_horizon`);
- `hypnos.ignition_audit.saliences` and its nested copy in `hypnos.sleep.completed` (one per realised intent since the last sleep, unbounded).

**Consumers:** no Nexus consumer reads any numeric array from the filtered stream, in Python or JS. No test asserts that a vector survives the filter.

**The rule.** A length threshold alone does not separate the cases: the Hypnos and Phantasia lists are unbounded, and test fakes use 2-8 element latents. So the filter applies two rules at every depth:
1. **Named vector fields are always removed:** `latent`, `peripheral`, `foveal`, `temporal_context`, `feature_vector`. These join a `VECTOR_FIELDS` set beside `CONTENT_FIELDS`, so a short test latent is removed too.
2. **A backstop for unnamed vectors:** any list or tuple of 16 or more numbers is removed, unless its key is one of the reviewed non-embedding keys `saliences` and `step_magnitudes`. Booleans do not count as numbers. Tuples are handled like lists, since in-process payloads can hold them.

A new module that publishes an embedding under a new name is therefore still stopped. Adding a key to the exemption list is a reviewed change with a test.

**Effect on callers.**
- **Nexus and the Nexus record** lose the vectors. Nothing displays them, and the Topos and Chronos reports shrink from about 49 KB and 1.9 KB to a few hundred bytes.
- **The research observer** loses nothing: its allowlist already excluded these fields, and the 5- and 3-element lists are below the backstop.
- **The trajectory** drops payloads entirely (section 3), so it no longer depends on this rule.

**Found by the audit, out of scope here.** These are recorded for a follow-up:
- `workspace.broadcast` entries never reach the Nexus bridge or the Nexus record. They are written with `snapshot`/`timestamp`/`source` fields and no `type`, and `_decode_entry` drops entries without a type.
- `cycle.tick` is published to `cycle.out` (routing by source), which the diagnostics streams exclude.
- The Nexus coherence chart reads `metadata.coherence` as a dict, but it is a float.
- The comment in `privacy_filter.py` names `selected_events[].payload`, but the key is `selected[].payload`.
- `tests/test_nexus_privacy.py` lists `temporal_context` as a reviewed operational key. Its comment must change with this rule.

## 5. Lifecycle of the graphs
- The ignition log is written with `retention_days=0` and is never deleted automatically. This change makes that a requirement.
- Purpose, in order: the paper analysis, then world-model training data for Phantasia or a future module.
- Deletion is done by the operator after both uses, never automatically. It goes through an operator command, not a retention timer, so a study's graphs cannot disappear before the analysis has read them.
- **Not built here:**
  - **The training consumer.** Phantasia today trains only on an in-memory buffer of waking workspace trajectories that is never saved (`phantasia` spec).
  - **The deletion command.** Both need their own changes.

## 6. Volume
For a 29 h gestation step:

| | Before | After |
|---|---|---|
| Nexus record | ~10.5 GB | 0 |
| Workspace trajectory | ~5.1 GB | 0 |
| Ignition log | 0.32 GB | 0.32 GB |
| Evaluation, research events, safety records | ~1.4 GB | ~1.4 GB |

The total goes from about 17 GB to about 1.7 GB. With the evaluation instruments counted, a study keeps about 1.4 GB a day (13 GB a day before). Compressing rotated logs, considered on 2026-10-02, is no longer needed.

## 7. Research impact
- **Instrument and privacy.** The analysis input, the ignition log, is unchanged.
- **No admissibility effect.** No study is running, and `moc7-2026-10`'s run data was deleted at the operator's request on 2026-10-03.
