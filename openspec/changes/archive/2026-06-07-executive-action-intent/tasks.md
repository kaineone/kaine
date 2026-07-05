## 1. Intent types + Volition action-selector

- [x] 1.1 Define intent types (`kind: speak|think|act`, `about`/referent,
      optional `effector`/`params`) in a new module (e.g.
      `kaine/workspace/volition.py`).
- [x] 1.2 Implement `Volition` with an injectable `ActionSelectionPolicy`.
      `select(snapshot) -> list[Intent]`: returns `[]` when `snapshot.inhibited`;
      otherwise delegates to the policy.
- [x] 1.3 Default policy: emit one `speak` intent when a non-inhibited coalition
      contains a user-communication event the entity is disposed to answer;
      never about the entity's own `lingua.external`; one-in-flight guard.

## 2. Cycle wiring + transport

- [x] 2.1 Invoke Volition from the cycle right after the experiential broadcast;
      publish produced intents to `volition.out` (via the bus, using the same
      encode path as other control/event writes). No direct cycle→effector calls.
- [x] 2.2 Add `volition.out` to the canonical producer set in
      `tests/test_config_stream_wiring.py`.

## 3. Effectors realize intents (no self-trigger)

- [x] 3.1 Lingua: add an intent-subscription loop (mirroring Audio Out's
      dedicated stream loops); realize `speak`→`speak()`, `think`→`think()`
      using the intent referent as prompt. Confirm Lingua has NO self-trigger.
- [x] 3.2 Praxis: realize `act` intents by dispatching to the named effector +
      audit; no action on the raw broadcast.

## 4. Tests (fakes only — no live boot)

- [x] 4.1 Volition: inhibited snapshot → `[]`; non-inhibited + disposed content
      → one `speak` intent; experiential-only invocation.
- [x] 4.2 Feedback/in-flight guards: own `lingua.external` in coalition → no
      intent; second intent suppressed while one is in flight.
- [x] 4.3 Lingua realizes a `speak` intent → one `lingua.external` output; no
      intent (e.g. inhibited) → silence. Use the fake chat client.
- [x] 4.4 Praxis realizes an `act` intent → effector invoked + audited; no
      intent → no effector call.
- [x] 4.5 Config stream-wiring test still green with `volition.out` added.

## 5. Verify

- [x] 5.1 Full suite green (`.venv/bin/python -m pytest -q`) — no skips/xfails
      added to pass; fix root causes legitimately.
- [x] 5.2 `openspec validate "executive-action-intent"` passes.
