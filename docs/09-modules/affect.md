# Affect

The affect module is the affective core. It holds a dimensional state of valence, arousal and dominance, runs an appraisal of every workspace broadcast, and keeps four homeostatic drives. Its arousal is the global gain on the workspace competition. Read this page if you enable the module, run the `first_configuration` profile, or need to know what moves arousal and valence and what the sleep module resets.

The affect module ships disabled in the default config (`[modules].affect = false` in `config/kaine.toml`). The `first_configuration` profile enables it, because a global gain that sets how readily content gains access, and that surprise itself moves, belongs to the minimal machinery of the first configuration. It needs nothing beyond the core stack.

## Arousal: the global gain and contrast

Every predictive processor scales its own prediction error by its recent errors (local precision). Arousal adds one gain across all of them, following the adaptive-gain account of locus coeruleus function. The workspace computes each candidate's priority as `p = clip(intensity × novelty × goal, 0, 1)`, with the goal factor held at 1 by default (`[workspace].salience_goal_factor = "static"`), and turns it into a score with two arousal terms:

```
T = 0.2 + 0.8 × a                                 level gain, common to every candidate
g = g_max × clip((a - a0) / (1 - a0), 0, 1)       contrast gain, zero at or below baseline
score = T × C_g(p)
```

`a` is arousal, `a0` is `[affect].baseline_arousal` (0.3), and `g_max` is `[workspace].arousal_contrast_gain` (8.0). `C_g` is a logistic in the priority, rescaled so that it fixes 0 and 1 and reduces to the identity at `g = 0`. Because the level gain is shared and `C_g` is strictly increasing, arousal never reorders the candidates of a tick. It moves the best score relative to the access threshold and the report bars, it decides which members of a coalition reach the threshold, and it widens the gap between the scores of strong and weak candidates.

Arousal also sizes the sensory apertures. The vision module narrows its fovea and the audition module shortens its attended window as arousal rises. Tonic arousal raises the access rate as well (see [The cognitive cycle](../08-cognitive-cycle/README.md)).

The cycle reads arousal from the latest `affect.state` event it has collected, through `AffectStateProvider` (`kaine/cycle/affect_state.py`), which starts at the baseline before the first event. The workspace gain, the fovea, the auditory window and the access rate therefore see arousal as it stood at the affect module's last state publication, up to one `publish_interval_s` old.

### What moves arousal

The appraisal of a broadcast does not move arousal, so a higher access rate cannot feed back into it. Arousal rises on three paths, all read directly from the producing modules' streams whether or not the report wins access:

| Source | Condition | Change in arousal |
|---|---|---|
| `vision.report`, `audition.perception` | `alert: true` | `+0.15 × min(4, max(0, r - 1))`, with `r` the report's `normalised_error` (its error over its running mean) |
| `interoception.report` | non-empty `alerts` list (a host metric past its hard limit) | `+0.05` |
| `episodic_memory.recall` | `max_affect_intensity > 0` | `+0.05 × max_affect_intensity` (the episodic memory module is held in the first configuration) |

An alert raised by a change criterion alone, with `r <= 1`, leaves arousal unchanged. Between these nudges arousal and dominance relax toward their baselines: at each update `a <- a + (a0 - a) × min(1, drift_rate_per_s × dt)`, a time constant of 20 entity seconds at the default rate. Arousal is clipped to `[0, 1]`.

## Valence from learning progress

