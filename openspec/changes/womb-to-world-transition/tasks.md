## 1. Birth record
- [x] 1.1 Record `womb_t_at_birth`, the womb seed and a parameter digest in the stage file when the bloom completes, and report bloom completion (in runtime.json).
- [x] 1.2 The study runner requests the seed's preservation only after the bloom is complete.

## 2. Transition
- [x] 2.1 `kaine/modules/perception_transition.py`:
  - pure crossfade functions: a monotonic alpha curve with fixed endpoints, a video blend, and an audio fade-in;
  - video and audio transition sources wrapping the playlist sources.
- [x] 2.2 Boot wiring. Build the transition when the conditions hold. Start the playlist clock paused under `transition` and release it at the fade's end. Log the reason when no transition is rendered.
- [x] 2.3 `[perception_feed].transition_seconds` (default 20) and `transition_audio_fade_seconds` (default 3) in config/kaine.toml. The run manifest records both and `transition_planned`; `perception.transition` events record the outcome; ignition-log records carry `paused_by`.

## 3. Verification
- [x] 3.1 Tests:
  - determinism: identical frames and samples from one seed;
  - fade endpoints and bounds;
  - film time zero at the end of the fade;
  - no writes;
  - no transition without a birth record.
- [x] 3.2 Docs (docs/operations.md, gestation and the study). The full offline suite is green.
