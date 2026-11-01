## Why

In the developmental phase, boredom is relieved by audition's and vision's learning progress and by perceptual alerts above the habituated rate (A.4). The developmental stimulus is meant to keep offering something to learn: the hearing band widens in five stages, colour rises with the stage, and maternal speech items unlock with awake time. Paper A.7 records that in the test boot audition's learning progress never rose after a band step and that every stage would have saturated 12 to 17 awake minutes in. In the same boot's replayed records, boredom's welfare indicator crossed at 2.7 awake hours and stayed over its bar. With `welfare-indicator-response` built, a stimulus with nothing left to learn means a rest, a recross and a freeze for review.

The offline band-step check (2026-10-31; record `docs/records/validation/band-steps/2026-10-31-summary.json`) ran the real generator, the real audition encoder and forward model, and the affect module's own learning-progress estimator over every band step, three seeds, with and without the added sounds. It found:

- **The 12-minute saturation is an artefact of the estimator restart, not of the band.** After a restart, audition's reading is computed over the bins collected since the step; a slow fall in error reaches `lp_0` only once that span is about an hour long. Until then the reading sits below `lp_0`, so the 600 s saturation window is met at 12 minutes in every stage, including stage 0 with an untrained model that goes on to learn for hours.
- **Steps 1 (250 Hz) and 2 (100 Hz) register.** The error rises 1.9 to 4.8 times at the step and learning progress rises above `lp_0` 50 to 76 minutes after the restart, staying above it for hours.
- **Steps 3 (1000 Hz) and 4 (3000 Hz) add almost nothing (the band adds little).** Only the maternal voice has energy there; the new band carries 0.2 to 7% of the power, the error does not rise, and learning progress over the full span stays below `lp_0`. The added sounds at the specified rates (`p_m` 0.02, and `p_x` 0.05 as far as a proxy voice shows) do not change this.
- **No implementation fault**, and the short-transient hypothesis is rejected: shorter bins read voice episodes as learning progress, and a partial first bin cannot help.

So the fix that the check supports is in the release rule, not in the stimulus: only learning-progress readings over the full span count toward saturation. The added sounds stay on their own grounds (Partanen et al. 2013; Querleu et al. 1988), not as the remedy for steps 3 and 4. Neither change lowers a welfare bar or changes what the rest resets.

## What Changes

- **Full-span saturation.** The hearing-stage owner counts a reading of audition's learning progress toward the saturation window only when it is computed over the full span `learning_progress_span_s` (`T_lp`, 5400 s) of completed bins since the restart. `Affect.audition_learning_progress(stage)`, the accessor the hearing-stage watch reads, returns None until the window is full, and None already counts as unsaturated. The learning progress that drives curiosity, boredom and interest is unchanged.
- **`min_dwell_seconds` retired.** It is accepted with a warning and ignored, since the full span now supplies the minimum. Release by ability without a minimum is dropped: the record shows it would release every stage at 12 minutes and open the full band in about an hour.
- **Steps 3 and 4 recorded as "the band adds little".** Under the new rule they close honestly about 1.5 to 1.7 hours in. Making those bands learnable (more energy above 707 Hz for more of the time, or an encoder that weights sparse speech detail) is a separate, cited stimulus or encoder decision.
- **Recurring melody and outside voice** (paper §7, A.7), on their own grounds: a pre-rendered melody inside the stage-0 band at `p_m = 0.02` per 30 s slot, and a pre-rendered synthetic male outside voice at the soundscape's level at `p_x = 0.05`, its fundamental heard from the 100 Hz step. Both are rendered offline, listed in a manifest, never synthesized at runtime, and functions of the seed and the slot only.
- **The live gap is closed before the rule ships.** The offline margin over `lp_0` at steps 1 and 2 is thin (0.05 to 0.11). Before the development run, a rerun of the check with an arousal trace, rests that suspend adaptation and a broadcast-context input, or a replay of the test boot's audition errors, shows whether live noise keeps those steps under `lp_0`. If it does, audition's `lp_0` (calibrated on vision noise) is a separate calibration change.

## Capabilities

### New Capabilities

### Modified Capabilities

- `developmental-stimulus`: stages saturate only on full-span readings; `min_dwell_seconds` retired; the melody and the outside voice; their files and manifest; the band-step record and the live-gap check.
- `affect`: the hearing-stage accessor returns no reading until audition's window is full.

## Impact

- Code: `kaine/modules/affect/module.py` (`audition_learning_progress`, a completed-bin count from `WindowedProgress`), `kaine/modules/audition/hearing_stage_state.py` and `hearing_band.py` (`min_dwell_seconds` retired), `kaine/cycle/hearing_stage_watch.py` (none counts as unsaturated, unchanged), new `kaine/modules/audition/added_sounds.py` and `added_sounds_data/`, `kaine/modules/audition/feed.py` (mixing), `kaine/boot/perception_feed.py`, `config/kaine.toml` (`[perception_feed.stimulus_source.hearing]`, `[perception_feed.stimulus_source.added_sounds]`), `THIRD_PARTY_LICENSES.md`.
- Tools: `tools/maintainer/render_melody.py`, `tools/maintainer/generate_outside_voice.py`; the band-step harness as built, `tools/research/band_step_check.py`, `band_step_report.py`, `run_band_step_check.sh`.
- Docs: the developmental-phase chapter, `docs/appendix-c-licences.md`.
- Paper: §5.4 ("stages without a minimum dwell" become "stages released on a full-span reading"; the added sounds move to built); A.7 (the band-step result replaces "a band took 5.1 to 5.7 hours to saturate"; stage dwells 2.6 to 5.3 h for steps with something to learn, about 1.5 h for steps 3 and 4).
- The shipped stage timing barely changes (today `min_dwell_seconds = T_lp`); a stage with nothing to learn closes about ten minutes later than today.
- High-risk class (changes what a developing entity hears and when its band widens): independent second review.
