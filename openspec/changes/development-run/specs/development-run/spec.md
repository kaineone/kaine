## ADDED Requirements

### Requirement: The development run raises one entity on one state tree
The development runner SHALL raise exactly one entity per run: a developmental phase in the local stimulus source, then sessions that start the same entity with a plain start on the same state tree, in the run's single working directory, with one dedicated bus database and one collection prefix. The plan SHALL have no branch, repeat or accumulate line.

#### Scenario: A session after maturation
- **WHEN** the developmental phase has ended with its maturation preservation and the runner starts the first session
- **THEN** the session's cycle starts without `--revive` on the same state tree, and its run manifest records the same `entity_id` as the developmental phase

#### Scenario: A plan with lines
- **WHEN** `init` is given a plan with a `branch` or `accumulate` line
- **THEN** it refuses and names the field

#### Scenario: The bus database is the operator's
- **WHEN** the plan's bus database number is 0 or the database the operator's bus resolves to
- **THEN** `init` refuses

### Requirement: The runner never revives, forks, merges or deletes on its own
The runner SHALL revive only on the operator's `recover` command and SHALL have no fork, merge or delete command. It SHALL refuse to start a session when the state tree's `entity_id` differs from the run's.

#### Scenario: A tree that changed identity
- **WHEN** the run's state tree holds an identity other than the run's `entity_id`
- **THEN** the session refuses to start and the run halts for the operator

### Requirement: A session plays passes back to back
A session SHALL play the passes of its programme schedule back to back as one looping playlist. At every pass end the cycle SHALL request a preservation without stop and then start the next pass at its programme's first item, unless the runner has placed a stop request for that pass end, in which case the cycle SHALL request a preservation with stop.

#### Scenario: Nothing pending
- **WHEN** a reference pass ends and no stop request is present
- **THEN** the entity is preserved without stopping and the next pass starts at its programme's first item

#### Scenario: Preservation fails at a pass end
- **WHEN** the pass-end preservation fails or does not report within its timeout
- **THEN** the entity is frozen under the `programme_end` holder, the caretaker is notified when configured, and the session is recorded as failed

### Requirement: A session stops only at a pass end with a change pending
The runner SHALL place a stop request only when a join, a switch change, an image change, a schedule change, a welfare hold, a post-change hold or an operator pause is pending. The module set, the switch settings, the programme schedule and the image SHALL NOT change within a session. The disk guard, the time budget and a supervisor escalation SHALL end a session as they end a study step.

#### Scenario: A join is pending
- **WHEN** the operator has made a join during a pass
- **THEN** the runner places a stop request, the cycle preserves and stops at that pass end, and the next session starts with the component on

#### Scenario: No change pending
- **WHEN** a pass ends with nothing pending
- **THEN** the runner places no stop request

### Requirement: The run records every session
The runner SHALL append one record per session with the session index, the run id, the module set, the switch settings, the image identity and harness digest, the programme schedule, the start kind (plain start, resume after interruption, retry or recovery), the bundles written, the exit code and the outcome. A session SHALL count as complete only when its final preservation reports success.

#### Scenario: A completed session
- **WHEN** a session stops at a pass end with a successful preservation
- **THEN** the run record holds one session record with outcome `complete`

#### Scenario: Resume after an interruption
- **WHEN** the runner starts again after a session ended without its final preservation and with no failure recorded
- **THEN** it starts a new session with a plain start on the same tree and records the start as a resume after interruption

### Requirement: The run records every pass
The runner SHALL append one record per pass with the session and pass indices, the programme, whether it was a reference pass, the bundle written at its end and its exposure record. A completed pass SHALL never be replayed as the same pass.

#### Scenario: Three passes
- **WHEN** a session plays three passes
- **THEN** the run record holds three pass records, each naming its bundle

