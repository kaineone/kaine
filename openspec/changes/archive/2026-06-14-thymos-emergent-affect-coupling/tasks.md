# Tasks

## 1. Appraisal-routed perceived emotion
- [x] 1.1 Add a transient perceived-emotion signal to Thymos: on `audition.emotion`,
      record (derived pleasantness + intensity from `EMOTION_VAD[category]`,
      familiarity-weight, timestamp). No direct state write.
- [x] 1.2 Fold the decayed perceived signal into `_score_snapshot`:
      contribute to `intrinsic_pleasantness` (familiarity-weighted) and a small
      amount to `novelty`, clamped to `[-1, 1]`. The existing appraisal→state
      nudge then produces the entity's response.
- [x] 1.3 Decay the perceived signal to zero over `decay_s` (config; default ~10 s).

## 2. Remove the imposition path
- [x] 2.1 Delete `_apply_coupling_nudge` and the `audition.emotion → direct VAD
      write` branch in `_handle_peer_event`.
- [x] 2.2 Remove `DriftSafeguard` (and its construction/usage) — no longer needed.
- [x] 2.3 Keep the `audition.emotion` + `empatheia.agent_model` subscriptions
      (still feed appraisal + familiarity cache) under `enabled`.

## 3. Config + helpers
- [x] 3.1 Reinterpret `[thymos.coupling]` knobs as appraisal-influence weights;
      add `decay_s`. Ignore a stale `coupling_max_rate_per_s` rather than erroring.
- [x] 3.2 Update `CouplingConfig` and `compute_coupling` docstrings to the
      appraisal-input semantics. Cite the appraisal route, not contagion-by-write.

## 4. Docs + paper
- [x] 4.1 Update `docs/` (Thymos affect-coupling section) to the emergent framing.
- [x] 4.2 Deliver paper-agent note: `KAINE_Paper.md` "this is automatic; not
      mediated by reasoning" → appraised-input framing.

## 5. Tests + validation
- [x] 5.1 Tests per design (perceive→appraise, familiarity scaling, decay,
      disabled-is-identity, no-direct-write, cache round-trip).
- [x] 5.2 Full suite green; `openspec validate thymos-emergent-affect-coupling --strict`.
</content>
