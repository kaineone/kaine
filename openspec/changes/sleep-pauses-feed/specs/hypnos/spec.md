## ADDED Requirements

### Requirement: Sleep pauses the perceptual feed
Hypnos SHALL suspend external perception (desired locus `off` and the shared playlist clock paused under the `hypnos` holder) when a sleep starts, whatever modules are active, and SHALL restore the pre-sleep locus and resume the clock when the sleep ends, including when the sleep pipeline fails or is cancelled.

#### Scenario: Sleep without Mnemos pauses the feed
- **WHEN** a sleep runs on a profile with Mnemos off and the pre-sleep locus is `virtual`
- **THEN** the desired locus is `off` while the sleep runs and `virtual` after it ends

#### Scenario: A failed sleep restores perception
- **WHEN** the sleep pipeline raises or is cancelled
- **THEN** the pre-sleep locus is restored and the playlist clock is resumed
