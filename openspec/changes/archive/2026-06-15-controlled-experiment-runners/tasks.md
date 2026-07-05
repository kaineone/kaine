# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

## 1. Package scaffold

- [x] 1.1 Create `kaine/evaluation/benchmarks/instrument_runners/` with
      `__init__.py` re-exporting the three runners + their configs/verdicts.
- [x] 1.2 Shared helpers: seeded JSONL `write_jsonl`, a battery dataclass shape,
      and the `set_global_seed(seed)` call at the top of each `run_*`.

## 2. A/B divergence runner

- [x] 2.1 Fixed battery of `(utterance, conditioning)` cases: empty-conditioning
      cases (expect ~0) + heavy-conditioning cases (expect large divergence).
- [x] 2.2 Run each case through `divergence_control` with the echo conditioned-
      inference client (the control `_EchoModelClient` pattern, factored into the
      runner) + a chosen embedder (process-stable DeterministicHashEmbedder
      default, offline — so a seeded run reproduces its metrics, not just verdict).
- [x] 2.3 Verdict: WIN when every conditioned case > floor AND every empty case
      ~0 (dynamic range); NULL otherwise. Record per-case divergence + embedder.

## 3. Memory coherence runner

- [x] 3.1 Fixed battery of planted facts in a REAL in-memory `MnemosCore` (the B2
      fixture pattern), built via an injected `mnemos_builder` (lazy local import
      fallback) so the eval package never imports `kaine.modules` at module top.
- [x] 3.2 Full-system (retrieval) arm vs bare arm via `MemoryProbeRunner`/
      `score_async`; include a never-stored fact → honest non-recall (score 0).
- [x] 3.3 Recorded retrieval proof: re-run the SAME client against an EMPTIED
      Mnemos; the advantage must vanish.
- [x] 3.4 Verdict: WIN when retrieval advantage > floor AND never-stored fact
      yields non-recall AND emptied-Mnemos advantage vanishes; NULL otherwise.

## 4. Self-model accuracy runner

- [x] 4.1 Fixed battery of `(planted-signal, claim, expected-score)` cases; plant
      signals into a temp logs dir and run the calibrated Eidolon scorer.
- [x] 4.2 Verdict: WIN when the scorer reproduces every expected score; NULL
      otherwise. Record states it validates the scorer arithmetic, not self-truth.

## 5. Output + CLI

- [x] 5.1 Each runner: seeded JSONL records (config, per-case rows, verdict) +
      a summary dict; `write_jsonl` + `format_summary`.
- [x] 5.2 `__main__.py` CLI dispatch selecting the instrument, with `--seed`,
      `--out`, and per-instrument knobs.

## 6. Docs + tests

- [x] 6.1 `docs/processes/controlled-experiment-runners.md`: how to run each;
      what WIN/NULL mean; honest scope of each.
- [x] 6.2 Tests per runner (offline): sane verdict on the battery; seeded run
      reproduces verdict + metrics; A/B empty ~0 + conditioned large; memory
      advantage vanishes on emptied Mnemos; self-model scorer reproduces expected
      scores; offline (socket connect patched to raise, runner still works).

## 7. Verify

- [x] 7.1 `openspec validate controlled-experiment-runners --strict`.
- [x] 7.2 `pytest -k "runner or divergence or memory or eidolon or self_model"`
      green; sidecar-boundary test green (no new core import of kaine.evaluation,
      no kaine.modules import at eval-package import time).
