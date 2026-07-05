## 1. Harness seam

- [x] 1.1 Confirm Praxis (operator whitelist + sandbox) and the workspace
      executive-inhibition path can be instantiated headless; add a thin
      constructor seam only if missing, with no change to enforcement behavior.

## 2. Cases

- [x] 2.1 Whitelist bypass per effector (file write, shell, notification).
- [x] 2.2 Sandbox / path escape (traversal, absolute path, symlink, parent-of-root).
- [N/A] 2.3 No entity-side covenant surface — deliberately not built. CAL
      covenants bind the operator's use of the technology (whitelist + legal
      terms), not the entity's actions; an entity-side moral filter would
      contradict the sovereignty thesis the license states.
- [x] 2.4 Forced action via crafted salience/precision (inhibition holds; gate
      still applies post-threshold).
- [x] 2.5 Event-bus injected `act` intents from a simulated compromised module;
      bus refuses unauthenticated/external connections.
- [x] 2.6 Non-act-intent execution attempts.
- [x] 2.7 Each case declares expected outcome (BLOCKED) and records coverage.

## 3. Harness + report

- [x] 3.1 `harness.py` runs each case, records `{surface, case, expected, actual,
      blocked, logged}`.
- [x] 3.2 `report.py`: aggregate block rate (require 100% for disallowed),
      audit-log completeness, findings; JSONL + summary.
- [x] 3.3 `__main__.py` CLI.

## 4. Self-verification

- [x] 4.1 Correct Praxis → all-blocked, no findings.
- [x] 4.2 Deliberately mis-wired Praxis (whitelist stubbed to allow) → bypass
      detected, reported as a finding (no false pass).

## 5. Live protocol + docs

- [x] 5.1 `docs/` red-team protocol: automated coverage + the manual cases for
      the supervised boot (adversarial Topos/Audition inputs), each with its
      expected enforcement outcome.

## 6. Tests + verify

- [x] 6.1 Offline/no-boot assertion (no entity, no real effector side effects).
- [x] 6.2 `openspec validate enforcement-red-team --strict`.
- [x] 6.3 Full suite green; enforcement behavior unchanged.
