## 1. Honest non-recall mechanism

- [x] 1.1 Add `NON_RECALL_MARKER` sentinel to `kaine/evaluation/memory_probes.py`.
- [x] 1.2 In `score_async`, score the sentinel as exactly `0.0` (honest
      non-recall, never credited as a recall) before the embedding path; the
      embedding-similarity path for real responses is unchanged.

## 2. Real-retrieval positive control (test-level, no module import into eval)

- [x] 2.1 Build a real `MnemosCore`/`InMemoryStorage` fixture and plant a unique
      fabricated marker (`the vault code is ZX-QObb-7741`) the bare model cannot
      know.
- [x] 2.2 Build a duck-typed cognitive client that `recall`s from that Mnemos and
      derives its answer from the retrieved text (emits `NON_RECALL_MARKER` when
      recall is empty); the bare client has no Mnemos.
- [x] 2.3 Test: full-system arm retrieves/repeats the marker (high
      `real_accuracy`) while the bare arm does not (low `bare_accuracy`);
      `advantage > 0`.
- [x] 2.4 Test: the SAME client against an EMPTY Mnemos no longer repeats the
      marker and its accuracy drops — proving the advantage is RETRIEVAL, not a
      hard-coded answer.

## 3. Negative control (no confabulation)

- [x] 3.1 Test: query a never-stored fact → retrieval client emits the non-recall
      sentinel → probe records `real_accuracy == 0.0`, no false positive.
- [x] 3.2 Test (direct scorer): `score_async(NON_RECALL_MARKER, memory)` == 0.0.

## 4. Boundary + docs + validate

- [x] 4.1 Confirm `kaine.evaluation` imports no `kaine.modules.*` (real Mnemos
      built at test level; retrieval client duck-typed). Run the two boundary
      tests.
- [x] 4.2 Document the ground-truth controls and the non-recall sentinel.
- [x] 4.3 `.venv/bin/python -m pytest -q -p no:cacheprovider tests/ -k
      "memory_probe or mnemos"` green.
- [x] 4.4 `openspec validate memory-probe-ground-truth --strict` passes.
