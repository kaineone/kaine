## 1. Control seam (symmetric, injectable)

- [x] 1.1 Factor the pure metric into `divergence_for(conditioned_text,
      bare_text, *, embedder)` (`1 - cosine`); identical text → 0, empty arm → 1.
- [x] 1.2 Add `ConditionedInferenceClient` protocol —
      `complete_conditioned(utterance, conditioning)` — one path for both arms.
- [x] 1.3 Add `divergence_control(client, utterance, conditioning, *, embedder)`:
      conditioned arm = `utterance` under `conditioning`; bare arm = same
      `utterance` under EMPTY conditioning; returns divergence + both arms +
      embedder kind.
- [x] 1.4 Add `AssemblerConditionedClient` (duck-typed `build_prompt` +
      `complete`) so the control reuses the REAL Lingua conditioning path without
      `kaine.evaluation` importing `kaine.modules.*`.
- [x] 1.5 Wire the real path at the cycle entrypoint
      (`build_ab_divergence_control_client`): real `ContextAssembler` + chat
      client, empty conditioning ⇒ "nothing salient" prompt.

## 2. Negative control (permanent)

- [x] 2.1 Test: empty conditioning ⇒ both arms identical ⇒ divergence < floor
      (~0), with `HashEmbedder` (always-on, no model).
- [x] 2.2 Test: pure-metric identity floor — `divergence_for(x, x)` == 0.

## 3. Positive control

- [x] 3.1 Test (always-on, HashEmbedder): injected large conditioning ⇒ output
      differs ⇒ divergence > 0 (structural/lexical claim).
- [x] 3.2 Test (sentence-transformers): injected large conditioning ⇒ LARGE
      semantic divergence; `importorskip` + load-failure skip; never fake a
      semantic result. Also re-asserts the negative control semantically.

## 4. Live observer untouched

- [x] 4.1 No behavior change to `ABDivergenceObserver` (still samples
      `lingua.external`); existing observer tests stay green.

## 5. Docs + validate

- [x] 5.1 Document the controls and which embedder validates which property.
- [x] 5.2 `.venv/bin/python -m pytest -q -p no:cacheprovider tests/ -k
      "divergence or ab_divergence"` green.
- [x] 5.3 `openspec validate ab-divergence-controls --strict` passes.
