# Roadmap

This page shows the engineering work in flight, the operator and on-device steps still open from finished work, and the overall backlog size. It is for contributors choosing what to work on and for operators who want to know which parts of the system are still under construction.

## Active changes

| Change | Progress | Summary |
| --- | --- | --- |
| docs-front-pages-voice | 3/4 (75%) | Rewrite the README opening and the book's front page so KAINE is introduced as source-available software implementing Global Workspace Theory and Predictive Processing, leading with the architecture and the activation roadmap; held for the operator's review. |
| seed-entity-distribution | 0/2 (0%) | Consider distributing an entity preserved at maturation with the runtime that continues from it, so installations can skip the developmental phase. Design only: under consideration, not decided. |
| interface-roles-and-launcher | 0/3 (0%) | Fieldtrip is the basic interface for entities, remote or local on smaller devices such as phones, with a few minor admin and operator actions; the dashboard web UI is the deeper operator control plane; bringing up an entity or a research study run, the seed included, is a scripted task started in a click or two of a small GUI. Design only: not scheduled. |
| act-intent-derivation | 0/5 (0%) | Action path, step 1 of 6: the action-selection module derives act intents by the act outcome of the report-or-act decision the report bars stand in for (Whyte and Smith 2021), and the first whitelisted device effector is a light in the camera's view. Design only: not scheduled. Starts at the module-addition study's hardware stage (paper §6.5) once a light is attached. |
| planning-act-proposals | 0/5 (0%) | Action path, step 2 of 6: the planning module's action space grows by the attached effector's declared actions, so its proposals can ask for acts. Design only: not scheduled. Starts after act-intent-derivation, at the module-addition study's hardware stage (paper §6.5). |
| embodiment-motor-contingency | 0/6 (0%) | Action path, step 3 of 6: a motor-contingency learner, its driving loop and body-declared freeze-then-free stages for the embodiment control surface, with a pan-tilt camera as the first body. Design only: not scheduled. Starts after act-intent-derivation, at the module-addition study's hardware stage (paper §6.5) once the camera is attached. |
| active-vision | 0/5 (0%) | Action path, step 4 of 6: the entity chooses where to look by expected free energy and turns the pan-tilt camera to look. Design only: not scheduled. Starts after embodiment-motor-contingency has freed the camera's gaze channels, at the module-addition study's hardware stage (paper §6.5). |
| world-model-action-outcomes | 0/5 (0%) | Action path, step 5 of 6 (parallel with step 4): the world model conditions on the entity's own acts and motor commands, so it predicts their outcomes. Design only: not scheduled. Starts after act-intent-derivation and embodiment-motor-contingency, at the module-addition study's hardware stage (paper §6.5). |
| goal-directed-grasping | 0/5 (0%) | Action path, step 6 of 6: goal-directed grasping with an arm and gripper, composed from steps 1 to 5. Design only: not scheduled. Starts after all five earlier steps, at the module-addition study's hardware stage (paper §6.5) once the arm is attached. |
| attention-driven-audition | 19/32 (59%) | Move hearing beyond speech transcription so audio can drive workspace salience. |
| attention-driven-foveation | 14/18 (78%) | Replace uniform screen downsampling with a foveated capture that keeps fine detail where it matters. |
| entity-key-custody | 1/12 (8%) | Redesign entity-state encryption so keys can be recovered or rotated without manual re-encryption. Design only: awaiting the integrator's review (task 0.1) and the operator's key ceremony (task 0.3); nothing is implemented. |
| individuation-rebuild | 57/67 (85%) | Replace the individuation signal with a real test against the entity's own maturation reference, produced at runtime and read the same way by preservation and decommission. The real-organ calibration (task 10) is next. |
| module-ignition-study | 29/33 (88%) | The module-addition study: seed an entity through a developmental phase, then add held modules one at a time on branches from the preserved seed, every branch viewing the same film programme, with a content-free report. |
| module-residency-and-speech-tiers | 9/60 (15%) | Make the same entity run on weak hardware by selectively loading and tiering speech backends. |
| stream-wiring-quality | 20/20 (100%) | Clean up bus stream names, remove phantom reads and enforce the stream contract across modules. |
| adapter-merge-out-of-process | 3/3 (100%) | Run the real adapter merge in a child process, so its non-float32 model load can never change a long-lived process's default dtype. Built; awaiting archive. |
| sequence-scalar-timing | 1/3 (33%) | Test whether the sequence module's interval timing shows the scalar property (timing variability proportional to the interval), as a falsification test. Design only. |
| functional-module-names-drop-aliases | 0/10 (0%) | After release 27.02, refuse the old configuration names and remove the operator aliases the module rename kept for a bounded window; stored names stay readable for good. Waits for that release. |
| workspace-feedback | 12/14 (86%) | Held extension (paper §3.2, §6.4): top-down heads, a zero-sum gain on the processors' standardized errors and conflict resolution, shipped off with the five ablation arms selectable by study. |
| decision-server | 3/10 (30%) | Serve the K1-Jev decision model on its own loopback llama-server, apart from the language organ, with a fail-closed client (the client is built). |
| sleep-replay | 1/3 (33%) | Protect what the small online learners learned from later interference with sleep-like replay (Wei, Krishnan and Bazhenov). Design only. |
| k1-jev-decision-model | 11/33 (33%) | Train K1-Jev, a small local model that answers typed questions about the entity's external speech for the instruments and welfare signals (data and trainer built). Schema v2 is designed and blocked: labelling and training are not scheduled (neither the v2 rebuild nor the operator's labelling pass has a date), and the integrator's design check (task 0.1) is open. |
| episodic-memory-retrieval-energy | 1/3 (33%) | Publish a familiarity signal from the episodic memory module as the modern-Hopfield retrieval energy of the current content. Design only. |
| affect-active-inference | 1/4 (25%) | Derive the affect module's affect from active inference over the body's internal state. Design only, after the workspace-mediation test. |
| voice-development | 7/17 (41%) | Let the entity individuate a voice of its own instead of reciting workspace readings, in stages, with heard speech never persisted. |
| docs-sweep-2026-10 | 8/9 (89%) | Bring every page of the book into line with the revised paper and the merged code. |
| per-entity-shared-volumes | 0/6 (0%) | Shared adapter and job volumes keep each entity's files under its own id, so ownership is structural. |
| ablation-positive-control | 9/10 (90%) | The positive control of the information-gain measure: shadow forward models with an informative and a non-informative component, a per-processor verdict in the research log, and an offline all-processors check. Off by default. |
| pilot-calibration | 20/21 (95%) | The tool that derives the planned test's settings from the pilot runs into one versioned record, the positive control on the inputs' first principal component with per-processor SNR and the learning period, and a boot check that refuses live runs without a complete record. |
| vox-default-voice | 16/18 (89%) | With no voice configured, the vocal module picks a voice the speech engine ships, first in sorted order and filtered by an optional gender preference where the engine reports gender (Kokoro yes, Chatterbox no); an explicit voice wins, and no voice degrades the module to silence with a clear message. The entity choosing its own voice is designed as a follow-up only. |
| trainer-shares-the-gpu | 4/4 (100%) | The voice trainer loads its base with PyTorch's expandable-segments allocator, so it fits beside other processes on a shared GPU, and a failed load reports the real allocation error. |
| trainer-without-unsloth | 8/8 (100%) | The voice trainer runs its own DPO loop on transformers, PEFT and bitsandbytes, without Unsloth or TRL. |
| welfare-response-fail-safe | 10/10 (100%) | The welfare response tells a failed freeze from a placed pause, retries the freeze, falls back to a pause when an end cannot be enacted, and never overwrites a corrupt control file. |

