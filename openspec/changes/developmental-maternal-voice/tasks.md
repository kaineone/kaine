## 1. Implementation

- [x] 1.1 Generation tool, original texts and the rendered repertoire with its checksummed manifest and attribution
- [x] 1.2 Repertoire loader that verifies, decodes, upsamples and low-pass filters every take, failing loudly on a missing or corrupt file, and the seeded slot schedule with arousal-paced episodes and awake-time unlocking
- [x] 1.3 The stimulus-source audio stream mixes the voice; boot reads `[perception_feed.stimulus_source.voice]`, loads the repertoire, passes the awake-time provider and records the voice in the run descriptor
- [x] 1.4 Config keys with Table A1 defaults, package data, licences and docs
- [x] 1.5 Tests: determinism under the seed, spectrum below the intrauterine cutoff, repertoire growth with awake time, byte-identical audio with the voice disabled, loud failure on a missing or corrupt file
