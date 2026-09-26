## 1. Feed and liveness (phase 1)

- [ ] 1.1 `WombProceduralSource` in `kaine/modules/topos/feed.py` (archived §3 video: dim low-contrast field, heartbeat-pulsed luminance, maternal-state hue and flow, colour saturation from the schedule), pure in `(seed, index)`.
- [ ] 1.2 `WombProceduralAudioStream` in `kaine/modules/audition/feed.py` (archived §3 audio: low-pass soundscape, heartbeat thud phase-shared with the video pulse).
- [ ] 1.3 Maternal state and heartbeat generator (archived §4–§5): bounded, seed-keyed, entity-independent; optional coupling of maternal arousal to beat rate.
- [ ] 1.4 Colour and sense-onset schedule on lived time (archived §7).
- [ ] 1.5 `[perception_feed.womb]` config (archived §11); boot feed factories accept `womb`; the virtual locus is selected like seeded/playlist; shipped mode stays `off`.
- [ ] 1.6 Liveness interface: a local womb probe (discard-only) and an external-presence check on `gestation.out`; tests for both and for "configuration alone is not a womb".
- [ ] 1.7 Tests: determinism per seed, bounds (maternal state, beat rate, luminance), the pulse tracks the beat across modalities, colour starts near grey and ramps on lived time, no entity state feeds the womb, zero persistence, CPU-only.

## 2. Self-rhythm oscillator (phase 2)

- [ ] 2.1 A dedicated self-rhythm oscillator and the optional bounded `external_drive` seam (archived §6); coalition oscillators never receive it; disabled is bit-for-bit identical.

## 3. Readiness readout (phase 3)

- [ ] 3.1 The `gestation` cycle-layer owner publishing `gestation.readiness` on `gestation.out` (archived §8 markers), imposing nothing on the entity; perturbation protocol bounded and off by default beyond the minimum.
- [ ] 3.2 Gate runner default readout stream `womb.out` → `gestation.out`.

## 4. Docs

- [ ] 4.1 Operations docs: running a gestating entity on one host with the local womb; what the womb is and is not.
