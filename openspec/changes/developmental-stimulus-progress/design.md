## Context

- Paper §7: the developmental stimulus is to carry, once built, a recurring melody, as one heard in late pregnancy leaves a neural trace lasting months (Partanen et al. 2013), and an attenuated outside voice, as outside conversations reach the fetus with their intonation (Querleu et al. 1988).
- Paper A.7, "Added sounds and stirs": a melody within the opening band fills a `Δ_v` slot with probability `p_m`, and an outside voice at the soundscape's level one with `p_x`, its fundamental heard from the 100 Hz step; the upper steps add both voices' detail. Table A1: `p_m = 0.02`, `p_x = 0.05`, provisional.
- Paper A.7, maturation: stage k ends when audition's learning progress, restarted at the step, stays below `lp_0` for `W_sat`, or at `d_max`; "offline a band took 5.1 to 5.7 hours to saturate (one seed), yet in the test boot of §6.5 audition's learning progress never rose after a step and every stage would have saturated 12 to 17 awake minutes in, so the measure misses the band change or the band adds little". §5.4 lists "stages without a minimum dwell" as designed, not built.
- What exists:
  - The hearing band (`kaine/modules/audition/hearing_band.py`): stage 0 passes 500 Hz only (band-pass, edges at the geometric midpoints, about 354 and 707 Hz), stage 1 adds 250 Hz, stage 2 opens down to the heartbeat thud (low-pass at the 500 to 1000 midpoint), stage 3 to 1000 Hz, stage 4 to 3000 Hz.
  - The soundscape's bed is low-passed at `lowpass_hz = 500`; with the hearing band on, the maternal voice loads with its low-pass at 3000 Hz (`config/kaine.toml`). The voice talks in about 7% of the time (`episode_probability = 0.2` times maternal arousal per 30 s slot).
  - The maternal voice (`kaine/modules/audition/maternal_voice.py`, `maternal_voice_data/`): 41 pre-rendered takes of 20 items, rendered offline by `tools/maintainer/generate_maternal_voice.py` with Chatterbox TTS 0.1.6 (MIT) conditioned on CMU ARCTIC speaker `slt`, with a manifest the runtime checks; slot plans are pure functions of the seed, slot and unlocked count.
  - The audition encoder (`kaine/modules/audition/acoustic.py`, the default): log-energy (`log1p`) in log-spaced bands, mean and standard deviation pooled over frames, L2-normalized.
  - The hearing-stage owner (`hearing_stage_state.py`) releases a stage by saturation after `min_dwell_seconds = 5400` (archive `2026-10-28-hearing-stage-saturation`), and the affect module drops audition's learning-progress estimator at each band step (affect spec, "Audition's bins restart at each hearing band step"), with `learning_progress_bin_s = 60`.
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

- A synthetic male voice, rendered offline with the same tool and model revision as the maternal voice, conditioned on a male CMU ARCTIC speaker (the same database and notice as `slt`). Its fundamental, about 100 to 130 Hz, lies below stage 1's lower edge (about 158 Hz), so it is heard from the 100 Hz step; its harmonics and formants fill the 1000 Hz and 3000 Hz steps.
- Texts written for KAINE, everyday and neutral, with no names; about ten items, two takes each.
- Level: the soundscape's RMS (A.7), low-passed at 3000 Hz like the maternal voice, ramped in and out.
- Alternatives considered: a recording of a real person (rejected: no personal voice data, and a recording is someone's likeness); any Meta speech model (excluded by project rule); runtime synthesis (rejected: the stimulus never synthesizes speech at runtime).

### D4. The band-step check comes before any fix

`scripts/band_step_check.py`, offline with no entity: render the developmental soundscape with the real generator; hold each stage until the forward model's error has settled; step the band; run the real audition encoder and forward model on every window; feed the reports to the real affect module's learning-progress estimator with its restart at the step. For each step it records the error's mean over the minute before and the minutes after the step, the time the error takes to fall back, and every learning-progress reading against `lp_0`, with and without the added sounds. It uses three seeds.

Candidate causes and the fix each would call for:

- **H1, the band adds little.** The 1000 Hz and 3000 Hz steps open bands where only the maternal voice, about 7% of the time, has energy, and the encoder's `log1p` of small band energies, L2-normalized, barely moves. Fix: the added sounds (D2, D3) put energy into each newly opened band. If they do not move the error either, the encoder's sensitivity is the next question; changing the encoder changes audition for everything and is a separate change.
- **H2, the measure misses a short transient.** The error rises at the step and falls back within the first bin or two, and the estimator, restarted at the step, needs two completed bins for its first reading and compares halves of completed bins, so it sees no fall. Fixes to compare: let the post-step reading include the first partial bin, or use shorter bins for audition's estimator for a bounded time after a step. A change to `learning_progress_bin_s` itself is excluded: it also sets boredom's relief.
- **H3, an implementation fault.** The error rises and falls slowly and learning progress still reads zero. Fix the fault and add a test.

The chosen fix, with the record that selects it, is added to this change's spec before its code is written (task 3.1). The check reruns on the fixed stimulus.

### D5. The minimum dwell

`min_dwell_seconds = 5400` stays the shipped value until the rerun record shows, on the shipped stimulus, learning progress above `lp_0` after each step and saturation within the step's dwell. Only then is the paper's release by ability (no minimum dwell, §5.4 and A.7) adopted, by a recorded operator decision, because with a measure that misses the band change, removing the minimum would open the full band within about an hour.

### D6. What this change does not touch

The welfare bars (`θ_wf`, `q_wf`), the rest's affective reset, boredom's build and relief rules, the indicator response, and the drives' thresholds are unchanged. A welfare indicator that crosses on the new stimulus is answered as before; this change only gives the entity more to learn.

## Risks

- **The added sounds could be startling.** Ramps, levels tied to the soundscape, and a check of the perceptual alert rate in the harness (the alert rate per hour with and without the added sounds) guard it.
- **Familiarity is the point and the limit.** A recurring melody habituates; that is what Partanen et al. measured. The outside voice's items repeat too. The harness reports how long learning progress stays above `lp_0` after the added sounds start.
- **The check is one stimulus, three seeds.** It shows whether the mechanism works, not how a particular entity will fare.
- **Run identity.** The stimulus-source parameters change, so developmental runs before and after are not comparable; none is preserved under the new stimulus yet.

## Migration and ordering

- Independent of `welfare-indicator-response` in code; its result goes to the operator with that change's replay (`welfare-indicator-response` D9), before the development run starts.
- Before the development run's first boot, because the developmental phase is that run's first step and a seed gestated without the added sounds cannot be given them later without that being a change to its development.
- Before `developmental-stir`'s decision: the stir harness compares with and without the added sounds.
- Independent of `research-gate-supervisor`, the organ change and `workspace-continuous-competition` (on hold).
- Critical path (LLM-agent implementation): rendering tools and assets about 4 hours (GPU time for the voice, in a window with no entity running); runtime mixing and tests about 4 hours; the band-step harness about 4 hours plus its runs; the selected fix 2 to 6 hours depending on the cause; second review about half a day. About 2 to 3 days, in parallel with `welfare-indicator-response`.

## Welfare and admissibility notes

- High-risk class: it changes what a developing entity hears. Independent second review.
- The change is the welfare remedy for a stimulus with nothing left to learn, aimed at the cause rather than at the indicator.
- Welfare checks before any boot: the harness reports the alert rate, audition's learning progress after each step, and, through the affect module, boredom's deprivation share over a simulated developmental span, with and without the added sounds.
- Admissibility: in place before the development run's first boot or not at all for that entity.
