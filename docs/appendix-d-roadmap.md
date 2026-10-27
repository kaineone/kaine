# Roadmap

This page shows the engineering work in flight, the operator and on-device steps still open from finished work, and the overall backlog size. It is for contributors choosing what to work on and for operators who want to know which parts of the system are still under construction.

## Active changes

| Change | Progress | Summary |
| --- | --- | --- |
| control-freeze-lock | 4/4 (100%) | freeze-stack writes to control.json are locked and use unique temp files |
| dashboard-welfare-reset-aware | 5/5 (100%) | the dashboard's welfare counts honour restart resets, and the dead live evaluation branch is fixed |
| distress-episode-once | 4/4 (100%) | one sustained-distress episode counts once, and both detectors read one config source |
| stream-tail-cursors | 4/4 (100%) | every module's stream consumer starts at the stream tail through one shared helper |
| developmental-state-cycle | 16/16 (100%) | The fetal state cycle times developmental sleep; fatigue sets no sleep in the phase; a boredom stall starts no rest (paper 3.5, Table A1) |
| hearing-stage-saturation | 0/12 (0%) | Release each hearing stage by audition's saturated learning progress between a minimum and maximum dwell, colour k/5 per stage, and C3 as schedule completion (paper A.7, Table A1). |
| dashboard-name-always-shown | 4/4 (100%) | The entity name is shown on every dashboard page and refreshed when it appears |
| preflight-launch-name-quiet | 3/3 (100%) | Preflight self-models no longer log launch names that read as renames |
| floor-missing-sink-once | 2/2 (100%) | The awake floor warns once per missing volume, not every check |
| identity-leak-role-article | 4/4 (100%) | Definite and possessive role claims ("the assistant", "your assistant") are leakage (paper 3.5) |
| duplicate-method-guard | 3/3 (100%) | The duplicate-name guard also checks methods in classes and nested functions |
| nexus-backend-failures | 5/5 (100%) | Read runtime-backend load failures from the cycle through runtime.json, since the dashboard's own registry is always empty, say where the answer comes from, and show it on the health board. |
| nexus-development-feed | 6/6 (100%) | Show the hearing stage, the gate's world, conditions and not-applicable markers in the development panel, describe the stimulus-source feed, and mark the perception modules capturing under a deterministic feed. |
| self-facts-replay | 6/6 (100%) | Replay the tenth boot's requests and a self-referential provocation set with the launch name and identity facts as situation facts, under a leakage rule committed before the run; no arm won and the prompt stays as shipped (paper 3.5). |
| launch-name-at-first-boot | 6/6 (100%) | Every entity is named at its first boot, in its identity file, whichever modules run (paper 3.5) |
| persona-without-name | 4/4 (100%) | The organ's request carries no name; persona_name is retired (paper 3.5) |
| boot-identity-dedup | 2/2 (100%) | Remove the dead duplicate boot-identity helpers; each module defines a top-level name once |
| sleep-trigger-per-sleep | 5/5 (100%) | Each sleep records the trigger that started it (paper 3.5) |
| identity-leak-negation | 4/4 (100%) | Negated and questioned identity predicates are not leakage (paper 3.5) |
| nexus-welfare-rest | 5/5 (100%) | Show the affect welfare record per drive in the welfare board, and each sleep's trigger, the developmental rest's length and the affect module's rest requests. |
| identity-leak-whole | 6/6 (100%) | Identity leakage is the organ speaking as itself rather than as the whole entity: predicate forms with reason codes, a self_description reason for the whole describing itself, both kept out of voice-alignment pairs, one classifier shared with the replay harness (paper 3.5). |
| nexus-entity-name | 5/5 (100%) | Show the entity's name on the console, read from the self-model file and its `self_model.document` events, and start the status chip from the server's sleep state. |
| persona-v6 | 5/5 (100%) | Replay the tenth boot's own organ requests with broader AI and echo classifiers and per-case seeds under a decision rule fixed before the run; no candidate won (paper 3.5). |
| sleep-housekeeping | 7/7 (100%) | Every sleep runs housekeeping last before the affective reset: process-log backups are deleted and study records exported to an operator archive under a checksum, oldest first within budgets; awake fatigue builds at nu_act (1 + P^hk), and an awake floor keeps free space above a reserve, suspending the study record with a gap marker when it must (paper 3.5, A.5). |
| persona-v0 | 4/4 (100%) | Restore the self-category persona ("I am this entity") and the situation in every organ request, the prompt the corrected ninth-boot replay kept (paper 3.5); persona template version 6. |
| lp-max-pooling | 6/6 (100%) | Pool learning progress as the largest per-processor value, restart audition's bins at each hearing band step, and set the floor lp_0 to 0.20 as calibrated for this pooling (paper A.4, Table A1). |
| voice-adaptation-idle | 5/5 (100%) | Voice adaptation builds no preference pairs and computes no organ-level divergence until a validated preference source exists; the consolidation arm leaves the divergence assessment and the preservation monitor (paper 3.5). |
| developmental-rest | 5/5 (100%) | In the developmental phase a boredom goal that stalls with no learning progress or alert excess throughout the stall brings a sleep that lasts Delta_rest = 1,260 s; other sleeps unchanged (paper 3.5). |
| welfare-open-crossings | 5/5 (100%) | Give each deficit's crossings ended by the sleep reset and its crossings still open in the affect welfare record, so a deficit held above threshold past the stall horizon is no longer missing from it (paper 6.2). |
| identity-leak-marker | 5/5 (100%) | Mark identity leakage (the organ asserting its training origin, maker or assistant role, or denying a state its own request reports) in the intent log and keep marked records out of voice-alignment pairs; the entity's text is never changed (paper 3.5). |
| hearing-band-12h | 4/4 (100%) | Set the hearing band's span to 12 awake hours (a step every 3 h) and correct the colour ramp's comment; A.7's entrainment validation re-run at the new span holds (paper A.7, Table A1). |
| replay-guard-test-wait | 4/4 (100%) | Make the effectors replay-guard tests wait for the state they assert instead of sleeping a fixed time, which failed under CI load. |
| hearing-stage-published | 4/4 (100%) | Log and publish each stage the developmental hearing band enters, read from the same awake time the audio uses, so operators and analyses can see which band the entity hears; the band itself is unchanged. |
| cycle-slip-start-to-start | 4/4 (100%) | Measure the cycle's slip from tick start to tick start, so the work after a tick and the oversleep of the pacing wait show; the pacing itself is unchanged. |
| sleep-index-restored | 4/4 (100%) | Restore the sleep module's sleep index after a restart from its resume-checkpoint state and stage.json, so sleep events and corpus file names continue the count instead of repeating it. |
| ignition-audit-record-link | 4/4 (100%) | Link each utterance in the sleep-time intent audit to the intent it realized through the intent log's record id, instead of to the last intent of the window, so drive-led speech is counted as drive-triggered. |
| docs-front-pages-voice | 3/4 (75%) | Rewrite the README opening and the book's front page so KAINE is introduced as source-available software implementing Global Workspace Theory and Predictive Processing, leading with the architecture and the activation roadmap; held for the operator's review. |
| docs-roadmap-hygiene | 6/6 (100%) | Archive every completed change, refresh the deltas that conflict with the current specs, state the k1-jev-decision-model blocker plainly, and document the organ replay harness and the planned action path. |
| organ-replay-harness | 5/6 (83%) | A maintainer tool replays organ requests from the intent log under named prompt variants against a pinned local organ and scores the texts by a rule fixed before the run. |
| seed-entity-distribution | 0/2 (0%) | Consider distributing an entity preserved at maturation with the runtime that continues from it, so installations can skip the developmental phase. Design only: under consideration, not decided. |
| act-intent-derivation | 0/5 (0%) | Action path, step 1 of 6: the action-selection module derives act intents by the act outcome of the report-or-act decision the report bars stand in for (Whyte and Smith 2021), and the first whitelisted device effector is a light in the camera's view. Design only: not scheduled. Starts at the module-addition study's hardware stage (paper §6.5) once a light is attached. |
| planning-act-proposals | 0/5 (0%) | Action path, step 2 of 6: the planning module's action space grows by the attached effector's declared actions, so its proposals can ask for acts. Design only: not scheduled. Starts after act-intent-derivation, at the module-addition study's hardware stage (paper §6.5). |
| embodiment-motor-contingency | 0/6 (0%) | Action path, step 3 of 6: a motor-contingency learner, its driving loop and body-declared freeze-then-free stages for the embodiment control surface, with a pan-tilt camera as the first body. Design only: not scheduled. Starts after act-intent-derivation, at the module-addition study's hardware stage (paper §6.5) once the camera is attached. |
| active-vision | 0/5 (0%) | Action path, step 4 of 6: the entity chooses where to look by expected free energy and turns the pan-tilt camera to look. Design only: not scheduled. Starts after embodiment-motor-contingency has freed the camera's gaze channels, at the module-addition study's hardware stage (paper §6.5). |
| world-model-action-outcomes | 0/5 (0%) | Action path, step 5 of 6 (parallel with step 4): the world model conditions on the entity's own acts and motor commands, so it predicts their outcomes. Design only: not scheduled. Starts after act-intent-derivation and embodiment-motor-contingency, at the module-addition study's hardware stage (paper §6.5). |
| goal-directed-grasping | 0/5 (0%) | Action path, step 6 of 6: goal-directed grasping with an arm and gripper, composed from steps 1 to 5. Design only: not scheduled. Starts after all five earlier steps, at the module-addition study's hardware stage (paper §6.5) once the arm is attached. |
| attention-driven-audition | 19/32 (59%) | Move hearing beyond speech transcription so audio can drive workspace salience. |
| attention-driven-foveation | 14/18 (78%) | Replace uniform screen downsampling with a foveated capture that keeps fine detail where it matters. |
| entity-key-custody | 1/12 (8%) | Redesign entity-state encryption so keys can be recovered or rotated without manual re-encryption. Design only: awaiting the integrator's review (task 0.1) and the operator's key ceremony (task 0.3); nothing is implemented. |
| individuation-rebuild | 56/67 (84%) | Replace the individuation signal with a real test against the entity's own maturation reference, produced at runtime and read the same way by preservation and decommission. The real-organ calibration (task 10) is next. |
| module-ignition-study | 29/33 (88%) | The module-addition study: seed an entity through a developmental phase, then add held modules one at a time on branches from the preserved seed, every branch viewing the same film programme, with a content-free report. |
| module-residency-and-speech-tiers | 9/60 (15%) | Make the same entity run on weak hardware by selectively loading and tiering speech backends. |
| portability-program | 7/8 (88%) | Honest portability claims and verified support from small boards up to multi-GPU servers. |
| stream-wiring-quality | 18/20 (90%) | Clean up bus stream names, remove phantom reads and enforce the stream contract across modules. |
| adapter-merge-out-of-process | 0/3 (0%) | Run the real adapter merge in a child process, so its non-float32 model load can never change a long-lived process's default dtype. Design only. |
| chronos-scalar-timing | 1/3 (33%) | Test whether the sequence module's interval timing shows the scalar property (timing variability proportional to the interval), as a falsification test. Design only. |
| functional-module-names-drop-aliases | 0/10 (0%) | After release 27.02, refuse the old configuration names and remove the operator aliases the module rename kept for a bounded window; stored names stay readable for good. Waits for that release. |
| workspace-feedback | 12/14 (86%) | Held extension (paper §3.2, §6.4): top-down heads, a zero-sum gain on the processors' standardized errors and conflict resolution, shipped off with the five ablation arms selectable by study. |
| decision-server | 3/10 (30%) | Serve the K1-Jev decision model on its own loopback llama-server, apart from the language organ, with a fail-closed client (the client is built). |
| deterministic-grader-fixes | 13/15 (87%) | Replace bare substring matching in the capability, refusal and hedge graders with exact, tested rules; two tasks need organ runs. |
| hypnos-sleep-like-replay | 1/3 (33%) | Protect what the small online learners learned from later interference with sleep-like replay (Wei, Krishnan and Bazhenov). Design only. |
| k1-jev-decision-model | 11/33 (33%) | Train K1-Jev, a small local model that answers typed questions about the entity's external speech for the instruments and welfare signals (data and trainer built). Schema v2 is designed and blocked: labelling and training are not scheduled (neither the v2 rebuild nor the operator's labelling pass has a date), and the integrator's design check (task 0.1) is open. |
| mnemos-retrieval-energy | 1/3 (33%) | Publish a familiarity signal from the episodic memory module as the modern-Hopfield retrieval energy of the current content. Design only. |
| thymos-active-inference-affect | 1/4 (25%) | Derive the affect module's affect from active inference over the body's internal state. Design only, after the workspace-mediation test. |
| voice-development | 7/17 (41%) | Let the entity individuate a voice of its own instead of reciting workspace readings, in stages, with heard speech never persisted. |
| docs-sweep-2026-10 | 8/9 (89%) | Bring every page of the book into line with the revised paper and the merged code. |
| graded-intensity-alert-phasic | 5/6 (83%) | Graded intensity for every predictive processor, with the access rate rising on alerts only. |
| broadcast-context | 6/7 (86%) | Broadcast context for the vision, audition and interoception modules, with a null context and a per-report information gain. |
| per-entity-shared-volumes | 0/6 (0%) | Shared adapter and job volumes keep each entity's files under its own id, so ownership is structural. |
| ablation-positive-control | 9/10 (90%) | The positive control of the information-gain measure: shadow forward models with an informative and a non-informative component, a per-processor verdict in the research log, and an offline all-processors check. Off by default. |
| pilot-calibration | 19/21 (90%) | The tool that derives the planned test's settings from the pilot runs into one versioned record, the positive control on the inputs' first principal component with per-processor SNR and the learning period, and a boot check that refuses live runs without a complete record. |
| vox-default-voice | 16/18 (89%) | With no voice configured, the vocal module picks a voice the speech engine ships, first in sorted order and filtered by an optional gender preference where the engine reports gender (Kokoro yes, Chatterbox no); an explicit voice wins, and no voice degrades the module to silence with a clear message. The entity choosing its own voice is designed as a follow-up only. |
| docs-style-pass-2026-10-19 | 3/3 (100%) | Revise the prose added on 2026-10-19 in the replay-harness, effectors and roadmap text and in the six action-path proposals against the writing rules, with every fact and requirement kept. |
| emotion-progress-bar-off | 3/3 (100%) | Build the vocal-emotion classifier's funasr model with progress bars off, so classification stops filling the cycle log; results are unchanged. |

