## Why

In the tenth test boot the hearing band stepped every 6 h (Delta_hear = 24 h awake), while the paper's offline calibration says each low step gives two to four hours of learning progress (A.7). Each step therefore left two to four hours with no new sound, and boredom sat near its ceiling between steps. The paper (predictive-workspace-paper #48) now sets Delta_hear to 43,200 s in Table A1, a step every 3 h, and colour's time constant to Delta_awake, the phase's awake-time floor of 86,400 s, which it keeps. The shipped config comment still says the colour ramp equals the band's span, which is no longer true.

## What Changes

- `[perception_feed.stimulus_source.hearing].maturation_seconds` is 43,200 s in `config/kaine.toml`, and the `HearingBandParams` default and its `from_section` fallback are 43,200 s.
- `colour_ramp_seconds` stays 86,400 s. Its comment now says it equals the phase's awake-time floor (`[developmental_stage].min_lived_seconds`, Table A1 Delta_awake).
- The hearing-band stream tests take their stage times from the default span instead of hard-coding the 24 h one, and a config test pins the shipped span and the colour ramp to Table A1.
- A.7's offline entrainment validation is re-run with the archived harness on the current classes (`validation.md`).

## Capabilities

### Modified Capabilities

- `developmental-stimulus`: the hearing band spans 12 awake hours, and the colour ramp's span is the phase's awake-time floor.

## Impact

- `kaine/modules/audition/hearing_band.py`, `config/kaine.toml`, `docs/06-operation/development.md`, `docs/appendix-a-configuration/perception-and-sleep.md`, `tests/test_hearing_band.py`, `tests/test_stimulus_source_hearing_band.py`, `tests/test_stimulus_source_colour_ramp_config.py`.
- Behaviour: the band reaches each stage twice as early in awake time, so the heartbeat thud is heard from 6 h awake instead of 12 h and the band is open at 12 h. The self-rhythm's drive reads the heartbeat phase alone, so the entrainment marker, the self-rhythm and the viability watch read nothing the band changes. The hearing parameters stay out of the stimulus-source parameter digest, so the digest recorded at maturation is unchanged.