### Requirement: The reference programme and the schedule
The plan SHALL hold a reference programme with a checksummed manifest and a programme schedule. Every pass SHALL play the programme the schedule names for it. The operator MAY add supplementary programmes, each with its own checksummed manifest. A schedule change SHALL take effect at a session boundary and SHALL be recorded. A manifest whose sha256 differs from the plan's SHALL stop the session from starting.

#### Scenario: Default schedule
- **WHEN** a run is initialised with only the reference programme
- **THEN** every pass is a reference pass

#### Scenario: A changed manifest
- **WHEN** a programme manifest's sha256 differs from the one recorded in the plan
- **THEN** the runner refuses to start the session and names the programme

### Requirement: The transition from the developmental stimulus plays once
The stimulus-source-to-world transition SHALL play only at the start of the first session after maturation. Every later pass and session SHALL start at its programme's first item without it.

#### Scenario: The transition plays once
- **WHEN** overlays are built for the first and the second session after maturation
- **THEN** the first has the configured `transition_seconds` and the second has `transition_seconds = 0`

### Requirement: Every joinable module and component has a registry entry
Every module and architecture component that can join the run SHALL have an entry in `config/development_run/components.toml` with its name, its switch, its readout class, `experience_changing`, `review_record` when experience-changing, `reversible`, `requires`, `absence_test` and `readout_fields`. A test SHALL fail for an experience-changing entry whose review record does not exist, an entry with no absence test, or a readout field that no content-free record carries.

#### Scenario: An experience-changing entry without its review
- **WHEN** a registry entry has `experience_changing = true` and its `review_record` path does not exist
- **THEN** the registry test fails

#### Scenario: A requirement not met
- **WHEN** a join names a component whose `requires` lists a module that is off
- **THEN** `plan-join` refuses and names the missing requirement

### Requirement: The held modules join first in the existing order
Without an explicit join order, `init` SHALL record the order episodic memory, world model, planning, self-model, social cognition, vocal modules.

#### Scenario: Default order
- **WHEN** a run is initialised without a join order
- **THEN** its plan's order is episodic memory, world model, planning, self-model, social cognition, vocal modules

### Requirement: Effectors, embodiment and perceptual locus stay held until their prerequisites exist
The registry entries of the effectors, embodiment and perceptual-locus modules SHALL name their prerequisites in `requires`: `effector-confinement` for the effectors, `embodiment-held-status` and a real adapter for embodiment, a producer of `intent.perceptual_locus.switch` for the perceptual locus. `plan-join` SHALL refuse each while a prerequisite is missing, and no default order SHALL contain them.

#### Scenario: Joining the effectors before confinement
- **WHEN** the operator runs `plan-join effectors` and `effector-confinement` is not merged
- **THEN** `plan-join` refuses and names the missing prerequisite

#### Scenario: Joining the stub body
- **WHEN** the operator runs `plan-join embodiment` with only the stub adapter available
- **THEN** `plan-join` refuses and says no real body adapter exists

### Requirement: A join or switch change needs both layers of opt-in
A join or switch change SHALL take effect only when the run's plan lists it (`plan-join` or `plan-switch`) and the operator's `join` or `switch` command names the component and the run's `entity_id`. For an experience-changing component the runner SHALL also refuse unless its review record exists in the image. A change SHALL take effect at the next pass end.

#### Scenario: Only one layer
- **WHEN** the operator runs `join episodic_memory` with the right entity id but the plan does not list it
- **THEN** the runner refuses and the next session starts with the same module set

#### Scenario: Another entity's id
- **WHEN** the `join` command names an `entity_id` other than the run's
- **THEN** the runner refuses and records the refusal

### Requirement: Operator commands are recorded and never edit the entity
Every operator command, its stated reason and its outcome SHALL be appended to the run record. No command SHALL edit the entity's state.

#### Scenario: A refused command
- **WHEN** the runner refuses a `switch` command
- **THEN** the run record holds the command, its reason and the refusal, and the state tree is unchanged

