# Controlled experiment runners (passive instruments, promoted)

Three of KAINE's measuring instruments normally run as **passive live sidecars**:
they record opportunistically while the entity runs. These three controlled
runners promote each to a **seeded, offline experiment** of the same shape as the
active-inference benchmark and the oscillatory-ablation runner: a fixed stimulus
battery, a seed, a shared `Verdict` (WIN / NULL), and reproducible JSONL.

All three are headless and synthetic. They drive only deterministic / echo clients
and an in-memory Mnemos. They do **not** boot an entity, attach to live modules,
start a real bus connection, or open a network connection. Each calls
`set_global_seed(seed)` at the start of a run.

Run any one of them:

```
python -m kaine.evaluation.benchmarks.instrument_runners ab_divergence   --seed 1234 --out ab.jsonl
python -m kaine.evaluation.benchmarks.instrument_runners memory_coherence --seed 1234 --out mem.jsonl
python -m kaine.evaluation.benchmarks.instrument_runners self_model       --seed 1234 --out sm.jsonl
```

## A/B divergence runner

**What it measures:** the meter's *dynamic range*. A fixed battery of
`(utterance, conditioning)` cases — empty-conditioning cases and heavy-conditioning
cases — runs through the production `divergence_control` seam with a deterministic
*echo* conditioned-inference client (the model returns its prompt verbatim). Because
output is a pure function of the prompt, empty conditioning makes both arms
byte-identical (divergence ≈ 0), while heavy conditioning makes them differ by the
conditioning block (divergence large).

**Verdict:** **WIN** when every empty case stays at ~0 **and** every conditioned
case exceeds the floor — the meter can tell conditioned from unconditioned output.
**NULL** when it cannot (the meter is flat on this battery).

**Embedder:** the dependency-free `HashEmbedder` (blake2b token buckets) so a
seeded run reproduces its *metrics*, not just its verdict. The embedder is
process-stable: blake2b is deterministic (unlike Python's per-process-salted
`hash()`), so a seeded run reproduces its numbers across processes and operators.

**Honest scope:** uses an echo client, not a live language organ. It proves the
meter's dynamic range on the production divergence path; it does not measure a live
model's divergence — that remains the live observer's job.

## Memory coherence runner

**What it measures:** the *retrieval advantage*. A fixed battery of unique
fabricated facts is planted into a **real in-memory `MnemosCore`**
(`FakeEmbedder` + `InMemoryStorage`). A full-system arm (a retrieval client whose
answer is derived from what Mnemos returns) is scored against a bare arm (no
memory) with the production `score_async`.

**Verdict:** **WIN** when (a) full-system retrieval accuracy exceeds the bare arm
by at least the floor on the planted battery, (b) a never-stored fact yields the
honest `NON_RECALL_MARKER` (scored 0, never a confabulated positive), **and**
(c) the advantage **vanishes** when the same client runs against an *emptied*
Mnemos — proving the advantage is retrieval, not a hard-coded answer. **NULL**
otherwise.

**Boundary note:** `kaine.evaluation` does not import `kaine.modules.*` at module
top level. The real Mnemos is built by an injected `mnemos_builder` callable
(the test supplies one); the CLI default uses a lazy, function-local import inside
`_default_mnemos_builder` so the import never runs at module-import time.

## Self-model accuracy runner

**What it measures:** whether the Eidolon scorer's **fixed-threshold heuristic**
reproduces the expected score. A fixed battery of
`(planted-signal, claim, expected-score)` cases plants known affect/activity signals
into a temp evaluation-logs dir and runs the real `EidolonAccuracyRunner` scorer on
a self-description carrying a known claim.

**Verdict:** **WIN** when the scorer reproduces **every** expected score; **NULL**
otherwise.

**Honest scope (load-bearing):** this validates the scorer's
trait-keyword-vs-derived-signal **arithmetic** against **fixed, hand-chosen
thresholds** (NOT fitted against a labelled set), NOT predicted-vs-actual
self-knowledge. A WIN means "the scorer's fixed-threshold heuristic behaves as
specified," NOT "the scorer is calibrated" and NOT "the entity knows itself." The
verdict detail, the JSONL `validates` field, and the printed summary all say so.
The scorer also reports "no scorable claim" as *no evidence* (aggregate `null`),
distinct from a claim scored 0 (wrong).

## Reproducibility and null results

Given the same `--seed` and battery, each runner reproduces its verdict and its
metrics. A **NULL** is a first-class, reportable result — the meter was flat, the
retrieval advantage did not hold, or the scorer mismatched — not a harness failure.
