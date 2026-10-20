## ADDED Requirements

### Requirement: The arousal-set auditory window shapes what is encoded
Audition's general acoustic path SHALL encode only the most recent fraction of each captured window, the fraction given by the arousal-to-window map, and never less than one analysis frame, and SHALL compute the published energy on the same span. The published `attended_window` SHALL report the fraction and `attended_seconds` the span encoded.

#### Scenario: Higher arousal encodes a shorter, more recent span
- **WHEN** the same captured window is perceived at arousal 0.0 and at arousal 1.0 with the default window range
- **THEN** the span encoded at arousal 1.0 is the most recent 15 percent of the window and the span at arousal 0.0 is the whole window

### Requirement: The tone feature is the utterance's length
The speech-path forward model's duration feature SHALL be the utterance's audio duration normalised over the maximum utterance length, and SHALL NOT depend on how long the classifiers took. Its checkpoint SHALL carry the feature-layout tag `utterance_duration_v2`, and a checkpoint without that tag SHALL be discarded so the model re-learns.

#### Scenario: Classifier latency does not change the feature
- **WHEN** the same utterance is classified once quickly and once slowly
- **THEN** the duration feature is the same

### Requirement: Every spectral band covers a distinct frequency bin
The fixed spectral encoder's band edges SHALL be strictly increasing FFT-bin indices that start above the DC bin, so no two bands read the same bins, and its `model_id` SHALL change whenever the band layout changes.

#### Scenario: No degenerate bands at 16 kHz
- **WHEN** the encoder runs with 32 bands, 25 ms frames and a 16 kHz sample rate
- **THEN** all 32 bands have distinct edge pairs and none includes the DC bin
