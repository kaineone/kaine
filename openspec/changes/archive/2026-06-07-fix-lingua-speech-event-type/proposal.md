## Why

Lingua publishes external and internal speech with the event **type set to the
stream name** (`_produce`: `"type": f"{stream}"` → `"lingua.external"` /
`"lingua.internal"`). But every consumer that filters by type expects the
**semantic** types `"external_speech"` / `"internal_speech"`:
- the Nexus conversation router (`conversation.py:71,110`),
- three evaluation observers — `ab_divergence`, `proactive_audit`,
  `affect_correlation` (each `if event.type != "external_speech": continue`),
- the privacy filter and ~15 tests.

So in the **live** system the conversation view shows **none** of KAINE's
speech, and those three thesis observers never record it — a direct cause of
the "total silence" the operator experienced. The unit tests passed only
because they hand-construct events with the intended `external_speech` type;
**no test exercised the real producer→consumer contract**, so the producer's
divergence went unnoticed. (The recently added `volition` guard-clearing keyed
on the producer's *current* wrong type, so it must be updated in lockstep.)

## What Changes

- Lingua `_produce` emits the **semantic** event type by mode: external →
  `"external_speech"`, internal → `"internal_speech"` (still published to the
  `lingua.external` / `lingua.internal` streams). This aligns the producer with
  every consumer.
- Update `kaine/workspace/volition.py` `OWN_EXTERNAL_SPEECH_TYPE` /
  `OWN_INTERNAL_SPEECH_TYPE` to the semantic types, so drive-policy
  guard-clearing keys on the real published type.
- Add a **producer-contract regression test**: `Lingua.speak()` publishes an
  event of type `external_speech`; `think()` publishes `internal_speech`. This
  closes the gap that let the divergence ship.
- Update the volition/drive-policy tests that encoded the old stream-name type.

## Capabilities

### Modified Capabilities

- `lingua`: external/internal speech is published with a stable semantic event
  type (`external_speech` / `internal_speech`) that consumers filter on — the
  conversation view and the affected evaluation observers now receive it.

## Impact

- **Code**: `kaine/modules/lingua/module.py` (`_produce` type), `kaine/workspace/
  volition.py` (two constants). No consumer code changes — they already expect
  the semantic types.
- **Behavior**: the conversation view shows KAINE's external speech; A/B
  divergence, proactive-audit, and affect-correlation observers receive it;
  drive-policy guard-clearing stays correct.
- **Tests**: new producer-contract test; update volition/drive-policy tests'
  event types from the old `lingua.external`/`lingua.internal` to the semantic
  types.
