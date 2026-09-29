## Why

The operator's study protocol has a newborn move from the womb into the films "with a pleasant transition between environments", identical for every run.

Today:
- At birth the womb brightens over five seconds to a calm, pulse-free field while its soundscape fades to silence, and then it stops.
- Switching to the films needs a stop and a revive in `playlist` mode, and the revived run opens abruptly on the first film's first frame and first sample.
- Nothing records the womb's state at birth, so no later run can continue from what the being last perceived.
- The study runner preserves the being as soon as the stage turns embodied, which can fall mid-bloom.

## What Changes

- **The womb's state at birth is recorded.** When the birth bloom completes, the stage file records `womb_t_at_birth`: the womb time at which the bloom ended. It also records the womb seed and a digest of the womb parameters. A preservation carries the stage file, so the record travels with the seed.
- **A transition opens every viewing after birth.**
  - When `[perception_feed].transition_seconds` is above zero, the mode is `playlist`, and the stage is embodied, the feed opens with a crossfade over `transition_seconds` (20 s by default).
  - Video: from the womb's bloom-peak field rendered at `womb_t_at_birth` (bright, pulse-free, full colour) to the first film's opening frame, held still.
  - Audio: the film's sound fades in from the silence the bloom ended in.
  - The womb side is the womb generator's pure function of seed, time and parameters, and the fade curve is fixed, so the transition is identical in every run.
  - Frames and samples are generated in memory and never written.
- **Film time starts when the fade ends.** The playlist clock starts paused under the holder `transition` and is released at the end of the fade, so film minute 0 is the end of the transition. The ignition log's film position needs no correction. The step manifest records `transition_seconds`.
- **The birth preservation waits for the bloom.** Once the stage is embodied, the study runner requests the seed's preservation only after the womb reports the bloom complete.
- **Unchanged:**
  - a womb-mode boot of a born being still delivers nothing and warns;
  - `playlist` runs of unborn or unstaged entities are unaffected.

## Capabilities

### Modified Capabilities
- `perception-feed`: a post-birth viewing opens with the womb-to-world transition, and film time starts at its end.
- `gestational-stimulus`: the womb's state at birth is recorded.

## Impact

- **Code:**
  - `kaine/lifecycle/stage.py` and the birth hook (the birth record);
  - a new `kaine/modules/perception_transition.py` holding the pure crossfade and the transition sources;
  - the playlist factory wiring in `kaine/boot.py`;
  - `config/kaine.toml` (`[perception_feed].transition_seconds`);
  - the study runner's birth preservation;
  - `docs/operations.md`.
- **Safety:** zero raw-sense-data persistence holds.
