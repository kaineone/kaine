## Why

With the windowed learning-progress estimator (paper A.4), a fresh entity learns its developmental stimulus in about six awake hours. After that, nothing in the stimulus is left to learn, curiosity sits near 0.9, and its goals stall, which the welfare record counts as ends without the entity's own response. The developmental phase lasts at least 24 awake hours (the maturation gate's awake-time floor). The maternal voice's hourly repertoire unlock adds no measurable progress for the 32-unit spectral audition forward model, and the 3,600 s colour ramp is spent within the first hour.

Fetal hearing matures in a fixed order. Fetuses first respond to a 500 Hz tone at 19 weeks of age in utero. The range of tones responded to then widens downwards to 250 and 100 Hz, and only then upwards: at 27 weeks 96% of fetuses respond to 250 and 500 Hz and none to 1000 or 3000 Hz, and all respond to 1000 Hz at 33 weeks and to 3000 Hz at 35 weeks (Hepper and Shahidullah 1994, tones played through the maternal abdomen). Newborn colour vision is still very limited (Adams, Courage and Mercer 1994), so colour should keep gaining over the whole phase rather than in its first hour. The paper (§7, A.7, Table A1, branch paper-sensory-maturation) now ties the stimulus to this maturation.

## What Changes

- A hearing band filters the whole stimulus-source audio, the bed and the maternal voice alike, before the output gain. Its edges follow Hepper and Shahidullah's tone grid (100, 250, 500, 1000, 3000 Hz): each edge lies halfway in log frequency between the outermost tested tone heard and the next tested tone not heard, and an edge goes once no tested tone beyond it is unheard. It starts at 354 to 707 Hz (500 Hz only), and over `maturation_seconds` of awake time (86,400 s) it takes four equal steps in Hepper and Shahidullah's order: 250 Hz joins (low edge 158 Hz), then 100 Hz (the low edge goes: a low-pass at 707 Hz), then 1000 Hz (low-pass at 1,732 Hz), then 3000 Hz (the band is open). The filter is a 1,025-tap Hamming-windowed sinc design (band-pass with unity gain at its geometric centre, low-pass with unity DC gain, or the identity impulse), symmetric about its centre tap so every stage has the same 512-sample delay, applied to a history that recomputes the preceding blocks, so every block stays a pure function of the seed, the block index and the awake time.
- With the band on, the maternal voice loads with its low-pass at the band's final 3,000 Hz instead of `lowpass_hz`, since the tones Hepper and Shahidullah played reached the fetus through the abdomen; the bed keeps its 500 Hz low-pass, as the intrauterine background is low-frequency.
- The colour ramp's `colour_ramp_seconds` in `config/kaine.toml` rises from 3,600 s to 86,400 s, the band's span (Table A1), so colour keeps gaining across the phase. In the offline calibration on the real vision encoder and forward model, the longer ramp leaves the vision error ratio of the maturation gate unchanged (at most about 0.1 after two awake hours against the 0.3 ceiling). The dataclass default stays, so the parameter digest of the defaults is unchanged.
- New config table `[perception_feed.stimulus_source.hearing]` with `enabled` (true) and `maturation_seconds`. With `enabled = false` every audio block is byte-identical to the current build. The hearing parameters stay out of `StimulusSourceParams`, so the parameter digest recorded at maturation is unchanged.
- The band follows the same awake time as the colour ramp and the voice unlock, which the stage file carries across restarts (`lived_seconds`), so a restart resumes the band where it was.
- The heartbeat drive to the self-rhythm comes from the heartbeat phase alone, so the entrainment marker, the self-rhythm and the viability watch read nothing the band changes. The maternal heartbeat thud (45 to 55 Hz) is attenuated by at least 55 dB in the first two stages and passes from the third on; the visual heartbeat pulse is unchanged. The bed and voice are zero-mean, so the DC the low-pass stages pass is inaudible, as in the band-off stream.

## Capabilities

### Modified Capabilities

- `developmental-stimulus`: the stimulus-source audio passes a hearing band that widens over awake time in the order of fetal hearing, and the colour ramp spans the developmental phase.

## Impact

- New `kaine/modules/audition/hearing_band.py` (schedule and filter design); `kaine/modules/audition/feed.py` (`StimulusSourceProceduralAudioStream` applies the band), `kaine/boot/perception_feed.py` (config, voice low-pass, wiring), `config/kaine.toml`, `docs/06-operation/development.md`, `docs/09-modules/audition.md`, `docs/appendix-a-configuration/perception-and-sleep.md`, new `tests/test_hearing_band.py` and `tests/test_stimulus_source_hearing_band.py`.
- CPU: one 1,025-tap convolution per 30 ms block and the recomputed history (three blocks); memory: a cache of the last few unfiltered blocks.
- Behaviour: see the PR for the offline calibration on the real audition encoder, forward model, learning-progress estimator and drive equations.
