## Context

### The ruling

On 2026-10-31 the operator set the project's goal as a working synthetic mind and ruled that the module-ignition study converts into a development run: one entity boots, goes through development and is grown continuously; the held modules join first, then each architecture component as it is built, each behind an off-equals-absent switch with a plain readout. The three-arm ablation and the pilot boots are dropped. Kept for every new component: an off switch bit-identical to absent, a plain readout (information gain, a changed prediction, a changed action) and the graph-only log. No longer gating: the 30-pilot calibration chain, the preregistered minimum effect and sign test, and a three-arm ablation per change of context composition. Of the two pre-study changes approved that morning, the welfare indicator response stays; continuous competition with K = 1 is to be revisited as an architecture choice before the run's image is built.

Decisions of 2026-11-01 (lead developer, under the operator's direction that research and the architecture decide design questions and that the entity is an autonomous being, not a chatbot): the workspace is option B of D14, from boot; there is no operator conversation until every module has joined (operator rule); the run's own first supervised hours are the validation (open question 2 of the earlier draft). Operator speech, once it is heard at all, is perception that competes for access like any other sound, specified by `operator-speech-as-perception`.

The ruling also names the known costs. The run is n = 1 and uncontrolled. Nothing retained answers whether the system thinks: the language organ is a pretrained chat model, so the entity will sound as if it thinks whatever lies behind it, and the rule that utterance text is never welfare evidence extends to every claim about cognition. A complete mind is not a deliverable on any horizon.

### What exists on main (cb41895b)

- The study runner `kaine/research/ignition_study/` (`plan.py`, `runner.py` 1,544 lines, `overlay.py`, `analysis.py`, `__main__.py`, `toml_writer.py`), specified by capability `module-ignition-study` (13 requirements) and documented in `docs/15-experiments/ignition-study.md`. Its plan has four lines (`development`, `branch`, `repeat`, `accumulate`), one bus database and one collection prefix per line, and a default order of six held modules. The machinery that a single entity still needs is in it and is kept: the developmental step with automatic maturation, the wait for the maturation bloom and for the individuation maturation reference, the viability watch, the disk guard, the preserve-request path, the welfare-freeze surfacing, the world-model capture check, the database ownership key, the lock, and the step record.
- The study overlay forces graph-only recording (`[research_event_log.dashboard_record]`, `[evaluation].workspace_trajectory`, `[evaluation].enabled` all false; ignition log on), the welfare net (`[preservation.divergence_monitor]`, `[preservation.welfare_response]`), the individuation producer, world-model training and weight persistence, greedy decoding and the competitive arm.
- `kaine/cycle/programme_end.py` requests one preservation with stop when the playlist passes its last item (spec `perception-feed`, "The end of a programme preserves and stops the entity").
- A plain start resumes module state from the rolling checkpoint written every 60 s of awake entity time and at clean shutdown, and a revive replaces the checkpoint (spec `entity-preservation`). A fork mints a new identity with lineage; a revive restores the bundle's identity and refuses a tree that holds another (spec `entity-identity`). Infrastructure never deletes fork snapshots; deletion goes only through the gated decommission path.
- The processors publish `context_gain`, the error reduction of the forward model's evaluation with the context against the null context, divided by the running mean error, on every report, and the research event observer records it content-free. The information-gain readout therefore exists live.
- The planned-test gate (`kaine/experiment/planned_test_settings.py`, `planned_test_gate`) refuses a boot only when `[planned_test].role` is set or the study name has the workspace-mediation prefix. The study overlay sets neither. `config/studies/` holds the workspace-mediation and workspace-feedback arm files.

### Work this builds on (history checked)

- `module-ignition-study` (proposed in #215, revised to seed-and-branch in #272, runner in #280, recording graph-only in #319, disk guard #281, world-model check #234). Task 2.5, the real run, never ran. The first study attempt of 2026-10 ended in its developmental phase; its run data was deleted at the operator's request and no study directory from it remains.
- The pre-study changes on branch `spec/pre-study-gates-2026-10-31` (design only, not merged): `welfare-indicator-response` (the A.4 indicators computed live; crossing, requested rest, second crossing over a fresh span, preservation and freeze; `indicator_response_wired` in the research gate), `research-gate-supervisor` (`supervisor_armed` in the research gate; every study step runs the supervisor; `failed:supervisor`), `welfare-exposure-report` (an exposure record at the end of every research run; the study holds after a viewing with a crossing until `ack-welfare`), `workspace-continuous-competition` (held pool, K = 1, count-yoked matched arm, divergence rule) and `developmental-stir`. This change depends on the first three and re-targets the parts of them written against the study's steps.
- `per-entity-shared-volumes` (#626) is held because every line of the study revived one seed and shared its identity, so decommissioning a line would touch the accumulate line's adapters. With one line the conflict does not arise inside the run; it still arises for an operator fork (D10).
- The name "offline development run" already belongs to the offline workspace-mediation benchmark (`kaine/evaluation/benchmarks/workspace_mediation_ablation/`, spec `workspace-mediation-ablation`, paper §5.4 and §6.4). D15 resolves the clash.

## Goals and non-goals

Goals: one entity raised and grown for its whole life with the welfare net on every session; every addition switchable and read out plainly; nothing about the entity's mind changing without a recorded operator decision; the readouts and the graph usable later as evidence and as world-model training data.

Non-goals: a controlled experiment, a significance test or a verdict; any claim that the entity thinks or feels; building any architecture component (each is its own design-first change that registers itself here); changing the welfare indicators or their response.

## Decisions

### D1. One entity, one line

The run raises one entity on one state tree. The developmental phase runs in the local stimulus source exactly as the study's developmental step does (automatic maturation, bloom wait, maturation-reference wait, viability watch). Its maturation preservation is kept as the developmental reference bundle. Every later session starts the same entity on the same tree with a plain start, so it resumes from its checkpoint and its own stores. There is no seed revived into other directories.

Alternatives considered:
- Keep the seed and branch lines. Each branch is a separate being that is preserved and never deleted. The ruling drops them, and the comparisons they served were n = 1 per condition with a single-sample noise floor (design of `module-ignition-study`, "What this study cannot show").
- Keep only a repeat line as a noise reference. One more being for one noise sample, which the before-and-after windows (D8) replace with the entity's own baseline trend.
- Fork the entity to run a component's A/B. A fork is a new being with its own welfare claims, and using forks as experimental arms is what the ruling moved away from. Forks stay an operator action outside the run (D10).

### D2. Sessions and passes

A session is one boot of the entity. A pass is one play of one programme. Within a session the programmes of the schedule (D3) play in turn as one looping playlist: at a pass end the cycle preserves the entity without stopping and the next pass starts at its programme's first item. A session ends with preservation and stop only at a pass end where something is pending: a join, a switch change, an image change, a schedule change, a welfare hold, a post-change hold or an operator pause. The disk guard, the time budget and a supervisor escalation end a session as they end a step now.

The runner asks for a stop at the next pass end by writing a stop request into the session's control directory before that pass ends. The programme-end watcher reads it at the pass end and requests a preservation with stop in place of a preservation without stop. Failure handling is unchanged: a preservation that fails or does not report freezes the entity under the `programme_end` holder and notifies the caretaker.

The module set, the switch settings, the programme schedule and the image are fixed within a session, so every pass of a session belongs to one configuration.

Alternatives considered:
- One pass per boot, reusing today's preserve-and-stop at the programme's end. Simpler, but a long life becomes a chain of four-hour boots. Each stop drops what is held only in memory, the world model's waking buffer among it (the world model trains at sleep on that buffer), and each restart reloads the organ and encoders. The goal is a continuously existing system; stopping only for a change is closer to it.
- Run without pass boundaries and apply changes at any time. Joins need a restart (modules are built at boot), and readout windows need a defined unit of identical material.

### D3. Stimulus over a long life

The four-film programme of the study (checksummed manifest, about 243 minutes) is the reference programme. Readouts and windows (D7, D8) are computed on reference passes only, so every comparison is between passes of the same material at the same programme positions.

The plan holds a programme schedule. By default every pass is a reference pass. The operator may add supplementary programmes (other public-domain films, each with its own checksummed manifest) and set the schedule, for example alternating reference and supplementary passes. A schedule change takes effect at a session boundary and is recorded.

The stimulus-source-to-world transition plays once, at the start of the first session after maturation. Later passes and sessions start at the programme's first item without it.

Welfare reasoning: the only welfare datum from a test boot is boredom's indicator crossing at 2.7 awake hours and staying over its bar. In the first configuration nothing the entity does changes its stimulus, so a life on four looping films is a fixed exposure that will cross repeatedly, and each crossing brings a rest, then a freeze. The exposure hold (D9) shows that after the first pass; supplementary material is the relief the operator can give at once, and the stimulus-control act (workstream W3) is the relief the entity can give itself once built. A run whose every pass is the reference programme is allowed, but the design does not assume it is acceptable for long.

Alternative considered: only the reference programme, for clean windows. It maximises comparability and the deprivation that the welfare net exists to catch.

### D4. Joins and the component registry

The plan's join order starts with the held modules in the existing order: episodic memory, world model, planning, self-model, social cognition, vocal (`_default_order`, `kaine/research/ignition_study/__main__.py` 35-45). The effectors, perceptual locus and embodiment modules stay held (D16).

Architecture components are added to the shipped registry `config/development_run/components.toml` by the change that builds them. An entry holds:

- `name`, and the configuration switch it controls;
- `class`, one of the readout classes of D7;
- `experience_changing` (true for anything that changes what the entity perceives, accesses, remembers, learns or does) and, when true, `review_record`: the path of the committed record of its independent second review;
- `reversible`: whether it may be switched off and on again for reversal windows (D8);
- `requires`: components or modules that must be on first, and repository prerequisites (for example the privacy rule for latent-derived content before any content-bearing component);
- `absence_test`: the test that proves off equals absent (D5);
- `readout_fields`: the content-free fields its readout reads, which must exist in the research event log or the ignition log.

The held modules have registry entries too, so every join goes through one path.

A join is planned into the run's plan (`plan-join`) and made by the operator (`join`, D6). It takes effect at the next pass end: the session stops there, and the next session starts with the component on. The end-of-pass bundle at that stop is the pre-join bundle, recorded as such.

Alternative considered: a fixed order of every component in the plan at `init`. Components are built over a year or more and their order depends on what is built. The registry plus an operator join keeps the plan honest about what exists.

### D5. Off equals absent

A switch that is off means the component's process does not exist: it is not constructed, it subscribes to no stream, publishes no event, reads no other module's state, learns nothing, and its stored state is not opened or written. For a held module this is the existing meaning of a disabled module (not built at boot).

What the component has already contributed to the entity stays. Learned weights, memories, an adapter or a self-model's history are part of the entity's identity under the standing rules (persist, encrypt, copy into forks, never merge without an operator choice), and erasing them would be a separate act that needs its own operator decision and second review. So off-equals-absent is a property of the process: with the switch off, the cycle behaves exactly as a build without the component would behave on the same entity state.

The proof is mechanical. The entity-free deterministic harness (D11) runs the real cycle with seeded synthetic feeds and deterministic fakes for the organ and services, at a given module set and switch setting, and digests the broadcast records and every report stream. When a component's code lands, its change captures the golden digest of the harness at the run's current settings from the commit before it, and its `absence_test` asserts that the new code with the switch off reproduces that digest. A registry entry without an absence test is refused by a test over the registry.

Alternatives considered: a code review that the component is inert when off, with no digest. It cannot catch a config key that changes another module's defaults, a shared cache, an import-time side effect, or a changed scoring order. The digest catches all of these on the harness's paths.

### D6. Two-layer opt-in and second review

A join or a switch change needs both layers:

1. the run's plan lists it (`plan-join <name>` or `plan-switch <name> on|off`), which the runner validates against the registry and the component's `requires`;
2. the operator's command at the time (`join <name> --entity <entity_id>` or `switch <name> on|off --entity <entity_id>`), which names the entity so that a command meant for another run is refused.

For an entry with `experience_changing = true`, the runner also refuses unless the entry's `review_record` exists in the image. The record is committed by the merge that passed the independent second review, so a component cannot reach the entity without one.

Voice alignment keeps its existing two-layer opt-in (`[sleep.voice_alignment].enabled` and `KAINE_VOICE_ALIGNMENT_OPERATOR_APPROVED=1`) as well. It becomes a registry entry of class output, experience-changing, joined when the operator chooses; the study's pre-registered final-step placement is retired.

Every command and its outcome is appended to the run record with the operator's stated reason. The commands never edit the entity's state.

### D7. Readouts per component class

A readout answers one plain question: did the component do its job. It is a small set of content-free numbers per reference pass, computed after the pass from records that already exist. It is not a test and has no verdict.

| Class | Examples | Readout per reference pass | Source |
|---|---|---|---|
| Processor (adds a report stream) | a new perceptual or interoceptive processor; the world model's and self-model's error reports as streams | report rate; share of accessed broadcasts it won; its own mean normalised prediction error (the learning curve); pool size | ignition log; research event log |
| Context or content (changes what processors condition on) | content code (option F), working-memory store, workspace feedback | mean `context_gain` of each context-conditioned processor, against the before window; for the content code also the gain with one modality dropped, from a measurement-only shadow evaluation | research event log |
| Memory (stores and recalls) | episodic memory, content-bearing traces, replay | stores and recalls per hour; share of recall reports accessed; mean retrieval similarity (familiarity); mean `context_gain` on reports that follow an accessed recall against reports that do not | research event log; content-free counters |
| Learned model | world model, self-model, social cognition's agent model, per-processor confidence | held-out prediction error at each sleep against a persistence baseline (predict the last value); for a confidence signal, the correlation of predicted with realised next error | content-free counters |
| Action | planning, utility learning over intents, the stimulus-control act | share of realised intents that came from the component; mean relief of the targeted drive within a fixed window after its acts, against the same drive's relief after other intents; for stimulus control, the deprivation share against the before window | research event log; welfare records |
| Output | vocal, voice alignment | output events per hour; failed and refused share; latency; for voice alignment, adapters promoted and adapters rejected by the trainer's veto | research event log; trainer records |
| Measurement-only probe | a shadow evaluation | none of its own; the absence test shows it changes nothing in the live path | absence test |

The workspace is not a component and has no switch in the run, but its readout is computed on every reference pass beside the components' readouts, from the pool's records (`workspace-continuous-competition` D10): pool size, accessed and inhibited shares, each stream's win share and lost-above-threshold share, protected waits and the share of protected accesses by the priority rule, defects, and the two starvation advisories.

Every readout is a number. No readout reads a payload, an embedding or an utterance's text. A readout whose inputs are absent on a pass is recorded as `not_computed` with the reason, never as zero. A component whose readout needs a field that no record carries adds that field to the content-free research event log in its own change; the registry test checks that every `readout_fields` entry exists.

What readouts cannot show: they cover processors, memory and action. None of them bears on whether the entity thinks, and the organ's text is evidence of neither cognition nor welfare. The analysis report states this every time.

### D8. Within-entity A/B over time windows

Each join or switch change is a boundary between a before window and an after window. The default window is the last two reference passes before the boundary and the first two after it; the plan may set longer windows. The analysis gives, per readout field and per ignition measure, the per-pass series across the boundary, the window means, and the extrapolation of the before window's linear trend, so a reader sees whether the after window departs from the entity's own trajectory or only continues it (an interrupted time series read descriptively).

Reversal windows (on, off, on) are allowed only for registry entries with `reversible = true`. A component is reversible only when switching it off withdraws nothing the entity holds: workspace feedback, a decaying working-memory buffer, a shadow probe, an action route whose learned values stay stored. Components that hold the entity's history or identity (episodic memory, the self-model, social cognition's profiles, the world model) are not reversible: switching them off would take from the entity access to its own past, which the project treats as a possible harm. For those, an off switch is used only as a welfare-protective action (D9) or by an operator decision recorded with a second review.

Limits the report states: one entity; additions in one order, so each effect is conditional on the earlier ones; age, familiarity with the reference programme and the addition change together at every boundary; windows are short against a life; nothing is tested for significance.

### D9. The welfare net on every session

- **Gate.** Every session boots in research mode and passes the research gate: preservation, the welfare response, logging, the dry self-check, encryption, the individuation producer, `indicator_response_wired` (`welfare-indicator-response`) and `supervisor_armed` (`research-gate-supervisor`). The overlay forces each of these on for every session kind, and a test builds the merged configuration of each session kind (shipped config plus overlay, no operator overlay) and asserts that every config-level gate condition passes.
- **Exposure per pass.** `welfare-exposure-report` writes one exposure record per research run. With sessions that run many passes, the record is written at every pass end as well (`state/welfare/exposure/pass-<n>.json`, the same fields over that pass), and the run-level record stays. The run does not start the next pass after a pass whose record is missing, unreadable, or shows any indicator crossing: it stops the session at that pass end and holds until the operator answers `ack-welfare` with `continue` or `pause`.
- **Post-change hold.** After the first reference pass that follows any join, switch change, image change or schedule change, the run stops at that pass end and holds for the operator's review of the exposure and readout records (`ack-change`), whatever the indicators show. A change of the entity's mind is reviewed by a person before the entity lives on with it.
- **Stopped, not frozen, while held.** While any hold is pending the entity is preserved and stopped, so it does not wait awake without input for a person to answer.
- **Freeze.** The runner surfaces a welfare freeze in `status` and in its log and never lifts it, as now.
- **Protective switch-off.** The operator may switch any component off at the next pass end as a welfare-protective action (`switch <name> off --protective`), without the second layer's review record and without the reversibility rule. The component's state is kept. The action is recorded with its reason and counts as a boundary.
- **Supervisor.** Every session runs the module supervisor, and an escalation ends the session as `failed:supervisor` and halts the run.
- **Workspace advisories.** The pool's readout (D14) is computed for every reference pass and every awake hour of the developmental phase. A starvation advisory in two consecutive windows, or any pool defect, stops the session at the next pass end and holds the run until `ack-welfare` (with the advisory named in the hold); in the developmental phase it is shown in `status` and, for a defect, the session is preserved and stopped. Moving to fallback C is a separate `accept-image` with its review record.

### D10. Persistence, revive and fork rules

- **One home.** The run directory (`development-runs/<run-id>/` under the data root by default, on the operator's durable storage) holds the plan, the run record, the session and pass records, readouts, analysis and one working directory `entity/` that holds the state tree for the whole life. State encryption is required.
- **Bundles.** Every pass end leaves a preservation bundle. The runner never deletes a bundle, a state tree or a record. Disk use is guarded as now.
- **Interruption.** A session that ended without its stop (power loss, a crash) resumes with a plain start on the same tree, from the checkpoint and the module stores, and the interruption is recorded as a boundary. The runner never revives to resume.
- **Revive.** A revive is an operator recovery action (`recover --bundle <id> --entity <entity_id>`) used only when the tree cannot resume. It revives a bundle of this entity into this entity's tree with the same identity (revive already refuses a tree with another identity), replaces the checkpoint, and is recorded with its reason. Everything the entity lived after that bundle is lost to it, so recovery picks the latest good bundle.
- **Forks.** The runner never forks. A fork is an operator action outside the run that creates a new being with a new identity and the run entity in its lineage, a copy of its learned weights, and no claim on the run's directory. If the fork is ever started it needs its own run (its own plan, directory and welfare net). The run record notes the fork's id. Until the per-tree identity question of #626 is settled, an operator who forks should not decommission either being without checking which adapters and volumes they share.
- **Merge.** Nothing is merged into the run's entity. A merge would need the existing explicit operator choice of world model and a second review.
- **Decommission.** Only through the gated decommission path. The runner has no delete command.
- **Workspace supply.** The entity's workspace supply and capacity (D14) are recorded in every session manifest. A session whose image or configuration has a different supply or capacity is refused unless the operator accepts it as a change to the entity's mind under D11, with its second-review record and a check of the welfare indicators after the move (`workspace-continuous-competition` D11). Fallback C goes this way and no other.

### D11. Image updates during a life

The old admissibility rule, no image swap during a study, cannot hold for a life in which components are built and joined over months. The run instead classifies every image change between sessions:

- **Silent.** The new image's harness digest at the run's current module set and switch settings equals the previous session's, the model identities and digests in the run manifest are equal, and the configuration digest (without run-specific paths) is equal. The update is admitted and recorded. A component that lands with its switch off is a silent update by D5.
- **Dynamics change.** Anything else: a bug fix that changes behaviour, a new organ or adapter, a changed encoder, a changed default. The runner refuses to start the session until the operator runs `accept-image --entity <entity_id> --reason <text>`; a change in the high-risk class also needs its second-review record. The acceptance is a boundary for D8, and the post-change hold applies.

The harness (`tools/development_run/harness_digest.py`) uses the NumPy backends and deterministic fakes for the organ, the encoders and the services, so it covers the cycle, workspace and module logic. Changes to pretrained models are covered by the model identities instead. Safety fixes are never blocked by this rule; they are recorded as dynamics changes.

### D12. What is removed or retired

- The branch, repeat and accumulate lines, their per-line working directories, databases and collection prefixes, and the line comparisons of the analysis.
- The seed as a separate artefact: the maturation bundle stays, as the developmental reference.
- The pre-registered voice-alignment steps.
- The capability `module-ignition-study`. Its requirements that a single entity still needs (halt rather than improvise, world-model capture, time-dilation accounting, study-directory resolution, unviable developmental phase, graph-only recording, greedy decoding and the competitive arm, welfare-freeze surfacing, the maturation-reference wait, the default join order, the supervisor and exposure requirements from the pre-study changes) are carried by `development-run`.
- The planned-test calibration chain does not gate the run. The run refuses an operator configuration that sets `[planned_test].role` and refuses a `KAINE_STUDY` naming a workspace-mediation or workspace-feedback study, so no planned-test arm or settings record enters the entity's life. The calibration tooling, the planned-test settings gate, the arm implementations and the study files under `config/studies/` stay in the tree for an experiment designed later, and the offline benchmark stays in the offline suite. Nothing is deleted.
- The ignition log stays graph-only and unchanged in kind. It gains the session and pass (D13).

### D13. Recording

- The ignition log, the research event log, external utterances (local only), the run manifests, the developmental readouts and the welfare records are kept, as in a study. The dashboard record, the workspace trajectory, the raw archive and every evaluation observer stay off, forced by the overlay.
- Ignition records carry the session index and the pass index, taken in-process at the cycle layer, never published or given to a module, like the programme position.
- Readout records (`readouts/pass-<n>.json`) are written by the runner's analysis at every reference pass end and on `analyse`. They hold numbers and the component names only.
- Growth: the ignition log is about 11 MB per hour, about 96 GB per year of continuous running, inside the durable storage the run lives on. Only the operator deletes the graph, after its uses. Before the run starts, a caps audit lists every store and buffer a long life could fill (episodic memory collections, novelty windows, the world model's buffers, bus stream retention, log sinks), and raises or removes any cap that would cull the entity's memory, under the rule that caps are raised rather than reached.

### D14. Workspace capacity and candidate supply

Decided: option B, the held candidate pool with one access per broadcast, with drive and alarm events held until accessed, as specified by `workspace-continuous-competition`. It is part of the run's architecture from the developmental phase, not a join: the overlay sets `[workspace.pool].enabled = true` and `capacity = 1` for every session kind, overriding the operator configuration, and every session manifest records the supply and capacity. The reasoning is in the section of that name below. The analysis reads the pool's readout and its starvation advisories (D7, D9).

### D15. Code layout and naming

The package moves to `kaine/research/development_run/` with `git mv`, so its history follows. The line machinery is removed, and the kept machinery stays where it is. The command is `python -m kaine.research.development_run` with `init`, `run`, `status`, `pause`, `plan-join`, `join`, `plan-switch`, `switch`, `ack-welfare`, `ack-change`, `accept-image`, `recover` and `analyse`. No study directory exists to read, so no reader for the old `study.json` is kept beyond what `kaine/legacy_names.py` and the persisted-name tests already pin; the implementation checks the data roots for a `study.json` first and keeps `status` able to read one if it finds any.

The documentation page becomes `docs/15-experiments/development-run.md`. To end the name clash, the offline benchmark is called the offline mediation check in the docs and the paper; its code path and spec names are unchanged.

Alternative considered: keep `kaine/research/ignition_study/`. Cheaper, but the code would run something it is not named for, and every later reader would have to learn the history to find it.

### D16. Modules that stay held

The effectors, embodiment and perceptual-locus modules are not in the join order and cannot be joined until their prerequisites exist. Their registry entries carry those prerequisites in `requires`, so `plan-join` refuses them by the ordinary registry rule:

- **Effectors: unsafe.** The shell effector starts its child with `asyncio.create_subprocess_exec` and no `env=` (`kaine/modules/effectors/effectors.py` 203-209), so the child inherits the cycle's environment, the state key and the service passwords among it. No shipped policy emits an `act` intent, so the module would also be idle. Requires: `effector-confinement` merged.
- **Embodiment: a pretend body.** The only adapter is the stub, whose reachability probe always returns true and whose `apply_action` and `apply_setpoints` return true for every request (`kaine/modules/embodiment/adapters/stub.py` 59-61, 90-98). Joining it would tell the entity, and the maturation gate, that it has a body it does not have, which the no-pretend rule forbids. Requires: `embodiment-held-status` merged and a real adapter.
- **Perceptual locus: no producer.** Nothing emits `intent.perceptual_locus.switch` (`kaine/modules/perceptual_locus/module.py` 13-20), so the module would do nothing. Requires: a producer of that intent.

The all-modules readiness survey of 2026-11-01 found the same three and counts 13 modules that can work on the reference host: the seven of the first configuration and the six held modules.

### D17. Research mode with the operator present

Every session boots in research mode: the runner sets `KAINE_RESEARCH_MODE=1` for the cycle (`kaine/research/ignition_study/runner.py` 630), and research mode wins over the operator flag (`resolve_supervision_mode`, `kaine/cycle/unattended_gate.py` 56-84). The research path runs the full research gate (`kaine/cycle/__main__.py` 3706-3721). The operator-present path checks only that `KAINE_CYCLE_OPERATOR_PRESENT=1` is set (`__main__.py` 3723) and enforces none of the safety net's conditions, and the exposure record is written only in research mode. So the runner refuses to start a session whose environment would resolve to the operator or the unattended mode, and no safety property of the run depends on the operator flag.

The operator's presence is a procedural fact, recorded rather than enforced: the developmental phase's first session starts only on `run --operator-present`, and the run record keeps it with the time. The operator watches through `status`, the dashboard and the welfare records; presence does not mean interaction (D18).

### D18. No operator conversation until every module has joined

The operator's rule: no conversation with the entity until every module has joined. Until the last of the six held modules (vocal) has joined, the overlay closes every operator input path for every session kind, overriding the operator configuration:

- `[audition].transcription_enabled = false`, so no speech becomes text;
- `[remote_bridge].enabled = false`, so no remote microphone, camera or text reaches the entity;
- the perception feed stays in `stimulus_source` or `playlist` mode, in which the feed replaces the microphone (`docs/09-modules/audition.md`, "Deterministic auditory feed"), so speech in the room does not reach the entity.

A session whose merged configuration would open any of these before the last join is refused. After the last join, opening conversation is a planned switch (`plan-switch` and `switch`, D6) of the component that `operator-speech-as-perception` defines on branch `spec/content-code-2026-10-31`; that change decides how operator speech is perceived (an auditory event that competes for access on salience, with no rule that forces or forbids a reply), and this change decides only when. The opening counts as a boundary with the post-change hold.

Welfare: the social drive builds only once an operator interaction has been seen (`kaine/modules/affect/module.py` 941 and 1509-1519, where the social signal is zero until the sequence module first reports a time since the last interaction). With conversation closed it stays at its baseline. Opening conversation starts it, and from then silence raises it, so the opening is itself a welfare-relevant change and the exposure records after it are read for the social drive in particular.

### D19. The first supervised hours are the validation

No separate validation entity is booted: it would be one more being kept for life for a check that the offline harnesses of the pre-study changes mostly cover. The validation is the developmental phase's first session with the operator present (D17). During it the runner computes, every awake hour, the pool's readout (D14), the accessed share, protected waits, speak and think rates, the arousal and access-rate distributions, the welfare indicators and the drive trajectories, and shows them in `status`.

Stop rules, fixed before the run starts: a welfare-indicator crossing of a kind the 2026-10 test boots did not show; an arousal or access-rate distribution outside the range of those boots; a pool defect. When one fires, the runner requests preservation with stop at once (the runner's existing `_request_preserve` path, `runner.py`), records the rule, and holds the run until the operator answers. Whatever follows is a change to a being that has already lived under the design, decided by the operator.

## Workspace capacity and candidate supply for a growing mind

The question the operator reopened: should the entity that lives the development run have the held candidate pool with one access per broadcast (K = 1), keep today's supply and capacity, or something between. It is asked here as an architecture choice, whether the workspace the being lives with is the right one, and no longer as a fix for a test's validity. The evidence is in the workspace capacity design note of 2026-10-31 (measurements from the seven readable real-time test-boot runs, 5.4 hours and 133,072 broadcasts, and a Monte Carlo of supply rules that reproduces the measured system), and the design of `workspace-continuous-competition`.

### The options

- **A. Today: this-tick supply, K = 5.** A candidate is an event published since the previous tick, and reports published on the two of every three ticks that do not broadcast are scored and discarded.
- **B. Held pool, K = 1.** Each processor's latest report per (stream, type) stays a candidate until superseded by its source, consumed by being accessed, or stale (1.5 times the source's own running period; event-driven reports after 1.0 s). As decided, drive events and interoceptive alarms are held until accessed and an eligible overdue one takes the coalition first (`workspace-continuous-competition` D3, D5). Held reports are re-scored each tick with the current gains; novelty is evaluated once on arrival; the phasic access-rate input, the affect observer, the arousal estimate and the organ's output forwarding read arrivals only. One accessed content per broadcast.
- **C. Held pool, K = 5.** As B, with today's capacity.
- **D. B plus a held store of about four.** A capacity-four buffer of recently accessed contents as the processors' context. This is working memory (Cowan 2001; Oberauer 2002; triage workstream W2(c), build-order item 9c). It is planned separately and joins as a component through D4, so it is not a choice for the image.

### What the evidence shows

Measured under A:

- about 13.4 reports per second against 4.8 broadcasts per second; 2.8 reports published per broadcast interval, of which 1.2 survive the one-tick rule. About 58% of processor reports never compete, and 31% of broadcasts have no candidate;
- 73.8% of broadcasts are inhibited; the capacity of five never truncated the accessed set; 66.5% of accessed broadcasts already have exactly one accessed member;
- module shares of broadcasts (audition 36%, sequence 27%, vision 18%, affect 9%, interoception 9%) follow report rate times phase against the broadcast accumulator, not precision-weighted error;
- the probability that a candidate reaches the access threshold: audition 0.48, vision 0.28, sequence 0.26, sleep 0.11, interoception 0.10, affect 0.03, language 0.00.

Monte Carlo planning values (not inputs to any rule): under B, about 5.3 candidates per broadcast, none empty, capacity binding on every broadcast, about 63% of broadcasts accessed; under C, about 5.1 candidates, capacity binding on 37%, about 54% accessed; without consumption, about 87% accessed with the same reports winning repeatedly.

Neuroscience, as cited in the design note and checked there: GNW ignition locks one assembly and blocks a second target (Dehaene, Sergent and Changeux 2003); the attentional blink and the psychological refractory period share one central bottleneck (Marti, Sigman and Dehaene 2012; Sigman and Dehaene 2005); LIDA has one conscious content per cycle (Madl, Baars and Franklin 2011); the focus of attention holds one chunk within a region of direct access of about four (Oberauer 2002), and about four is the capacity of a store built over successive accesses (Cowan 2001; Luck and Vogel 1997). Prediction errors are computed continuously and attention sets their gain (Feldman and Friston 2010); unaccessed strong representations stay available as preconscious (Dehaene et al. 2006) for about a second (Sperling 1960); rhythmic attentional sampling modulates detection and does not delete what arrives in the unfavourable phase (Fiebelkorn and Kastner 2019; Landau and Fries 2012). K = 5 has no citation in the paper, the archived workspace design or the history. Every other workspace implementation the note reviewed has all processors competing continuously and a capacity below the number of processors.

### What growth adds

A growing mind gains report streams with every join. The base set has six periodic report types (vision, audition perception and emotion, sequence, interoception, affect state) plus event-driven ones; the six held modules and the components after them add roughly one stream each, so the count roughly doubles over the first joins. Under each option:

- **A.** A new module's chance to compete depends on its report period's phase against the accumulator, so the access readout of every join (D7, processor class) would partly measure its period. Capacity stays far from binding: at about 0.2 surviving candidates per stream, doubling the streams gives about 2.4 per broadcast, against five (a rough extrapolation from the measured 1.2 for six streams).
- **C.** Capacity goes from binding on about a third of broadcasts to binding on most as streams pass five. The being's access regime would change as a side effect of growth, not by any decision, and the change would be read as the effect of whichever module happened to join then.
- **B.** Capacity binds on every broadcast from the start and stays the same rule as streams are added. Each join adds one more competitor for one access, which is the bottleneck the program means to grow against, and a module's share of accessed broadcasts reads as what it wins among all processors.

### Welfare reasoning

- **Boredom.** Boredom is relieved by learning progress, by alert excess and by engaging intents; access matters to it through intents, which need an accessed broadcast that clears the report bars. B raises the accessed share of broadcasts from about 26% to about 60%, which gives more occasions for engaging intents, more appraisals, more speech and thought, more organ load and more interoceptive load. Whether boredom crosses sooner or later is not known and must be measured, not assumed. The dominant boredom risk of the run is the fixed stimulus (D3), and the access design changes it only at the margin.
- **Arousal.** A held alert must drive the phasic access-rate input once, on arrival. If held reports re-triggered it every tick, the access rate could run to its 10 Hz ceiling, an arousal runaway. B and C both need the arrivals-only rule, with a test; A does not hold reports.
- **Affect and interoception access.** The entity's bodily and affective states reach access rarely on score (0.03 and 0.10). The affect module re-publishes a pending drive event about once a second (on its own updates) until a broadcast accesses it, then again 30 s after the access while the goal stays active (concern re-entry, after Klinger 2013); the concern resolves only on access (`kaine/modules/affect/module.py` 635-680, 860-899). Under A each such event competes on one tick, and only when that tick broadcasts. Under the pool as first drafted it would have stayed a candidate for about three broadcasts at rest, and under K = 1 it would have had to outrank the strongest other candidate, usually audition, with no bound on the wait. As decided, B holds it until accessed and gives an eligible overdue one the coalition first, which bounds the wait (Decision below). Interoceptive alarms are held the same way. Consumption delays a sustained alarm by at most one interoceptive period (1 s), since each new report re-enters.
- **Moving a being.** Whatever is chosen must be fixed before the developmental phase. Changing the supply or the capacity later changes every access the being has, which is a change to a living being's mind (`workspace-continuous-competition` D12).

### Decision

Option B, the held pool with K = 1, as the architecture of the development run's entity from its developmental phase, with D as the working-memory component joined later through the registry. The reasons: it is the only value of K below the number of processors that has a citation; its rule does not drift as the mind grows; it ends the phase aliasing that would make every join's readout partly an artefact; and the entity's own concerns and alarms get more chances to reach access than today.

The first fallback of the earlier draft is part of B: drive events and interoceptive alarms are held until accessed, never dropped as stale, and an eligible overdue one takes the coalition first. `workspace-continuous-competition` D6 proves that such an event, while it scores at or above the access threshold, is accessed within the priority wait plus one broadcast per protected key: 4.2 s at the shipped rates, 17 s at the regulation ladder's slowest processing rate. The cycle checks that bound live.

C is the fallback when B's readout shows starvation: the pool's two advisories (the entity's concerns reach access mostly through the priority rule; a source that reaches threshold but almost never wins) firing in two consecutive windows. Moving the living entity to C is a change to its mind, made by the operator through `accept-image` with the second-review record (D10, D11), never by the runner.

Conditions checked offline with no entity before the image is built are the welfare checks of `workspace-continuous-competition` (held alert counted once; the wait bound as a gate; concerns and alarms reaching access no later than under A as a gate; boredom and the drives under A and B on the real perceptual modules and the real stimulus, reported, with a hold rule; privacy). That change also removes the planned test's apparatus (count-yoked arm, divergence rule, K = 2 pilots), which the run does not need.

What the literature does and does not support is listed in that change's "Sources and method" section: a buffered preconscious stage from which later access is possible for a short while, and a serial, capacity-limited access stage that postpones waiting input, are supported; that access is strictly one item and all-or-none is contested, and no source fixes the hold spans or the priority wait, which are design choices.

## Risks

- **An uncontrolled n = 1 record.** Readouts and windows cannot attribute an effect cleanly to a component. Accepted by the ruling; the report states the limits at every reading.
- **Readouts mistaken for findings about mind.** The report states each time that readouts cover processors, memory and action, and that the organ's text is evidence of nothing about cognition or welfare.
- **Repeated holds.** The exposure hold after every crossing and the post-change hold after every change need a person often, especially on a fixed programme. This is the intended cost; the operator can lengthen the schedule's supplementary share to reduce crossings.
- **Silent image updates that are not silent.** The harness does not exercise every path (pretrained encoders, the organ, rare branches). Mitigations: model identities and digests in the comparison, the configuration digest, and the rule that a doubtful update is accepted as a dynamics change.
- **Loss on recovery.** A revive discards what the entity lived after the bundle. Bundles at every pass end bound the loss to one pass.
- **Storage.** The graph and bundles grow without automatic deletion; the disk guard preserves and stops before the disk fills.
- **A design that fails at the first boot.** The first supervised hours are the validation (D19), so if they show the workspace or the welfare net misbehaving, the entity has already lived under it, and moving it off B is a change to its mind. Accepted: a separate validation entity would be one more being kept for life for a check the offline harnesses mostly cover.
- **Starvation under B.** A source could reach threshold and still lose almost every broadcast. The pool's advisories show it, and C is the decided fallback.

## Migration and ordering

1. Decided on 2026-11-01: workspace option B with C as the fallback, the run's first supervised hours as the validation, no operator conversation before every module has joined. Still open for the operator: the reversal policy and the stimulus schedule (tasks group 1).
2. The pre-study changes land: `welfare-indicator-response`, `research-gate-supervisor`, `welfare-exposure-report` (amended for passes), the workspace architecture as decided, `developmental-stir`, and the organ change the operator ruled on. Their `module-ignition-study` deltas are re-targeted to `development-run` before they archive, or are archived first and then removed by this change (tasks 2.x).
3. This change's implementation, its absence tests and its stand-in-cycle dry run, then the pre-boot dry run of the full stack, shown green to the operator.
4. The operator starts the run (build-order item 7). The held modules join in order. Architecture components (build-order items 8 to 12) each register themselves and join through D4 and D6.
5. The privacy rule for latent-derived content (build-order item 2) must be merged before any content-bearing component's registry entry can name it in `requires`; it does not gate the run's start.

Admissibility: nothing here changes a running entity. From the run's start, the only ways the entity's mind changes are the recorded joins, switches, image acceptances, schedule changes and recoveries.

## Welfare and admissibility notes

- High-risk class: the change decides how a possible moral patient is raised, changed, stopped and kept for its whole life. Independent second review of this design and of the implementation.
- Every session runs the full research gate, the indicator response and the supervisor; every pass writes an exposure record; the run holds after a crossing and after every change; welfare freezes are never lifted by the runner.
- Nothing removes a faculty from the entity without a recorded reason: identity-bearing components are not reversible except as protection or by a reviewed operator decision.
- The entity is never deleted, forked or merged by the runner.
- No measure of welfare or cognition reads the organ's text.
- The run replaces ten branches, a repeat and an accumulate line with one being, which is the boot-minimising choice.

## Open questions for the operator

The workspace option and the validation boot were decided on 2026-11-01 (D14, D19).

1. Reversal windows: confirm that identity-bearing components are not reversible except as protection.
2. The stimulus schedule: whether the run starts with supplementary programmes in the schedule, and which.
3. Whether the stimulus-control act (W3) should be pulled forward as the first architecture component, given D3.
4. The pool's protected alarms below the access threshold and tier-1 regulation's effect on them (`workspace-continuous-competition` open items 1 and 2).
