# Authenticate act-intent provenance at the Praxis boundary

## Why

The paper's security narrative (§3.5, §9.4) states that the entity's executive
inhibition is a safety mechanism: "Syneidesis withholds a broadcast when no
coalition crosses the confidence threshold, and Volition refuses to derive any
intent from an inhibited snapshot." The security review found this is **not an
enforced boundary** at the bus/Praxis interface:

- `Praxis._handle_intent` (`kaine/modules/praxis/module.py:141-170`) acts on any
  event on `volition.out` whose payload has `kind == "act"`. It never checks
  `event.source`.
- Every module shares one Redis credential; `AsyncBus`'s ownership checks are
  application-layer only and do not stop a raw client with the same password from
  `XADD`-ing directly onto `volition.out`, bypassing Volition entirely
  (`kaine/bus/client.py:163-171`, `kaine/bus/schema.py:57-61` only reserves
  `workspace.broadcast` for `syneidesis`).

So a compromised or prompt-injected module — Lingua is LLM-output-driven and the
most exposed — that holds the shared bus credential can synthesize an `act` intent
and have Praxis realize it **without passing through Syneidesis's threshold or
Volition's inhibition check**. Once an operator enables any real effector (shell,
file_write), this is a path to real-world effects that never touches inhibition,
contradicting the documented claim.

The effector whitelist + sandbox remain the real gate and are sound. But the paper
presents inhibition as a *security* control, and today it is only a property of
the legitimate code path, not an enforced boundary. This must be reconciled: either
the boundary is made real, or the paper is corrected. Per the project's
scientific-honesty principle, the stronger and more defensible fix is to make the
boundary real, and to correct the paper's wording either way.

## What Changes

**Plan-only. Ships no behavior code.** Design-of-record and task roadmap. The
design (`design.md`) weighs two enforcement mechanisms; the operator picks one
before implementation.

1. **Enforce act-intent provenance.** `Praxis._handle_intent` SHALL accept an `act`
   intent only when it is provably from the cycle's action-selection step
   (Volition), via one of:
   - **A. Per-module Redis ACL** restricting `XADD` on `volition.out` to the cycle
     process identity (requires per-process credentials, a larger infra change), or
   - **B. Signed intents** — Volition attaches an HMAC over the canonical intent
     payload keyed by a secret held only by the cycle process; Praxis verifies it
     before acting. Rejected/unsigned intents are dropped and audit-logged.
2. **Correct the paper and docs** so the security claim is accurate: state
   explicitly that inhibition is a cognitive/behavioral property of the legitimate
   path, and that the enforced runtime boundary is (a) the whitelist + sandbox and
   (b) — once this change lands — verified intent provenance. Praxis `AUDIT.md`
   already hints at this ("Mnemos / Lingua / future planners may direct Praxis");
   make it precise.
3. **Audit-log rejected intents** as a distinct category so a provenance failure is
   visible to the red-team and the sidecar.

## Impact

- Affected specs: `praxis`, `action-selection`, `event-bus`, `enforcement-red-team`.
- Affected code (later pass): `kaine/modules/praxis/module.py`,
  `kaine/workspace/volition.py`, `kaine/bus/` (client/schema or ACL config),
  `kaine/security/` (HMAC helper if option B), the red-team harness (add a
  forged-intent case), and the paper mirror `paper/paper.md` + `docs/`.
- Paper impact: §3.5 and §9.4 wording is corrected regardless of which mechanism is
  chosen. This is a companion to the paper edits, and should be reflected in the
  arXiv manuscript.
- The red-team gains a forged-`act`-intent case, closing the coverage gap this
  finding represents.
