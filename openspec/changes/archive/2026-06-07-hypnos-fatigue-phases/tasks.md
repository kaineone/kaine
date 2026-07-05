## 1. Fatigue trigger

- [x] 1.1 Subscribe Hypnos to `soma.fatigue`; trigger maintenance on `crossed == true`
- [x] 1.2 Keep `interval_seconds` as a max-interval safety net; retain deferral + non-interruptibility + freeze preemption

## 2. Phase ordering and stubs

- [x] 2.1 Rename and reorder Hypnos phases to the paper's five (light-consolidation, deep-consolidation, associative-replay, affective-reset, voice-alignment); stub phases 3/5 behind their respective feature flags
- [x] 2.2 Phase 1: weak-trace decay; strong-trace tagging for deep consolidation

## 3. Phase-1 oscillator frequency-reduction hook

- [x] 3.1 Add `ModuleOscillator.set_frequency(scale)` no-op interface to `BaseModule` / oscillator layer; document that `oscillatory-layer` provides the real body
- [x] 3.2 Invoke `set_frequency` across all active modules at start of phase 1; confirm no-op when oscillatory-layer absent

## 4. Phase 2 — deep consolidation + downscaling

- [x] 4.1 Mnemos `downscale_activations(factor)` preserving relative ordering; invoked by Hypnos phase 2
- [x] 4.2 Open a `replay_window`; suspend external perception (reuse freeze/locus machinery); drive `mnemos.replay` re-injection (no-op stub until `mnemos-replay` ships)
- [x] 4.3 Restore perception after the replay window

## 5. Phase 4 — affective + fatigue reset

- [x] 5.1 Phase 4: existing affective reset + explicitly reset Soma's fatigue accumulator to baseline

## 6. Config

- [x] 6.1 `[hypnos.consolidation]`: `fatigue_triggered`, `downscale_factor`, `replay_window_s`; keep `interval_seconds` as safety net; update `make_hypnos` allowed keys

## 7. Tests

- [x] 7.1 `tests/test_hypnos_trigger.py` — `soma.fatigue` triggers; safety-net interval still fires without fatigue
- [x] 7.2 `tests/test_hypnos_phases.py` — five phases in order; downscaling preserves ordering; perception suspended during replay then restored; fatigue reset in phase 4
- [x] 7.3 `tests/test_hypnos_oscillator_hook.py` — phase-1 `set_frequency` is a no-op when oscillatory-layer absent; no error raised

## 8. Verification

- [x] 8.1 Full unit suite green
- [x] 8.2 `openspec validate hypnos-fatigue-phases --strict` clean
- [x] 8.3 Commit (Kaine.One), branch-per-change, merge, archive
