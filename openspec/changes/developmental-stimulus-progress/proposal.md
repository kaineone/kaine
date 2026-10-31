## Why

In the developmental phase, boredom is relieved by audition's and vision's learning progress and by perceptual alerts above the habituated rate (A.4). The developmental stimulus is meant to keep offering something to learn: the hearing band widens in five stages, colour rises with the stage, and maternal speech items unlock with awake time. Paper A.7 records that it does not work that way on the live system: in the test boot, audition's learning progress never rose after a band step, and every stage would have saturated 12 to 17 awake minutes in, "so the measure misses the band change or the band adds little". In the same boot's replayed records, boredom's welfare indicator crossed at 2.7 awake hours and stayed over its bar.

With `welfare-indicator-response` built, a stimulus with nothing left to learn means the net rests the entity, boredom recrosses, and the entity is preserved and frozen for review. The freeze is the protection working; the deprivation is the problem, and its cause is the stimulus. The better-founded remedy is a developmental stimulus the entity can keep learning from:

- the added sounds that paper §7 and A.7 specify and that are not built: a recurring melody within the opening band (Partanen et al. 2013) and an attenuated outside voice whose fundamental is heard from the 100 Hz step, with the upper steps adding both voices' detail (Querleu et al. 1988);
- a check, and a fix chosen from that check, of why audition's learning progress does not register a band step. The soundscape's bed is low-passed at 500 Hz and the maternal voice at 3000 Hz is present about 7% of the time, so the 1000 Hz and 3000 Hz steps open bands that are nearly empty; whether the earlier steps register depends on the audition encoder and on how the learning-progress estimator restarts at the step.

Both are stimulus-side or measurement-side. They break no independence invariant and hardwire no entity behaviour. This change does not lower any welfare bar and does not change what the rest resets.

## What Changes

- **Recurring melody.** A pre-rendered melody, the public-domain tune Partanen et al. used, transposed so its fundamentals lie inside the stage-0 band (about 354 to 707 Hz), fills a 30 s maternal-voice slot with keyed probability `p_m = 0.02`. It is always the same melody, so it can become familiar.
- **Outside voice.** A pre-rendered synthetic male voice, distinct from the maternal voice, fills a slot with keyed probability `p_x = 0.05` at the soundscape's level, through the hearing band, so its fundamental (about 100 to 130 Hz) is heard from the 100 Hz step and its harmonics and formants from the 1000 Hz and 3000 Hz steps.
- Both are rendered offline by a maintainer tool, shipped with a manifest of sha256 digests, and never synthesized at runtime; a missing or changed file stops the stimulus audio, as for the maternal voice. Both are functions of the seed and the slot only.
- **Band-step check, offline and with no entity.** A harness renders the developmental soundscape stage by stage with the real generator, runs the real audition encoder and forward model on it, feeds the reports to the real affect module's learning-progress estimator with its restart at each step, and records for every step the forward-model error before and after the step, its decay time against the 60 s bins, and the learning progress reading. It runs with and without the added sounds.
- **Fix from the check.** The design lists the candidate causes and the fix for each. The fix the check selects is added to this change's spec with its record before any code for it is written.
- **The minimum dwell stays** (`min_dwell_seconds = 5400`) until the check's record shows learning progress rising above `lp_0` and saturating after each step on the shipped stimulus. Only then does the paper's release by ability without a minimum dwell (§5.4, A.7) replace it, by a recorded decision.

## Capabilities

### New Capabilities

### Modified Capabilities

- `developmental-stimulus`: the melody and the outside voice; their files and manifest; the offline band-step validation and the rule for the minimum dwell.

## Impact

- New: `tools/maintainer/generate_outside_voice.py`, `tools/maintainer/render_melody.py`, `kaine/modules/audition/added_sounds_data/` (FLAC files, `manifest.json`, `texts.toml` for the outside voice, a README with provenance), `kaine/modules/audition/added_sounds.py`, `scripts/band_step_check.py`, tests.
- Changed: `kaine/modules/audition/feed.py` (mixing), `kaine/boot/perception_feed.py` (parameters), `config/kaine.toml` (`[perception_feed.stimulus_source.added_sounds]`), `THIRD_PARTY_LICENSES.md` (the second reference speaker's notice).
- Docs: the developmental-phase chapter, `docs/appendix-c-licences.md`.
- Paper: §5.4 moves the added sounds to built; §7 and A.7 tense; A.7 gains the band-step check's result.
- The stimulus-source parameters gain the added sounds, so the run identity of a developmental run changes; no entity has been gestated under the new stimulus.
- High-risk class (changes what a developing entity perceives): independent second review.