Valence follows learning progress, the reading of valence as the negative rate of change of free energy (Joffily and Coricelli 2013). For each perceptual source (the vision module and the audition module's acoustic path) the affect module keeps a fast and a slow time-decayed mean of the raw `prediction_error` its reports carry, counting from the source's first positive error:

```
S <- d*S + e,  N <- d*N + 1,  E = S / N,  d = exp(-dt / tau)
       tau = fast_time_constant_s (10) or slow_time_constant_s (100)
g        = mean over sources of clip((E_slow - E_fast) / E_slow, -1, 1)
pl       = clip(tanh(valence_progress_gain * g) + coupling, -1, 1)
v_target = clip(pl + (wellness - 0.5), -1, 1)
valence += (v_target - valence) * (1 - exp(-dt / valence_time_constant_s))
```

Falling errors make `g` positive and pull valence up; rising errors make it negative. `pl` is the appraisal's pleasantness check, and `coupling` is the perceived-emotion term described under [Affect coupling](#affect-coupling), zero in the first configuration. `wellness` is the value the interoception module last reported, 0.5 before the first report. Early on the fast and slow means are both close to the plain mean of the samples so far, so `g` starts near zero.

## Drives

Each drive is a deficit in `[0, 1]` that builds while its need goes unmet and is reduced by the events that meet it, the reduction serving as the drive's reward (Hull 1943; Keramati and Gutkin 2014). Between updates a drive follows the exact solution of `dD/dt = build_rate × u × (1 - D) - decay_rate × D`, so it relaxes toward `build_rate × u / (build_rate × u + decay_rate)` at a rate that does not depend on how often the affect module updates. Each default decay rate is about a ninth of its build rate, so a fully deprived drive settles near 0.9, above its 0.7 threshold.

Relief comes in two forms. Curiosity and boredom are relieved continuously, `D <- D × exp(-relief_gain × c × dt)`, so the amount relieved does not depend on how often the perceptual modules report. The social drive and restlessness are relieved per event, `D <- D × (1 - relief_gain × c)`.

| Drive | Builds with `u` | Relieved by | Grounding |
|---|---|---|---|
| `curiosity` | `1 - LP` | continuously, `c = LP` | learning progress (Oudeyer and Kaplan 2007; Schmidhuber 2010) |
| `boredom` | `1 - N` | continuously, `c = N` | relief by novelty, this design's reading of Eastwood et al. 2012 and Westgate and Wilson 2018 |
| `social_drive` | `1` once the entity has heard a voice, else `0` | each new voice, `c = 1` | social homeostasis (Matthews and Tye 2019) |
| `restlessness` | `1 - intent_rate` | each action selection module intent other than `intent.rest`, `c = 1` | a design choice with no established model behind it |

`LP = max(0, g - learning_progress_floor) / (1 - learning_progress_floor)` is learning progress above a noise floor, so rectified noise in `g` does not relieve curiosity on a scene where nothing is being learned. `N = clip(r_fast / max(r_slow, 0.05) - 1 - alert_excess_margin, 0, 1)` is the novelty of the alert stream. Each perceptual alert raises the fast rate `r_fast` by `1 / fast_time_constant_s` and the slow rate `r_slow` by `1 / slow_time_constant_s`, and both decay with their own time constant. The alert criterion is self-calibrating, so even a still scene alerts at a steady base rate, and only alerts in excess of that habituated rate relieve boredom.

The social drive reads the sequence module. The sequence module counts an interaction when a tone-of-voice or transcription event arrives from a live source (`live_mic`, `microphone` or `remote`). The first finite `time_since_last_interaction_s` in a `sequence.report` starts the drive building, and each later drop in that value relieves it. The intent rate is an exponential average updated on every broadcast, `r <- r + intent_rate_weight × (min(1, n) - r)`, with `n` the number of non-rest intents since the previous broadcast.

A drive that crosses its threshold publishes one `affect.drive` event and re-arms only after it falls below 0.9 of the threshold.

## Appraisal

On every broadcast, accessed or inhibited, the affect module first updates its state and drives and then scores the broadcast coalition on the five checks of Scherer's component process model:

| Check | Computation |
|---|---|
| Novelty | `1 - prod(1 - s)` over coalition members that carry a `normalised_error` ratio `r`, with `s = clip(ln r / ln 3, 0, 1)`; a ratio of 2.2 gives 0.72 |
| Intrinsic pleasantness | `pl`, the learning-progress term above |
| Goal significance | the conducive part `r` minus the obstruction `o`, clipped to `[-1, 1]` |
| Coping potential | `2p - 1`, only when goal significance is nonzero (below) |
| Norm compatibility | fixed at `0.0` and unavailable, since KAINE has no standards until an operator writes a list; no categorical rule reads it |

The cycle injects a drive-to-source table built from each registered module's `relieves_drives` declaration. With dominant drive value `v > 0` and `f` the intensity-weighted share of coalition members whose source relieves that drive, the drive score is `v × f`: `v` when every member serves the drive and `0` when none does (irrelevant, per Scherer's relevance check). With no drive above zero the score is `0.0`. When the `GoalLedger` holds active goals, their token-overlap `relevance` in `[0, 1]` is also computed and the check takes the larger of the two. The conducive part `r` is in `[0, 1]` and the obstruction below can make the goal score negative, and drive crossings fill the ledger. The goal score feeds the categorical emotion and does not enter selection, where the goal factor is held constant.

