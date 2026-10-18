## ADDED Requirements

### Requirement: The stimulus-source audio passes a hearing band that widens in the order of fetal hearing
When `[perception_feed.stimulus_source.hearing].enabled` is true (the default), every stimulus-source audio block SHALL be the soundscape plus the maternal voice, filtered by a band-pass whose edges depend only on the awake time, then scaled, limited and quantized as before. The edges SHALL follow the tone grid 100, 250, 500, 1000 and 3000 Hz of Hepper and Shahidullah (1994): each edge lies at the geometric mean of the outermost tone heard and the next tone tested, or at the outermost tested tone. With `W` = `maturation_seconds` and awake time `T`, the band SHALL be 353.6 to 707.1 Hz for `T < W/4`, 158.1 to 707.1 Hz for `W/4 <= T < W/2`, 100 to 707.1 Hz for `W/2 <= T < 3W/4`, 100 to 1732.1 Hz for `3W/4 <= T < W`, and 100 to 3000 Hz from `T >= W` on; a non-finite or negative `T` SHALL give the first band. The filter SHALL be a 1,025-tap Hamming-windowed sinc band-pass with unity gain at the band's geometric centre, convolved over the unfiltered mix of the preceding blocks and the current one (blocks before index 0 are silent), so a block SHALL be a pure function of the seed, the block index, the awake time and the voice plan, whatever blocks were rendered before. When the band is enabled the maternal voice SHALL load with its low-pass at 3,000 Hz; the bed SHALL keep `lowpass_hz`. When the band is disabled, every audio block SHALL be byte-identical to the stream without it. The hearing parameters SHALL NOT enter the stimulus-source parameter digest.

#### Scenario: Disabled band leaves the audio unchanged
- **WHEN** `enabled` is false, with or without the maternal voice
- **THEN** every block equals, byte for byte, the block the stream produced before the band existed

#### Scenario: The band starts at 500 Hz and widens down first, then up
- **WHEN** blocks are rendered at awake times in each of the five stages
- **THEN** the power below the stage's low edge divided by √2 and above its high edge times √2 is at least 40 dB below the in-band power, and the edges move in the order low, low, high, high

#### Scenario: A block does not depend on the blocks rendered before it
- **WHEN** one stream renders block `k` first and another renders blocks `k - 10` to `k` in order, with the same seed and awake time
- **THEN** both produce the same bytes for block `k`

#### Scenario: A restart resumes the band
- **WHEN** a stream is rebuilt with an awake-time provider that resumes from the stage file's lived seconds
- **THEN** its band edges equal the edges before the restart at the same awake time

### Requirement: The colour ramp spans the developmental phase
The shipped configuration SHALL set `colour_ramp_seconds` so that colour saturation keeps rising across the developmental phase rather than within its first hour, with the value of the paper's Table A1. The `StimulusSourceParams` default SHALL stay 3,600 s so the parameter digest of the defaults is unchanged.

#### Scenario: Colour still rises late in the phase
- **WHEN** the shipped configuration is loaded
- **THEN** the colour saturation at 12 awake hours is below its value at 24 awake hours by at least 0.05 of full saturation
