# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

## 1. Scripted stimulus

- [x] 1.1 Reuse the `ScriptedBus` pattern (fixed entry ids, captured broadcasts
      + intents) factored into the runner package (no dependency on the test
      module).
- [x] 1.2 Build a fixed, reproducible multi-tick stimulus across prediction /
      cognition streams, crafted so phase-locked sources carry lower raw salience
      than desynchronized competitors (so an effective layer can re-rank them).
- [x] 1.3 Scripted phase registry exposing `all_modules()` with per-source phase
      schedules (phase-locked vs desynchronized), so `collect_phases=True` feeds
      the cycle real phases deterministically.

## 2. Two-arm controlled runner

- [x] 2.1 Build the cycle for one arm: `set_global_seed(seed)`,
      `deterministic=True`, `Syneidesis(coherence=scorer)` for enabled vs
      `coherence=None` for disabled; same seed + same stimulus both arms.
- [x] 2.2 Run N ticks per arm, capturing the per-tick trajectory (selected
      entries, salience scores, inhibited), excluding wall-clock latency.

## 3. Effect metric + verdict

- [x] 3.1 Selection-divergence fraction (top-entry differs across arms) +
      mean salience-ranking divergence (normalized footrule).
- [x] 3.2 Emit a shared-schema `Verdict`: WIN when the selection-divergence
      fraction exceeds the floor, NULL otherwise; effect size in `metrics`.

## 4. Output

- [x] 4.1 Seeded JSONL result (config, per-arm trajectory digest, metrics,
      verdict) + a summary dict; `write_jsonl` + `format_summary`.
- [x] 4.2 `__main__.py` CLI: `--seed`, `--ticks`, `--out`, gain knobs
      (`--coherence-floor`, `--coherence-ceiling`, `--plv-window`),
      `--min-effect`.

## 5. Docs + tests

- [x] 5.1 `docs/processes/oscillatory-ablation.md`: how to run; what WIN/NULL
      mean; the determinism guarantee.
- [x] 5.2 Tests: seeded run reproduces verdict + metrics (run twice, identical);
      crafted stimulus yields a measurable effect (WIN, effect > 0); disabled arm
      is bit-for-bit the layer-absent baseline; offline / no-boot assertion.

## 6. Verify

- [x] 6.1 `openspec validate oscillatory-ablation-runner --strict`.
- [x] 6.2 `pytest -k "oscillatory or ablation"` green; sidecar-boundary tests
      green (imports unchanged).