## Designed in the paper, not built

The paper's §5.4 lists these parts as specified ahead of their code.

| Part | What it is |
| --- | --- |
| NOT EXERCISED share rule | A planned-test run is NOT EXERCISED when fewer than a share φ_min of the on arm's broadcasts, fixed before the pilots, have more candidates than the coalition holds. The calibration tool counts a run as exercised once one such broadcast occurs. |
| Coalition capacity and candidate supply | Settings that make competition operate in the planned test, chosen before the pilots: in seven developmental test boots the workspace received 1.18 candidates per broadcast tick on average and more than five on 0.06 percent of them. |
| The seed's wait for its individuation reference | The seed entity is preserved at maturation only once its individuation reference is captured within one waking span. |
| Stir | In the developmental phase, when the entity's boredom or restlessness leads an accessed broadcast, it stirs and the maternal voice may answer. Until it is built, nothing the entity does changes its stimulus; a sleep it requests pauses the feed. |
| Added sounds | A recurring melody and an attenuated outside voice in the developmental stimulus. |
| Hearing stages without a minimum dwell | Hearing stages that end only when audition's learning saturates; the built schedule keeps a minimum dwell of 1.5 awake hours per stage. |

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

The roadmap contains 34 active changes, 423 archived changes and 109 capability specs.

If you want to pick up one of these changes, see [Contributing](21-contributing.md).
