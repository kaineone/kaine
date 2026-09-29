## 1. Birth record
- [ ] 1.1 Record `womb_t_at_birth`, the womb seed and a parameter digest in the stage file when the bloom completes, and report bloom completion (in runtime.json).
- [ ] 1.2 The study runner requests the seed's preservation only after the bloom is complete.

## 2. Transition
- [ ] 2.1 `kaine/modules/perception_transition.py`:
  - pure crossfade functions: a monotonic alpha curve with fixed endpoints, a video blend, and an audio fade-in;
  - video and audio transition sources wrapping the playlist sources.
- [ ] 2.2 Boot wiring. Build the transition when the conditions hold. Start the playlist clock paused under `transition` and release it at the fade's end. Log the reason when no transition is rendered.
- [ ] 2.3 `[perception_feed].transition_seconds` (default 20) in config/kaine.toml. The step manifest records it.

## 3. Verification
- [ ] 3.1 Tests:
  - determinism: identical frames and samples from one seed;
  - fade endpoints and bounds;
  - film time zero at the end of the fade;
  - no writes;
  - no transition without a birth record.
- [ ] 3.2 Docs (docs/operations.md, gestation and the study). The full offline suite is green.
