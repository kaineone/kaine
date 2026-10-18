## ADDED Requirements

### Requirement: The developmental soundscape carries a pre-rendered maternal voice
When `[perception_feed.stimulus_source.voice].enabled` is true (the default), the stimulus-source audio SHALL mix a maternal voice into the soundscape from pre-rendered utterances shipped with the package and listed in a manifest, and SHALL NOT synthesize speech at runtime. Every take SHALL be upsampled by two to the stream rate, low-pass filtered with the soundscape's `lowpass_hz` filter, scaled to unit RMS, and played at `level_db` above the soundscape's RMS over its first 60 s of stimulus time for the run seed, times a seeded per-utterance gain of up to `jitter_db` either way. The output headroom SHALL include the loudest possible voice peak so the mix does not clip. When the voice is disabled, every audio block SHALL be byte-identical to the stream without the voice. The voice parameters SHALL NOT enter the stimulus-source parameter digest.

#### Scenario: Disabled voice leaves the audio unchanged
- **WHEN** the voice is disabled
- **THEN** every block of the stimulus-source audio equals, byte for byte, the block the stream produced before the voice existed

#### Scenario: The voice stays below the intrauterine cutoff
- **WHEN** a talking slot is rendered with `lowpass_hz` = 500
- **THEN** the voice layer's power above 1,000 Hz is at least 40 dB below its power below 500 Hz

### Requirement: Maternal speech follows the maternal state and a growing repertoire
Stimulus time SHALL be cut into slots of `slot_seconds`. Slot `s` SHALL hold speech when a keyed draw on `(seed, s)` is below `episode_probability` times the maternal arousal at the slot's start. A talking slot SHALL start within its first 2 s and hold whole utterances separated by seeded pauses in `[pause_min_seconds, pause_max_seconds]`, never running past the slot's end. Its first utterance SHALL be the first item, the repeated passage, with probability `repeat_share`; every other choice SHALL be uniform over the unlocked items, and the take uniform over the item's takes. The unlocked count SHALL be `min(N, initial_unlocked + floor(T_awake / unlock_seconds))`, with `T_awake` the awake time the colour ramp uses, evaluated when the slot is first rendered and fixed for that slot. The plan of a slot SHALL be a pure function of the seed, the slot index and that count. The voice SHALL keep playing while the entity sleeps.

#### Scenario: The same seed and awake time give the same audio
- **WHEN** two streams with the same seed render the same blocks with the same awake-time readings
- **THEN** their PCM is identical, and a stream with another seed differs

#### Scenario: Locked items are never heard
- **WHEN** awake time is below `unlock_seconds`
- **THEN** only the first `initial_unlocked` items are chosen, and after `k` more multiples of `unlock_seconds` the first `initial_unlocked + k` items are

#### Scenario: Calm maternal state means less speech
- **WHEN** slots are compared across maternal arousal
- **THEN** the share of talking slots rises with arousal, and no slot talks when `episode_probability` is 0

#### Scenario: Sleep pauses unlocking, not speech
- **WHEN** awake time stops advancing while stimulus time runs on
- **THEN** talking slots keep occurring and no further item unlocks

### Requirement: A missing or corrupt maternal-voice file fails loudly
At load, the repertoire SHALL verify every manifest entry's sha256, decode it, and check its sample rate, channel count and frame count against the manifest. A missing manifest, a missing or altered file, a decode failure, a mismatch, or PyAV being absent SHALL raise `PerceptionUnavailableError` naming the problem, and boot SHALL NOT start the stimulus-source audio without the voice when the voice is enabled.

#### Scenario: An altered file stops the load
- **WHEN** one take's bytes differ from its manifest sha256
- **THEN** loading raises `PerceptionUnavailableError` naming that file

#### Scenario: A missing file stops the load
- **WHEN** a take listed in the manifest is absent
- **THEN** loading raises `PerceptionUnavailableError` naming that file
