## Context

- Paper §7: the developmental stimulus is to carry, once built, a recurring melody, as one heard in late pregnancy leaves a neural trace lasting months (Partanen et al. 2013), and an attenuated outside voice, as outside conversations reach the fetus with their intonation (Querleu et al. 1988).
- Paper A.7, "Added sounds and stirs": a melody within the opening band fills a `Δ_v` slot with probability `p_m`, and an outside voice at the soundscape's level one with `p_x`, its fundamental heard from the 100 Hz step; the upper steps add both voices' detail. Table A1: `p_m = 0.02`, `p_x = 0.05`, provisional.
- Paper A.7, maturation: stage k ends when audition's learning progress, restarted at the step, stays below `lp_0` for `W_sat`, or at `d_max`; "offline a band took 5.1 to 5.7 hours to saturate (one seed), yet in the test boot of §6.5 audition's learning progress never rose after a step and every stage would have saturated 12 to 17 awake minutes in, so the measure misses the band change or the band adds little". §5.4 lists "stages without a minimum dwell" as designed, not built.
- What exists:
  - The hearing band (`kaine/modules/audition/hearing_band.py`): stage 0 passes 500 Hz only (band-pass, edges at the geometric midpoints, about 354 and 707 Hz), stage 1 adds 250 Hz, stage 2 opens down to the heartbeat thud (low-pass at the 500 to 1000 midpoint), stage 3 to 1000 Hz, stage 4 to 3000 Hz.
  - The soundscape's bed is low-passed at `lowpass_hz = 500`; with the hearing band on, the maternal voice loads with its low-pass at 3000 Hz (`config/kaine.toml`). The voice talks in about 7% of the time (`episode_probability = 0.2` times maternal arousal per 30 s slot).
  - The maternal voice (`kaine/modules/audition/maternal_voice.py`, `maternal_voice_data/`): 41 pre-rendered takes of 20 items, rendered offline by `tools/maintainer/generate_maternal_voice.py` with Chatterbox TTS 0.1.6 (MIT) conditioned on CMU ARCTIC speaker `slt`, with a manifest the runtime checks; slot plans are pure functions of the seed, slot and unlocked count.
  - The audition encoder (`kaine/modules/audition/acoustic.py`, the default): log-energy (`log1p`) in log-spaced bands, mean and standard deviation pooled over frames, L2-normalized.
  - The hearing-stage owner (`hearing_stage_state.py`) releases a stage by saturation after `min_dwell_seconds = 5400` (archive `2026-10-28-hearing-stage-saturation`), and the affect module drops audition's learning-progress estimator at each band step (affect spec, "Audition's bins restart at each hearing band step"), with `learning_progress_bin_s = 60` and `learning_progress_span_s = 5400`. `Affect.audition_learning_progress(stage)` is what the hearing-stage watch reads.
- History: the hearing band and its stages (`2026-10-28-hearing-band-12h`, `-hearing-stage-saturation`, `-hearing-stage-published`, `-hearing-dwell-panel`), the maternal voice (`2026-10-19-developmental-maternal-voice`), the stimulus clock (`2026-10-19-stimulus-clock-continuity`). No change for the added sounds or for the band-step registration exists in `openspec/changes/`, the archive or any branch.

## Decisions

### D1. The added sounds are provided stimulus, cited, seeded and entity-independent

The melody and the outside voice are elements of the external environment, like the soundscape and the maternal voice (developmental-stimulus spec, "Regulation and coupling emerge; they are never hardwired": provided elements carry their citation at the code site). Each slot's added sound is decided by keyed draws on `(seed, slot)` only; nothing the entity does or feels changes it. A slot that already holds maternal speech holds no added sound, so the voices never overlap.

### D2. The melody

