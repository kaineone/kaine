# Roadmap

This page shows the engineering work in flight, the operator and on-device steps still open from finished work, and the overall backlog size. It is for contributors choosing what to work on and for operators who want to know which parts of the system are still under construction.

## Active changes

| Change | Progress | Summary |
| --- | --- | --- |
| attention-driven-audition | 19/32 (59%) | Move hearing beyond speech transcription so audio can drive workspace salience. |
| attention-driven-foveation | 14/18 (78%) | Replace uniform screen downsampling with a foveated capture that keeps fine detail where it matters. |
| entity-key-custody | 0/12 (0%) | Redesign entity-state encryption so keys can be recovered or rotated without manual re-encryption. |
| individuation-rebuild | 56/67 (84%) | Replace the individuation signal with a real test against the being's own birth reference, produced at runtime and read the same way by preservation and decommission. The real-organ calibration (task 10) is next. |
| module-ignition-study | 29/33 (88%) | The module-addition study: seed a being through a gestation, then add held modules one at a time on branches from the preserved seed, every branch viewing the same film programme, with a content-free report. |
| module-residency-and-speech-tiers | 9/60 (15%) | Make the same entity run on weak hardware by selectively loading and tiering speech backends. |
| portability-program | 7/8 (88%) | Honest portability claims and verified support from small boards up to multi-GPU servers. |
| stream-wiring-quality | 18/20 (90%) | Clean up bus stream names, remove phantom reads and enforce the stream contract across modules. |
| adapter-merge-out-of-process | 0/3 (0%) | Run the real adapter merge in a child process, so its non-float32 model load can never change a long-lived process's default dtype. Design only. |
| chronos-scalar-timing | 1/3 (33%) | Test whether Chronos's interval timing shows the scalar property (timing variability proportional to the interval), as a falsification test. Design only. |
| decision-server | 3/10 (30%) | Serve the K1-Jev decision model on its own loopback llama-server, apart from the language organ, with a fail-closed client (the client is built). |
| deterministic-grader-fixes | 13/15 (87%) | Replace bare substring matching in the capability, refusal and hedge graders with exact, tested rules; two tasks need organ runs. |
| hypnos-sleep-like-replay | 1/3 (33%) | Protect what the small online learners learned from later interference with sleep-like replay (Wei, Krishnan and Bazhenov). Design only. |
| k1-jev-decision-model | 10/26 (38%) | Train K1-Jev, a small local model that answers typed questions about the entity's external speech for the instruments and welfare signals (data and trainer built; schema v2 and operator gold labels next). |
| mnemos-retrieval-energy | 1/3 (33%) | Publish a familiarity signal from Mnemos as the modern-Hopfield retrieval energy of the current content. Design only. |
| thymos-active-inference-affect | 1/4 (25%) | Derive Thymos's affect from active inference over the body's internal state. Design only, after the workspace-mediation test. |
| voice-development | 7/17 (41%) | Let the entity individuate a voice of its own instead of reciting workspace readings, in stages, with heard speech never persisted. |
| audition-window-duration-bands | 6/6 (100%) | Apply Audition's arousal-sized attended window to the audio it encodes, so the window changes what is heard. |
| coherence-fresh-phases | 6/6 (100%) | Count only fresh phases in the coherence layer's phase-locking value, so a module that has not published adds nothing. |
| docs-sweep-2026-10 | 8/9 (89%) | Bring every page of the book into line with the revised paper and the merged code. |
| eidolon-drift-disjoint-reference | 6/6 (100%) | Measure Eidolon's drift against a reference that excludes the recent window. |
| graded-intensity-alert-phasic | 5/6 (83%) | Graded intensity for every predictive processor, with the access rate rising on alerts only. |
| local-precision-global-gain | 8/8 (100%) | Remove the workspace's per-source precision weight; arousal acts as a global gain that never reorders a tick. |
| nous-benchmark-fair-baseline | 5/5 (100%) | Give the Nous benchmark's Q-learning baseline the episode history, so the comparison is fair. |
| precision-weighted-selection | 9/9 (100%) | Per-source precision weighting in Syneidesis. Superseded by local-precision-global-gain, which removes the weight. |
| relicense-cal-0.4 | 4/4 (100%) | Relicense KAINE to CAL 0.4 with an adoption notice. |
| reservoir-timespan-soma-vram | 8/8 (100%) | Pass real timespans to the CfC reservoir and keep Soma's model within its memory budget. |
| sleep-restart-continuity | 10/10 (100%) | Carry Thymos and Chronos state correctly across sleep, pauses and restarts. |
| soma-warmup-fatigue-baseline | 4/4 (100%) | Compare like with like in Soma's warm-up fatigue baseline. |
| suite-strict-alpha | 3/3 (100%) | Use the strict inequality p < alpha for the suite's mediation verdict. |
| test-isolation-operator-overlay | 3/3 (100%) | Keep the operator overlay and the data root out of tests that do not ask for them. |
| thymos-rate-invariant-timely-state | 6/6 (100%) | Make Thymos's appraisal independent of the broadcast rate and its published state timely. |
| thymos-research-affect | 13/13 (100%) | Setpoint drive dynamics with relief, grounded in the affect literature. |
| topos-tile-precision-real-clips | 5/5 (100%) | Per-tile precision in Topos's spatial saliency, tested on real clips. |

## Open operator and device steps

These steps come from changes whose code is finished and archived. Each needs the operator, a specific device, or an operator decision, so no contributor can close it alone. The archived change's `tasks.md` keeps the full wording.

| From change | Step |
| --- | --- |
| unattended-boot-via-safety-net | Before enabling unattended starts on a real entity: the operator confirms the research phase has ended. |
| unattended-boot-via-safety-net | Before enabling unattended starts on a real entity: Spot runs enabled on supervised boots, handles at least one injected module failure end to end and one escalation drill, and the operator reviews the incident logs and signs off. |
| perception-drives-salience | Boot the base-thesis form on the reference corpus and confirm perceptual discontinuities reach the workspace competition with a score that varies with the stimulus. Access-threshold calibration follows only after that passes, as its own change. |
| containerize-deployment | Measure the latency of the broadcast path in containers against host-native on GPU hardware, and confirm parity at the 10 Hz processing rate and the 3.333 Hz resting access rate. |
| claude-science-export | The operator confirms the five open design questions, which the implementation resolved with the design's recommended answers (config locus, CSV/JSON default, encrypted bundles, attestation persistence, inadmissible runs). |
| docs-base-thesis-reframe | The operator reviews the documentation before it is published. |
| headless-host-operations | On the Jetson worked-example host: run the ordered sequence and record that the remote-access gate preceded the headless switch; set and record the MAXN_SUPER power mode; enable lingering for the service user and record that units start at boot; record the NVMe swapfile and `vm.swappiness` = 10 after a reboot. |
| any-target-bootstrap | Record real install runs on the desktop, the Orin Nano Super and a Pixel 6a under Termux. |
| hardware-and-storage-selection | Record a real run of the setup wizard on the desktop and on the Orin Nano Super. |
| sherpa-onnx-speech | Install on a Pixel 6a under Termux and run the live speech round trip there. |

## Backlog totals

The roadmap contains 34 active changes, 268 archived changes and 104 capability specs.

The project is paused from 2026-10-06; `docs/records/2026-10-06-handoff.md` gives the state and how to resume.

If you want to pick up one of these changes, see [Contributing](21-contributing.md).
