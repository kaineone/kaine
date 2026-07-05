## Why

The oscillatory coherence layer multiplies a coalition's salience by a
phase-locking factor before Syneidesis selection. The existing controls are
**shallow** (per the architecture audit): a single-tick negative control
(`test_selection_bit_for_bit_identical_when_disabled`) and a single
moderate-gain positive control (`test_phase_locked_coalition_outranks_desync_when_enabled`).

That leaves three gaps the audit called out:

- The bit-for-bit "disabled == absent" guarantee is only checked for ONE tick.
  The disabled path must hold the line across MANY cycles with the same seed and
  inputs — a coherence side effect that only manifests after several ticks (e.g.
  a buffer that leaks state) would slip past a single-tick check.
- "Disabled ⇒ factor exactly 1.0" is asserted only indirectly (via identical
  selection). There is no explicit assertion that the multiplier path is a
  literal no-op — the applied factor is unit and no `metadata['coherence']` key
  is written.
- The positive control uses a MODERATE gain, which proves the toggle does
  *something* but not that the toggle is firmly connected to the selection
  mechanism. An EXTREME precision gain should demonstrably FLIP selection — a
  strong proof the control is wired to the mechanism it claims to drive.

## What Changes

Deepen the oscillatory-layer controls. No production code change is required —
the layer already skips the coherence branch entirely when disabled
(`coherence=None`) and `CoherenceScorer.factor_from_plv` already maps PLV onto
`[floor, ceiling]`. This change adds the missing depth as tests + spec.

- **Multi-cycle bit-for-bit identity:** drive a disabled-layer `Syneidesis` and a
  layer-absent baseline `Syneidesis` through MANY cycles with the same seed and
  the same per-cycle events/phases; assert selected events, scores, inhibition,
  and the absence of `metadata['coherence']` are identical on EVERY cycle.
- **Explicit unit-multiplier / no-op assertion:** assert the disabled path is a
  literal no-op — no `metadata['coherence']` key is written, and the salience
  scores equal the raw strategy scores (an effective multiplier of exactly 1.0),
  while a directly constructed `CoherenceScorer` confirms `factor_from_plv(1.0)`
  equals the ceiling and the bounded map is monotone.
- **Extreme-gain positive control:** enable the layer with the precision gain
  cranked to an EXTREME ceiling (and a low floor) and assert selection
  demonstrably FLIPS — a desynchronized higher-raw-salience event is overtaken by
  a phase-locked lower-raw-salience event once the extreme coherence gain
  applies. This complements the existing moderate-gain test, proving the toggle
  is firmly connected to the selection mechanism.

## Capabilities

### Modified Capabilities

- `oscillatory-binding`: the coherence multiplier's disabled-path guarantee is
  strengthened to bit-for-bit identity across MANY cycles with an explicit unit
  (1.0) multiplier / no-op, and an extreme precision gain is shown to demonstrably
  change selection.

## Impact

- **Code:** none required — the disabled path is already a hard skip and the gain
  map already exists. (No behavior change.)
- **Tests:** `tests/test_syneidesis_coherence.py` — multi-cycle bit-for-bit
  identity, explicit unit-multiplier/no-op assertions, and an extreme-gain
  selection-flip positive control.
- **Docs:** `docs/processes/global-workspace.md` (or the oscillatory-layer doc)
  notes the multi-cycle disabled guarantee and the extreme-gain flip control.
- **Safety:** offline unit tests only. No entity boot, no live bus, no snnTorch
  (coherence runs on phase sequences fed via context).