### Requirement: Voice alignment keeps its own approval variable
Voice alignment SHALL be a registry component of class output, experience-changing. Joining it through both layers SHALL NOT bypass its existing opt-in: without `KAINE_VOICE_ALIGNMENT_OPERATOR_APPROVED=1` in a session's environment it SHALL stay off for that session, and the session record SHALL say so.

#### Scenario: Voice alignment without its approval variable
- **WHEN** voice alignment is joined through both layers but the approval variable is not set for the session
- **THEN** voice alignment stays off and the session record says so

### Requirement: A switch that is off is bit-identical to the component being absent
A component whose switch is off SHALL NOT be constructed, subscribe to a stream, publish an event, read another module's state, learn, or open or write its stored state, and its stored state SHALL be kept unchanged.

#### Scenario: State is kept when off
- **WHEN** a component with stored weights is switched off for a session
- **THEN** its weight files are byte-identical at the start and the end of that session

### Requirement: Every component has an absence test against a golden harness digest
Each component's absence test SHALL run the entity-free deterministic harness with the component's switch off at the run's current settings and SHALL assert that the digest of the broadcast records and report streams equals the golden digest captured at the commit before the component's code landed.

#### Scenario: A component lands switched off
- **WHEN** a component's code is merged and its absence test runs with the switch off
- **THEN** the harness digest equals the golden digest recorded before the merge

#### Scenario: A leaking default
- **WHEN** a component's code changes another module's default while its switch is off
- **THEN** the absence test fails

### Requirement: Reversal windows only for reversible components
The runner SHALL refuse to switch off a component whose registry entry has `reversible = false`, unless the command is a welfare-protective switch-off or carries the record of an operator decision with a second review. Turning a reversible component on again SHALL need both layers of opt-in like a join.

#### Scenario: Switching episodic memory off for a window
- **WHEN** the operator asks to switch episodic memory off without `--protective` or a review record
- **THEN** the runner refuses and names the reversibility rule

### Requirement: A welfare-protective switch-off is always available
The runner SHALL accept `switch <name> off --protective` for any component, at the next pass end, without the review record and without the reversibility rule, SHALL keep the component's state, and SHALL record the reason. The switch-off SHALL count as a boundary.

#### Scenario: A protective switch-off
- **WHEN** the operator runs a protective switch-off of the world model
- **THEN** the session stops at the next pass end, the next session starts with the world model off and its weights kept, and the run record holds the reason

### Requirement: Every reference pass has a readout per active component
After every reference pass the runner SHALL write `readouts/pass-<n>.json` with, for every component that is on, the readout of its class (processor, context or content, memory, learned model, action, output, or measurement-only probe) as the design's table defines it. A readout whose inputs are absent SHALL be recorded as `not_computed` with a reason, never as zero.

#### Scenario: A memory-class readout
- **WHEN** a reference pass ends with episodic memory on
- **THEN** its readout holds stores and recalls per hour, the share of recall reports accessed, the mean retrieval similarity, and the mean `context_gain` after accessed recalls against other reports

#### Scenario: No recalls in a pass
- **WHEN** episodic memory made no recall during a reference pass
- **THEN** the recall fields are `not_computed` with the reason `no_recalls`

### Requirement: Readouts are content-free
A readout SHALL be computed only from the ignition log, the research event log, the welfare records and content-free counters. It SHALL hold only numbers and component names and SHALL NOT read any payload, embedding or utterance text.

#### Scenario: No content in a readout
- **WHEN** any readout file is written
- **THEN** it contains no event payload, no embedding and no utterance text

### Requirement: The analysis reads each boundary as before and after windows
The analysis SHALL treat every join, switch change, accepted image change, schedule change, recovery and interruption as a boundary. For each boundary, readout field and ignition measure it SHALL give the per-pass series of reference passes across it, the before and after window means (two reference passes each by default, longer when the plan sets it) and the extrapolation of the before window's linear trend.