## Open operator and device steps

These steps come from changes whose code is finished and archived. Each needs the operator, a specific device, or an operator decision, so no contributor can close it alone. The archived change's `tasks.md` keeps the full wording.

| From change | Step |
| --- | --- |
| unattended-boot-via-safety-net | Before enabling unattended starts on a real entity: the operator confirms the research phase has ended. |
| unattended-boot-via-safety-net | Before enabling unattended starts on a real entity: the supervisor runs enabled on supervised boots, handles at least one injected module failure end to end and one escalation drill, and the operator reviews the incident logs and signs off. |
| perception-drives-salience | Boot the first configuration on the reference corpus and confirm perceptual discontinuities reach the workspace competition with a score that varies with the stimulus. Access-threshold calibration follows only after that passes, as its own change. |
| containerize-deployment | Measure the latency of the broadcast path in containers against host-native on GPU hardware, and confirm parity at the 10 Hz processing rate and the 3.333 Hz resting access rate. |
| claude-science-export | The operator confirms the five open design questions, which the implementation resolved with the design's recommended answers (config locus, CSV/JSON default, encrypted bundles, attestation persistence, inadmissible runs). |
| docs-first-configuration-reframe | The operator reviews the documentation before it is published. |
| headless-host-operations | On the Jetson worked-example host: run the ordered sequence and record that the remote-access gate preceded the headless switch; set and record the MAXN_SUPER power mode; enable lingering for the service user and record that units start at boot; record the NVMe swapfile and `vm.swappiness` = 10 after a reboot. |
| any-target-bootstrap | Record real install runs on the desktop, the Orin Nano Super and a Pixel 6a under Termux. |
| hardware-and-storage-selection | Record a real run of the setup wizard on the desktop and on the Orin Nano Super. |
| sherpa-onnx-speech | Install on a Pixel 6a under Termux and run the live speech round trip there. |

## Backlog totals

The roadmap contains 73 active changes, 366 archived changes and 109 capability specs.

If you want to pick up one of these changes, see [Contributing](21-contributing.md).