Coping potential is checked whenever goal significance is nonzero, negative included. At exactly 0 the content is irrelevant and coping is unavailable: `coping_available` is false in `affect.emotion`, and fear, anger and sadness are not eligible. Otherwise `p = (s + 1) / (s + f + 2)`. When the drive term sets goal significance (also on a tie), `s` counts the dominant drive's crossings that the entity's own response ended (fell below the re-arm band): learning progress for curiosity and intents for restlessness, by relief or by holding the build input down, the latter only when a counterfactual step at the no-response input would not have fallen back. `f` counts every other end: decay alone, novelty for boredom, another's voice for the social drive. When the ledger sets it, `s` and `f` are completed and abandoned goals. Coping is `2p - 1`, so `0.0` before any history. Arousal and valence do not enter it. A sleep reset counts as neither. (Paper A.4; Sander, Grandjean and Scherer 2005; Maier and Seligman 2016; Williams et al. 2015).

`goal_significance_method` in each `affect.emotion` event records how the check was computed:

| Method | Meaning |
|---|---|
| `drive_relevance_v1` | Scored against the dominant drive |
| `drive_relevance_v1+token_overlap_v1` | Drive score and active ledger goals both computed; the larger is used |
| `token_overlap_v1` | No drive-to-source table was injected, and active ledger goals were scored |
| `unavailable` | Neither exists; the score is `0.0` |

## Goals and obstruction

(Paper A.4, "Goals." and "Obstruction.") A crossing of a drive threshold creates the goal of relieving that drive. The goal description is `relieve <drive>` and its priority is the drive value at the crossing, unless that drive already has an active goal. Intents are responses to goals, not sources of goals; only a drive crossing or an explicit `add_goal` call creates a goal. Each drive goal carries an expected-relief likelihood `L` in `[0, 1]`, set at creation to the drive's success ratio `p = (s + 1) / (s + f + 2)`. The same own-response and other-response counts that set coping potential also set `p`; `s` counts crossings ended by the entity's own response and `f` counts crossings ended otherwise.

A goal ends in one of four ways:

| End | Condition | Outcome |
|---|---|---|
| Completed | The drive falls below 0.9 of its threshold and the credit rule counts the fall as the entity's own response | The goal ends as completed and the completed count rises |
| Abandoned (another's response) | The drive falls below the re-arm band but the credit rule counts the fall as another's response | The goal ends as abandoned and the abandoned count rises |
| Abandoned (stalled) | The drive stays at or above its threshold for `goal_stall_s` (600 entity s) without a dip below the threshold restarting the timer | The goal ends as abandoned and the abandoned count rises |
| Abandoned (cap) | Active goals exceed `goal_cap` (3) and this goal has the lowest priority, with ties broken by earliest creation | The goal ends as abandoned and the abandoned count rises |

Goals added through `add_goal` count toward the cap. When a drive goal is active, the ledger is active and the token-overlap term is computed alongside the drive term; the appraisal method is then `drive_relevance_v1+token_overlap_v1`. With no goal active the appraisal is as before.

While a drive goal is active, every non-rest intent opens a response window of `goal_response_window_s` (10 entity s) against the drive's value just before the intent. The window checks whether the drive has dropped below that value by the first update at or after the window ends. If it has not, the expected-relief likelihood falls by `ΔL = goal_likelihood_fall × L` (default 0.5) and `ΔL` is held for the next appraisal. If several windows close before the next appraisal, their held `ΔL` values are summed. The next appraisal takes the obstruction `o = v* × ΔL` from the dominant drive's active goal, where `v*` is the dominant drive's value at appraisal time and `ΔL` is the held likelihood fall; if there is no held `ΔL` then `o = 0`. After the appraisal every held `ΔL` is cleared. The goal score is `clip(r - o, -1, 1)`, where `r` is the conducive part (the larger of the drive score and the ledger relevance). With no injected drive table there is no dominant drive and `o = 0`.

Coping is checked whenever the goal score is nonzero, negative included, and is unavailable only at exactly 0. The term that supplies `r` also supplies `p` for coping; on a tie between the drive term and ledger relevance the drive term supplies `p`.

Every lifecycle change publishes `affect.goal`: `added` carries `drive` and `likelihood`; `completed` and `abandoned` carry `drive` and `reason`, with reasons `own_response`, `without_response`, `stalled` and `cap`.

A rule-based `classify()` maps the five scores to `joy`, `sadness`, `anger`, `fear`, `surprise`, `disgust` or `neutral`, and the affect module publishes `affect.emotion` when the category changes. The rules are modeled on the predicted appraisal profiles of Sander, Grandjean and Scherer (2005, Table 3). KAINE has a single novelty check that covers suddenness, familiarity and predictability together, so Table 3's low familiarity maps to high novelty here: a report the processor did not expect is unfamiliar to it. Surprise is reachable when the coalition carries a strongly surprising report and pleasantness and goal significance are near zero. Disgust is returned when pleasantness is at or below -0.5, novelty is above 0.3 and the absolute goal score is below 0.3; it is checked after fear and anger (which require coping potential) and before sadness. Table 3 leaves the standards check open for disgust, and very low standards would mark contempt, which KAINE does not classify. Anger needs a goal score at or below -0.3 and coping at least 0.3, which obstruction of a goal with a strong own-response history supplies; it matches at best Table 3's irritation profile, because Table 3's rage profile needs the obstruction attributed to another agent, which KAINE does not do, and the irritation profile's standards check is also missing.

## Sleep reset

At the end of every sleep [the sleep module](sleep.md) calls `affective_reset()`. It returns valence, arousal and dominance to their baselines, resets every drive to 0 and re-arms its crossing, and sets the categorical emotion to neutral. It also clears the learning-progress error means, the fast and slow alert rates, the intent rate and the recorded perceived emotion, so valence starts the waking period from baseline instead of relaxing back toward the pre-sleep target. The last reported wellness, the record of whether and when the entity last heard a voice and the familiarity cache are kept. The goal ledger keeps its finished goals and its running completed and abandoned counts, but active goals are removed without counting as completed or abandoned; response windows and held obstruction clear. The relief and decay outcome counts on each drive are kept. The affect module then publishes a `affect.state` event with `reset: true` at its alert intensity.

## Peer streams

Besides the workspace broadcast, the affect module reads the peer streams below on its own loop. The cursor of each stream advances past every entry it scans, and an event whose handling raises (a malformed payload, for example) is logged and skipped, so one bad event cannot stall the loop or be read again.

## Inputs

| Stream | Event type | Use |
|---|---|---|
| `workspace.broadcast` | broadcast snapshot | Every broadcast, accessed or inhibited: state update, then appraisal |
| `vision.out` | `vision.report` | Learning-progress means; on `alert: true`, alert rates and arousal |
| `audition.out` | `audition.perception` | Learning-progress means; on `alert: true`, alert rates and arousal |
| `audition.out` | `audition.emotion` | Perceived speaker emotion, recorded only when coupling is enabled |
| `interoception.out` | `interoception.report` | `wellness` shifts the valence target; a non-empty `alerts` list raises arousal |
| `sequence.out` | `sequence.report` | `time_since_last_interaction_s` starts and relieves the social drive |
| `action_selection.out` | `intent.*` | Each intent other than `intent.rest` relieves restlessness and counts toward the intent rate |
| `episodic_memory.out` | `episodic_memory.recall` | `max_affect_intensity` raises arousal |
| `social_cognition.out` | `social_cognition.agent_model` | Familiarity per `agent_id`, read only when coupling is enabled |

The vision, audition and social cognition modules' stream names are fixed. The interoception, sequence, episodic memory and action selection modules' stream names are configurable (below).

## Outputs

| Stream | Event type | When | Intensity |
|---|---|---|---|
| `affect.out` | `affect.state` | Every `publish_interval_s` of entity time, on its own timer and after a broadcast once the interval has passed; carries the VAD state, the drives and the current emotion label, plus `reset: true` after a sleep reset | `baseline_salience`; `alert_salience` after a reset |
| `affect.out` | `affect.emotion` | On a change of categorical emotion; carries the five scores, the state, `norm_compatibility_available`, `coping_available`, `goal_significance_method`, `obstruction` and `alert` (true for a non-neutral emotion) | `alert_salience`, or `baseline_salience` for `neutral` |
| `affect.out` | `affect.drive` | On a threshold crossing; carries the drive name and value, and `alert: true`, so a crossing raises the access rate | `alert_salience` |
| `affect.out` | `affect.goal` | On a goal's creation from a crossing and on each end; carries `drive`, `likelihood` (added) and `reason` (completed, abandoned) | `baseline_salience` |

The affect module reports at these fixed levels; its events are not graded by surprise.

## Configuration

The full `[affect]` reference is in the [modules configuration page](../appendix-a-configuration/modules.md). All time constants run in entity time.

| Key | Type | Default | Meaning |
|---|---|---|---|
| `baseline_valence` | float `[-1, 1]` | `0.0` | Initial valence and its value after a sleep reset; valence otherwise relaxes toward its target |
| `baseline_arousal` | float `[0, 1]` | `0.3` | Arousal baseline `a0`; also the point above which the contrast gain rises |
| `baseline_dominance` | float `[-1, 1]` | `0.0` | Dominance baseline |
| `drift_rate_per_s` | float `>= 0` | `0.05` | Relaxation rate of arousal and dominance toward baseline |
| `publish_interval_s` | float `> 0` | `1.0` | Period between `affect.state` publications |
| `baseline_salience` | float `[0, 1]` | `0.1` | Intensity of routine events |
| `alert_salience` | float `[0, 1]` | `0.7` | Intensity of emotion changes, drive crossings and the post-reset state |
| `fast_time_constant_s` | float `> 0` | `10.0` | Fast mean of each perceptual source's error and the fast alert rate |
| `slow_time_constant_s` | float `> fast` | `100.0` | Slow mean of each perceptual source's error and the slow alert rate |
| `learning_progress_floor` | float `[0, 1)` | `0.05` | Noise floor subtracted from learning progress before it relieves curiosity |
| `alert_excess_margin` | float `>= 0` | `0.5` | Fraction by which the fast alert rate must exceed the slow one before it relieves boredom |
| `intent_rate_weight` | float `(0, 1]` | `0.05` | Per-broadcast weight of the intent-rate average |
| `valence_time_constant_s` | float `> 0` | `30.0` | Time constant of valence's relaxation toward its target |
| `valence_progress_gain` | float `>= 0` | `2.0` | Gain on learning progress in the pleasantness check |
| `goal_stall_s` | float `> 0` | `600.0` | Seconds a drive may stay at or above its threshold before its active goal is abandoned |
| `goal_cap` | int `>= 1` | `3` | Maximum number of active goals |
| `goal_response_window_s` | float `> 0` | `10.0` | Seconds a response window stays open after a non-rest intent |
| `goal_likelihood_fall` | float `[0, 1]` | `0.5` | Fraction by which expected-relief likelihood falls when a response window closes without relief |
| `action_selection_stream` | string | `"action_selection.out"` | Stream the affect module reads intents from |
| `interoception_stream` | string | `"interoception.out"` | Stream the affect module reads the interoception module's reports from |
| `sequence_stream` | string | `"sequence.out"` | Stream the affect module reads the sequence module's reports from |
| `episodic_memory_stream` | string | `"episodic_memory.out"` | Stream the affect module reads the episodic memory module's recalls from |

The retired key `social_drive_time_scale_s` is accepted and ignored with a warning, so older local configs still boot.

The perceptual arousal gain (0.15), its cap (4), the interoceptive step (0.05) and the drive hysteresis (0.9) are constants in `kaine/modules/affect/module.py` and `drives.py`; no config key sets them.

Drive sub-tables `[affect.drives.<name>]`, for `curiosity`, `boredom`, `social_drive` and `restlessness`. An unknown drive name or key stops boot.

| Key | Type | Defaults (curiosity, boredom, social_drive, restlessness) | Meaning |
|---|---|---|---|
| `build_rate` | float `>= 0` | `0.05`, `0.04`, `0.01`, `0.03` | Build rate per second at `u = 1` |
| `decay_rate` | float `>= 0` | `0.0055`, `0.0045`, `0.0011`, `0.0033` | Decay rate per second |
| `threshold` | float `(0, 1]` | `0.7` for all | Crossing threshold |
| `relief_gain` | float `[0, 1]` | `0.5`, `0.3`, `0.8`, `0.5` | Curiosity and boredom: relief rate per second at full strength. Social drive and restlessness: fraction one relieving event removes |

Coupling sub-table `[affect.coupling]`:

| Key | Type | Default | Meaning |
|---|---|---|---|
| `enabled` | bool | `false` | Turns affect coupling on |
| `coupling_base` | float `>= 0` | `0.05` | Appraisal-influence weight when no familiarity is known |
| `coupling_familiarity_gain` | float `>= 0` | `0.10` | Additional weight per unit of the social cognition module's familiarity |
| `coupling_ceiling` | float `>= 0` | `0.15` | Ceiling on the appraisal-influence weight |
| `decay_s` | float `> 0` | `10.0` | Seconds over which a perceived-emotion signal decays to zero |

The retired key `coupling_max_rate_per_s` is accepted and ignored with a warning, so older local configs still boot.

## Affect coupling

Coupling is off in the default config and in the first configuration. When `[affect.coupling].enabled = true`, the affect module records each `audition.emotion` event as a transient signal and never writes it to the dimensional state:

1. It maps the perceived category to a pleasantness and an intensity through the `EMOTION_VAD` table.
2. It looks up the speaker's familiarity, keyed on the event's `source_label` (the audio channel), in the cache filled from `social_cognition.agent_model` events, which carry the `source_label` of the audio event that updated the agent model (0.0 when unknown).
3. It computes `weight = clip(coupling_base + coupling_familiarity_gain × familiarity, 0, coupling_ceiling)`.
4. It stores `{pleasantness, intensity, weight, ts}`.

When the appraisal runs, the signal is folded in with a linear decay, `decay = max(0, 1 - (now - ts) / decay_s)`. It adds `weight × decay × pleasantness` to the pleasantness check and `weight × decay × intensity × 0.5` to the novelty check, and both checks are clipped to `[-1, 1]`. Valence responds only through the pleasantness check, which sets its target.

```mermaid
flowchart TD
    AE[audition.emotion] -->|category, source_label| R[Record perceived signal\npleasantness, intensity, weight, ts]
    EM[social_cognition.agent_model] -->|familiarity| FC[Familiarity cache]
    FC -->|lookup| R
    R -->|decaying| AP[Appraisal checks]
    AP -->|classify| EMO[affect.emotion]
    AP -->|pleasantness + wellness| VT[valence target]
    VT -->|exponential relaxation| S[DimensionalState]
```

The weight ceiling, the clip on each check and the decay window bound the contribution. Once a speaker stops talking the signal decays to zero within `decay_s`, and valence relaxes toward a target without it.

## Bounds on the affective state

Every dimension is clipped to its range after each update. The perceived emotion of another speaker enters only through the bounded, decaying appraisal path and never writes to the state. Arousal relaxes toward baseline between nudges, and the sleep reset returns affect and drives to baseline at the end of every sleep, so arousal cannot drift across a whole run.

## Serialization

`Affect.serialize()` stores the state, the baseline, the drive values, the last emotion, the familiarity cache and the goal ledger. The cache holds opaque agent-id strings and familiarity values only, no transcribed text. Each drive's own and other outcome counts persist as `drive_outcomes`. Active goals persist with their `drive` and `likelihood`; the ledger stores the running completed and abandoned counts and keeps at most the 256 most recent finished goals (the counts include pruned goals). Response windows and stall timers are transient and restart after a restore. Restoring goals publishes no `affect.goal` events.

## Enabling and use

1. Set `[modules].affect = true`, or run the `first_configuration` profile.
2. Enable the vision and audition modules for the perceptual error and alert streams, and the interoception and sequence modules for wellness, interoceptive alarms and the social drive.
3. For affect coupling, set `[affect.coupling].enabled = true` and enable the [audition](audition.md) and [social cognition](social-cognition.md) modules.

## Key files

| File | Role |
|---|---|
| `kaine/modules/affect/module.py` | `Affect`: update, appraisal, arousal paths, peer consumer, reset, publishing |
| `kaine/modules/affect/state.py` | `DimensionalState`: relaxation, nudges, clipping |
| `kaine/modules/affect/appraisal.py` | `AppraisalScores` and `classify()` |
| `kaine/modules/affect/drives.py` | `Drive`, `DriveSet`, `DriveCrossing` |
| `kaine/modules/affect/coupling.py` | `CouplingConfig`, `EMOTION_VAD`, `compute_coupling` |
| `kaine/modules/affect/goals.py` | `GoalLedger` |
| `kaine/modules/affect/modulator.py` | `StateModulator`: level gain and contrast gain |
| `kaine/modules/affect/regulation.py` | `RegulationPolicy` protocol and the no-op `PassiveDecay` |
| `kaine/cycle/affect_state.py` | `AffectStateProvider`: the cycle's copy of the last published state |
| `kaine/boot/wiring.py` | Builds the workspace's `StateModulator` from `[workspace]` and `[affect]` |

## Tests

| File | Coverage |
|---|---|
| `tests/test_affect_state.py` | Relaxation, nudges, clipping |
| `tests/test_affect_appraisal.py` | `classify()` rules for each emotion |
| `tests/test_affect_drives.py` | Build, decay, threshold and hysteresis |
| `tests/test_affect_rate_invariant.py` | Appraisal independent of the broadcast rate; the state timer |
| `tests/test_affect_goal_check.py` | Goal-significance check against the dominant drive |
| `tests/test_affect_goals.py` | Goal lifecycle and relevance scoring |
| `tests/test_affect_goal_lifecycle.py` | Creation, completion, abandonment, stall, cap, likelihood fall, obstruction, anger, sleep reset, persistence |
| `tests/test_affect_modulator.py` | Level gain: range, floor, ceiling and monotonicity |
| `tests/test_affect_research_affect.py` | Drives, learning progress, valence, the appraisal leaving arousal unchanged, the sleep reset and the peer-consumer guard |
| `tests/test_affect_coupling.py` | Perceived emotion entering the appraisal, familiarity scaling, no direct write |
| `tests/test_affect_coupling_drift.py` | Perceived-signal decay and boundedness |
| `tests/test_affect_coupling_persistence.py` | Familiarity cache round trip |
| `tests/test_affect_module.py` | Module lifecycle and event publishing |
| `tests/test_affect_coping.py` | Coping potential: relevance gate and success ratio |

## Spec and related pages

- Spec: `openspec/specs/affect/spec.md`
- Affect coupling spec: `openspec/specs/thymos-affect-coupling/spec.md`
- [Global workspace](../08-cognitive-cycle/global-workspace.md): scoring, access and the arousal gain
- [Vision](vision.md), [Audition](audition.md): perceptual alerts and error streams
- [Interoception](interoception.md), [Sequence](sequence.md), [Episodic memory](episodic-memory.md): peer inputs
- [Sleep](sleep.md): calls `affective_reset()`
- [Social cognition](social-cognition.md): familiarity for coupling
- [Self-model](self-model.md): norm check stays undefined until an operator writes a standards list
- [Configuration reference](../appendix-a-configuration/modules.md)