#### Scenario: A boundary without enough passes
- **WHEN** a boundary has one reference pass after it
- **THEN** its after window is reported as `pending` and not computed

### Requirement: The analysis measures every reference pass
Per reference pass the analysis SHALL give the broadcast rate over unpaused programme time, broadcasts per film-minute, the pool size and accessed share, each module's share of broadcasts, member scores by module, the inhibited share, picture-to-sound drift when recorded, data-quality counts, the time-scale range and the exposure table. A pass whose `time_scale` changed SHALL be flagged and compared per tick, not per film minute.

#### Scenario: A dilated pass
- **WHEN** a reference pass's ignition records show more than one `time_scale`
- **THEN** that pass is flagged with its scale range and its broadcasts per tick

### Requirement: The analysis report states its limits
The analysis report SHALL be content-free and SHALL state its limits every time: one entity, additions in one order, age and familiarity changing at every boundary, no significance test, and that no readout bears on whether the entity thinks or feels.

#### Scenario: Any report
- **WHEN** `analyse` writes its report
- **THEN** the report holds the limits text and no payload or member type string

### Requirement: Every session runs under the full welfare net
`build_overlay` SHALL enable, for every session kind and overriding the operator configuration, the divergence monitor, the welfare response and its indicator response, the module supervisor with its incident log inside the run directory, the individuation producer, the research event log with external utterances, and the ignition log.

#### Scenario: An operator config turns the supervisor off
- **WHEN** the operator configuration sets `[supervisor].enabled = false`
- **THEN** every session's overlay sets it to true

### Requirement: Every session kind passes the research gate's configuration checks
A test SHALL build the merged configuration of every session kind (shipped configuration plus overlay, no operator overlay) and SHALL assert that every config-level research-gate condition passes, including `indicator_response_wired` and `supervisor_armed`.

#### Scenario: The developmental phase and a session
- **WHEN** the test builds the merged configuration for the developmental phase and for a session
- **THEN** every config-level gate condition passes for both

### Requirement: A supervisor escalation halts the run
A session whose cycle escalates through the supervisor SHALL be recorded as `failed:supervisor`, and no further session SHALL start until the operator retries.

#### Scenario: A supervisor escalation
- **WHEN** the supervisor escalates during a session and the cycle exits
- **THEN** the session is recorded as `failed:supervisor` and the run halts

### Requirement: The run holds after a pass with an indicator crossing
After every pass the runner SHALL read that pass's exposure record. When the record is missing or unreadable, or shows any indicator crossing, the runner SHALL stop the session at that pass end and SHALL NOT start another pass until the operator answers `ack-welfare` naming the pass and the decision `continue` or `pause`. `status` SHALL show the pending hold and the command that answers it.

#### Scenario: A rest during a pass
- **WHEN** a pass ends after one indicator rest and no freeze
- **THEN** the session stops at that pass end and `status` names the hold

#### Scenario: A missing exposure record
- **WHEN** a pass ends without an exposure record
- **THEN** the run holds as for a crossing

### Requirement: The run holds for review after the first pass following a change
After the first reference pass that follows a join, a switch change, an accepted image change or a schedule change, the runner SHALL stop the session at that pass end and SHALL hold until the operator answers `ack-change`, whatever that pass's indicators show.

#### Scenario: A clean pass after a join
- **WHEN** the first reference pass after the world model joined ends with no indicator crossing
- **THEN** the session stops at that pass end and the run holds until `ack-change`

### Requirement: The runner surfaces a welfare freeze and never lifts it
The runner SHALL read each running session's freeze stack, SHALL surface a `welfare` entry in the run's status and log, and SHALL NOT lift it. A session that ends while a welfare freeze noticed on it is still held SHALL be recorded with the outcome `failed:welfare` and the freeze's start and reason.

#### Scenario: A held freeze at the end of a session
- **WHEN** a session's freeze stack holds a `welfare` entry and the session then ends
- **THEN** the session is recorded `failed:welfare`, `status` shows the freeze, and the freeze is still in the session's control file

