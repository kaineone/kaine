## MODIFIED Requirements

### Requirement: The stimulus-source audio passes a hearing band that widens in the order of fetal hearing
When `[perception_feed.stimulus_source.hearing].enabled` is true (the default), every stimulus-source audio block SHALL be the soundscape plus the maternal voice, filtered by a band-pass whose edges depend only on the hearing stage (see the stage requirement below), then scaled, limited and quantized as before. The edges SHALL follow the tone grid 100, 250, 500, 1000 and 3000 Hz of Hepper and Shahidullah (1994): each edge lies at the geometric mean of the outermost tested tone heard and the next tested tone not heard, and there is no edge on a side with no unheard tested tone. The band SHALL be 353.6 to 707.1 Hz in stage 0, 158.1 to 707.1 Hz in stage 1, a low-pass at 707.1 Hz in stage 2, a low-pass at 1732.1 Hz in stage 3, and open in stage 4. The filter SHALL be a 1,025-tap Hamming-windowed sinc design, a band-pass with unity gain at the band's geometric centre, a low-pass with unity DC gain, or the unit impulse at the centre tap when open, so every stage delays by 512 samples, convolved over the unfiltered mix of the preceding blocks and the current one (blocks before index 0 are silent), so a block SHALL be a pure function of the seed, the block index, the hearing stage and the voice plan, whatever blocks were rendered before. When the band is enabled the maternal voice SHALL load with its low-pass at 3,000 Hz; the bed SHALL keep `lowpass_hz`. When the band is disabled, every audio block SHALL be byte-identical to the stream without it. The hearing parameters SHALL NOT enter the stimulus-source parameter digest.

#### Scenario: Disabled band leaves the audio unchanged
- **WHEN** `enabled` is false, with or without the maternal voice
- **THEN** every block equals, byte for byte, the block the stream produced before the band existed

#### Scenario: The band starts at 500 Hz and widens down first, then up
- **WHEN** blocks are rendered in each of the five stages
- **THEN** the power below the stage's low edge divided by √2 and above its high edge times √2, where the stage has those edges, is at least 40 dB below the in-band power, the low edge moves twice and goes before the high edge moves, and the 45 to 55 Hz heartbeat thud is at least 40 dB down in the first two stages and within 1 dB of the band-off stream from the third on

#### Scenario: A block does not depend on the blocks rendered before it
- **WHEN** one stream renders block `k` first and another renders blocks `k - 10` to `k` in order, with the same seed and stage
- **THEN** both produce the same bytes for block `k`

#### Scenario: A restart resumes the band
- **WHEN** a stream is rebuilt with a stage owner restored from its file
- **THEN** its band edges equal the edges before the restart

### Requirement: The colour ramp spans the developmental phase
During the developmental phase the visual source's schedule saturation SHALL be k/5 in hearing stage k, scaled by the maternal-state hue gain as before; the exponential ramp is retired. `colour_ramp_seconds` SHALL be accepted in the configuration with a warning and ignored. The `StimulusSourceParams` field SHALL stay, at its code default of 3,600 s, so the parameter digest of the defaults is unchanged.

#### Scenario: Colour still rises late in the phase
- **WHEN** the hearing stage is 0, 2 or 4
- **THEN** the schedule saturation is 0, 0.4 or 0.8 before the hue gain

#### Scenario: A retired key boots with a warning
- **WHEN** `colour_ramp_seconds` is set
- **THEN** boot succeeds and logs that the key is retired and ignored

## ADDED Requirements

### Requirement: Hearing-band stages advance by saturation
The hearing band SHALL widen through five stages in the existing fetal order. One persisted owner SHALL decide the stage; the audio stream, the visual source, the affect module and the maturation gate SHALL read that stage and SHALL NOT compute one from time. Stage k SHALL end when audition's learning progress, restarted at the step, has stayed below lp_0 for `saturation_window_seconds` (W_sat, 600) of awake time once the stage has run `min_dwell_seconds` (d_min, 5400) of awake time, or when the stage has run `max_dwell_seconds` (d_max, 25200) of awake time. A missing learning-progress reading SHALL count as unsaturated. Dwell SHALL advance only with awake time, so rests add none, SHALL persist across restarts, and the saturation window SHALL restart fresh after a restart.

#### Scenario: Saturation advances the stage after the minimum dwell
- **WHEN** learning progress stays below lp_0 for 600 awake seconds and the stage has run at least 5400 awake seconds
- **THEN** the stage advances by one

#### Scenario: Saturation before the minimum dwell does not advance
- **WHEN** learning progress has been below lp_0 for 600 awake seconds but the stage has run 5399 awake seconds
- **THEN** the stage does not advance until the minimum dwell has run

#### Scenario: The maximum dwell caps the stage
- **WHEN** a stage has run 25200 awake seconds with learning progress never saturated
- **THEN** the stage advances

#### Scenario: A missing reading is unsaturated
- **WHEN** no learning-progress reading is available for the whole of the minimum dwell and beyond
- **THEN** the stage advances only at the maximum dwell

#### Scenario: A reading at or above lp_0 resets the window
- **WHEN** learning progress is below lp_0 for 500 seconds, reaches lp_0, and then stays below for 500 seconds
- **THEN** the stage does not advance

#### Scenario: Restart keeps dwell and restarts the window
- **WHEN** the entity restarts 400 saturated seconds into the window after 6000 seconds of dwell
- **THEN** dwell resumes at 6000 seconds and the stage advances only after a further 600 saturated awake seconds

#### Scenario: Rests add no dwell
- **WHEN** the awake time does not advance across a rest
- **THEN** dwell and the saturation window do not advance

### Requirement: The hearing keys are retired and the new ones validated
`[perception_feed.stimulus_source.hearing]` SHALL accept `enabled`, `saturation_window_seconds`, `min_dwell_seconds` and `max_dwell_seconds`, and SHALL accept `maturation_seconds` with a warning, ignored. The dwell bounds SHALL satisfy `0 < saturation_window_seconds` and `saturation_window_seconds <= min_dwell_seconds <= max_dwell_seconds`.

#### Scenario: Inverted dwell bounds are refused
- **WHEN** `min_dwell_seconds` exceeds `max_dwell_seconds`
- **THEN** boot fails naming the keys
