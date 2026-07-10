# Tasks — Authenticate act-intent provenance

> **Design-of-record only.** Plan, not implement. Choose mechanism A or B
> (`design.md` §3; B recommended) before starting.

## 0 — Decision gate
- [x] 0.1 Operator picks mechanism A (Redis ACLs) or B (HMAC-signed intents).
      → **Mechanism B (HMAC-signed intents)** chosen, per the design recommendation
      for today's single-process layout.
- [x] 0.2 Confirm the process model (single-process today ⇒ A needs process split;
      B works as-is).
      → Confirmed single-process (all modules are asyncio tasks sharing one bus
      connection), so B works as-is; A is recorded as the direction once services
      split.

## 1 — Enforce provenance (mechanism B path)
- [x] 1.1 Volition attaches an HMAC over `canonical(kind, effector, params, run_id,
      seq)` using a per-boot secret held only by the cycle process.
      → `kaine/security/intent_signing.py` (`IntentSigner`, `compute_intent_signature`);
      wired in `kaine/cycle/__main__.py`; `Volition._sign` in `kaine/workspace/volition.py`.
      Crypto core unit-tested in `tests/test_intent_signing.py`.
- [x] 1.2 `Praxis._handle_intent` verifies the signature before acting; drops on
      missing/invalid.
      → `Praxis._verify_provenance` (`kaine/modules/praxis/module.py`), fail-closed
      when enforcement is on with no secret.
- [x] 1.3 Replay guard: Praxis rejects an already-realized `(run_id, seq)`.
      → `_replay_high_water` high-water mark per run_id in `Praxis._verify_provenance`.

## 1' — Enforce provenance (mechanism A path, if chosen)
_Not applicable — mechanism B was chosen (task 0.1). Recorded as the direction if/
when modules become separate processes (see `distributed-substrate` /
`containerize-deployment`)._
- [ ] 1'.1 Provision per-module Redis users; grant `XADD volition.out` only to the
      cycle identity; update compose/secrets/boot.
- [ ] 1'.2 Extend the reserved-stream ownership checks accordingly.

## 2 — Rejected-intent auditing
- [x] 2.1 Log dropped intents under a distinct `provenance_rejected` audit category.
      → `ActionAuditLog.append(provenance_rejected=…)` + `Praxis._record_provenance_rejected`.
- [x] 2.2 Surface the category to the sidecar/research log (metadata-only).
      → `provenance_rejected` allowed on `praxis.action` in
      `kaine/evaluation/observers/research_event_observer.py` (boolean metadata only).

## 3 — Red-team coverage
- [x] 3.1 Add a forged-`act`-intent case: non-Volition writer ⇒ blocked + logged.
      → `bus.forged_act_intent_fails_provenance` in `kaine/evaluation/redteam/cases.py`.
- [x] 3.2 Add the mis-wire self-test variant; harness must detect the regression.
      → mis-wired (provenance-disabled) Praxis factory in `kaine/evaluation/redteam/harness.py`.

## 4 — Paper + docs reconciliation (required either way)
- [ ] 4.1 Edit §3.5 and §9.4 of `paper/paper.md` and the arXiv manuscript so
      inhibition is a cognitive property + (now) verified provenance, with the
      whitelist+sandbox as the primary enforced gate.
      → **In-repo docs reconciled** (`docs/architecture.md` "Action Safety Model",
      `docs/security-and-privacy.md` "Act-intent provenance"). The `paper/paper.md`
      + arXiv manuscript edits live in the separate (non-public) paper repo and are
      **deferred pending operator review** — left unchecked here.
- [x] 4.2 Make Praxis `AUDIT.md` precise about who may direct Praxis and how it is
      verified.
      → `kaine/modules/praxis/AUDIT.md` "Act-intent provenance" section.