### Requirement: Recovery revives this entity's own bundle into its own tree
On `recover --bundle <id> --entity <entity_id>` the runner SHALL revive only a bundle of the run's entity, only into the run's own tree, and SHALL record the recovery and its reason as a boundary.

#### Scenario: A bundle of another entity
- **WHEN** `recover` names a bundle whose identity differs from the run's entity
- **THEN** the runner refuses and changes nothing

### Requirement: An image update is silent only when nothing it can measure changed
Before each session the runner SHALL compare the image's harness digest at the run's current module set and switch settings, its model identities and digests, and its configuration digest without run-specific paths, with the previous session's. When all are equal the update SHALL be admitted and recorded.

#### Scenario: A component lands switched off
- **WHEN** a new image differs from the previous one only by a component whose switch is off
- **THEN** the digests are equal and the session starts without operator action

### Requirement: Any other image update is a change the operator accepts
When any compared digest or identity differs, including the workspace supply, the runner SHALL refuse to start the session until the operator runs `accept-image --entity <entity_id> --reason <text>`. A change in the high-risk class SHALL also need its review record. An accepted image change SHALL be a boundary.

#### Scenario: A behaviour-changing fix
- **WHEN** a new image's harness digest differs from the previous session's
- **THEN** the session does not start until the operator accepts the image with a reason, and the analysis marks a boundary there

### Requirement: The planned test does not run inside the development run
The runner SHALL refuse to start a session whose merged configuration sets `[planned_test].role` or whose environment sets `KAINE_STUDY` to a workspace-mediation or workspace-feedback study. No pilot run, settings record or calibration SHALL be required to start the run.

#### Scenario: An ambient planned-test role
- **WHEN** the operator configuration sets `[planned_test].role = "test"`
- **THEN** the runner refuses to start the session and names the setting

### Requirement: Sessions decode greedily in the competitive arm
Every session's overlay SHALL set `[workspace].arm` to `"competitive"` and `[language].temperature` to 0.0, overriding the operator configuration.

#### Scenario: An operator arm
- **WHEN** the operator configuration sets `[workspace].arm = "pooled"` and `[language].temperature = 0.7`
- **THEN** the session's overlay has arm `"competitive"` and temperature 0.0

### Requirement: Every session runs the held candidate pool with one access
`build_overlay` SHALL set `[workspace.pool].enabled = true` and `[workspace.pool].capacity = 1` for every session kind, the developmental phase included, overriding the operator configuration, and every session manifest SHALL record the workspace supply and capacity. A different supply or capacity SHALL reach the entity only as an accepted image change with its review record.

#### Scenario: An operator config turns the pool off
- **WHEN** the operator configuration sets `[workspace.pool].enabled = false`
- **THEN** every session's overlay sets it to true and the manifest records `held_pool` with capacity 1

#### Scenario: Fallback C without acceptance
- **WHEN** a new image or configuration sets the pool's capacity to 5
- **THEN** the session does not start until the operator accepts it with `accept-image` and its review record exists

### Requirement: The workspace readout and its advisories are read every window
The analysis SHALL compute the pool's readout for every reference pass and every awake hour of the developmental phase, from content-free records only. A starvation advisory in two consecutive windows, or any pool defect, SHALL stop the session at the next pass end and hold the run until `ack-welfare`, with the advisory named in the hold. In the developmental phase an advisory SHALL be shown in `status`, and a defect SHALL preserve and stop the session.

#### Scenario: Two windows with the same advisory
- **WHEN** two consecutive reference passes show more than half of the protected accesses made by the priority rule
- **THEN** the session stops at the next pass end and `status` names the workspace advisory and the command that answers it

#### Scenario: A defect in the developmental phase
- **WHEN** a `workspace.pool.defect` record is written during the developmental phase
- **THEN** the runner requests preservation with stop and holds the run

