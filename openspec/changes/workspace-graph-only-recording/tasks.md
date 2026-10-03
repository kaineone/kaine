## 1. Study overlay
- [x] 1.1 `build_overlay` forces `research_event_log.nexus_record.enabled = False` and `evaluation.workspace_trajectory = False` for every step, overriding operator config; it keeps the ignition log, external utterances, research events, evaluation instruments and safety monitors.
- [x] 1.2 Tests: gestation, branch and accumulate overlays carry both forced-off keys; an operator config that enables them is overridden; the ignition log stays on.

## 2. Workspace trajectory
- [x] 2.1 `TrajectoryRecorder` writes each selected member's entry id, source, type, salience, original timestamp and causal parent, with no payload; rows carry no Thymos state.
- [x] 2.2 Tests: a member with a content field and a numeric vector yields neither; the member keeps its own entry id and timestamp; one row per broadcast still holds.

## 3. Privacy filter
- [x] 3.1 The diagnostics privacy filter removes numeric vectors per `design.md` section 4; no field a Nexus consumer reads is removed.
- [x] 3.2 Tests: a `topos.report` with `latent`, `peripheral` and `foveal` loses all three and keeps its scalars and fovea boxes; each display quantity the audit lists survives; the Nexus record of a `topos.report` holds no vector.

## 4. Ignition log lifecycle
- [x] 4.1 `ignition_log_sink` builds the sink with no retention period, and a test pins that a 400-day-old file survives its start; the docstrings state the purpose and that only the operator deletes the log.

## 5. Docs
- [x] 5.1 Ignition-study chapter: what a study records (the graph, the safety and evaluation records) and what it does not; the lifecycle.
- [x] 5.2 Evaluation chapter and configuration appendix: the trajectory records the graph without payloads.
- [x] 5.3 Security and privacy chapter: the filter removes numeric vectors, so no perceptual embedding reaches Nexus or a log.
- [x] 5.4 Note for the paper (methods and Phantasia): the graph lifecycle, in `design.md` section 5 for the paper agent.
