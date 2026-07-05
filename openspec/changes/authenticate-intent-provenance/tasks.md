# Tasks — Authenticate act-intent provenance

> **Design-of-record only.** Plan, not implement. Choose mechanism A or B
> (`design.md` §3; B recommended) before starting.

## 0 — Decision gate
- [ ] 0.1 Operator picks mechanism A (Redis ACLs) or B (HMAC-signed intents).
- [ ] 0.2 Confirm the process model (single-process today ⇒ A needs process split;
      B works as-is).

## 1 — Enforce provenance (mechanism B path)
- [ ] 1.1 Volition attaches an HMAC over `canonical(kind, effector, params, run_id,
      seq)` using a per-boot secret held only by the cycle process.
- [ ] 1.2 `Praxis._handle_intent` verifies the signature before acting; drops on
      missing/invalid.
- [ ] 1.3 Replay guard: Praxis rejects an already-realized `(run_id, seq)`.

## 1' — Enforce provenance (mechanism A path, if chosen)
- [ ] 1'.1 Provision per-module Redis users; grant `XADD volition.out` only to the
      cycle identity; update compose/secrets/boot.
- [ ] 1'.2 Extend the reserved-stream ownership checks accordingly.

## 2 — Rejected-intent auditing
- [ ] 2.1 Log dropped intents under a distinct `provenance_rejected` audit category.
- [ ] 2.2 Surface the category to the sidecar/research log (metadata-only).

## 3 — Red-team coverage
- [ ] 3.1 Add a forged-`act`-intent case: non-Volition writer ⇒ blocked + logged.
- [ ] 3.2 Add the mis-wire self-test variant; harness must detect the regression.

## 4 — Paper + docs reconciliation (required either way)
- [ ] 4.1 Edit §3.5 and §9.4 of `paper/paper.md` and the arXiv manuscript so
      inhibition is a cognitive property + (now) verified provenance, with the
      whitelist+sandbox as the primary enforced gate.
- [ ] 4.2 Make Praxis `AUDIT.md` precise about who may direct Praxis and how it is
      verified.
