## MODIFIED Requirements

### Requirement: Hearing-band stages advance by saturation
The hearing band SHALL widen through five stages in the existing fetal order. One persisted owner SHALL decide the stage; the audio stream, the visual source, the affect module and the maturation gate SHALL read that stage and SHALL NOT compute one from time. Stage k SHALL end when audition's learning progress, restarted at the step and read only over the full span `learning_progress_span_s` (`T_lp`, 5400) of completed bins since the restart, has stayed below lp_0 for `saturation_window_seconds` (W_sat, 600) of awake time, or when the stage has run `max_dwell_seconds` (d_max, 25200) of awake time. A missing reading, including one over less than the full span, SHALL count as unsaturated. Dwell SHALL advance only with awake time, so rests add none, SHALL persist across restarts, and the saturation window SHALL restart fresh after a restart.

#### Scenario: Saturation advances the stage after the minimum dwell
- **WHEN** the full-span reading has stayed below lp_0 for 600 awake seconds
- **THEN** the stage advances by one, which is no earlier than 6000 awake seconds after the step

#### Scenario: Saturation before the minimum dwell does not advance
- **WHEN** readings over less than the full span have been below lp_0 for 600 awake seconds, 720 s after the step
- **THEN** the stage does not advance, because those readings count as missing

#### Scenario: The maximum dwell caps the stage
- **WHEN** a stage has run 25200 awake seconds with learning progress never saturated
- **THEN** the stage advances

#### Scenario: A missing reading is unsaturated
- **WHEN** no learning-progress reading is available for the whole of the full span and beyond
- **THEN** the stage advances only at the maximum dwell

#### Scenario: A reading at or above lp_0 resets the window
- **WHEN** the full-span reading is below lp_0 for 500 seconds, reaches lp_0, and then stays below for 500 seconds
- **THEN** the stage does not advance

#### Scenario: Restart keeps dwell and restarts the window
- **WHEN** the entity restarts 400 saturated seconds into the window after 6000 seconds of dwell
- **THEN** dwell resumes at 6000 seconds and the stage advances only after a further 600 saturated awake seconds

#### Scenario: Rests add no dwell
- **WHEN** the awake time does not advance across a rest
- **THEN** dwell and the saturation window do not advance

### Requirement: The hearing keys are retired and the new ones validated
`[perception_feed.stimulus_source.hearing]` SHALL accept `enabled`, `saturation_window_seconds` and `max_dwell_seconds`, and SHALL accept `maturation_seconds` and `min_dwell_seconds` with a warning, ignored. The bounds SHALL satisfy `0 < saturation_window_seconds` and `learning_progress_span_s + saturation_window_seconds <= max_dwell_seconds`, with `learning_progress_span_s` read from the affect section.

#### Scenario: Inverted dwell bounds are refused
- **WHEN** `max_dwell_seconds` is shorter than the learning-progress span plus the saturation window
- **THEN** boot fails naming the keys

#### Scenario: A retired minimum dwell
- **WHEN** the configuration sets `min_dwell_seconds = 600`
- **THEN** boot logs a warning that the key is retired, and no stage advances before its full-span reading has saturated

## ADDED Requirements

### Requirement: The band-step record is kept and the live gap closed before the release rule ships
The offline band-step record SHALL be stored under `docs/records/validation/band-steps/`. Before the full-span rule is used in a developmental run, a second record SHALL give the same per-step readings with arousal, rests and broadcast context, or from a test boot's audition errors, and SHALL say which. A test SHALL check that both records exist and name the shipped stimulus version.

#### Scenario: The live record is missing
- **WHEN** the shipped stimulus version has a band-step record but no live-gap record
- **THEN** the records test fails

### Requirement: A recurring melody plays within the opening band
When `[perception_feed.stimulus_source.added_sounds].enabled` is true, a slot without maternal speech SHALL hold the shipped melody when a keyed draw on `(seed, slot)` is below `melody_probability` (default 0.02). The melody's fundamentals SHALL lie inside the stage-0 band, it SHALL be played at the maternal voice's level above the soundscape with 0.5 s ramps, and it SHALL pass the hearing band.

#### Scenario: Heard from the first stage
- **WHEN** a melody slot is rendered in hearing stage 0
- **THEN** at least half of the melody layer's power lies inside the stage-0 pass band

### Requirement: An attenuated outside voice plays through the hearing band
A slot without maternal speech or melody SHALL hold one outside-voice utterance when a keyed draw on `(seed, slot)` is below `outside_voice_probability` (default 0.05), at the soundscape's RMS level, low-passed at 3000 Hz, with 0.5 s ramps, through the hearing band.

#### Scenario: The fundamental arrives at the 100 Hz step
- **WHEN** the same outside-voice slot is rendered in stage 1 and in stage 2
- **THEN** the power below 112 Hz (stage 1's stopband edge, 158 Hz divided by the square root of 2) is at least 40 dB higher in stage 2 than in stage 1

### Requirement: Added sounds are seeded and entity-independent
Each slot's added sound SHALL be a pure function of the seed and the slot index. No added sound SHALL depend on the entity's state or output, and a slot SHALL hold at most one of maternal speech, melody and outside voice. With the added sounds disabled, every audio block SHALL be byte-identical to the stream without them.

#### Scenario: The same seed gives the same sounds
- **WHEN** two streams with the same seed render the same blocks
- **THEN** their PCM is identical, and a stream with another seed differs

#### Scenario: Disabled added sounds leave the audio unchanged
- **WHEN** the added sounds are disabled
- **THEN** every block equals, byte for byte, the block the stream produced before they existed

### Requirement: Added-sound files are listed in a manifest and fail loudly
The melody and outside-voice takes SHALL be pre-rendered files shipped with the package and listed with their sha256 digests in a manifest; the runtime SHALL NOT synthesize them. A missing file or a digest mismatch SHALL stop the stimulus audio with an error naming the file, as for the maternal voice.

#### Scenario: A changed file
- **WHEN** one outside-voice take differs from its manifest digest
- **THEN** the stimulus audio refuses to start and the error names that take