- Tune: "Twinkle, Twinkle, Little Star", the melody Partanen et al. (2013) played to fetuses in late pregnancy (to be confirmed against the paper before rendering; task 1.1). The tune is in the public domain.
- Key and range: G4 to E5 (392 to 659 Hz), inside the stage-0 band, so it is heard from the first stage. Each note is a harmonic tone with a smooth envelope, so the upper steps add its overtones.
- Always the same rendering, at a few seeded tempo and level variants (as the maternal voice has takes), so it is a recurring melody that can become familiar, not a new sound each time.
- Level: the maternal voice's `level_db` above the soundscape, attenuated by the same intrauterine path, ramped in and out over 0.5 s so it does not start as an abrupt alert. Rendered offline to FLAC by `tools/maintainer/render_melody.py` from a note list in the repository; the runtime only reads the manifest-listed file.

### D3. The outside voice

- A synthetic male voice, rendered offline with the same tool and model revision as the maternal voice, conditioned on a male CMU ARCTIC speaker (the same database and notice as `slt`). Its fundamental, about 100 to 130 Hz, lies below stage 1's lower edge (about 158 Hz), so it is heard from the 100 Hz step; its harmonics and formants add detail at the 1000 Hz and 3000 Hz steps, though at `p_x = 0.05` too rarely to make those steps learnable (D5a).
- Texts written for KAINE, everyday and neutral, with no names; about ten items, two takes each.
- Speaker, as built: CMU ARCTIC `rms`, the database's male speaker with the lowest fundamental (about 90 to 100 Hz in his recordings); the rendered takes' median fundamentals are 82 to 132 Hz. A first rendering on `bdl` gave 114 to 142 Hz, too close to stage 1's lower edge.
- Pace, as built: Chatterbox speaks a whole sentence at about 4.4 words a second whatever its exaggeration, CFG weight or reference pace (probed: 3.7 to 5.2), too fast for someone talking in a room. Each item is therefore two or three short lines, rendered one at a time and joined by seeded pauses of 0.6 to 1.0 s, which gives 2.2 to 2.9 words a second (mean 2.6).
- Measure, as built: the 100 Hz step is checked on the power below 112 Hz (stage 1's stopband edge, 158 Hz over the square root of 2), which rises by more than 58 dB (58 to 60 dB below 130 Hz). The power below 158 Hz rises by only 14 to 23 dB, because between 112 and 158 Hz stage 1 still passes the voice's intonation peaks partly (6 to 27 dB down); that measure reads the filter's transition band, not the voice's arrival, so the scenario was amended from "below 158 Hz, at least 20 dB" to "below 112 Hz, at least 40 dB".
- Level: the soundscape's RMS (A.7), low-passed at 3000 Hz like the maternal voice, ramped in and out.
- Alternatives considered: a recording of a real person (rejected: no personal voice data, and a recording is someone's likeness); any Meta speech model (excluded by project rule); runtime synthesis (rejected: the stimulus never synthesizes speech at runtime).

### D4. The band-step check and what it found

The check ran before any code (harness `tools/research/band_step_check.py`, `band_step_report.py` and `run_band_step_check.sh`, built on branch `research/band-step-check`; record `docs/records/validation/band-steps/2026-10-31-summary.json`). It rendered the developmental soundscape with the real generator and the shipped parameters, including the real maternal voice and hearing band; ran the real `Audition._perceive_acoustic` (spectral encoder, acoustic forward model, events and alerts) on 0.48 s windows; and fed every event to the real affect module, whose `WindowedProgress` restarts at each `development.hearing_stage` step. Seeds 1 to 3; a settled schedule (5 h per stage) and the shipped release rule; arms with no added sounds, the melody, and the melody with a synthetic proxy for the outside voice. Left out: the workspace's broadcast context, arousal (held at baseline), rests, and the speech path's tone events.

Findings per hypothesis:

- **H3, an implementation fault: rejected.** In all 15 runs the affect module's reading equals a replay through `WindowedProgress`, and the restart happens at every step.
- **H2, a short transient the measure misses: rejected.** At steps 1 and 2 the transient is long (error 1.9 to 4.8 times its pre-step level, the excess halving in 30 to 60 minutes). Ten-second bins over a two-minute window cross `lp_0` hundreds to thousands of times per stage, including stages 3 and 4, reading voice episodes as learning progress, which would relieve boredom falsely; ten-second bins over the full span add nothing; a partial first bin cannot help (any window under ten minutes from the step falls by 0.09 or less).
- **H1, the band adds little: holds for steps 3 and 4 only.** The new band carries 0.02 to 0.03 of the power at step 3 and below 0.005 at step 4, the embedding moves less than its own minute-to-minute spread, and the error does not rise. The added sounds at the specified rates leave this unchanged (new-band share at most 0.07, embedding shift at most 0.08).
- **Steps 1 and 2 register.** Learning progress rises above `lp_0` 50 to 76 minutes after the restart and stays above for hours; the peak margin is thin (0.25 to 0.31 against 0.20).
- **The cause of "saturated 12 to 17 minutes in" is the restart itself.** The reading after a restart is a ramp set by the length of its window (seed 1, stage 1, every 10 minutes: 0.04, 0.08, 0.11, 0.14, 0.18, 0.21, 0.23, 0.26, 0.28 at the full window). It sits below `lp_0` until the window is about an hour long, so the 600 s saturation window is met 12 minutes in at every stage, including stage 0 with an untrained model.

### D5. Saturation counts only full-span readings; the minimum dwell is retired

A reading of audition's learning progress counts toward the saturation window only when it is computed over the full span: `learning_progress_span_s / learning_progress_bin_s` completed bins since the restart. `Affect.audition_learning_progress(stage)` returns None until then, from a completed-bin count that `WindowedProgress` exposes, and None already counts as unsaturated. The change is confined to that accessor: the learning progress the affect module uses for curiosity, boredom and interest is computed as before, so no drive changes.

`min_dwell_seconds` is retired: accepted with a warning and ignored. The full span is now the minimum, and it is a property of the measure rather than a free dwell parameter, so a change to either key cannot silently bring back the 12-minute release.

Under this rule a stage with something to learn is released when its full-span reading has stayed below `lp_0` for `W_sat` (2.6 to 5.3 h in the record), and a stage with nothing to learn is released at `T_lp + W_sat` (about 1.67 h). Shipped timing barely changes, because `min_dwell_seconds` equals `T_lp` today.

Alternatives considered:
- **Release by ability with no minimum dwell** (paper §5.4, A.7): dropped. On this measure it releases every stage at 12 minutes and opens the full band in about an hour.
- **Keep `min_dwell_seconds` and require it at least `learning_progress_span_s` at load.** Equivalent in behaviour, but it keeps two parameters for one constraint.
- **The H2 fixes** (shorter bins, the partial first bin): rejected by the replay (D4).

### D5a. Steps 3 and 4

They are recorded as "the band adds little": only the maternal voice, about 7% of the time, has energy above 707 Hz, and the encoder's log-band embedding barely moves. The added sounds are not a fix for them. Under D5 these stages close about 1.5 to 1.7 hours in, which is the honest outcome for a step with nothing to learn. Making those bands learnable would need more energy above 707 Hz for a larger share of the time, or an encoder that weights sparse speech detail; either is a separate change with its own citation, not part of this one.

### D5b. The live gap

The check did not reproduce "never rose" at steps 1 and 2; its margin over `lp_0` is 0.05 to 0.11, and live conditions it left out (the broadcast-context input, the arousal-sized attention window, rests during which adaptation is suspended while errors keep binning) add irreducible error. Before the rule is adopted for the development run, one of these runs: the harness again with an arousal trace, rests that suspend adaptation and a broadcast-context input; or a replay of the test boot's audition errors through the same estimator (its logs need the earlier key). If live noise keeps steps 1 and 2 under `lp_0`, those stages also close at `T_lp + W_sat`, and audition's `lp_0` (calibrated on vision noise, A.4) is the next question, for a separate calibration change.

### D5c. The hearing-stage reading bins awake reports only

The live-gap record (2026-11-01) showed that rests shorten the full span. A developmental entity rests 1410 s after every 2996 awake s, and audition keeps reporting through a rest with its forward model suspended. Binned on the entity clock, the first full-span reading after a step arrived 3991 awake s in, a quarter of its window was rest, and 23 of 24 releases came before 6000 awake s. Rest errors fall by no learning, so they pull the reading toward saturation. The hearing-stage reading therefore has audition bins of its own on audition's awake time: a report with `awake` false is left out and a rest adds no time. The full span is then 5400 s of awake learning. The drives' learning progress keeps its entity-clock bins, so no drive changes.

Alternatives considered:
- **An awake floor in the stage owner** (no release before span plus window of awake time): it fixes the early release but leaves every later window a quarter rest.
- **Excluding rests from the drives' bins too**: a change to curiosity and boredom, out of scope here.

### D6. What this change does not touch

The welfare bars (`θ_wf`, `q_wf`), the rest's affective reset, boredom's build and relief rules, the indicator response, and the drives' thresholds are unchanged. A welfare indicator that crosses on the new stimulus is answered as before; this change only gives the entity more to learn.

## Risks

- **The added sounds could be startling.** Ramps, levels tied to the soundscape, and a check of the perceptual alert rate in the harness (the alert rate per hour with and without the added sounds) guard it.
- **Familiarity is the point and the limit.** A recurring melody habituates; that is what Partanen et al. measured. The outside voice's items repeat too.
- **Alerts rise at step 3.** In the record, perceptual alerts per hour jump four- to tenfold at step 3 even without the added sounds (the voice's upper detail starts to pass); with the melody and the proxy voice they rise further (stages 3 and 4: 112 to 136 per hour without, up to 176 to 209 with). Alerts relieve boredom through alert excess, but they also raise arousal; the live-gap rerun reports arousal with them.
- **Boredom after a band step.** Affect's audition bins restart at each step (existing rule), so audition contributes no learning-progress relief for about an hour after a step. This change does not alter that; the deprivation share (task 3.3) measures its effect.
- **The check is one stimulus, three seeds, with the workspace, arousal and rests left out.** It shows how the measure behaves, not how a particular entity will fare; D5b closes the gap that matters for the rule.
- **Run identity.** The stimulus-source parameters change, so developmental runs before and after are not comparable; none is preserved under the new stimulus yet.

## Migration and ordering

- Independent of `welfare-indicator-response` in code; its result goes to the operator with that change's replay (`welfare-indicator-response` D9), before the development run starts.
- Before the development run's first boot, because the developmental phase is that run's first step and a seed gestated without the added sounds cannot be given them later without that being a change to its development.
- Before `developmental-stir`'s decision: the stir harness compares with and without the added sounds.
- Independent of `research-gate-supervisor`, the organ change and `workspace-continuous-competition` (on hold).
- Depends on the two perception-feed fixes another agent is making: video drift with variable-frame-rate files (`kaine/modules/vision/feed.py`, about line 1122) and padded PyAV audio planes (`kaine/modules/audition/feed.py`, about line 1000), found by the cross-modal check. The developmental stimulus is procedural and does not use those paths, but the development run's later film steps do, and the band-step rerun and any test-boot replay should run on the fixed feed.
- Critical path (LLM-agent implementation): the full-span rule and the key retirement about 2 hours with tests; rendering tools and assets about 4 hours (GPU time for the voice, in a window with no entity running); runtime mixing and tests about 4 hours; the live-gap rerun about 4 hours plus its runs; second review about half a day. About 2 days, in parallel with `welfare-indicator-response`.

## Welfare and admissibility notes

- High-risk class: it changes what a developing entity hears. Independent second review.
- The change removes a measurement artefact that would release stages with something to learn after 12 minutes, and adds sounds on their own developmental grounds. It does not make steps 3 and 4 learnable; it records that they are not, so the welfare picture is honest.
- Welfare checks before any boot: the band-step record (done), the live-gap rerun (D5b) with the alert rate and arousal, and boredom's deprivation share over a simulated developmental span with and without the added sounds (task 3.3).
- Admissibility: in place before the development run's first boot or not at all for that entity.