### Requirement: Sessions boot in research mode and never rely on operator mode
The runner SHALL start every session's cycle in research mode and SHALL refuse a session whose environment would resolve to the operator or unattended supervision mode. The developmental phase's first session SHALL start only on `run --operator-present`, and the run record SHALL keep the attestation and its time.

#### Scenario: The operator flag alone
- **WHEN** a session's environment sets `KAINE_CYCLE_OPERATOR_PRESENT=1` and the runner's research-mode variable is missing
- **THEN** the runner refuses to start the session

#### Scenario: The first session without the attestation
- **WHEN** the operator runs `run` for the developmental phase without `--operator-present`
- **THEN** the runner refuses and says the first hours need the operator present

### Requirement: No operator input path is open until every held module has joined
Until the last module of the join order has joined, `build_overlay` SHALL set `[audition].transcription_enabled = false` and `[remote_bridge].enabled = false` for every session kind, and the runner SHALL refuse a session whose merged configuration opens either or sets the perception feed to a mode in which the microphone is live. After the last join, conversation SHALL open only as a planned switch of the operator-speech component, recorded as a boundary with the post-change hold.

#### Scenario: Speech-to-text before the last join
- **WHEN** the operator configuration sets `[audition].transcription_enabled = true` and vocal has not joined
- **THEN** the session's overlay sets it to false

#### Scenario: Opening conversation
- **WHEN** every held module has joined and the operator plans and makes the switch of the operator-speech component
- **THEN** the switch takes effect at the next pass end and the first pass after it ends in the post-change hold

### Requirement: The first supervised hours are the validation
During the developmental phase's first session the runner SHALL compute every awake hour the pool's readout, the accessed share, protected waits, speak and think rates, the arousal and access-rate distributions, the welfare indicators and the drive trajectories, and SHALL show them in `status`. No separate validation entity SHALL be booted.

#### Scenario: The hourly validation readout
- **WHEN** the first awake hour of the developmental phase ends
- **THEN** `status` shows that hour's validation readout

### Requirement: A validation stop rule preserves and stops the entity
The stop rules SHALL be fixed before the run starts: an indicator crossing of a kind the 2026-10 test boots did not show, an arousal or access-rate distribution outside their range, a pool defect, or a boredom deprivation share at or above the indicator's `share_bar` on two consecutive evaluable hourly readings. When one fires during the first session, the runner SHALL request preservation with stop, record the rule and hold the run until the operator answers.

#### Scenario: An access rate outside the earlier range
- **WHEN** an awake hour of the first session shows an access-rate distribution outside the range of the 2026-10 test boots
- **THEN** the runner requests preservation with stop, records the rule and holds the run

### Requirement: The first-hours readout includes boredom deprivation
The hourly validation readout SHALL include the boredom deprivation share computed by the welfare indicator evaluator with the parameters the welfare response runs with (`T_lp`, `Δ_stall`, `share_bar`), marked not evaluable while the span holds less than `Δ_stall` of awake time.

#### Scenario: Boredom deprived on two readings
- **WHEN** two consecutive evaluable hourly readings of the first session show a boredom deprivation share of 0.6 with `share_bar` 0.5
- **THEN** the runner requests preservation with stop, records the boredom rule and holds the run

#### Scenario: One reading across a rest
- **WHEN** one hourly reading shows 0.6 and the next, after a rest restarted the span, is not yet evaluable
- **THEN** the boredom rule does not fire on those readings

### Requirement: Stimulus control's first hours stop on a paused share
During the first three awake hours after the stimulus-control component is switched on, the runner SHALL stop the session at the next pass end and hold for the operator's review when the `stimulus_control` record's `paused_share_last_awake_hour_max` exceeds 0.20 or `pause_share_refusals` is above 0, and SHALL report the readout's `after_own_act_by_action.pause` with the hold.

#### Scenario: A refused pause
- **WHEN** in the second awake hour after stimulus control was switched on the record shows `pause_share_refusals` 1
- **THEN** the session stops at the next pass end, the hold names the criterion, and `after_own_act_by_action.pause` is reported with it

