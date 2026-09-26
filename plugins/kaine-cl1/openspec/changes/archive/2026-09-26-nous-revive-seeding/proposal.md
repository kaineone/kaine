## Why

KAINE now seeds Nous' engine with the posterior restored on a revive, and logs "nous: engine %s cannot take the restored posterior" at INFO when the engine has no `seed_posterior`. The CL1 wrapper passes that method through to KAINE's own engine by forwarding unknown attributes. Today only a unit test with a fake engine checks that forwarding. Nothing proves that a revived Nous booted through the real loader seeds the real engine through the wrapper. If the forwarding broke, a revive would quietly lose its seed and only an INFO line would show it.

## What Changes

- A boot test revives a Nous that the CL1 wrapper wraps, built through KAINE's plugin loader. It asserts that the inner `PymdpEngine` holds the restored posterior, and that neither the "cannot take the restored posterior" INFO nor the "does not match the model" WARNING is logged.
- A control test wraps the engine in a wrapper that does not forward. It shows the INFO is logged there, so the absence check above can fail.
- The existing requirement's revive scenario is tightened to name this outcome.

No runtime code changes.

## Impact

- Affected spec: `nous-wetware-backend` (modified requirement "Failures and optional engine methods pass through").
- Affected code: `plugins/kaine-cl1/tests/test_nous_revive.py` (new).
