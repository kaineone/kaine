## Why

A test boot (2026-10-18) showed the developmental stimulus starves curiosity. The soundscape is four fixed sinusoids, low-passed noise and a heartbeat thud, so the audition forward model learns it and its error stops falling, the noise cannot be learned, learning progress sits below its floor, and curiosity holds near 0.85 with about one relief an hour. Relief by learning progress is the entity's own response (paper A.4), so the stimulus must offer something whose prediction can improve. A fetus hears its mother's voice above the intrauterine background, low-pass filtered by the body (Querleu et al. 1988; Gerhardt and Abrams 2000; Richards et al. 1992; Benzaquen et al. 1990), and learns from it: newborns prefer a passage their mother read aloud in late pregnancy (DeCasper and Spence 1986), fetal heart rate tells the mother's voice from a stranger's (Kisilevsky et al. 2003), and prenatal exposure shapes responses to pseudowords (Partanen et al. 2013), vowels (Moon et al. 2013) and the melody of cries (Mampe et al. 2009). The paper (§7, A.7, Table A1, branch paper-maternal-voice) now adds a maternal voice to the developmental stimulus.

## What Changes

- The stimulus-source audio mixes in a maternal voice: pre-rendered utterances shipped in the package (`kaine/modules/audition/maternal_voice_data/`, 41 FLAC files, 8 kHz mono, about 2.1 MB, 200 s), rendered offline with Chatterbox 0.1.6 conditioned on the CMU ARCTIC `slt` speaker, a female voice recorded for speech synthesis, by `tools/maintainer/generate_maternal_voice.py` from original texts in `texts.toml`. No speech is synthesized at runtime.
- At load every file is checked against the manifest's sha256 and decoded with PyAV; a missing, altered or undecodable file raises `PerceptionUnavailableError` naming the file, so the stimulus never falls silent quietly.
- Each utterance is upsampled to 16 kHz and passes the same intrauterine low-pass as the soundscape (`lowpass_hz`), then plays at `level_db` (6 dB) above the soundscape's RMS, with a seeded level jitter of up to `jitter_db` (3 dB). The headroom grows by the voice's RMS level and a soft tanh limiter rounds the rare peaks above it, so the heartbeat-and-noise bed is 2.4 dB lower than without the voice (worst-case-peak headroom would cost 11.2 dB) and the limiter acts on about 0.25% of speech samples.
- Timing: time is cut into `slot_seconds` (30 s) slots; a slot holds speech with probability `episode_probability` (0.2) times the maternal arousal at its start, so speech follows the existing maternal state. A talking slot holds utterances separated by seeded pauses of `pause_min_seconds` to `pause_max_seconds` (0.5 to 1.5 s). Its first utterance is the repeated passage with probability `repeat_share` (0.25).
- Repertoire: items unlock in file order, `initial_unlocked` (5) at first and one more every `unlock_seconds` (3,600 s) of awake time, as the colour ramp follows awake time. The choice of a slot is fixed when the slot is first rendered.
- The voice continues through sleep like the rest of the stimulus; unlocking pauses while awake time does.
- The voice needs the 16 kHz stream rate (`[perception_feed.audio].sample_rate`, twice the takes' 8 kHz); any other rate fails boot unless the voice is disabled.
- The image build context keeps the takes (`.dockerignore` and `.containerignore` exempt them from `**/*.flac`).
- New config table `[perception_feed.stimulus_source.voice]` with `enabled` (true) and the keys above. With `enabled = false` the audio is byte-identical to the current build. The voice parameters stay out of `StimulusSourceParams`, so the parameter digest recorded at maturation is unchanged.
- The heartbeat, the self-rhythm drive (computed from the heartbeat phase alone), the maturation gate (vision error ratio, self-rhythm markers) and the viability watch read nothing the voice changes.

## Capabilities

### Modified Capabilities

- `developmental-stimulus`: the stimulus-source soundscape carries a pre-rendered maternal voice with arousal-paced episodes and a repertoire that grows with awake time.

## Impact

- New `kaine/modules/audition/maternal_voice.py` (repertoire loader and schedule) and the package data under `kaine/modules/audition/maternal_voice_data/`; `kaine/modules/audition/feed.py` (`StimulusSourceProceduralAudioStream` mixes the voice), `kaine/boot/perception_feed.py` (config, loading, descriptor), `config/kaine.toml`, `pyproject.toml` (package data), `tools/maintainer/generate_maternal_voice.py`, `THIRD_PARTY_LICENSES.md`, `docs/06-operation/development.md`, `docs/09-modules/audition.md`, new `tests/test_maternal_voice.py`.
- Disk: about 2.1 MB in the repository and the image. Memory: about 26 MB of float64 samples while the stimulus runs.
- Behaviour: in an offline calibration on the real audition encoder, forward model and affect drive equations, curiosity is relieved by learning progress about 8 times an hour instead of never. A phase-randomized control with the same timing and spectrum relieves it as often, so the relief comes from the forward model re-adapting at each speech episode rather than from learning the speech itself; see the PR for the numbers.