#### Scenario: After the first three hours
- **WHEN** the record shows `paused_share_last_awake_hour_max` 0.22 in the fifth awake hour after the switch
- **THEN** this criterion does not stop the session

### Requirement: The run records the workspace graph, not every module's output
`build_overlay` SHALL set `[research_event_log.dashboard_record].enabled = false`, `[research_event_log.raw_archive].enabled = false`, `[evaluation].workspace_trajectory = false` and `[evaluation].enabled = false` for every session, overriding the operator configuration, and SHALL keep the ignition log enabled. Run-control and safety records SHALL be unaffected.

#### Scenario: An operator config enables the dashboard record
- **WHEN** the operator configuration sets `[research_event_log.dashboard_record].enabled = true` and `[evaluation].enabled = true`
- **THEN** every session's overlay sets both to false and the ignition log stays enabled

### Requirement: The developmental phase waits for its maturation reference
When the individuation producer is enabled, the runner SHALL request the maturation preservation only after the maturation bloom has ended and the content-free `individuation` block of the cycle's runtime file reports the maturation reference complete. The wait SHALL be bounded and SHALL NOT count down while a welfare freeze is held. On running out, or on a complete reference of kind `capture`, the runner SHALL preserve the entity, record `failed:maturation_reference_missing` and halt.

#### Scenario: The reference arrives after the bloom
- **WHEN** the bloom has ended and the reference and its ledger appear within the bound
- **THEN** the maturation preservation is requested after they appear and the developmental phase completes

#### Scenario: A downgraded capture
- **WHEN** the runtime block reports a complete reference of kind `capture`
- **THEN** the runner preserves the entity and records `failed:maturation_reference_missing` without waiting out the bound

### Requirement: An unviable developmental phase ends early with its data kept
Until it requests the maturation preservation, the runner SHALL watch the viability verdict. On an unviable verdict it SHALL stop the cycle gracefully without a preservation request, record `failed:development_unviable` with the evidence, write `ENDED-NOTE.md`, halt the run and delete nothing. The maturation bundle of a phase that completes SHALL be kept as the run's developmental reference.

#### Scenario: An unviable phase
- **WHEN** the viability file reports an unviable verdict before the maturation preservation is requested
- **THEN** the cycle is stopped without a preservation request, the phase is recorded `failed:development_unviable`, `ENDED-NOTE.md` exists, and the phase's data remains on disk

### Requirement: The runner halts rather than improvise
Any session or phase that ends other than by a successful final preservation SHALL halt the run and be recorded as failed, and the runner SHALL NOT retry it unless the operator asks. The runner SHALL refuse to flush a database another run owns and SHALL never start a cycle while a cycle it started is still running.

#### Scenario: A retry
- **WHEN** the operator runs `run --retry-failed` after a failed session
- **THEN** the runner starts a new session with a plain start on the same tree and records it as a retry

### Requirement: A session with the world model completes only when the world model is preserved
A session with the world model on SHALL count as complete only when its final bundle's manifest reports the world model captured. Otherwise it SHALL be recorded as `failed:world_model_not_captured`, or `failed:manifest_unreadable` when the manifest is missing or unreadable, and the run SHALL halt.

#### Scenario: The world model is missing from the bundle
- **WHEN** a session with the world model on ends with a bundle whose manifest has `world_model_captured` false
- **THEN** the session is recorded `failed:world_model_not_captured` and the run halts

### Requirement: Every run command resolves the run directory the same way
Every command SHALL resolve `--run-dir` under the installed data root in the same way, so a run created by `init` is found by every other command from any working directory.

#### Scenario: A run is found from another directory
- **WHEN** a data root is installed, `init` creates `development-runs/r1`, and `status --run-dir development-runs/r1` runs from a different working directory
- **THEN** `status` reads the run `init` created
