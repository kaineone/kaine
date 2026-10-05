# Research runs record the workspace graph, not every module's output

## Why
A study records far more than the research needs, and part of what it records is perception.

**The plan.** A run saves the global workspace graph, meaning what competed, what ignited, and when. The paper analysis uses it, and later a future module or Phantasia uses it as training data for the world model. Then it is deleted. That is the operator's statement of 2026-10-03, and it matches the paper: Phantasia is "trained on accumulated workspace trajectories" (the paper's Phantasia description; `docs/02-architecture/README.md:220` says the same). No surviving spec says it. The spring conversations where it was first stated no longer exist, so this change writes it down.

**What studies record today.** Measured on the 2026-10-01 module-ignition study (gestation, about 29 h):

| Record | Per day | What it holds |
|---|---|---|
| Nexus record (`data/nexus_record/`) | ~8.7 GB | Every event on every stream Nexus displays, after the privacy filter. 86% of the bytes are `topos.report`. |
| Workspace trajectory (`data/workspace_trajectory/`) | ~4.2 GB | One row per broadcast, holding each coalition member's filtered payload and the Thymos state. |
| Ignition log (`data/ignition/`) | ~0.27 GB | One row per broadcast: coalition members (source, type, salience), salience scores, inhibition, timing and programme position. No payloads. |

**How it grew.**
- The `run-recording` change (2026-09-28) read the operator's "everything from nexus recorded" as every stream Nexus displays. The operator's earlier description of the study had named the target: changes "via its workspace graph".
- The privacy filter (`kaine/privacy_filter.py`) is a denylist of text fields, so it passes numeric vectors. Each `topos.report` carries the 768-dimensional InternVideo-Next clip embedding as `latent`, and again as `peripheral` when foveation is on, plus the `foveal` embedding.
- About 150,000 such reports a day were persisted by the Nexus record, and by the trajectory whenever vision won the workspace. They also stream to the Nexus browser, which never displays them.
- A clip embedding is a compressed description of what the entity saw, and it can be partly inverted back to images. Persisting it breaks the zero raw-sense-data rule.

**Nothing depends on the excess.** No code in `kaine/` or `scripts/` reads the Nexus record or the workspace trajectory; only tests do. The ignition-study analysis reads only the ignition log and the evaluation streams (`kaine/research/ignition_study/analysis.py`).

Research impact: **instrument and privacy.** The ignition log, which the analysis reads, is unchanged. The data a study keeps shrinks from about 13 GB to about 1.4 GB a day. Of that, the graph is about 0.27 GB; the rest is the evaluation instruments and safety records, which are unchanged. No run is active. The 2026-10-01 module-ignition study's data was deleted at the operator's request, so no earlier run has records to match.

## What changes
- **The ignition log is the workspace-graph record.** It is kept at full rate, one row per broadcast, because ignitions are discrete events and a sample would miss them. It stays payload-free and is never deleted automatically.
- **Studies record the graph only.** The study overlay forces `research_event_log.nexus_record.enabled` and `evaluation.workspace_trajectory` off, the same way it already forces the raw archive off, so an operator config cannot turn them on for a study. Run-control and safety records stay as they are: gestation readouts, viability, welfare, preservation, incidents, the evaluation instruments and external utterances.
- **The workspace trajectory records the graph, not module payloads.** Each selected entry keeps its entry id, source, type, salience, timestamp and causal parent, and loses its payload. The Thymos state is no longer recorded. This narrows `nexus-privacy-hardening`, which routed the payload through the privacy filter, to no payload at all.
- **The privacy filter removes numeric vectors.** Perceptual and latent embeddings (Topos's clip embeddings and Chronos's `temporal_context` and `feature_vector`) are removed from every diagnostics surface: the Nexus stream, the Nexus record and anything else using the filter. The rule and its threshold are in `design.md`, and no field any Nexus panel reads is removed.
- **The graph's purpose and lifecycle are stated.** Workspace graphs are kept for the paper analysis and then as world-model training data. They are deleted only by the operator after both uses. The training consumer and the deletion command are future changes. This change records the requirement and keeps automatic retention off.

## Capabilities
### Modified Capabilities
- `ignition-log`: the log is the workspace-graph record, it is never purged automatically, and its purpose is stated.
- `module-ignition-study`: the study overlay forces the Nexus record and the workspace trajectory off.
- `research-event-log`: the Nexus record holds no numeric vectors.
- `evaluation-sidecar`: the trajectory records the graph without payloads or the Thymos state.

## Impact
- **Code:**
  - `kaine/research/ignition_study/overlay.py`
  - `kaine/evaluation/trajectory.py`
  - `kaine/privacy_filter.py`
- **Tests:**
  - overlay
  - trajectory
  - privacy filter
  - Nexus record and bridge filter tests
- **Docs:**
  - the ignition-study chapter
  - the evaluation chapter
  - security and privacy
  - the configuration appendix
- **The paper:** Phantasia's description and the methods section should state the lifecycle: graphs are kept for analysis, then used as training data, then deleted.
