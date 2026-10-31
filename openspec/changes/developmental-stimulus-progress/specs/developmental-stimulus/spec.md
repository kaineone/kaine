## ADDED Requirements

### Requirement: A recurring melody plays within the opening band
When `[perception_feed.stimulus_source.added_sounds].enabled` is true, a slot without maternal speech SHALL hold the shipped melody when a keyed draw on `(seed, slot)` is below `melody_probability` (default 0.02). The melody's fundamentals SHALL lie inside the stage-0 band, it SHALL be played at the maternal voice's level above the soundscape with 0.5 s ramps, and it SHALL pass the hearing band.

#### Scenario: Heard from the first stage
- **WHEN** a melody slot is rendered in hearing stage 0
- **THEN** at least half of the melody layer's power lies inside the stage-0 pass band

### Requirement: An attenuated outside voice plays through the hearing band
A slot without maternal speech or melody SHALL hold one outside-voice utterance when a keyed draw on `(seed, slot)` is below `outside_voice_probability` (default 0.05), at the soundscape's RMS level, low-passed at 3000 Hz, with 0.5 s ramps, through the hearing band.

#### Scenario: The fundamental arrives at the 100 Hz step
- **WHEN** the same outside-voice slot is rendered in stage 1 and in stage 2
- **THEN** the power below 158 Hz is at least 20 dB higher in stage 2 than in stage 1

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

### Requirement: Band steps are validated offline before a developmental run
Before a developmental run uses a stimulus version, an offline check with the real generator, audition encoder, forward model and learning-progress estimator SHALL record, for every hearing-band step and three seeds, the forward-model error before and after the step, its recovery time and every learning-progress reading against `lp_0`, with and without the added sounds. The record SHALL be stored with the change and the stimulus version recorded in each maturation record.

#### Scenario: A step the measure misses
- **WHEN** the check finds a step after which learning progress never rises above `lp_0`
- **THEN** the record names the step and the cause the check supports

### Requirement: The minimum dwell stays until band steps register
The shipped `min_dwell_seconds` SHALL stay 5400 until a stored band-step record shows learning progress above `lp_0` after every step and saturation within the step's dwell on the shipped stimulus. Removing it SHALL require that record and a recorded operator decision.

#### Scenario: A record that misses a step
- **WHEN** the latest record shows a step with no learning-progress rise
- **THEN** the shipped minimum dwell is 5400 s
