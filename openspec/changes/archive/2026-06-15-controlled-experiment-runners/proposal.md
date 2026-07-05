# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

## Why

Three of KAINE's measuring instruments — the **A/B divergence** meter, the
**memory-coherence** prober, and the **self-model (Eidolon) accuracy** scorer —
currently exist only as PASSIVE live sidecars. They record opportunistically
while the entity runs: whatever utterances, recalls, and self-descriptions
happen to occur get scored. That makes them useful monitors but poor
*experiments*: there is no fixed stimulus, no seed, and no reproducible verdict.
You cannot re-run yesterday's measurement, and a null reading is indistinguishable
from "nothing happened to be measured."

The Phase-B control seams already merged make a controlled version of each
instrument possible without a live entity:

- `divergence_control(client, utterance, conditioning, *, embedder)` runs both A/B
  arms through ONE conditioned-inference path, varying only the conditioning;
- `score_async` + `NON_RECALL_MARKER` plus a real in-memory `MnemosCore` let the
  memory prober's full-system arm actually *retrieve* a planted fact;
- the calibrated Eidolon scorer (`_signals_snapshot`, `_score_claim`, the
  aggregate) scores trait claims against planted derived signals.

The active-inference benchmark and the just-built oscillatory-ablation runner
established the shape these should take: seeded, offline, CLI, emits a shared
`Verdict` + JSONL, with a human summary. This change promotes each of the three
passive instruments to a CONTROLLED, SEEDED, OFFLINE runner of that shape.

## What Changes

A new offline package, `kaine/evaluation/benchmarks/instrument_runners/`, with one
submodule per instrument and a single CLI dispatch. Each runner calls
`set_global_seed(seed)` at the start, executes a FIXED stimulus battery against
the production control seam (deterministic/echo clients + a real in-memory Mnemos
only — no live modules, no network, no entity boot), emits a shared-schema
`Verdict`, and writes seeded reproducible JSONL plus a human summary.

### A/B divergence runner

A fixed battery of `(utterance, conditioning)` cases — empty-conditioning cases
(expect divergence ~0) and heavy-conditioning cases (expect large divergence) —
run through `divergence_control` with the deterministic echo conditioned-inference
client (the same `_EchoModelClient` pattern the controls use) and a chosen
embedder (HashEmbedder by default, offline + dep-free).

**Verdict:** WIN when the conditioned cases all diverge above a floor AND the empty
cases all stay ~0 — i.e. the meter has *dynamic range*: it reads zero when nothing
conditions the output and large when a lot does. NULL otherwise (the meter is
flat). Per-case divergence + the embedder kind are recorded.

### Memory-coherence runner

A fixed battery of planted facts in a REAL in-memory `MnemosCore`
(`FakeEmbedder` + `InMemoryStorage`, the B2 fixture pattern, constructed in the
runner — never importing `kaine.modules.*` into the eval package: the seam is the
duck-typed `CognitiveQueryClient`). The full-system (retrieval) arm derives its
answer from what Mnemos returns; the bare arm has no memory. A never-stored fact
is included to prove honest non-recall (`NON_RECALL_MARKER` → score 0).

**Verdict:** WIN when full-system retrieval accuracy exceeds the bare arm by a floor
AND the never-stored fact yields non-recall (score 0). NULL otherwise. The runner
PROVES the advantage is retrieval, not a hard-coded answer, by re-running the SAME
client against an EMPTIED Mnemos as a recorded check — the advantage must vanish.

### Self-model accuracy runner

A fixed battery of `(planted-signal, claim)` cases. For each case the runner
plants known affect/activity signals into a temp evaluation-logs dir and runs the
calibrated scorer on a self-description carrying a known claim, then compares the
scorer's output to the expected score.

**Verdict:** WIN when the scorer reproduces every expected score on the battery
(scorer is calibrated); NULL otherwise. The record states honestly that this
validates the SCORER (trait-keywords-vs-derived-signals arithmetic), not
predicted-vs-actual self-knowledge.

All three: `set_global_seed(seed)` at start, seeded JSONL (`--seed`, `--out`), a
`__main__.py` CLI dispatch (`run <instrument>` plus `--seed`/`--out`), fully
offline.

## Capabilities

### Modified Capabilities

- `evaluation-sidecar`: ADD a controlled, seeded, offline runner for each of the
  A/B-divergence, memory-coherence, and self-model instruments — each executes a
  fixed stimulus battery against the production control seam and emits a shared
  `Verdict` + reproducible JSONL, mirroring the active-inference benchmark and the
  oscillatory-ablation runner.

## Impact

- **Code (new):**
  - `kaine/evaluation/benchmarks/instrument_runners/__init__.py`
  - `.../ab_divergence_runner.py` — fixed `(utterance, conditioning)` battery +
    dynamic-range verdict.
  - `.../memory_coherence_runner.py` — planted-fact battery in a real in-memory
    Mnemos + retrieval-advantage verdict + emptied-Mnemos proof.
  - `.../self_model_runner.py` — planted-signal/claim battery + scorer-accuracy
    verdict.
  - `.../__main__.py` — CLI dispatch (`--seed`, `--out`, instrument selector).
- **Code (touch):** none of the instruments' internals change; the runners reuse
  `divergence_control`/`divergence_for`, `MemoryProbeRunner`/`score_async`/
  `NON_RECALL_MARKER`, `EidolonAccuracyRunner`'s scorer, `set_global_seed`, and the
  shared `Verdict`. `kaine.evaluation` importing a real Mnemos would violate the
  sidecar boundary, so the memory runner builds Mnemos via a small builder it
  receives or via a lazy local import *inside its own module under
  kaine.evaluation* — see Limitations.
- **Docs:** `docs/processes/controlled-experiment-runners.md` — how to run each,
  what WIN/NULL mean per instrument, and the honest scope of each.
- **Tests:** per runner, end-to-end offline: a sane verdict on the battery; a
  seeded run reproduces verdict + metrics; A/B empty cases ~0 and conditioned cases
  large; memory advantage vanishes on an emptied Mnemos; self-model scorer
  reproduces the expected scores; offline (socket connect patched to raise, runner
  still works).
- **Safety:** offline research instruments; read-only w.r.t. any running entity;
  enable no module, boot no entity, open no network connection.

## Limitations

- **A/B runner** uses a deterministic echo conditioned-inference client, not a live
  language organ. It proves the meter's *dynamic range* (zero when unconditioned,
  large when heavily conditioned) on the production `divergence_control` path; it
  does not measure a live model's divergence — that remains the live observer's
  job. This mirrors the active-inference benchmark's synthetic posture.
- **Memory runner** must construct a real `MnemosCore`. To keep the
  `kaine.evaluation` → `kaine.modules.*` boundary intact, the runner does NOT
  import Mnemos at module top level: it accepts an injected `mnemos_builder`
  callable (the entrypoint/test supplies one) and only falls back to a lazy
  function-local import when none is given, so the import never executes at package
  import time and the boundary test (which greps for `from kaine.modules`) is
  satisfied by keeping the fallback an attribute access, not a top-level import.
- **Self-model runner** validates the SCORER's arithmetic against known planted
  signals — trait-keyword-vs-derived-signal matching — NOT predicted-vs-actual
  self-knowledge. The verdict and records say so plainly; a WIN means "the scorer is
  calibrated," not "the entity knows itself."
