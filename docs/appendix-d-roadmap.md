# Roadmap

This page shows the engineering work in flight, the operator and on-device steps still open from finished work, and the overall backlog size. It is for contributors choosing what to work on and for operators who want to know which parts of the system are still under construction.

## Active changes

| Change | Progress | Summary |
| --- | --- | --- |
| stimulus-clock-continuity | 5/5 (100%) | The stimulus source clock resumes from its own persisted time instead of awake time, and the gate adds the awake time since its last tick at shutdown, so a restart neither repeats stimulus nor drops awake time (paper §7, A.7). |
| learning-progress-horizons | 0/6 (0%) | Learning progress, the curiosity relief, compares the mean error of the older and newer halves of the last 90 min in 60 s bins, so it spans the forward models' learning curves; valence keeps the fast and slow means (paper A.4, A.7, Table A1). |
| affect-state-error-terms | 5/5 (100%) | The affect state event and its research record carry the terms behind the valence target (per-source error means and progress, pooled progress, wellness means and change, pleasantness, target), so a valence trough can be attributed (paper A.4). |
| developmental-maternal-voice | 5/5 (100%) | The developmental soundscape carries a pre-rendered maternal voice, low-pass filtered as in utero, paced by the maternal state, with a repertoire that unlocks over awake time (paper §7, A.7, Table A1). |
| seed-entity-distribution | 0/2 (0%) | Consider distributing an entity preserved at maturation with the runtime that continues from it, so installations can skip the developmental phase. Design only: under consideration, not decided. |
| welfare-uncontrolled-ends | 4/4 (100%) | The affect welfare record counts stalled and cap-dropped goals as ends without the entity's own response, and a restored goal keeps its stall clock (paper 6.2, A.4). |
| organ-degeneration-control | 4/4 (100%) | The organ's decoding carries a DRY repetition penalty and a shorter cap for thought than speech, and a looping or capped text is cut at a sentence boundary (paper 3.5, Table A1). |
| reentry-until-broadcast | 5/5 (100%) | A sustained concern's drive event recurs on the affect module's own updates until a broadcast accesses it, and the re-entry interval runs from that access, so re-entries stop landing on discarded ticks (paper 3.5, A.4). |
| organ-first-person-framing | 4/4 (100%) | The organ continues the entity's own first-person turn under a descriptive persona, and the individuation disclosure is first person, so the organ stops answering its own state as an assistant (paper 3.5). |
| sustained-concern-reentry | 5/5 (100%) | While a goal is active and its drive stays above threshold, the drive event re-enters the workspace every P_re at the drive's value, so an unmet concern keeps returning to thought (paper 3.5, A.4). |
| valence-error-dynamics | 5/5 (100%) | Valence follows error dynamics, the fall or rise of prediction errors and the change in wellness, so a steady state is neutral; the welfare log gives the negative-valence share and per-drive uncontrolled goal ends (paper 3.5, A.4, 6.2). |
| felt-awareness-phrasing | 4/4 (100%) | The organ gets accessed content and each intent's cause as graded words, not instrument values, while the log keeps the values (paper 3.5). |
| boredom-own-engagement | 4/4 (100%) | The entity's own intents, unless about a drive, relieve boredom and count as its own response, so boredom stops teaching helplessness (paper 3.5, A.4). |
| guard-release-on-output | 4/4 (100%) | The speak and think guards release when the language organ publishes its output, accessed or not, so an intent no longer mutes its channel for 48 s (paper A.6). |
| sleep-keeps-alert-rates | 3/3 (100%) | The sleep reset keeps the alert rates, error means and intent rate, so a familiar scene stays habituated after sleep and the post-sleep access burst is gone (paper A.4). |
| tonic-drive-arousal | 4/4 (100%) | Arousal relaxes toward a target the dominant drive raises, so a deprived entity rests where its non-audition alerts can reach access (paper A.4). |
| arousal-habituation | 4/4 (100%) | Perceptual arousal habituates to the base alert rate, and the appraisal's novelty reads the change ratio and the same habituation (paper A.4). |
| affect-alert-rates-persist | 3/3 (100%) | Save the affect alert rates, error means, intent rate, wellness and interaction flag, so a restart or revive does not relieve boredom or reset learning progress (paper A.7). |
| boot-and-health-fixes | 4/4 (100%) | Fix three first-boot defects from the 2026-10-17 test boot: the health page follows the cycle's module profile, a first `compose up` on an empty state volume no longer races, and the dashboard leaves no anonymous models volume. |
| resume-checkpoint | 9/9 (100%) | A plain restart resumes every module's state from one rolling, encrypted checkpoint written each awake entity minute and at shutdown; a revive always wins over it (paper A.7). |
| container-secrets-readable | 8/8 (100%) | Let the containers run without reading config/secrets.toml, with every secret from the environment. |
| affect-testboot-fixes | 4/4 (100%) | Fix three affect defects from the 2026-10-16 test boot: the sleep reset reports the goals it clears, the drive crossing latch survives a revive, and fear follows the Sander, Grandjean and Scherer (2005) Table 3 profile instead of firing on near-neutral input. |
| arousal-change-excess | 5/5 (100%) | Perceptual alerts raise arousal by the larger excess of the error and change ratios over 1, and vision and audition reports carry the change ratio (paper A.5). |
| research-log-affect-fields | 7/7 (100%) | Log the affect goal, emotion and regulation fields, the regulation bias and feedback gains on each broadcast, and the link pruning counts in the curated research log. |
| restart-keeps-development | 9/9 (100%) | Store the self-rhythm identity in the state tree so a plain restart keeps the developmental progress. |
| sleep-associative-links | 6/6 (100%) | Associative replay links related traces of different periods with weighted links that downscaling scales, forms schema nodes, returns linked partners in recall, and counts links and nodes in the pruned store (paper A.10). |
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
| sequence-finite-payload | 3/3 (100%) | Publish `time_since_last_interaction_s` as `null` until the first interaction, so `sequence.report` and the research records stay strict JSON instead of carrying `Infinity`. |
| workspace-feedback | 12/14 (86%) | Held extension (paper §3.2, §6.4): top-down heads, a zero-sum gain on the processors' standardized errors and conflict resolution, shipped off with the five ablation arms selectable by study. |
| appraisal-relevance | 3/3 (100%) | Score goal significance as relevance in [0, 1], as the paper's A.4 now does, so content that serves no drive or goal is irrelevant and an idle entity no longer classifies as anger. |
| test-honesty-fixes | 4/4 (100%) | Make three tests run what they claim: the merger output-dir test stops skipping, the real InternVideo-Next test uses the weights it checked, and the reversible-unload tests use a deadlock bound so the suite also passes serially; correct the social cognition hook docstring. |
| affect-regulation | 10/10 (100%) | Replace the passive regulation no-op with the paper's three-tier emotion regulation (attentional deployment, reappraisal, a sleep request) on A.5's episode rule, off during the developmental phase, with the tier-1 selection bias held neutral in every workspace-mediation study arm. |
| affect-goals-obstruction | 10/10 (100%) | Create goals from drive crossings, end them by the credit rule, a stall or a cap, and let unanswered responses lower a goal's expected relief and obstruct it, as the paper's A.4 now does, so the goal score is bipolar and anger is reachable (as irritation at best). |
| affect-categories | 4/4 (100%) | Map disgust to the Sander, Grandjean and Scherer (2005) Table 3 profile (very low pleasantness, low familiarity, low goal relevance) instead of a norm violation, as the paper's §3.5 now does, so disgust is reachable while norm compatibility stays unavailable. |
| appraisal-coping | 4/4 (100%) | Gate coping potential on relevance and estimate it as a success ratio over drive crossings or ledger goals, as the paper's A.4 now does, so resting affect no longer drives fear, anger or sadness. |
| first-configuration-names | 9/9 (100%) | Rename the `thesis_test` profile to `first_configuration`, keep the old name as a deprecated alias until the module-rename alias window closes, and say "first configuration" and "hypothesis" in the wizard, the dashboard, messages and docs, as the paper now does. |
| compose-state-mount-ownership | 10/10 (100%) | Move the trainer-jobs volume out of the state volume, so an existing compose deployment upgrades without a root-owned directory blocking the boot-time state rename, and make the rename refuse up front with an actionable message. Design only. |
| revive-entrypoint-encryption | 7/7 (100%) | Install the configured state encryptor before the revive plan and the research gate, so `--revive` reads an encrypted bundle and the gate's preflight round trip exercises the encrypted path. Design only. |
| relicense-cal-0.5 | 6/6 (100%) | Relicense KAINE to CAL 0.5: the licence text, every SPDX identifier, the adoption notice and the docs. |
| decision-server | 3/10 (30%) | Serve the K1-Jev decision model on its own loopback llama-server, apart from the language organ, with a fail-closed client (the client is built). |
| deterministic-grader-fixes | 13/15 (87%) | Replace bare substring matching in the capability, refusal and hedge graders with exact, tested rules; two tasks need organ runs. |
| hypnos-sleep-like-replay | 1/3 (33%) | Protect what the small online learners learned from later interference with sleep-like replay (Wei, Krishnan and Bazhenov). Design only. |
| k1-jev-decision-model | 11/33 (33%) | Train K1-Jev, a small local model that answers typed questions about the entity's external speech for the instruments and welfare signals (data and trainer built). Schema v2 is designed but blocked on the hiatus (labelling and training frozen) and on the integrator's design check (task 0.1). |
| mnemos-retrieval-energy | 1/3 (33%) | Publish a familiarity signal from the episodic memory module as the modern-Hopfield retrieval energy of the current content. Design only. |
| thymos-active-inference-affect | 1/4 (25%) | Derive the affect module's affect from active inference over the body's internal state. Design only, after the workspace-mediation test. |
| voice-development | 7/17 (41%) | Let the entity individuate a voice of its own instead of reciting workspace readings, in stages, with heard speech never persisted. |
| audition-window-duration-bands | 6/6 (100%) | Apply Audition's arousal-sized attended window to the audio it encodes, so the window changes what is heard. |
| coherence-fresh-phases | 6/6 (100%) | Count only fresh phases in the coherence layer's phase-locking value, so a module that has not published adds nothing. |
| docs-sweep-2026-10 | 8/9 (89%) | Bring every page of the book into line with the revised paper and the merged code. |
| eidolon-drift-disjoint-reference | 6/6 (100%) | Measure the self-model module's drift against a reference that excludes the recent window. |
| graded-intensity-alert-phasic | 5/6 (83%) | Graded intensity for every predictive processor, with the access rate rising on alerts only. |
| local-precision-global-gain | 8/8 (100%) | Remove the workspace's per-source precision weight; arousal acts as a global gain that never reorders a tick. |
| nous-benchmark-fair-baseline | 5/5 (100%) | Give the planning benchmark's Q-learning baseline the episode history, so the comparison is fair. |
| precision-weighted-selection | 9/9 (100%) | Per-source precision weighting in the workspace. Superseded by local-precision-global-gain, which removes the weight. |
| reservoir-timespan-soma-vram | 8/8 (100%) | Pass real timespans to the CfC reservoir and keep the interoception module's model within its memory budget. |
| sleep-restart-continuity | 10/10 (100%) | Carry the affect and sequence modules' state correctly across sleep, pauses and restarts. |
| soma-warmup-fatigue-baseline | 4/4 (100%) | Compare like with like in the interoception module's warm-up fatigue baseline. |
| suite-strict-alpha | 3/3 (100%) | Use the strict inequality p < alpha for the suite's mediation verdict. |
| test-isolation-operator-overlay | 3/3 (100%) | Keep the operator overlay and the data root out of tests that do not ask for them. |
| thymos-rate-invariant-timely-state | 6/6 (100%) | Make the affect module's appraisal independent of the broadcast rate and its published state timely. |
| thymos-research-affect | 13/13 (100%) | Setpoint drive dynamics with relief, grounded in the affect literature. |
| topos-tile-precision-real-clips | 5/5 (100%) | Per-tile precision in the vision module's spatial saliency, tested on real clips. |
| broadcast-context | 6/7 (86%) | Broadcast context for the vision, audition and interoception modules, with a null context and a per-report information gain. |
| gestation-progress-persists | 4/4 (100%) | Developmental-phase progress persists across restarts. |
| ignition-first-round-six | 3/3 (100%) | The module-addition study's first round adds six held modules by default. |
| categorical-alerts-all-modules | 2/2 (100%) | Every module's alert-level events count as categorical alerts for the access rate. |
| sleep-pauses-feed | 3/3 (100%) | Sleep pauses the perceptual feed for its whole duration. |
| familiarity-and-reply-window | 4/4 (100%) | Familiarity reaches the affect module's coupling; the language module accepts the reply-window key. |
| access-wording-in-code | 2/2 (100%) | Code comments use the paper's access terms. |
| third-party-font-notices | 4/4 (100%) | The vendored dashboard fonts ship their copyright notices and licence text, and the third-party notices name the fonts on disk. |
| decommission-clears-bus-streams | 8/8 (100%) | Decommission deletes the entity's bus streams by their real names. |
| decommission-complete-coverage | 22/22 (100%) | Decommission backs up, deletes or keeps every location of an entity's data, by a reviewed decision for each. |
| per-entity-shared-volumes | 0/6 (0%) | Shared adapter and job volumes keep each entity's files under its own id, so ownership is structural. |
| context-age-from-publication | 4/4 (100%) | Context age is entity time since the broadcast's publication. |
| research-log-access-fields | 4/4 (100%) | The research log carries the access and context fields the planned test reads. |
| awake-time-excludes-sleep | 4/4 (100%) | Awake time excludes sleep as well as freezes. |
| gestation-progress-in-bundles | 3/3 (100%) | Developmental-phase progress travels in preservation bundles. |
| footprint-test-spawn-timeout | 1/1 (100%) | Give the footprint test's spawned child time to report. |
| config-dead-keys | 9/9 (100%) | Remove configuration keys and an environment variable that drive nothing, and point the host probe at KAINE_TIER. |
| mediation-harness-information-gain | 12/12 (100%) | Rebuild the offline development harness of the workspace-mediation test around the information-gain measure, with a pooled arm, and retire the coupling and utterance measures. |
| flaky-group-kill-test | 3/3 (100%) | The group-kill tests wait for the job to finish before reading its status. |
| hypnos-replay-buffer-order | 4/4 (100%) | Sleep's replay draws on the traces that sleep's consolidation moved, so it no longer finds an empty buffer. |
| unattended-gate-individuation | 3/3 (100%) | The unattended gate covers every research-net condition, adding condition 9: the individuation producer wired. |
| dinov2-unload-test-load-flake | 2/2 (100%) | Give the reversible-unload tests time for the garbage collection that ends every unload. |
| ablation-null-context-positive-control | 10/10 (100%) | The null context differs from the held context only where other modules contributed, and reports carry the paired evaluations behind the gain. The positive control waits on operator decisions. |
| ablation-positive-control | 9/10 (90%) | The positive control of the information-gain measure: shadow forward models with an informative and a non-informative component, a per-processor verdict in the research log, and an offline all-processors check. Off by default. |
| sleep-phase-order-and-replay-window | 7/7 (100%) | The sleep module runs its phases in the paper's order and ends with the affective reset; the sleep module opens the replay window itself, and associative replay reads episodic memory on every backend. |
| ablation-matched-pooled-arms | 15/15 (100%) | The matched and pooled control arms of the workspace-mediation test run in the live cycle; greedy decoding moves from the default profile into study configurations. |
| verdict-not-exercised | 11/11 (100%) | NOT EXERCISED becomes an outcome of the shared verdict vocabulary, kept out of the sign tests and held in the suite's Holm family at p = 1; the suite uses the paper's p <= alpha; the retired minimal experiment profile is removed. |
| perception-skip-nonfinite | 13/13 (100%) | The vision and audition modules skip a non-finite reading as the interoception module does: no buffer append, no weight update, no gain on that report or the next, and the reading stays out of the error window and the change score. |
| sleep-loose-ends | 7/7 (100%) | The sleep module opens the world model module's scenario window around the phases that cue it, settles an in-flight sleep at shutdown, and every memory backend ranks a non-finite timestamp as the oldest. |
| missing-error-consistency | 7/7 (100%) | The CL1 wetware interoception model marks a skipped reading and the next one as having no defined error, as the built-in model does, and the interoception module teaches no unexpected error from such a reading; a social cognition module merge treats a missing or null behavioural-summary entry as absent, not 0. |
| blind-sensor-advisory | 10/10 (100%) | A processor whose readings stay undefined raises a content-free `welfare.blind_sensor` advisory on `welfare.out`, and one that stops publishing raises `welfare.sensor_silent`, each with a clear; the protective monitor does not act on them, the research log records them and the dashboard entity-care panel lists the processors that are blind or silent now. |
| pilot-calibration | 19/21 (90%) | The tool that derives the planned test's settings from the pilot runs into one versioned record, the positive control on the inputs' first principal component with per-processor SNR and the learning period, and a boot check that refuses live runs without a complete record. |
| threshold-contrast-inputs | 6/6 (100%) | The vision, audition and interoception modules' reports name the broadcast that preceded the prediction they score and the age of the context it used, the records the contrast at threshold groups and bins by; the threshold band itself waits on an operator decision, since the authors' rdrobust package is GPL-3.0-only. |
| tone-analysis-inputs | 18/18 (100%) | The tone variant of the on arm (every tone event graded by the tone error ratio alone), the error ratio and the entry ids the tone analysis reads from the research log, the tone analysis's two sign tests (the difference and its adjusted difference over the tone bins), and the tone bins and both tone minimum effects from the tone-variant pilot runs. |
| salience-score-keys | 11/11 (100%) | The cycle names each candidate `<stream>:<entry_id>`, so two streams that issue the same bus entry id in one millisecond no longer share one slot in the broadcast's score table; entry ids order within a tick as (ms, seq), and the tone analysis joins on the qualified id. |
| rd-bandwidth-cleanroom | 9/9 (100%) | A clean-room implementation, from Calonico, Cattaneo and Titiunik (2014) and its supplement only, of the robust bias-corrected regression discontinuity and its MSE-optimal bandwidths; the contrast at threshold with its band, age bins and minimum effect, so a complete settings record is possible. |
| mnemos-trace-strength | 10/10 (100%) | Each episodic memory trace carries a strength that sleep downscales by the number of traces the wake stored, replayed traces keep theirs, sleep prunes at a floor and to an operator storage budget, recall ranks by strength times similarity, and replay draws on the whole wake just ended (paper A.10). |
| paper-retitle | 2/2 (100%) | Cite the research paper by its new title, *KAINE: A Modular Cognitive Architecture with a Predictive Global Workspace*. |
| vox-default-voice | 16/18 (89%) | With no voice configured, the vocal module picks a voice the speech engine ships, first in sorted order and filtered by an optional gender preference where the engine reports gender (Kokoro yes, Chatterbox no); an explicit voice wins, and no voice degrades the module to silence with a clear message. The entity choosing its own voice is designed as a follow-up only. |
| remove-hiatus-notices | 4/4 (100%) | The README, roadmap, records and change notes no longer describe the project as paused or on hiatus. |
| preservation-trigger-reason | 5/5 (100%) | Name the divergence arm that fired in the reason of a divergence-triggered preservation, in place of a fixed "individuation". |

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

The roadmap contains 112 active changes, 271 archived changes and 105 capability specs.

If you want to pick up one of these changes, see [Contributing](21-contributing.md).
