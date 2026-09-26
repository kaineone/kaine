## 1. Feed and liveness (phase 1)

- [x] 1.1 `WombProceduralSource` in `kaine/modules/topos/feed.py` (archived §3 video: dim low-contrast field, heartbeat-pulsed luminance, maternal-state hue and flow, colour saturation from the schedule), pure in `(seed, index)`.
- [x] 1.2 `WombProceduralAudioStream` in `kaine/modules/audition/feed.py` (archived §3 audio: low-pass soundscape, heartbeat thud phase-shared with the video pulse).
- [x] 1.3 Maternal state and heartbeat generator (archived §4–§5): bounded, seed-keyed, entity-independent; optional coupling of maternal arousal to beat rate.
- [x] 1.4 Colour and sense-onset schedule on lived time (archived §7).
- [x] 1.5 `[perception_feed.womb]` config (archived §11); boot feed factories accept `womb`; the virtual locus is selected like seeded/playlist; shipped mode stays `off`.
- [x] 1.6 Liveness interface: a local womb probe (discard-only) and an external-presence check on `gestation.out`; tests for both and for "configuration alone is not a womb".
- [x] 1.7 Tests: determinism per seed, bounds (maternal state, beat rate, luminance), the pulse tracks the beat across modalities, colour starts near grey and ramps on lived time, no entity state feeds the womb, zero persistence, CPU-only.

## 2. Self-rhythm oscillator (phase 2)

- [x] 2.1 `SelfRhythmOscillator` (OscillatorProtocol + keyword-only `external_drive` + `amplitude()`) built by `make_self_rhythm_oscillator`; coalition oscillators never receive the drive; no drive is bit-for-bit identical.
- [x] 2.2 Soma hosts, steps (own loop at `self_rhythm_step_hz`, default 20 Hz of subjective time; drive averaged over each step) and serializes the self-rhythm oscillator; the maternal-drive provider is injected in `womb` mode from the shared womb clock; feature slots 4-6 carry sin/cos(phase) and amplitude, and the width stays 8.
- [x] 2.3 `[soma].self_rhythm_enabled` (shipped false) and `[soma].self_rhythm_step_hz`; `check_womb_ready` refuses a gestating local womb without the self-rhythm.
- [x] 2.4 Tests: coherence factor identical with the drive on and off; the drive is bounded; Soma state round-trips the oscillator; the slots stay 0 without a womb; `check_womb_ready` reports a missing oscillator extra.

## 3. Readiness readout (phase 3)

- [ ] 3.1 The `gestation` cycle-layer owner publishing `gestation.readiness` on `gestation.out` (archived §8 markers), imposing nothing on the entity; perturbation protocol bounded and off by default beyond the minimum.
- [ ] 3.2 Gate runner default readout stream `womb.out` → `gestation.out`.
- [ ] 3.4 Probe protocol: withdrawal and perturbation windows with enforced hard maxima, `gestation.probe` start and end events, no probe while frozen, during a welfare response or in the first readout period, and abort on any of these.
- [ ] 3.5 The five markers as defined in the design, the persisted prediction-error baseline, and absent markers until data exists.
- [ ] 3.6 Birth transition: on `stage.birth`, the womb sources render the bounded bloom, stop delivering, and the presence publisher falls silent.
- [ ] 3.3 The gate runner reads the readout with `bus.latest()`, the newest entry only. Once `gestation.out` also carries `gestation.womb` presence events (at least 1 Hz), the newest entry is usually a presence event, so the readout must be found by scanning a time window for the newest `gestation.readiness`, as `kaine/lifecycle/womb_liveness.py` does for presence.

## 4. Docs

- [ ] 4.1 Operations docs: running a gestating entity on one host with the local womb; what the womb is and is not.
