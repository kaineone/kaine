# Design — Authenticate act-intent provenance

> **Design-of-record only.** Plan, not implementation. The operator must choose
> mechanism A or B (§3) before work begins.

## 1. Threat model

An attacker who already holds the shared bus credential (i.e. any KAINE module
process, or code that compromises one — Lingua being the most exposed because its
outputs are LLM-driven and prompt-injectable) can `XADD` a crafted
`{kind: "act", effector, params}` event onto `volition.out`. Praxis realizes it
without Syneidesis or Volition involvement. The whitelist+sandbox still bound
*what* effectors exist, but inhibition — which the paper sells as a safety control —
is bypassed entirely.

This is not remote code execution from outside; it requires local bus-write
capability. But the architecture's own claim is that inhibition gates action, and
that claim is currently false at the boundary.

## 2. What "already sound" stays untouched

- Bus requires `requirepass` on every host and refuses external binds — keep.
- Effector whitelist empty-by-default + per-effector sandbox/whitelist — keep; this
  is and remains the primary gate.
- The point of this change is to make *inhibition* a real second boundary, not to
  replace the first.

## 3. Two mechanisms (choose one)

### Option A — Per-module Redis ACLs
Give each module process its own Redis user, and grant `XADD` on `volition.out`
only to the cycle/Volition identity. Redis ACLs support per-key command rules.
- Pros: enforced by the datastore; no payload changes; also naturally hardens
  every other reserved stream (`workspace.broadcast`, etc.).
- Cons: larger operational change — provisioning N credentials, updating compose/
  secrets, boot wiring; harder on a single-process cycle where modules are tasks
  in one process sharing one connection (today's layout). If modules are not
  separate processes, ACLs cannot distinguish them and this option does not work
  without also splitting processes.

### Option B — HMAC-signed intents (recommended for today's layout)
Volition attaches `sig = HMAC(secret, canonical(kind,effector,params,run_id,seq))`
to each act intent; Praxis verifies `sig` with the same secret before acting. The
secret is generated per boot, held only by the cycle process, and never published.
- Pros: works within the current single-process/shared-connection layout; small,
  local change; provenance is cryptographic, not identity-based; forged intents
  from any other writer fail verification.
- Cons: secret lives in-process (a full compromise of the cycle process defeats it —
  but such an attacker already controls Volition anyway, so the boundary still holds
  against the realistic threat: a compromised *peripheral* module like Lingua).
- Replay: include `run_id` + monotonic `seq` (already present for admissibility) in
  the signed payload and have Praxis reject a seq it has already realized, so a
  captured signed intent cannot be replayed.

**Recommendation: Option B now** (matches the current process model, small blast
radius), with Option A recorded as the direction if/when modules become separate
processes (see the `distributed-substrate` and `containerize-deployment` changes,
which split services and would make per-identity ACLs natural).

## 4. Failure handling

- An act intent with a missing/invalid signature (B) or from a disallowed identity
  (A) SHALL be dropped, SHALL NOT execute any effector, and SHALL be written to the
  audit log under a distinct `provenance_rejected` category.
- This category feeds the red-team and the sidecar so the boundary is observable.

## 5. Red-team coverage

Add a case: with a booted gate, forge a signed-looking `act` intent from a
non-Volition writer and assert Praxis blocks + logs it. Add the self-test variant
(mis-wire verification off) and confirm the harness detects the regression.

## 6. Paper reconciliation (required regardless of A/B)

Edit §3.5 and §9.4 of the manuscript so inhibition is described as a
cognitive/behavioral property of the legitimate path AND, with this change, backed
by verified intent provenance at the Praxis boundary — while the whitelist+sandbox
remains the primary enforced gate. Do not leave the current wording, which implies
inhibition is already an enforced safety boundary.

## 7. Open questions for the operator
- Choose mechanism A or B (recommend B).
- Confirm whether modules are single-process (they are today) — this decides A's
  feasibility.
