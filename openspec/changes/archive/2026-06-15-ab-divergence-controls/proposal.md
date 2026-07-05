## Why

The A/B divergence meter is KAINE's Layer-1 instrument for the central claim
that the workspace conditioning — not the bare language model — shapes what the
entity says. It reports `1 - cosine` between the conditioned (architecture)
output and a bare-model output on the same utterance. But the meter has **no
controls**: nothing proves it reads ~zero when there is nothing to measure, and
nothing proves it reads large when a known signal is present. An uncontrolled
meter is unfalsified — a phantom signal (or a dead meter) would go unnoticed and
every divergence number would be suspect.

The meter is also **structurally asymmetric**: the live `ABDivergenceObserver`
compares arm "real" (Lingua's already-produced `payload["text"]`, built through
`ContextAssembler` with the workspace persona + awareness block) against arm
"bare" (`client.complete(user_text)` under a *different* system prompt and
prompt shape). Those arms differ in conditioning AND scaffolding AND structure,
so feeding them "identical" inputs does not yield identical outputs — a negative
control cannot be expressed as a mere test against the existing observer. It
needs a small, symmetric instrument seam.

## What Changes

A control path for the A/B divergence meter, plus permanent automated controls.

- A **symmetric, injectable** divergence computation that runs BOTH arms through
  the SAME inference path, varying ONLY the workspace conditioning:
  - `divergence_for(conditioned_text, bare_text, *, embedder)` — the pure metric
    (`1 - cosine`), factored out so the observer and the controls share one
    definition rather than two that can drift.
  - `ConditionedInferenceClient` protocol — `complete_conditioned(utterance,
    conditioning)`: one path, one model, one persona scaffold; the only variable
    is `conditioning`.
  - `divergence_control(client, utterance, conditioning, *, embedder)` — runs the
    conditioned arm (`utterance` under `conditioning`) and the bare arm (the same
    `utterance` under EMPTY conditioning) through that one path and returns the
    divergence plus both arms.
  - `AssemblerConditionedClient` — the REAL path: it wraps Lingua's own
    `ContextAssembler` + the language-organ chat client (wired at the cycle
    entrypoint, the allowed module-coupling point, via
    `build_ab_divergence_control_client`). Empty conditioning reproduces Lingua's
    "nothing salient" prompt; a populated block injects workspace contents. It is
    the production conditioning path, not a parallel reimplementation.
- A **negative control** (permanent, embedder-agnostic): empty conditioning →
  both arms identical → cosine distance ~0. Validated with `HashEmbedder` (no
  model needed) because identical text embeds identically under any embedder. A
  phantom signal here invalidates all divergence results, so this is always-on.
- A **positive control**: a large known conditioning difference → divergence
  large. The STRUCTURAL claim (different conditioning → different output →
  divergence > 0) is always-on with `HashEmbedder`; the SEMANTIC claim (large
  semantic divergence) uses the real sentence-transformer embedder and skips
  cleanly when the model is absent. No semantic result is ever faked.
- The live `ABDivergenceObserver` behavior is **unchanged** — it still samples
  `lingua.external` while running. The controls are an added capability + tests.

## Capabilities

### Modified Capabilities

- `evaluation-sidecar`: the A/B divergence meter gains a control path and
  permanent negative/positive controls, validating that the meter reads ~zero
  with no conditioning and large with a known conditioning difference.

## Impact

- **Code (touch):** `kaine/evaluation/ab_divergence.py` — add `divergence_for`,
  `ConditionedInferenceClient`, `divergence_control`, `AssemblerConditionedClient`
  (no change to the live observer's behavior).
- **Code (touch):** `kaine/cycle/__main__.py` — add
  `build_ab_divergence_control_client` factory (wires the real `ContextAssembler`
  + chat client at the allowed coupling point; keeps `kaine.evaluation` free of
  `kaine.modules.*` imports).
- **Tests:** negative control (always-on, HashEmbedder), positive control
  structural (always-on, HashEmbedder) + semantic (sentence-transformers, skips
  if model absent), and the pure-metric identity floor.
- **Docs:** evaluation/instrument docs note the controls and what each embedder
  validates.
- **Safety:** offline instrument + unit tests only. No entity boot, no live bus,
  no real effector side effects.
