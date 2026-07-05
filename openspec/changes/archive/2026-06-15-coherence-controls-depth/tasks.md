## 1. Multi-cycle bit-for-bit identity (disabled == absent)

- [x] 1.1 Test: drive a disabled-layer Syneidesis and a layer-absent baseline
      through MANY cycles with the same seed and the same per-cycle events/phases;
      assert selected events, order, scores, and inhibition identical on EVERY
      cycle, and no `metadata['coherence']` key on either.

## 2. Explicit unit-multiplier / no-op

- [x] 2.1 Test: disabled-layer salience scores equal the raw strategy scores
      (effective multiplier exactly 1.0) and no `metadata['coherence']` key.
- [x] 2.2 Test: `CoherenceScorer.factor_from_plv(1.0) == coherence_ceiling` and
      the bounded map is monotone non-decreasing across PLV in `[0, 1]`.

## 3. Extreme-gain positive control (selection flips)

- [x] 3.1 Test: with an EXTREME `coherence_ceiling` + low `coherence_floor`, a
      phase-locked lower-raw-salience event overtakes a desynchronized
      higher-raw-salience event; with the layer absent the desync event ranks
      first — proving the toggle drives selection.

## 4. Docs + validate

- [x] 4.1 Document the multi-cycle disabled guarantee and the extreme-gain flip
      control.
- [x] 4.2 `.venv/bin/python -m pytest -q -p no:cacheprovider tests/ -k
      "coherence or syneidesis or oscillat"` green.
- [x] 4.3 `openspec validate coherence-controls-depth --strict` passes.
