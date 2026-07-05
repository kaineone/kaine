## Why

The memory coherence probe is KAINE's Layer-1 instrument for the claim that the
full cognitive stack *recalls* episodic detail the bare language model cannot — it
asks the same question through the memory-augmented cognitive client and through
the bare bypass client, then logs the accuracy advantage. But the probe has **no
ground-truth control**: the only test manufactures the advantage with canned
`FakeCognitive`/`FakeBare` strings, so memory RETRIEVAL is never exercised. A
probe that "passes" without any memory actually being stored or recalled is
unfalsified — it could be reporting an advantage that comes from the test
hard-coding the right answer rather than from retrieval, and it could credit a
confabulated answer as a recall when nothing was ever stored.

There is also an honesty gap in the scorer: `score_async` is pure embedding
similarity with **no recall floor**. If memory is absent and the cognitive client
confabulates a plausible non-empty answer, the scorer can return a false positive
("recalled!") for an answer that was invented, not retrieved.

## What Changes

A planted-ground-truth control for the memory coherence probe, plus a minimal
honest non-recall mechanism so a confabulated answer cannot read as a recall.

- A **non-recall sentinel** (`NON_RECALL_MARKER`) and a scorer rule: a retrieval
  client that finds nothing in memory SHALL emit the sentinel instead of
  confabulating, and `score_async` SHALL score the sentinel as exactly `0.0`
  (honest non-recall, never credited). This is the minimal honest mechanism the
  negative control needs — the probe distinguishes "memory absent → said so"
  from "memory absent → made something up." Existing live behavior (embedding
  similarity for real responses) is unchanged.
- A **real-retrieval positive control** (test-level, no `kaine.modules.*` import
  into `kaine.evaluation`): a unique fabricated marker (`the vault code is
  ZX-QObb-7741`) is planted into a REAL `MnemosCore`/`InMemoryStorage`. A
  cognitive client that actually `recall`s from that Mnemos and derives its
  answer from the retrieved text repeats the marker (high `real_accuracy`); the
  bare client, with no Mnemos, does not (low `bare_accuracy`). The advantage is
  proven to come from RETRIEVAL — when the same client queries an EMPTY Mnemos
  its answer changes (it can no longer repeat the marker), so the fixture is not
  hard-coding the answer.
- A **negative control (no confabulation)**: query for a fact that was never
  stored. The retrieval client finds nothing and emits the non-recall sentinel;
  the probe reports failure-to-recall (accuracy `0.0`), NOT a false positive from
  a confabulated non-empty answer.
- `MemoryProbeRunner`'s live behavior is **intact** — this adds a real-retrieval
  control fixture + tests + the minimal honest non-recall mechanism.

## Capabilities

### Modified Capabilities

- `evaluation-observers`: the memory coherence probe gains a planted
  ground-truth positive control (full system retrieves a fact the bare model
  cannot) and a negative control (no planted fact → reports non-recall, no
  confabulation false positive), plus an honest non-recall sentinel in the
  scorer.

## Impact

- **Code (touch):** `kaine/evaluation/memory_probes.py` — add `NON_RECALL_MARKER`
  and the sentinel handling in `score_async`; no change to the live probe loop or
  the embedding-similarity path for real answers.
- **Tests:** `tests/test_evaluation_observers.py` — a real-`MnemosCore` retrieval
  client fixture (built at test level; no module import into the eval package),
  the positive control (retrieves planted marker; advantage proven by emptying
  Mnemos), the negative control (never-stored fact → non-recall sentinel → no
  false positive), and a direct scorer test for the sentinel.
- **Docs:** evaluation/instrument docs note the ground-truth controls and the
  non-recall sentinel.
- **Boundary:** the `kaine.evaluation` → no `kaine.modules.*` import boundary is
  preserved (the real Mnemos is constructed in the test, the retrieval client is
  duck-typed). The two boundary tests stay green.
- **Safety:** offline instrument + unit tests only. No entity boot, no live bus,
  no real effector side effects.
